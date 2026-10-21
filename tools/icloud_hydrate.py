import subprocess,time,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
while True:
 try:
  out=subprocess.run(['/usr/sbin/lsof','-c','Python','-c','git','-Fn'],stderr=subprocess.DEVNULL,stdout=subprocess.PIPE,text=True).stdout
  names={x[1:] for x in out.splitlines() if x.startswith('n'+str(root))}
  for pattern in ['src/spotify_pipeline/*.py','prompts/*.md','config/*.json']:
   names.update(map(str,root.glob(pattern)))
  names=sorted(n for n in names if Path(n).is_file() and os.stat(n).st_blocks==0)
  from concurrent.futures import ThreadPoolExecutor
  def hydrate(name):
   try:subprocess.run(['brctl','download',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
   except Exception:pass
  with ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(hydrate,names))
 except Exception:pass
 time.sleep(10)
