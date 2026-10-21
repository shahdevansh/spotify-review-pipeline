#!/usr/bin/env python3
"""Explicit paid Decisions/Nebius pilot; no human labels read during inference."""
import argparse, asyncio, hashlib, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from spotify_pipeline.engine import Engine, load_config, fingerprint
from spotify_pipeline.data import read_reviews
from spotify_pipeline.analysis import run_analysis
from spotify_pipeline.storage import atomic_json

async def run(args):
 load_dotenv(ROOT/'.env',override=False)
 c=load_config(ROOT/'config/decisions-pilot.json')
 out=ROOT/'runs/decisions-v1';out.mkdir(exist_ok=True)
 rows=list(read_reviews(ROOT/'data/learning_1000.csv'))
 if args.stage=='smoke':rows=rows[:1]
 elif args.stage in ('100-cold','100-warm'):rows=list(read_reviews(ROOT/'data/source/cost_100.csv'))
 elif args.stage=='human-predictions':
  rows=[json.loads(x) for x in (ROOT/'evals/human-evaluation-v1/sources.jsonl').read_text().splitlines()]
 elif args.stage.startswith('throughput-'):
  rows=rows[:200];c['requests_per_second']=int(args.stage.split('-')[1])
 elif args.stage=='synthetic':
  from run_model_experiment import synthetic_cases
  rows=[case["source"] for case in synthetic_cases()]
 if len(rows)>1000:raise ValueError('Pilot cannot exceed 1000 records')
 db=ROOT/'data'/('decisions-v1-human.sqlite3' if args.stage=='human-predictions' else 'decisions-v1-synthetic.sqlite3' if args.stage=='synthetic' else 'decisions-v1.sqlite3')
 if args.stage.startswith('throughput-'):db=ROOT/'data'/('decisions-v1-'+args.stage+'.sqlite3')
 if args.stage=='smoke':db=ROOT/'data/decisions-v1-smoke.sqlite3'
 if args.stage=='synthetic':c['fallback_fraction']=0
 allocation_path=out/'allocation.json'
 if allocation_path.exists():c['global_budget_usd']=json.loads(allocation_path.read_text())['absolute_ceiling_usd']
 e=Engine(c,db,out/args.stage,budget_usd=2,workers=1 if args.stage in ('smoke','100-cold','100-warm') else 8)
 prior=e.ledger.totals()['committed_usd']
 ceiling_path=out/'allocation.json'
 if not ceiling_path.exists():atomic_json(ceiling_path,{'prior_committed_usd':prior,'new_allocation_usd':3,'absolute_ceiling_usd':min(48,prior+3)})
 ceiling=json.loads(ceiling_path.read_text())['absolute_ceiling_usd'];e.config['global_budget_usd']=ceiling
 print(json.dumps({'stage':args.stage,'rows':len(rows),'label_config':e.label_config,'global_ceiling':ceiling}),flush=True)
 try:
  records=await e.enrich(rows,phase='resume' if args.stage=='1000' else 'initial')
  print(json.dumps({'enrichment':e.summary()}),flush=True)
  if args.stage in ('100-cold','100-warm','1000'):
   await e.verify(rows,records,10 if len(rows)==100 else 100)
   await run_analysis(records,e.run_dir,e.model_task)
  summary=e.finish();atomic_json(e.run_dir/'completed-stage.json',summary)
  print(json.dumps({'completed_stage':args.stage,'completed':summary['completed'],'cost':summary['api_cost_usd'],'seconds':summary['wall_seconds']}),flush=True)
 finally:await e.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute-paid',action='store_true');p.add_argument('--stage',choices=['smoke','100-cold','100-warm','1000','synthetic','human-predictions','throughput-8','throughput-16'],required=True)
 args=p.parse_args()
 if not args.execute_paid:p.error('Paid execution requires --execute-paid')
 asyncio.run(run(args))
