#!/usr/bin/env python3
"""Bundle closed, hash-verified trace archives; never delete source archives."""
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, subprocess, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def checked_bytes(path):
    before = path.stat()
    if before.st_size and before.st_blocks == 0:
        raise RuntimeError('Offloaded input: ' + path.name)
    content = path.read_bytes()
    after = path.stat()
    if len(content) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError('Short or changing input: ' + path.name)
    return content

def hydrate(path):
    try:
        subprocess.run(['brctl', 'download', str(path.resolve())], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass

def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as handle:
        json.dump(value, handle, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
    os.replace(temp, path)

def bundle(base, max_archive_bytes=40_000_000):
    base = base.resolve(); archives = base/'trace-archives'; out=base/'drive-offload'; out.mkdir(exist_ok=True)
    selected=[]; selected_bytes=0
    for receipt in sorted(archives.glob('*.json')):
        # Old remote-verified receipts outlive their deleted TARs. Do not hydrate
        # thousands of these merely to rediscover that there is nothing to copy.
        if not receipt.with_suffix('.tar').exists():continue
        if receipt.stat().st_size and receipt.stat().st_blocks == 0:
            hydrate(receipt);continue
        raw=checked_bytes(receipt);value=json.loads(raw)
        if value.get('remote_verified'):continue
        archive=Path(value['archive'])
        if archive.parent.resolve()!=archives.resolve() or archive.suffix!='.tar' or archive.is_symlink():
            raise RuntimeError('Unsafe archive path')
        if not archive.exists():continue
        if archive.stat().st_size and archive.stat().st_blocks==0:
            hydrate(archive);continue
        if selected and selected_bytes+archive.stat().st_size>max_archive_bytes:break
        if archive.stat().st_size>max_archive_bytes:raise RuntimeError('Archive exceeds bounded bundle size')
        content=checked_bytes(archive)
        if hashlib.sha256(content).hexdigest()!=value['sha256'] or archive.stem!=value['sha256'] or not value.get('local_readback_verified'):
            raise RuntimeError('Archive lacks matching local hash/read-back proof')
        selected.append((archive,receipt,value));selected_bytes+=len(content)
    if not selected:return {'status':'no_pending'}
    name=time.strftime('traces-%Y%m%d-%H%M%S')+'-'+str(time.time_ns()%1_000_000).zfill(6)+'.zip'
    path=out/name;temp=path.with_suffix('.zip.tmp');manifest=[]
    try:
        with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as zipped:
            for archive,receipt,value in selected:
                for source in (archive,receipt):
                    raw=checked_bytes(source)
                    if source==archive and hashlib.sha256(raw).hexdigest()!=value['sha256']:
                        raise RuntimeError('Archive changed during bundling')
                    zipped.writestr(source.name,raw)
                    manifest.append({'file':source.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
            zipped.writestr('bundle-manifest.json',json.dumps(manifest,indent=2))
        with zipfile.ZipFile(temp) as zipped:
            if zipped.testzip() is not None:raise RuntimeError('ZIP CRC failed')
            for item in manifest:
                raw=zipped.read(item['file'])
                if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise RuntimeError('Bundle read-back failed')
        os.replace(temp,path)
        raw=checked_bytes(path)
        receipt={'file':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'archives':[str(row[0]) for row in selected],'remote_verified':False}
        atomic_json(path.with_suffix('.receipt.json'),receipt)
        return receipt
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-archive-bytes',type=int,default=40_000_000);args=parser.parse_args()
    if args.max_archive_bytes<=0:raise SystemExit('Positive archive limit required')
    base=(ROOT/'runs/hero-v1').resolve()
    with (base/'bundle-traces.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(json.dumps(bundle(base,args.max_archive_bytes)))
if __name__=='__main__':main()
