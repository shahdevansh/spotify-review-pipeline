#!/usr/bin/env python3
"""Lossless trace compaction. Never remove a source without verified archive bytes."""
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runs/hero-v1'
ARCH = BASE / 'trace-archives'


def read_exact(path):
    """Reject iCloud's silent EOF/short reads and concurrent source replacement."""
    before = path.stat()
    content = path.read_bytes()
    after = path.stat()
    if not before.st_size or len(content) != before.st_size:
        raise OSError(f'Incomplete or empty read: {path}')
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise OSError(f'Source changed during read: {path}')
    return content


def validate_trace(content):
    """Decompression verifies gzip length/CRC; decoding verifies actual JSON."""
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant: ' + value)
    json.loads(gzip.decompress(content).decode('utf-8'), parse_constant=invalid_constant)


def read_trace(path):
    content = read_exact(path)
    validate_trace(content)
    return content


def atomic_receipt(path, value):
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_archive(path, manifest):
    content = read_exact(path)
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:') as tar:
        names = [item['path'] for item in manifest]
        if len(set(names)) != len(names) or tar.getnames() != names + ['manifest.json']:
            raise ValueError('Archive members differ from manifest')
        for item in manifest:
            member = tar.getmember(item['path'])
            if not member.isfile() or member.size != item['bytes']:
                raise ValueError('Archive member size/type mismatch')
            payload = tar.extractfile(member).read()
            if len(payload) != item['bytes'] or hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('Archive member readback mismatch')
            validate_trace(payload)
        stored_manifest = tar.extractfile('manifest.json').read()
        if len(stored_manifest) != tar.getmember('manifest.json').size or json.loads(stored_manifest) != manifest:
            raise ValueError('Archive manifest readback mismatch')
    return hashlib.sha256(content).hexdigest(), len(content)


def compact(directory, limit=3000):
    pairs = []
    hydration_requests = 0
    for response in directory.glob('*.response.json.gz'):
        request = response.with_name(response.name.replace('.response.', '.request.'))
        if request.exists() and time.time() - response.stat().st_mtime > 120:
            missing = [path for path in (request, response) if path.stat().st_blocks == 0]
            if missing:
                if hydration_requests < 25:
                    for item in missing:
                        try:
                            subprocess.run(['brctl', 'download', str(item.resolve())], timeout=3,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except subprocess.TimeoutExpired:
                            pass
                    hydration_requests += 1
                continue
            pairs.append((request, response))
        if len(pairs) >= limit:
            break
    if not pairs:
        return
    ARCH.mkdir(parents=True, exist_ok=True)
    temporary = ARCH / f'{time.time_ns()}.tar.tmp'
    manifest = []
    try:
        with tarfile.open(temporary, 'w') as tar:
            for pair in pairs:
                for path in pair:
                    content = read_trace(path)
                    name = str(path.relative_to(BASE))
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
                    manifest.append({'path': name, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
            content = json.dumps(manifest).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        with temporary.open('rb') as handle:
            os.fsync(handle.fileno())
        digest, size = verify_archive(temporary, manifest)
        final = ARCH / (digest + '.tar')
        receipt_path = ARCH / (digest + '.json')
        previous = {}
        if receipt_path.exists():
            previous = json.loads(read_exact(receipt_path))
            if previous.get('sha256') != digest or previous.get('members') != manifest:
                raise ValueError('Existing archive receipt conflicts with verified content')
        os.replace(temporary, final)
        # Preserve remote verification and previous metadata on an identical retry.
        receipt = {**previous, 'archive': str(final), 'sha256': digest, 'archive_bytes': size,
                   'members': manifest, 'local_readback_verified': True,
                   'remote_verified': previous.get('remote_verified', False)}
        atomic_receipt(receipt_path, receipt)
        deleted = []
        retained = []
        for index, pair in enumerate(pairs):
            members = manifest[index * 2:index * 2 + 2]
            try:
                # Keep both files if either source changed or cannot be read exactly.
                contents = [read_trace(path) for path in pair]
                matches = all(len(content) == item['bytes'] and hashlib.sha256(content).hexdigest() == item['sha256']
                              for content, item in zip(contents, members))
            except (OSError, ValueError, EOFError, UnicodeError):
                matches = False
            if not matches:
                retained.extend(item['path'] for item in members)
                continue
            for path, item in zip(pair, members):
                path.unlink()
                deleted.append(item['path'])
        receipt.update(deleted_source_paths=deleted, retained_changed_source_paths=retained)
        atomic_receipt(receipt_path, receipt)
        print(json.dumps({'archive': final.name, 'files_compacted': len(deleted), 'sources_retained': len(retained)}), flush=True)
        return receipt
    finally:
        temporary.unlink(missing_ok=True)


def loop():
    while True:
        try:
            paths = [ROOT/'.env', ROOT/'src', ROOT/'prompts', ROOT/'config', ROOT/'tools/run_hero.py',
                     ROOT/'data/hero_200000.csv', ROOT/'data/learning_1000.csv', ROOT/'data/source/cost_100.csv',
                     ROOT/'data/source/checkpoint_500.csv', ROOT/'data/source/analysis_10000.csv']
            for path in paths:
                subprocess.run(['brctl', 'download', str(path.resolve())], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5)
            for folder in BASE.glob('**/handoffs'):
                compact(folder)
            atomic_receipt(BASE/'trace-guard-status.json', {'pid': os.getpid(), 'updated_at': time.time(), 'state': 'healthy'})
        except Exception as exc:
            print(type(exc).__name__, str(exc), flush=True)
        time.sleep(60)


if __name__ == '__main__':
    loop()
