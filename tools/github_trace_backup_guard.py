#!/usr/bin/env python3
"""Back up closed trace archives to an authenticated, NEVER-published draft.

No inference, database changes, or human-label access. Deletion is limited to
validated trace TARs and their redundant ZIP after a fresh remote SHA read-back.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile


class UnsafeBackup(RuntimeError):
    pass


class DeferredBackup(RuntimeError):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def resident(path: Path):
    stat = path.stat()
    return stat.st_size == 0 or stat.st_blocks > 0


def request_hydration(path: Path):
    try:
        subprocess.run(['brctl', 'download', str(path.resolve())], timeout=3,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def checked_bytes(path: Path):
    if not resident(path):
        request_hydration(path)
        raise DeferredBackup('File is offloaded: ' + path.name)
    before = path.stat()
    value = path.read_bytes()
    after = path.stat()
    if len(value) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DeferredBackup('Short or changing read: ' + path.name)
    return value


def read_json(path: Path):
    return json.loads(checked_bytes(path))


def file_sha(path: Path):
    if not resident(path):
        request_hydration(path)
        raise DeferredBackup('File is offloaded: ' + path.name)
    before = path.stat()
    digest = hashlib.sha256()
    length = 0
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
            length += len(block)
    after = path.stat()
    if length != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DeferredBackup('Short or changing read: ' + path.name)
    return digest.hexdigest()


SECRET_PATTERNS = (
    re.compile(rb'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    re.compile(rb'(?i)(?:authorization|x-api-key|api[-_]key)\s*["\x27]?\s*[:=]\s*["\x27]?(?:bearer\s+)?[A-Za-z0-9_.-]{12,}'),
)
SECRET_KEYS = {'authorization', 'x-api-key', 'api_key', 'apikey', 'access_token', 'refresh_token'}


def load_secrets(env_file: Path):
    values = []
    for line in checked_bytes(env_file).decode().splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        name, value = line.split('=', 1)
        value = value.strip().strip('"').strip("'")
        if any(word in name.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'DATABASE_URL')) and len(value) > 12:
            values.append(value.encode())
    if not values:
        raise UnsafeBackup('No configured secret values available for exact-match scan')
    return values


def scan_json(content: bytes, secret_values):
    if any(secret in content for secret in secret_values) or any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise UnsafeBackup('Secret content detected; no upload or local deletion permitted')
    def unique_object(pairs):
        result = {}
        for key, child in pairs:
            if key in result:
                raise UnsafeBackup('Duplicate JSON key; secret scan cannot be unambiguous')
            result[key] = child
        return result
    value = json.loads(content, object_pairs_hook=unique_object)
    def walk(item):
        if isinstance(item, str):
            decoded = item.encode()
            if any(secret in decoded for secret in secret_values) or any(pattern.search(decoded) for pattern in SECRET_PATTERNS):
                raise UnsafeBackup('Secret content detected in decoded JSON; no upload or deletion permitted')
        if isinstance(item, dict):
            for key, child in item.items():
                if key.lower() in SECRET_KEYS:
                    raise UnsafeBackup('Credential/header key detected; no upload or local deletion permitted')
                walk(key)
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return value


def safe_member(name: str):
    parsed = PurePosixPath(name)
    return not parsed.is_absolute() and '..' not in parsed.parts and '\\' not in name


def inspect_bundle(receipt_path: Path, base: Path, secret_values):
    receipt = read_json(receipt_path)
    bundle = Path(receipt['file'])
    if bundle.parent.resolve() != (base / 'drive-offload').resolve() or bundle.suffix != '.zip' or bundle.is_symlink():
        raise UnsafeBackup('Bundle path is outside the permitted directory')
    if bundle.stat().st_size != receipt['bytes'] or file_sha(bundle) != receipt['sha256']:
        raise UnsafeBackup('Bundle hash/size mismatch')
    archive_dir = (base / 'trace-archives').resolve()
    archives = []
    seen = set()
    documents = 0
    with zipfile.ZipFile(bundle) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)) or any(not safe_member(name) for name in names):
            raise UnsafeBackup('Unsafe or duplicate ZIP member')
        expected_names = {'bundle-manifest.json'}
        bundle_manifest = scan_json(zipped.read('bundle-manifest.json'), secret_values)
        listed = {entry['file']: entry for entry in bundle_manifest}
        if len(listed) != len(bundle_manifest):
            raise UnsafeBackup('Duplicate bundle manifest member')
        for name in receipt['archives']:
            archive = Path(name)
            if archive.parent.resolve() != archive_dir or archive.suffix != '.tar' or archive.is_symlink() or archive.name in seen:
                raise UnsafeBackup('Unsafe or duplicate TAR path')
            seen.add(archive.name)
            manifest_path = archive.with_suffix('.json')
            manifest = read_json(manifest_path)
            if Path(manifest['archive']) != archive or not manifest.get('local_readback_verified'):
                raise UnsafeBackup('Archive lacks local read-back proof')
            content = zipped.read(archive.name)
            digest = hashlib.sha256(content).hexdigest()
            if digest != archive.stem or digest != manifest['sha256']:
                raise UnsafeBackup('Archive hash mismatch')
            if archive.exists() and file_sha(archive) != digest:
                raise UnsafeBackup('Local archive differs from backup bundle')
            expected_names.update((archive.name, manifest_path.name))
            embedded_manifest = scan_json(zipped.read(manifest_path.name), secret_values)
            if embedded_manifest['members'] != manifest['members'] or embedded_manifest['sha256'] != digest:
                raise UnsafeBackup('Embedded archive receipt differs')
            with tarfile.open(fileobj=io.BytesIO(content), mode='r:') as tar:
                members = tar.getmembers()
                names_in_tar = [member.name for member in members]
                expected = {entry['path']: entry for entry in manifest['members']}
                if len(expected) != len(manifest['members']) or len(names_in_tar) != len(set(names_in_tar)):
                    raise UnsafeBackup('Duplicate TAR member')
                if set(names_in_tar) != set(expected) | {'manifest.json'}:
                    raise UnsafeBackup('Unexpected TAR content')
                for member in members:
                    if not member.isfile() or not safe_member(member.name):
                        raise UnsafeBackup('Unsafe TAR member')
                    raw = tar.extractfile(member).read()
                    if len(raw) != member.size:
                        raise UnsafeBackup('Short TAR member')
                    if member.name == 'manifest.json':
                        if scan_json(raw, secret_values) != manifest['members']:
                            raise UnsafeBackup('TAR manifest differs from receipt')
                        continue
                    if '/handoffs/' not in member.name or not member.name.endswith(('.request.json.gz', '.response.json.gz', '.request.json', '.response.json')):
                        raise UnsafeBackup('Non-trace payload in archive')
                    item = expected[member.name]
                    if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
                        raise UnsafeBackup('Trace member hash/size mismatch')
                    decoded = gzip.decompress(raw) if member.name.endswith('.gz') else raw
                    scan_json(decoded, secret_values)
                    documents += 1
            archives.append((archive, manifest_path, manifest))
        if set(names) != expected_names or set(listed) != expected_names - {'bundle-manifest.json'}:
            raise UnsafeBackup('ZIP inventory differs from receipt')
        for name, item in listed.items():
            value = zipped.read(name)
            if len(value) != item['bytes'] or hashlib.sha256(value).hexdigest() != item['sha256']:
                raise UnsafeBackup('Bundle manifest hash/size mismatch')
    if not archives:
        raise UnsafeBackup('No archives to back up')
    return receipt, bundle, archives, documents


class GitHub:
    def __init__(self, config):
        self.config = config

    def run(self, args, timeout=180):
        result = subprocess.run([self.config.get('gh', 'gh'), *args], capture_output=True,
                                timeout=timeout, text=True)
        if result.returncode:
            # Never persist provider stderr, credentials, request content, or tokens.
            raise DeferredBackup('GitHub command failed: ' + args[0] + ' exit ' + str(result.returncode))
        return result.stdout

    def state(self):
        login = self.run(['api', 'user', '--jq', '.login']).strip()
        if login != self.config['account']:
            raise UnsafeBackup('Wrong authenticated GitHub account')
        state = json.loads(self.run(['release', 'view', self.config['release_tag'], '--repo', self.config['repository'], '--json', 'isDraft,id,url,assets']))
        if state.get('isDraft') is not True:
            raise UnsafeBackup('Backup release is not a draft; refusing all writes/deletion')
        if state['id'] != self.config['release_id']:
            raise UnsafeBackup('Unexpected backup release identity')
        if not state['url'].startswith('https://github.com/' + self.config['repository'] + '/releases/'):
            raise UnsafeBackup('Unexpected backup release repository')
        return state

    def upload(self, bundle):
        self.run(['release', 'upload', self.config['release_tag'], str(bundle), '--repo', self.config['repository']])

    def download(self, bundle, directory):
        self.run(['release', 'download', self.config['release_tag'], '--repo', self.config['repository'], '--pattern', bundle.name, '--dir', str(directory)])


def backup_one(receipt_path: Path, base: Path, config, github=None):
    github = github or GitHub(config)
    state = github.state()
    secrets = load_secrets(Path(config['env_file']))
    receipt, bundle, archives, documents = inspect_bundle(receipt_path, base, secrets)
    scan = {'checked_at': utc_now(), 'bundle_sha256': receipt['sha256'], 'tar_archives': len(archives),
            'trace_json_documents': documents, 'secret_pattern_hits': 0, 'exact_environment_secret_checks': len(secrets)}
    atomic_json(bundle.with_suffix('.safety-scan.json'), scan)
    existing = [asset for asset in state['assets'] if asset['name'] == bundle.name]
    if len(existing) > 1:
        raise UnsafeBackup('Duplicate remote asset names')
    if existing:
        asset = existing[0]
        if asset['size'] != receipt['bytes'] or asset.get('digest') != 'sha256:' + receipt['sha256'] or asset['state'] != 'uploaded':
            raise UnsafeBackup('Existing remote asset conflicts; never clobber')
    else:
        github.state()  # Recheck account/draft immediately before upload.
        if file_sha(bundle) != receipt['sha256']:
            raise UnsafeBackup('Bundle changed after secret scan')
        github.upload(bundle)
    state = github.state()
    asset = next(asset for asset in state['assets'] if asset['name'] == bundle.name)
    if asset['size'] != receipt['bytes'] or asset.get('digest') != 'sha256:' + receipt['sha256'] or asset['state'] != 'uploaded':
        raise UnsafeBackup('Uploaded asset metadata mismatch')
    with tempfile.TemporaryDirectory(prefix='spotify-trace-readback-', dir=config['scratch_dir']) as directory:
        github.download(bundle, Path(directory))
        downloaded = Path(directory) / bundle.name
        if downloaded.stat().st_size != receipt['bytes'] or file_sha(downloaded) != receipt['sha256']:
            raise UnsafeBackup('Remote read-back hash/size mismatch; local archives retained')
        final_state = github.state()  # No deletion after a draft was published externally.
        if final_state['id'] != state['id']:
            raise UnsafeBackup('Release identity changed')
        final_asset = next((item for item in final_state['assets'] if item['id'] == asset['id']), None)
        if final_asset is None or final_asset.get('digest') != 'sha256:' + receipt['sha256']:
            raise UnsafeBackup('Verified remote asset changed before local deletion')
        proof = {'destination': 'github_draft', 'release_tag': config['release_tag'], 'release_id': state['id'],
                 'release_url': state['url'], 'release_is_draft': True, 'asset_id': asset['id'],
                 'asset_api_url': asset['apiUrl'], 'asset_url': asset['url'],
                 'readback_sha256': receipt['sha256'], 'verified_at': utc_now(), 'bundle': bundle.name}
        # Persist every receipt before any source deletion. Partial completion is restart-safe.
        receipt.update(remote_verified=True, remote_backup=proof)
        atomic_json(receipt_path, receipt)
        for archive, manifest_path, manifest in archives:
            manifest.update(remote_verified=True, remote_backup=proof)
            atomic_json(manifest_path, manifest)
        atomic_json(bundle.with_suffix('.github-backup-proof.json'), {**proof, 'state': 'verified_before_local_reclamation', 'archive_count': len(archives)})
        removed = []
        for path, expected_sha in [(p, m['sha256']) for p, _, m in archives] + [(bundle, receipt['sha256'])]:
            if path.exists():
                if file_sha(path) != expected_sha:
                    raise UnsafeBackup('Local source changed after verification; retained')
                stat = path.stat()
                removed.append({'path': str(path), 'bytes': stat.st_size, 'allocated_bytes': stat.st_blocks * 512})
                path.unlink()
        report = {**proof, 'state': 'local_reclamation_completed', 'archive_count': len(archives), 'removed_file_count': len(removed),
                  'removed_logical_bytes': sum(item['bytes'] for item in removed),
                  'removed_allocated_bytes': sum(item['allocated_bytes'] for item in removed),
                  'removed': removed, 'trace_json_documents': documents}
        atomic_json(bundle.with_suffix('.github-backup-proof.json'), report)
    return report


def cycle(config, logger):
    base = Path(config['base']).resolve()
    out = base / 'drive-offload'
    completed = []
    deferred = []
    for path in sorted(out.glob('*.receipt.json')):
        if not path.with_name(path.name.removesuffix('.receipt.json') + '.zip').exists():
            continue
        if not resident(path):
            request_hydration(path)
            continue
        value = read_json(path)
        bundle = Path(value['file'])
        if bundle.exists() and (not value.get('remote_verified') or value.get('remote_backup', {}).get('destination') == 'github_draft'):
            if not resident(bundle):
                request_hydration(bundle)
                deferred.append(bundle.name)
                continue
            try:
                report = backup_one(path, base, config)
            except DeferredBackup:
                deferred.append(bundle.name)
                logger.info('deferred %s; retained locally and will retry', bundle.name)
                continue
            logger.info('verified %s archives=%s reclaimed=%s', bundle.name, report['archive_count'], report['removed_allocated_bytes'])
            completed.append(report['bundle'])
    pending_bytes = 0
    for path in (base / 'trace-archives').glob('*.json'):
        if not path.with_suffix('.tar').exists():
            continue
        if not resident(path):
            request_hydration(path)
            continue
        value = read_json(path)
        archive = Path(value['archive'])
        if archive.parent.resolve() != (base / 'trace-archives').resolve():
            raise UnsafeBackup('Archive receipt points outside trace directory')
        if not value.get('remote_verified') and archive.exists():
            pending_bytes += archive.stat().st_size
    free = shutil.disk_usage(base).free
    if pending_bytes and (pending_bytes >= config['pending_threshold_bytes'] or free < config['free_threshold_bytes']):
        if free < min(pending_bytes, config['max_bundle_archive_bytes']) * 2.5 + config['reserve_bytes']:
            raise DeferredBackup('Insufficient space for bundle and read-back; originals retained')
        result = subprocess.run([config['python'], config['bundle_tool'], '--max-archive-bytes', str(config['max_bundle_archive_bytes'])], cwd=config['runtime'],
                                capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise DeferredBackup('Trace bundler failed; archives retained')
        value = json.loads(result.stdout)
        if value.get('status') == 'no_pending':
            return {'completed_bundles': completed, 'deferred_bundles': deferred, 'disk_free': shutil.disk_usage(base).free, 'pending_archive_bytes_before_bundle': pending_bytes}
        path = Path(value['file']).with_suffix('.receipt.json')
        report = backup_one(path, base, config)
        logger.info('verified %s archives=%s reclaimed=%s', report['bundle'], report['archive_count'], report['removed_allocated_bytes'])
        completed.append(report['bundle'])
    return {'completed_bundles': completed, 'deferred_bundles': deferred, 'disk_free': shutil.disk_usage(base).free, 'pending_archive_bytes_before_bundle': pending_bytes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = read_json(args.config)
    if config.get('enabled') is not True or config.get('release_tag') != 'hero-private-trace-backups':
        raise SystemExit('Explicit enabled configuration and dedicated draft release required')
    base = Path(config['base']).resolve()
    lock = (base / 'github-trace-backup.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another trace backup guard owns the lock')
    logger = logging.getLogger('trace-backup')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(base / 'github-trace-backup.log', maxBytes=256 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.info('started pid=%s interval=%s', os.getpid(), config['interval_seconds'])
    while True:
        status = {'pid': os.getpid(), 'updated_at': utc_now(), 'destination': 'github_draft', 'release_tag': config['release_tag']}
        try:
            status.update(cycle(config, logger), state='healthy')
        except Exception as error:
            status.update(state='blocked' if isinstance(error, UnsafeBackup) else 'retrying',
                          error_type=type(error).__name__, error=str(error) if isinstance(error, (UnsafeBackup, DeferredBackup)) else 'Operation failed; original traces retained')
            logger.warning('%s: %s', status['error_type'], status['error'])
        atomic_json(base / 'github-trace-backup-status.json', status)
        if args.once:
            print(json.dumps(status))
            return 0 if status['state'] == 'healthy' else 1
        time.sleep(max(30, config['interval_seconds']))


if __name__ == '__main__':
    raise SystemExit(main())
