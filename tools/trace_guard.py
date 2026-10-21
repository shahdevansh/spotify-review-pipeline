#!/usr/bin/env python3
"""Local lossless trace compaction and iCloud materialization guard.
No network uploads, no provider calls, no deletion without archive readback.
"""
import hashlib,io,json,os,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'runs/hero-v1';ARCH=BASE/'trace-archives'
def compact(directory,limit=1000):
 pairs=[]; hydration_requests=0
 for response in directory.glob('*.response.json.gz'):
  request=response.with_name(response.name.replace('.response.','.request.'))
  if request.exists() and time.time()-response.stat().st_mtime>120:
   missing=[p for p in (request,response) if p.stat().st_blocks==0]
   if missing:
    if hydration_requests<25:
     for item in missing:
      try:subprocess.run(['brctl','download',str(item)],timeout=3,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
      except subprocess.TimeoutExpired:pass
     hydration_requests+=1
    continue
   pairs.extend((request,response))
  if len(pairs)>=limit*2:break
 if not pairs:return
 for path in pairs:
  if path.stat().st_blocks==0:subprocess.run(["brctl","download",str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
 ARCH.mkdir(exist_ok=True)
 temp=ARCH/f'{time.time_ns()}.tar.tmp';manifest=[]
 with tarfile.open(temp,'w') as tar:
  for path in pairs:
   content=path.read_bytes();name=str(path.relative_to(BASE));info=tarfile.TarInfo(name);info.size=len(content)
   tar.addfile(info,io.BytesIO(content));manifest.append({'path':name,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)})
  content=json.dumps(manifest).encode();info=tarfile.TarInfo('manifest.json');info.size=len(content);tar.addfile(info,io.BytesIO(content))
 with tarfile.open(temp) as tar:
  for item in manifest:
   assert hashlib.sha256(tar.extractfile(item['path']).read()).hexdigest()==item['sha256']
 digest=hashlib.sha256(temp.read_bytes()).hexdigest();final=ARCH/(digest+'.tar');os.replace(temp,final)
 receipt={'archive':str(final),'sha256':digest,'members':manifest,'local_readback_verified':True,'remote_verified':False}
 (ARCH/(digest+'.json')).write_text(json.dumps(receipt,indent=2))
 # The identical bytes remain in the verified local archive, not discarded.
 for path,item in zip(pairs,manifest):
  if hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:path.unlink()
 print(json.dumps({'archive':final.name,'files_compacted':len(pairs)}),flush=True)
def loop():
 while True:
  try:
   paths=[ROOT/'.env',ROOT/'src',ROOT/'prompts',ROOT/'config',ROOT/'tools/run_hero.py',ROOT/'data/hero_200000.csv',ROOT/'data/learning_1000.csv',ROOT/'data/source/cost_100.csv',ROOT/'data/source/checkpoint_500.csv',ROOT/'data/source/analysis_10000.csv']
   for path in paths:
    subprocess.run(['brctl','download',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
   for folder in BASE.glob('**/handoffs'):
    # Only closed request/response pairs, never cache tasks or checkpoints.
    compact(folder)
   (BASE/'trace-guard-status.json').write_text(json.dumps({'pid':os.getpid(),'updated_at':time.time(),'state':'healthy'}))
  except Exception as exc:print(type(exc).__name__,str(exc),flush=True)
  time.sleep(60)
if __name__=='__main__':loop()
