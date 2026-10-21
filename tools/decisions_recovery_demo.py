#!/usr/bin/env python3
"""Real process-stop/resume demonstration; explicitly paid, original reviews."""
import argparse,asyncio,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from spotify_pipeline.engine import Engine,load_config
from spotify_pipeline.data import read_reviews
from spotify_pipeline.storage import atomic_json
async def phase(which):
 load_dotenv(ROOT/'.env');c=load_config(ROOT/'config/decisions-pilot.json')
 c['global_budget_usd']=json.loads((ROOT/'runs/decisions-v1/allocation.json').read_text())['absolute_ceiling_usd']
 e=Engine(c,ROOT/'data/decisions-v1-recovery.sqlite3',ROOT/'runs/decisions-v1/recovery',budget_usd=.2,workers=1)
 try:
  rows=list(read_reviews(ROOT/'data/source/cost_100.csv'))[:40]
  await e.enrich(rows,phase=which,stop_after=10 if which=='initial' else None)
  s=e.finish();print(json.dumps({'phase':which,'completed':s['completed'],'pending':s['pending'],'requests':s['requests'],'cost':s['api_cost_usd']}),flush=True)
 finally:await e.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute-paid',action='store_true');p.add_argument('--phase',choices=['initial','resume']);a=p.parse_args()
 if not a.execute_paid:p.error('--execute-paid required')
 if a.phase:asyncio.run(phase(a.phase))
 else:
  for ph in ('initial','resume'):
   print('Starting separate process:',ph,flush=True)
   subprocess.run([sys.executable,__file__,'--execute-paid','--phase',ph],check=True)
   if ph=='initial':print('Process exited after durable checkpoint. Restarting with original cache.',flush=True)
  d=ROOT/'runs/decisions-v1/recovery';before=json.loads((d/'checkpoint_before.json').read_text())['completed_ids'];after=json.loads((d/'checkpoint_after.json').read_text())['completed_ids'];calls=[json.loads(x) for x in (d/'calls.jsonl').read_text().splitlines()]
  repeats=[c['request_id'] for c in calls if c['phase']=='resume' and set(before)&set(c['review_ids']) and c['role']=='enrich']
  assert len(before)==10 and len(after)==40 and not repeats
  proof={'before':10,'after':40,'reprocessed_completed_ids':0,'real_separate_process_restart':True,'forced_inflight_kill':False}
  atomic_json(d/'recovery-validation.json',proof);print(json.dumps(proof),flush=True)
