#!/usr/bin/env python3
"""Durable bounded hero supervisor. No model calls unless --execute-paid.

Each stage is a separate process; SQLite owns recovery and total spending.
Human labels are never loaded by this runner. Review text is untrusted data.
"""
import argparse,asyncio,csv,hashlib,json,math,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from spotify_pipeline.engine import Engine,load_config
from spotify_pipeline.data import read_reviews
from spotify_pipeline.storage import atomic_json,atomic_jsonl,utcnow,BudgetLedger
from spotify_pipeline.analysis import run_analysis
BASE=ROOT/'runs/hero-v1'
RUNBASE=BASE

def jl(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def status(state,**details):
 BASE.mkdir(parents=True,exist_ok=True)
 atomic_json(BASE/'status.json',{'state':state,'updated_at':utcnow(),'supervisor_pid':os.getpid(),**details})
 print(json.dumps({'state':state,**details}),flush=True)

def evaluation(directory):
 entries=jl(directory/'verification.jsonl');n=len(entries);out={'n':n,'reference':'blind independent model; not human ground truth','failed':sum(x['status']!='completed' for x in entries)}
 for f in ('topic','intent','severity'):
  ok=sum(x['status']=='completed' and f not in x['differences'] and 'enrichment_status' not in x['differences'] for x in entries)
  p=ok/n if n else 0;z=1.96;den=1+z*z/n if n else 1
  center=(p+z*z/(2*n))/den if n else 0;half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den if n else 0
  out[f]={'matches':ok,'denominator':n,'agreement':p,'wilson_95':[center-half,center+half]}
 out['targets_met']=out['topic']['agreement']>.90 and out['intent']['agreement']>.93
 atomic_json(directory/'evaluation.json',out);return out

def prepare():
 p=ROOT/'data/hero_200000.csv'
 if p.exists():return p
 source=list(read_reviews(ROOT/'data/selected_210000.csv'));rows=[r for r in source if r['review_text'].strip()][:200000]
 empty=[r for r in source if not r['review_text'].strip()]
 assert len(rows)==200000 and len(empty)==13
 fields=list(rows[0]);
 with p.open('w',newline='',encoding='utf-8') as h:
  w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows+empty)
 atomic_json(BASE/'selection.json',{'nonempty':200000,'empty':13,'unique_texts':len({r['review_text'] for r in rows}),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'selection':'first 200000 nonempty rows of existing SHA-256 ordered 210000 cohort; all source empty rows retained'})
 return p

async def stage(args):
 load_dotenv(ROOT/'.env');c=load_config(ROOT/args.config)
 db=ROOT/'data/hero-v1.sqlite3';name=args.stage
 if name in ('cold100','warm100'):rows=list(read_reviews(ROOT/'data/source/cost_100.csv'));sample=20
 elif name=='checkpoint500':rows=list(read_reviews(ROOT/'data/source/checkpoint_500.csv'));sample=100
 elif name=='pilot1000':rows=list(read_reviews(ROOT/'data/learning_1000.csv'));sample=200
 elif name=='confirmation1000':
  used={r['review_id'] for r in read_reviews(ROOT/'data/learning_1000.csv')}
  rows=[r for r in read_reviews(ROOT/'data/source/analysis_10000.csv') if r['review_id'] not in used][:1000];sample=200
 else:
  allrows=list(read_reviews(prepare()));rows=allrows if args.count==200000 else allrows[:args.count];sample=40000 if name=='final' else 2000 if args.count==10000 else 0
 out=RUNBASE/('run' if name in ('hero','final') else name)
 e=Engine(c,db,out,budget_usd=46,workers=1 if name in ('cold100','warm100') else 16)
 try:
  if shutil.disk_usage(ROOT).free<500_000_000:raise RuntimeError('Less than 500 MB free; offload verified trace archives before continuing')
  records=await e.enrich(rows,phase='initial' if name=='cold100' else 'resume')
  s=e.finish();print(json.dumps({'stage':name,'count':len(rows),'summary':s}),flush=True)
  if s['pending'] or s['quarantined']>sum(not r['review_text'].strip() for r in rows):raise RuntimeError('Unresolved enrichment records; durable progress retained')
  if sample:
   await e.verify(rows,records,sample)
   if e.stages['verify']['completed']!=sample:raise RuntimeError('Independent audit incomplete; required sample coverage retained as a blocker')
   ev=evaluation(out);print(json.dumps({'evaluation':ev}),flush=True)
  if name in ('cold100','warm100','pilot1000','confirmation1000','final'):
   await run_analysis(records,out,e.model_task)
  s=e.finish();s['input_path']=str(ROOT/'data/hero_200000.csv') if name in ('hero','final') else None
  atomic_json(out/'run_summary.json',s);atomic_json(out/'completed-stage.json',s)
  if name=='warm100' and s['requests']:raise RuntimeError('Warm run made paid calls')
 finally:await e.close()

def invoke(stage_name,count=0,config='config/hero.json',variant=''):
 cmd=[sys.executable,__file__,'--execute-paid','--stage',stage_name,'--count',str(count),'--config',config,'--variant',variant]
 status('running',stage=stage_name,count=count,config=config)
 with (BASE/f'{stage_name}-{count}.log').open('a') as h:subprocess.run(cmd,cwd=ROOT,stdout=h,stderr=subprocess.STDOUT,check=True)

def projection():
 calls=jl(BASE/'pilot1000/calls.jsonl')
 verify=[x for x in calls if x['role']=='verify'];n=sum(len(x['review_ids']) for x in verify if x['outcome']=='succeeded')
 verification=sum(x.get('cost_usd') or x.get('unknown_charge_hold_usd',0) for x in verify)/n*40000
 e=load_config(ROOT/'config/hero.json');ledger=BudgetLedger(ROOT/'data/spend.sqlite3');spent=ledger.totals();ledger.close()
 selection=json.loads((BASE/'selection.json').read_text());unique=selection['unique_texts']
 # Prior pilot measured ~1126 input tokens/text; use 1500 and 10% audit contingency.
 enrich=unique*1500*.1/1e6
 estimate=spent['committed_usd']+enrich+verification*1.1+3
 out={'committed':spent,'enrichment_conservative':enrich,'frontier_audit_base':verification,'other_reserved':3,'total_conservative':estimate,'ceiling':48}
 atomic_json(BASE/'projection.json',out)
 if estimate>48:raise RuntimeError('Measured 20% frontier verification exceeds $48 operating budget: '+json.dumps(out))
 return out

def finalize():
 from spotify_pipeline.export import export_grading
 from spotify_pipeline.database import import_run
 load_dotenv(ROOT/'.env')
 out=BASE/'run';grading=BASE/'grading';source=ROOT/'data/source/spotify_reviews_18months.csv';analysis=prepare()
 export_grading(out,grading,source_path=source,analysis_path=analysis)
 checker=ROOT/'vendor/course/check_submission.py'
 for command in [['reference','--full',str(source),'--analysis',str(analysis),'--out',str(BASE/'reference.json')],['check','--reference',str(BASE/'reference.json'),'--submission',str(grading),'--out',str(BASE/'checker.json')]]:
  subprocess.run([sys.executable,str(checker),*command],check=True,cwd=ROOT)
 check=json.loads((BASE/'checker.json').read_text())
 if check.get('status')!='pass':raise RuntimeError('Submission checker did not pass')
 publication=import_run(out,ingestion_report=grading/'ingestion.json',evaluation_path=out/'evaluation.json')
 atomic_json(BASE/'database-publication.json',publication)
 if publication['storage_bytes']>700_000_000:raise RuntimeError('Published database exceeds conservative storage threshold')
 # Public release contains course reviews and model evidence only, never human annotations or secrets.
 package=BASE/'release';package.mkdir(exist_ok=True)
 for src in [grading,out/'evaluation.json',out/'recommendations.json',BASE/'checker.json',BASE/'projection.json',BASE/'selection.json',BASE/'database-publication.json']:
  if src.is_dir():shutil.copytree(src,package/src.name,dirs_exist_ok=True)
  else:shutil.copyfile(src,package/src.name)
 archive=shutil.make_archive(str(BASE/'spotify-hero-evidence'),'zip',package)
 notes=BASE/'release-notes.md';ev=json.loads((out/'evaluation.json').read_text());s=json.loads((out/'run_summary.json').read_text())
 notes.write_text(f"Classified {s['completed']:,} selected reviews; 13 explicit empty-text quarantines. Independent frontier audit: {ev['n']:,} original IDs (20%). Topic agreement {ev['topic']['agreement']:.2%}; intent {ev['intent']['agreement']:.2%}. These are model-agreement diagnostics, not human accuracy. Full source profiled separately. See attached grading evidence and checker. Dashboard: https://spotify-review-observatory.vercel.app\n")
 subprocess.run(['gh','release','create','hero-v1',archive,'--title','200,000-review hero run','--notes-file',str(notes)],check=True,cwd=ROOT)
 status('completed',completed=s['completed'],evaluation=ev,dashboard='https://spotify-review-observatory.vercel.app',release='https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1')

def supervisor():
 BASE.mkdir(parents=True,exist_ok=True);prepare()
 for name in ('cold100','warm100','checkpoint500','pilot1000'):
  if not (BASE/name/'completed-stage.json').exists():invoke(name)
 projection()
 ev=json.loads((BASE/'pilot1000/evaluation.json').read_text())
 # One bounded revision: expand confidence-ranked whole-record fallback. No label overrides.
 if not ev['targets_met'] and not (BASE/'quality-decision.json').exists():
  initial=json.loads((ROOT/'config/hero.json').read_text())
  candidate={**initial,'fallback_fraction':.15,'maximum_fallback_fraction':.15,'uncertainty_threshold':.70,'prompt_version':'hero-frontier-v2'}
  candidate_path=ROOT/'config/hero-candidate.json';atomic_json(candidate_path,candidate)
  for name in ('cold100','warm100','checkpoint500','pilot1000'):
   if not (BASE/'candidate-v2'/name/'completed-stage.json').exists():invoke(name,config='config/hero-candidate.json',variant='candidate-v2')
  revised=json.loads((BASE/'candidate-v2/pilot1000/evaluation.json').read_text())
  # Compare on the same blind development sample; final confirmation uses fresh texts.
  def utility(x):return x['topic']['agreement']+x['intent']['agreement']
  accept=utility(revised)>utility(ev) and revised['topic']['agreement']>=ev['topic']['agreement']-.01 and revised['intent']['agreement']>=ev['intent']['agreement']-.01
  if accept:atomic_json(ROOT/'config/hero.json',candidate)
  atomic_json(BASE/'quality-decision.json',{'targets_met':(revised if accept else ev)['targets_met'],'candidate_accepted':accept,'initial':ev,'candidate':revised,'decision':'select higher joint development agreement with at most 1pp per-field regression; fresh confirmation and full hero audit remain independent; unmet targets disclosed'})
 else:
  if not (BASE/'quality-decision.json').exists():atomic_json(BASE/'quality-decision.json',{'targets_met':ev['targets_met'],'candidate_accepted':False,'initial':ev})
 projection()
 if not (BASE/'confirmation1000/completed-stage.json').exists():invoke('confirmation1000')
 for count in range(10000,200001,10000):
  marker=BASE/f'checkpoint-{count}.json'
  if marker.exists():continue
  invoke('hero',count)
  shutil.copyfile(BASE/'run/run_summary.json',marker)
  # Each checkpoint offers a closed trace segment to the Drive offload monitor.
  atomic_json(BASE/'offload-request.json',{'checkpoint':count,'directory':str(BASE/'run/handoffs'),'preserve_task_json':True})
 invoke('final',200000);status('publishing');finalize()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute-paid',action='store_true');p.add_argument('--stage');p.add_argument('--count',type=int,default=0);p.add_argument('--config',default='config/hero.json');p.add_argument('--variant',default='');a=p.parse_args()
 if not a.execute_paid:p.error('--execute-paid is required')
 os.chdir(ROOT)
 if a.variant:
  if a.variant != "candidate-v2":raise ValueError("Unknown variant")
  RUNBASE=BASE/a.variant;RUNBASE.mkdir(parents=True,exist_ok=True)
 try:
  if a.stage:asyncio.run(stage(a))
  else:supervisor()
 except BaseException as exc:
  status('blocked',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc(),resume='Rerun the same supervisor; completed checkpoints are skipped and caches persist.')
  raise
