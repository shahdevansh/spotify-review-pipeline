#!/usr/bin/env python3
"""Create a Drive upload bundle from losslessly compacted trace segments.
After download-and-hash verification, receipt files can mark remote_verified.
"""
import hashlib,json,time,zipfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'runs/hero-v1';archives=BASE/'trace-archives';out=BASE/'drive-offload';out.mkdir(exist_ok=True)
files=[]
for receipt in archives.glob('*.json'):
 if receipt.stat().st_blocks==0:
  subprocess.run(['brctl','download',str(receipt)],timeout=5)
  continue
 value=json.loads(receipt.read_text())
 if not value.get('remote_verified'):
  p=Path(value['archive'])
  if p.exists():
   if p.stat().st_blocks==0:
    subprocess.run(['brctl','download',str(p)],timeout=5)
    continue
   files.extend([p,receipt])
if not files:raise SystemExit('No pending trace archives')
for path in files:subprocess.run(['brctl','download',str(path)],check=True)
p=out/(time.strftime('traces-%Y%m%d-%H%M%S')+'.zip');manifest=[]
with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
 for f in files:
  b=f.read_bytes();z.writestr(f.name,b);manifest.append({'file':f.name,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)})
 z.writestr('bundle-manifest.json',json.dumps(manifest,indent=2))
with zipfile.ZipFile(p) as z:assert z.testzip() is None
receipt={'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'archives':[str(f) for f in files if f.suffix=='.tar'],'remote_verified':False}
p.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
