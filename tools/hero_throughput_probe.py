#!/usr/bin/env python3
import asyncio,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from spotify_pipeline.engine import Engine,load_config
from spotify_pipeline.data import read_reviews
from spotify_pipeline.storage import atomic_json
async def run():
 load_dotenv(ROOT/'.env');c=load_config(ROOT/'config/hero.json');c['requests_per_second']=32;c['tokens_per_second']['decisions']=400000
 e=Engine(c,ROOT/'data/hero-throughput32.sqlite3',ROOT/'runs/hero-v1/throughput32',budget_usd=.3,workers=16)
 try:
  rows=list(read_reviews(ROOT/'data/learning_1000.csv'))[:200];records=await e.enrich(rows)
  enrich=e.finish();atomic_json(e.run_dir/'enrichment-measurement.json',enrich)
  await e.verify(rows,records,40);s=e.finish();assert s['completed']==200 and s['stages']['verify']['completed']==40
  if s['failed_attempts']==0:
   p=ROOT/'config/hero.json';raw=json.loads(p.read_text());raw['requests_per_second']=32;raw['tokens_per_second']['decisions']=400000;atomic_json(p,raw)
  atomic_json(e.run_dir/'completed-stage.json',s);print(json.dumps({'requests':s['requests'],'failed':s['failed_attempts'],'enrich_seconds':enrich['wall_seconds'],'cost':s['api_cost_usd'],'32rps_enabled_for_next_checkpoint':s['failed_attempts']==0}),flush=True)
 finally:await e.close()
if __name__=='__main__':
 if '--execute-paid' not in sys.argv:raise SystemExit('--execute-paid required')
 asyncio.run(run())
