#!/usr/bin/env python3
"""Offline comparison of sealed pilot artifacts. Never makes model calls."""
from pathlib import Path
import collections, csv, hashlib, html, importlib.util, json, math, statistics, sys
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from spotify_pipeline.cost import calculate_cost,load_rates,price_call
from spotify_pipeline.data import read_reviews,row_sha
from spotify_pipeline.storage import atomic_json, atomic_jsonl
from spotify_pipeline.analysis import calculate_ranking
from spotify_pipeline.models import validate_record
FIELDS=('topic','intent','severity','sentiment')
def read(p):return json.loads(p.read_text())
def jl(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def indexed(rows):
 d={r['review_id']:r for r in rows};assert len(d)==len(rows);return d
def metric(ref,pred):
 result={}
 for f in FIELDS:
  pairs=[(r[f],pred[k][f]) for k,r in ref.items() if r.get(f) is not None and k in pred and pred[k].get('status','completed')=='completed']
  n=len(pairs);matches=sum(a==b for a,b in pairs)
  x={'n':n,'matches':matches,'agreement':matches/n if n else None}
  if f in ('severity','sentiment'):x['mae']=sum(abs(a-b) for a,b in pairs)/n if n else None
  if f in ('topic','intent'):
   labels=sorted({a for a,b in pairs}|{b for a,b in pairs});x['confusion']={a:dict(collections.Counter(b for t,b in pairs if t==a)) for a in labels}
   scores=[]
   for label in labels:
    tp=sum(a==b==label for a,b in pairs);fp=sum(a!=label and b==label for a,b in pairs);fn=sum(a==label and b!=label for a,b in pairs)
    scores.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
   x['macro_f1_observed_classes']=statistics.mean(scores) if scores else None
  result[f]=x
 pairs=[(r,pred[k]) for k,r in ref.items() if r.get('topic') is not None and r.get('intent') is not None and k in pred and pred[k].get('status','completed')=='completed']
 result['joint_topic_intent']={'n':len(pairs),'matches':sum(all(a[f]==b[f] for f in ('topic','intent')) for a,b in pairs)}
 return result

def main():
 base=ROOT/'runs/decisions-v1';out=ROOT/'private/decisions-pilot-v1';out.mkdir(exist_ok=True)
 for stage in ('100-cold','100-warm','1000','human-predictions','synthetic'):
  assert (base/stage/'completed-stage.json').exists(),stage+' incomplete'
 old=indexed(jl(ROOT/'runs/pilot/1000/records.jsonl'));new=indexed(jl(base/'1000/records.jsonl'))
 assert set(old)==set(new) and len(new)==1000
 for k,r in new.items():
  validate_record(r);assert r['source_sha256']==old[k]['source_sha256']==row_sha(r)
  if r.get('cache_source_id'):
   origin=new[r['cache_source_id']];assert not origin.get('cache_source_id') and origin['review_text']==r['review_text']
   assert all(origin[f]==r[f] for f in FIELDS)
 # Saved independent predictions were produced without seeing either new enrichments or human labels.
 verifier={r['review_id']:r['prediction'] for r in jl(ROOT/'runs/pilot/1000/verification.jsonl') if r['status']=='completed'}
 assert set(verifier)==set(new)
 first={k:r.get('initial_prediction',r) for k,r in new.items()}
 result={'version':'decisions-nebius-pilot-v1','models_called_by_analysis':0,'development_count':1000,
  'comparison_caveats':['Human reference is partial and adjudicated after prior model inspection; not blind population accuracy.','The old and new pipelines have different prompts, roles and inference routes. This is a configuration comparison, not isolated model capability.','Archived independent-verifier agreement is a proxy; verifier labels are not ground truth.','Human-label disagreements not explicitly approved remain unchanged.'],
  'against_archived_blind_verifier':{name:metric(verifier,p) for name,p in [('old_lightning_pipeline',old),('decisions_first_pass',first),('decisions_glm_hybrid',new)]},
  'stages':{stage:read(base/stage/'completed-stage.json') for stage in ('100-cold','100-warm','1000','human-predictions','synthetic')}}
 fresh_verifier={r['review_id']:r['prediction'] for r in jl(base/'1000/verification.jsonl') if r['status']=='completed'}
 result['against_new_blind_verifier_sample']={name:metric(fresh_verifier,p) for name,p in [('old_lightning_pipeline',old),('decisions_glm_hybrid',new)]}
 human_path=ROOT/'private/human-labels/adjudication-v2/annotations.corrected.json';human=indexed(read(human_path)['labels'])
 hp=indexed(jl(base/'human-predictions/records.jsonl'));assert set(human)==set(hp)
 for k,r in human.items():assert r['row_sha']==hp[k]['source_sha256'] and r['review_text']==hp[k]['review_text']
 models={'lightning-v5':indexed(jl(ROOT/'private/human-predictions-v1/lightning-v5/run/records.jsonl')),'glm-v6':indexed(jl(ROOT/'private/human-predictions-v1/glm-v6/run/records.jsonl')),'decisions-first':{k:r.get('initial_prediction',r) for k,r in hp.items()},'decisions-hybrid':hp}
 groups=read(ROOT/'evals/human-evaluation-v1/groups.json');groups['pooled_descriptive']=list(human)
 result['human_reference_sha256']=sha(human_path)
 result['human_adjudicated']={g:{name:metric({k:human[k] for k in ids},p) for name,p in models.items()} for g,ids in groups.items()}
 # Routing diagnostics on original IDs and unique origins are distinguished.
 origins={k:r for k,r in new.items() if not r.get('cache_source_id')}
 chosen={k:r for k,r in origins.items() if r.get('fallback_used')}
 def correct(p,k):return all(p[f]==verifier[k][f] for f in ('topic','intent','severity'))
 result['routing']={'unique_origins':len(origins),'fallback_origins':len(chosen),'fallback_fraction':len(chosen)/len(origins),
   'final_needs_review_ids':sum(r['needs_review'] for r in new.values()),'final_needs_review_unique':sum(r['needs_review'] for r in origins.values()),
   'fallback_fixed_vs_verifier':sum(not correct(r['initial_prediction'],k) and correct(r,k) for k,r in chosen.items()),
   'fallback_harmed_vs_verifier':sum(correct(r['initial_prediction'],k) and not correct(r,k) for k,r in chosen.items()),
   'confidence_warning':'Provider confidences and agreement with a verifier are not calibrated accuracy.'}
 bins=[]
 for low,high in [(0,.4),(.4,.6),(.6,.8),(.8,1.00001)]:
  items=[(k,r.get('initial_prediction',r)) for k,r in origins.items() if low<=r.get('initial_prediction',r).get('uncertainty_score',-1)<high]
  bins.append({'min_confidence_low':low,'high':min(1,high),'n':len(items),'core_disagreements':sum(not correct(r,k) for k,r in items)})
 result['confidence_bins_against_verifier']=bins
 # Pure replay includes all original cold plus incremental attempts once.
 calls=[]
 for stage in ('100-cold','1000'):calls+=jl(base/stage/'calls.jsonl')
 assert len({c['request_id'] for c in calls})==len(calls)
 cold=read(base/'100-cold/completed-stage.json');warm=read(base/'100-warm/completed-stage.json');large=read(base/'1000/completed-stage.json')
 assert warm['requests']==0 and warm['api_cost_usd']==0
 before=set(read(base/'1000/checkpoint_before.json')['completed_ids'])
 assert len(before)==100
 assert not any(before.intersection(c['review_ids']) for c in jl(base/'1000/calls.jsonl') if c['role']=='enrich')
 result['resume']={'previous_completed_ids':100,'new_completed_ids':900,'paid_enrichment_of_previously_completed_ids':0,'process_restart':True,'recording_available':False}
 saved_ranking=list(csv.DictReader((base/'1000/ranking.csv').open()))
 replayed=calculate_ranking(list(new.values()),list(csv.DictReader((base/'1000/membership.csv').open())))['ranking']
 assert [{k:str(v) for k,v in r.items()} for r in replayed]==saved_ranking
 selected=[]
 for r in read_reviews(ROOT/'data/selected_210000.csv'):
  if r['review_text'].strip():selected.append(r)
  if len(selected)==200000:break
 assert len(selected)==200000
 unique=len({r['review_text'] for r in selected})
 result['hero_scope']={'reviews':200000,'unique_texts':unique,'sampling':'first 200000 nonempty rows of existing hash-ordered selected_210000.csv','source_file_sha256':sha(ROOT/'data/selected_210000.csv'),'selected_id_sha256':hashlib.sha256('\n'.join(r['review_id'] for r in selected).encode()).hexdigest()}
 costdir=out/'cost';costdir.mkdir(exist_ok=True)
 atomic_jsonl(costdir/'calls.jsonl',calls);atomic_jsonl(costdir/'records.jsonl',list(new.values()))
 summary={**large,'wall_seconds':cold['wall_seconds']+large['wall_seconds'],'cache_mode':'cold_plus_incremental'}
 atomic_json(costdir/'run_summary.json',summary)
 prior=read(base/'allocation.json')['prior_committed_usd']
 costs=calculate_cost(costdir/'calls.jsonl',ROOT/'config/rates.csv',costdir/'replay',selected_reviews=200000,selected_unique_texts=unique,spending_limit_usd=48,prior_spend_usd=prior,max_workers=8)
 result['cost']=costs
 rates=load_rates(ROOT/'config/rates.csv');prices=[price_call(c,rates) for c in calls]
 doubled={k:{**v,'usd_per_million':v['usd_per_million']*2} for k,v in rates.items()}
 assert all(not p['unknown_cost'] for p in prices)
 a=sum(p['api_cost_usd'] for p in prices);b=sum(price_call(c,doubled)['api_cost_usd'] for c in calls)
 assert math.isclose(b,2*a,abs_tol=1e-10)
 result['calculator_tests']={'double_rates_double_cost':True,'measured_api_total_usd':a}
 # Provider-specific forecast and runtime use measured per-stage timings, no imaginary parallel speedup.
 primary=[c for c in calls if c['purpose']=='initial_classification'];fallback=[c for c in calls if c['purpose']=='fallback'];verify=[c for c in calls if c['role']=='verify'];fixed=[c for c in calls if c['role'] in ('group','memo')]
 unit=lambda cs:sum(c['cost_usd'] for c in cs)/len(set(x for c in cs for x in c['review_ids']))
 decisions=unit(primary)*unique;nebius=unit(fallback)*math.floor(unique*.05)+unit(verify)*2000+sum(c['cost_usd'] for c in fixed)
 rate=1/statistics.mean(c['api_duration_seconds'] for c in primary)
 result['provider_forecast']={'openai_decisions_base_usd':decisions,'openai_decisions_conservative_usd':decisions*1.5,'nebius_base_usd':nebius,'total_base_usd':decisions+nebius,'total_conservative_usd':(decisions+nebius)*1.5,'openai_credit_reported_by_user_usd':25,'openai_conservative_fits_reported_credit':decisions*1.5+sum(c['cost_usd'] for stage in ('smoke','smoke-long-prompt','100-cold','1000','human-predictions','synthetic') for c in jl(base/stage/'calls.jsonl') if c['provider']=='decisions')<=25,'first_pass_mean_input_tokens':statistics.mean(c['input_tokens'] for c in primary),'first_pass_p50_seconds':statistics.median(c['api_duration_seconds'] for c in primary),'first_pass_p95_seconds':sorted(c['api_duration_seconds'] for c in primary)[int(.95*(len(primary)-1))],'configured_aggregate_rps':8,'first_pass_pacing_floor_hours':unique/8/3600,'runtime_note':'1000 development and human side-run overlapped under shared pacing; 100-cold was isolated. Do not compare aggregate wall times as isolated model throughput.'}
 from run_model_experiment import synthetic_cases
 sr=indexed(jl(base/'synthetic/records.jsonl'));cases=[]
 for x in synthetic_cases():
  r=sr[x['source']['review_id']];diff={f:{'expected':v,'actual':r.get(f)} for f,v in x['expected'].items() if r.get(f)!=v};cases.append({'case':x['case'],'text':x['source']['review_text'],'differences':diff,'passed':not diff})
 result['synthetic']={'n':len(cases),'passed':sum(x['passed'] for x in cases),'cases':cases}
 result['new_pilot_nominal_spend_usd']=sum(c['cost_usd'] or 0 for stage in ('smoke','smoke-long-prompt','100-cold','100-warm','1000','human-predictions','synthetic') for c in jl(base/stage/'calls.jsonl'))
 # Save representative disagreements for inspection; do not invent additional human labels.
 differences=[]
 for k in new:
  if any(new[k][f]!=verifier[k][f] for f in ('topic','intent','severity')):
   differences.append({'review_id':k,'review_text':new[k]['review_text'],'old':{f:old[k][f] for f in FIELDS},'new':{f:new[k][f] for f in FIELDS},'verifier':{f:verifier[k][f] for f in FIELDS},'fallback_used':new[k].get('fallback_used'),'needs_review':new[k]['needs_review']})
 differences.sort(key=lambda r:hashlib.sha256(('decisions-v1-audit:'+r['review_id']).encode()).digest())
 atomic_json(out/'audit-candidates.json',differences[:30]);atomic_json(out/'evaluation.json',result)
 # Hash evidence after evaluation; raw labels were never read by inference runner.
 paths=[p for stage in ('100-cold','100-warm','1000','human-predictions','synthetic') for p in (base/stage).iterdir() if p.is_file() and p.suffix in ('.json','.jsonl','.csv','.md')]
 # Bind the evaluation to canonical records, calls, configuration and saved results.
 # Raw per-request handoffs remain available, but are outside this compact manifest.
 def identity(p):return str(p.relative_to(ROOT)),{'sha256':sha(p),'bytes':p.stat().st_size}
 with ThreadPoolExecutor(max_workers=16) as pool:artifacts=dict(pool.map(identity,paths))
 atomic_json(out/'sealed-artifacts.json',artifacts)
 print(json.dumps({'human':result['human_adjudicated']['pooled_descriptive'],'verifier':result['against_archived_blind_verifier'],'routing':result['routing'],'forecast':result['provider_forecast'],'synthetic':result['synthetic'],'spend':result['new_pilot_nominal_spend_usd']},indent=2))
if __name__=='__main__':main()
