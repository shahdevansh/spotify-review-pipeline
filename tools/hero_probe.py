#!/usr/bin/env python3
"""Explicitly paid bounded frontier-audit preflight; never reads human labels."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from spotify_pipeline.engine import Engine,load_config
from spotify_pipeline.data import read_reviews
async def run():
 load_dotenv(ROOT/'.env');c=load_config(ROOT/'config/hero.json')
 e=Engine(c,ROOT/'data/hero-probe-glm53.sqlite3',ROOT/'runs/hero-v1/probe-glm53',budget_usd=.75,workers=4)
 try:
  rows=list(read_reviews(ROOT/'data/learning_1000.csv'))[:100]
  old={r['review_id']:r for r in map(json.loads,(ROOT/'runs/decisions-v1/1000/records.jsonl').read_text().splitlines())}
  e.rows=rows;e.records=[old[r['review_id']] for r in rows]
  await e.verify(rows,e.records,100)
  print(json.dumps(e.finish()),flush=True)
 finally:await e.close()
if __name__=='__main__':
 if '--execute-paid' not in sys.argv:raise SystemExit('--execute-paid required')
 asyncio.run(run())
