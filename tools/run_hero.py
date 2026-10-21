#!/usr/bin/env python3
"""Durable bounded hero supervisor. No model calls unless --execute-paid.

Each stage is a separate process; SQLite owns recovery and total spending.
Human labels are never loaded by this runner. Review text is untrusted data.
"""
import argparse,asyncio,csv,hashlib,json,math,os,shutil,sqlite3,subprocess,sys,time,traceback,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from spotify_pipeline.engine import Engine,load_config,fingerprint,text_hash
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
 # Match the dashboard's public model-comparison schema without changing saved labels.
 out.update(status='compared',comparison_type='independent_model_agreement',ground_truth=False,
  verified_count=n,comparable_count=sum(x['status']=='completed' and 'enrichment_status' not in x['differences'] for x in entries),
  disagreement_count=sum(bool(x['differences']) for x in entries),
  field_agreement={f:out[f]['agreement'] for f in ('topic','intent','severity')},
  limitations=['Independent model agreement is not human accuracy.',
   'Failed or unavailable comparisons remain in the agreement denominator.',
   'The independent verifier and fallback share a model family; correlated errors remain possible.',
   'Sentiment and review-flag agreement are not measured by this summary.'])
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
 cohort_texts={text_hash(row['review_text']) for row in read_reviews(ROOT/'data/hero_200000.csv') if row['review_text'].strip()}
 if len(cohort_texts)!=unique:raise RuntimeError('Hero selection distinct-text count changed')
 completed_texts=set();db=ROOT/'data/hero-v1.sqlite3'
 if db.exists():
  with sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True) as connection:
   completed_texts={row[0] for row in connection.execute("SELECT DISTINCT text_hash FROM records WHERE config=? AND json_extract(record_json,'$.status')='completed'",(fingerprint(e),))}
 completed_unique=len(cohort_texts & completed_texts);remaining_unique=unique-completed_unique
 # Prior pilot measured ~1126 input tokens/text; use 1500 and 10% audit contingency.
 # Already-paid hero work is in committed_usd; only remaining exact texts need forecasting.
 enrich=remaining_unique*1500*.1/1e6
 estimate=spent['committed_usd']+enrich+verification*1.1+3
 out={'committed':spent,'selected_unique_texts':unique,'completed_unique_texts':completed_unique,'remaining_unique_texts':remaining_unique,'enrichment_conservative':enrich,'frontier_audit_base':verification,'other_reserved':3,'total_conservative':estimate,'ceiling':48}
 atomic_json(BASE/'projection.json',out)
 if estimate>48:raise RuntimeError('Measured 20% frontier verification exceeds $48 operating budget: '+json.dumps(out))
 return out

def preserve_grading_checkpoint(grading):
 """Export a real saved initial boundary instead of the final no-op resume snapshot."""
 choice=json.loads((BASE/'quality-decision.json').read_text())
 initial=BASE/('candidate-v2/cold100' if choice['candidate_accepted'] else 'cold100')
 before=json.loads((initial/'checkpoint_after.json').read_text())
 after=json.loads((BASE/'run/checkpoint_after.json').read_text())
 before_ids=set(before['completed_ids']);after_ids=set(after['completed_ids'])
 if not before_ids or not before_ids<after_ids:raise RuntimeError('Saved cold checkpoint is not a strict subset of final progress')
 if before.get('label_config')!=after.get('label_config'):raise RuntimeError('Checkpoint configurations differ')
 completed={}
 with (grading/'records.jsonl').open() as handle:
  for line in handle:
   if not line.strip():continue
   r=json.loads(line)
   if r['status']=='completed':completed[r['review_id']]={'label_config':r['label_config'],'cache_source_id':r.get('cache_source_id')}
 if not after_ids<=completed.keys():raise RuntimeError('Final checkpoint contains non-completed grading IDs')
 if any(completed[rid]['label_config']!=before.get('label_config') for rid in before_ids):raise RuntimeError('Saved checkpoint classification configuration differs from final records')
 initial_ids=set();resumed_ids=set()
 with (grading/'calls.jsonl').open() as handle:
  for line in handle:
   if not line.strip():continue
   call=json.loads(line)
   if call['role']!='enrich':continue
   ids=set(call['review_ids'])
   if call.get('phase')=='resume' and before_ids & ids:raise RuntimeError('Saved initial checkpoint was reprocessed during resume')
   if call['outcome']=='succeeded':
    matching={rid for rid in ids if rid in completed and call['label_config']==completed[rid]['label_config']}
    if call.get('phase')=='initial':initial_ids.update(matching)
    elif call.get('phase')=='resume':resumed_ids.update(matching)
 cached={rid for rid,r in completed.items() if r.get('cache_source_id')}
 if before_ids-cached-initial_ids or not ((after_ids-before_ids-cached)&resumed_ids):raise RuntimeError('Saved checkpoint lacks matching initial/resume call evidence')
 shutil.copyfile(initial/'checkpoint_after.json',grading/'checkpoint_before.json')
 atomic_json(BASE/'grading-checkpoint-provenance.json',{'before_source':str(initial.relative_to(ROOT)/'checkpoint_after.json'),'after_source':'runs/hero-v1/run/checkpoint_after.json','before_completed':len(before_ids),'after_completed':len(after_ids),'note':'Exact saved cold-run completion boundary; subsequent processes resumed this configuration from persistent SQLite. Final no-op resume snapshots are not used as interruption evidence. Separate recovery recording is packaged under recovery/.'})

def package_evidence():
 """Build the public release offline; never run inference or publish a database."""
 out=BASE/'run';grading=BASE/'grading';pilot=ROOT/'evals/hero-pilot'
 # Explicit destinations preserve the assignment's sibling grading/, cost/, evals/ layout.
 required=[
  grading/'run.json',grading/'ingestion.json',grading/'records.jsonl',grading/'calls.jsonl',
  grading/'membership.csv',grading/'ranking.csv',grading/'claims.csv',
  grading/'checkpoint_before.json',grading/'checkpoint_after.json',
  pilot/'cold100/report.json',pilot/'cold100/rates.csv',pilot/'cold100/pilot_calls.jsonl',
  pilot/'cold100/pilot_records.jsonl',pilot/'cold100/run_summary.json',
  pilot/'warm100/report.json',pilot/'warm100/run_summary.json',
  out/'evaluation.json',out/'verification.jsonl',out/'disagreements.jsonl',
  out/'configuration.json',out/'run_summary.json',out/'recommendations.json',out/'memo.md',
  BASE/'checker.json',BASE/'database-publication.json',BASE/'recovery.cast',
  BASE/'recovery/recovery-validation.json',BASE/'recovery/checkpoint_before.json',
  BASE/'recovery/checkpoint_after.json',BASE/'recovery/calls.jsonl',
 ]
 missing=[str(p.relative_to(ROOT)) for p in required if not p.is_file()]
 if missing:raise RuntimeError('Cannot package incomplete final evidence: '+', '.join(missing))
 package_sources=[(grading,'grading'),(pilot,'evals/hero-pilot'),
  (pilot/'cold100','cost'),(pilot/'warm100','cost/warm100')]
 for name in ('evaluation.json','verification.jsonl','disagreements.jsonl'):
  package_sources.append((out/name,'evals/hero/'+name))
 for name in ('configuration.json','run_summary.json'):
  package_sources.append((out/name,'run/'+name))
 for name in ('recommendations.json','memo.md','issues.json'):
  package_sources.append((out/name,name))
 for name in ('checker.json','projection.json','selection.json','database-publication.json','quality-decision.json','grading-checkpoint-provenance.json','recovery.cast'):
  package_sources.append((BASE/name,name))
 for name in ('recovery-validation.json','checkpoint_before.json','checkpoint_after.json','calls.jsonl','configuration.json','run_summary.json'):
  package_sources.append((BASE/'recovery'/name,'recovery/'+name))
 archive=BASE/'spotify-hero-evidence.zip';temporary=archive.with_suffix('.zip.tmp')
 names=set()
 # Stream directly into ZIP: avoid a second large staging copy on the constrained Mac.
 with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
  for source,destination in package_sources:
   if not source.exists():continue
   files=sorted(source.rglob('*')) if source.is_dir() else [source]
   for child in files:
    if not child.is_file():continue
    if child.is_symlink():raise RuntimeError('Release evidence must not contain symlinks: '+str(child))
    member=str(Path(destination)/child.relative_to(source)) if source.is_dir() else destination
    if member in names:raise RuntimeError('Duplicate release member: '+member)
    names.add(member);z.write(child,member)
 with zipfile.ZipFile(temporary) as z:
  bad=z.testzip()
  if bad is not None:raise RuntimeError('Release archive integrity failure: '+bad)
  if not all(any(n.startswith(prefix) for n in names) for prefix in ('grading/','cost/','evals/','recovery/')):
   raise RuntimeError('Release archive is missing a required evidence directory')
 temporary.replace(archive)
 return archive

def finalize():
 from spotify_pipeline.export import export_grading
 from spotify_pipeline.database import import_run
 load_dotenv(ROOT/'.env')
 out=BASE/'run';grading=BASE/'grading';source=ROOT/'data/source/spotify_reviews_18months.csv';analysis=prepare()
 export_grading(out,grading,source_path=source,analysis_path=analysis)
 preserve_grading_checkpoint(grading)
 checker=ROOT/'vendor/course/check_submission.py'
 for command in [['reference','--full',str(source),'--analysis',str(analysis),'--out',str(BASE/'reference.json')],['check','--reference',str(BASE/'reference.json'),'--submission',str(grading),'--out',str(BASE/'checker.json')]]:
  subprocess.run([sys.executable,str(checker),*command],check=True,cwd=ROOT)
 check=json.loads((BASE/'checker.json').read_text())
 if check.get('status')!='pass':raise RuntimeError('Submission checker did not pass')
 publication=import_run(out,ingestion_report=grading/'ingestion.json',evaluation_path=out/'evaluation.json')
 atomic_json(BASE/'database-publication.json',publication)
 if publication['storage_bytes']>700_000_000:raise RuntimeError('Published database exceeds conservative storage threshold')
 # Public release contains course reviews and model evidence only, never human annotations or secrets.
 archive=package_evidence()
 notes=BASE/'release-notes.md';ev=json.loads((out/'evaluation.json').read_text());s=json.loads((out/'run_summary.json').read_text())
 notes.write_text(f"Classified {s['completed']:,} selected reviews; 13 explicit empty-text quarantines. Independent frontier audit: {ev['n']:,} original IDs (20%). Topic agreement {ev['topic']['agreement']:.2%}; intent {ev['intent']['agreement']:.2%}. These are model-agreement diagnostics, not human accuracy. Full source profiled separately. See attached grading evidence and checker. Dashboard: https://spotify-review-observatory.vercel.app\n")
 exists=subprocess.run(['gh','release','view','hero-v1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=ROOT).returncode==0
 if exists:
  subprocess.run(['gh','release','upload','hero-v1',str(archive),'--clobber'],check=True,cwd=ROOT)
  subprocess.run(['gh','release','edit','hero-v1','--notes-file',str(notes),'--draft=false'],check=True,cwd=ROOT)
 else:
  subprocess.run(['gh','release','create','hero-v1',str(archive),'--title','200,000-review hero run','--notes-file',str(notes)],check=True,cwd=ROOT)
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
  status('checkpoint_complete',count=count,completed=json.loads(marker.read_text())['completed'])
  # Each checkpoint offers a closed trace segment to the Drive offload monitor.
  atomic_json(BASE/'offload-request.json',{'checkpoint':count,'directory':str(BASE/'run/handoffs'),'preserve_task_json':True})
 invoke('final',200000);status('publishing');finalize()

if __name__=='__main__':
 p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--execute-paid',action='store_true');mode.add_argument('--package-only',action='store_true',help='Rebuild final release ZIP offline; no inference, database, or GitHub calls');p.add_argument('--stage');p.add_argument('--count',type=int,default=0);p.add_argument('--config',default='config/hero.json');p.add_argument('--variant',default='');a=p.parse_args()
 os.chdir(ROOT)
 if a.package_only:
  if a.stage or a.variant or a.count:p.error('--package-only cannot be combined with stage/variant/count')
  print(package_evidence());sys.exit(0)
 if a.variant:
  if a.variant != "candidate-v2":raise ValueError("Unknown variant")
  RUNBASE=BASE/a.variant;RUNBASE.mkdir(parents=True,exist_ok=True)
 try:
  if a.stage:asyncio.run(stage(a))
  else:supervisor()
 except BaseException as exc:
  status('blocked',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc(),resume='Rerun the same supervisor; completed checkpoints are skipped and caches persist.')
  raise
