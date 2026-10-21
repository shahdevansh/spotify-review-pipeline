"""Guarded, offline factual presentation corrections for the frozen hero run.

This is an editorial acceptance step, not a new model run or label correction.
Raw group/memo handoffs and classification/ranking/audit evidence are immutable.
"""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from spotify_pipeline.analysis import render_memo, validate_recommendations

VERSION = 'hero-editorial-v1'
EXPECTED_CONFIG = 'spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a'
EXPECTED_RUN = 'run-07e2cb4b0e3d9be0'
TOPICS = {'access','usability','playback','downloads','catalog','billing','support','other'}
ARTIFACTS = ('issues.json','recommendations.json','memo.md')
PROTECTED = ('records.jsonl.gz','verification.jsonl.gz','membership.csv','ranking.csv','claims.csv',
             'handoffs/group.input.json','handoffs/group.output.json','handoffs/memo.input.json','handoffs/memo.output.json')
OLD_SUMMARY = 'The dataset is a self-selected historical review sample with a large quarantined and needs-review share, so it cannot establish population prevalence, revenue at risk, or causal retention effects.'
NEW_SUMMARY = 'The dataset is a self-selected historical review sample. Empty source texts are quarantined, while a substantial share of completed reviews is flagged as needing review. The sample cannot establish population prevalence, revenue at risk, or causal retention effects.'
OLD_VOLUME = 'combines the largest complaint volume with the highest severity sum'
NEW_VOLUME = 'combines the second-largest complaint and cancellation volume with the highest severity sum'
OLD_INTERVENTION = 'A quarter focused on preventing silent library loss, adding undo and recovery affordances, and clarifying destructive controls is the highest-ranked hypothesis to test.'
NEW_INTERVENTION = 'The topic ranking supports investigating usability. Preventing silent library loss, adding undo and recovery affordances, and clarifying destructive controls are illustrative candidate interventions supported by these examples, not separately ranked subtopics; their prevalence and intervention value require further study.'
OLD_LIMIT = 'A large share of the input was quarantined or flagged as needing review, and many bounded examples carry uncertain labels, so topic assignments and severities may be unreliable.'
NEW_LIMIT = 'Empty source texts are quarantined. A substantial share of completed reviews is flagged as needing review, and many bounded examples carry uncertain labels, so topic assignments and severities may be unreliable.'
EDITORIAL_NOTE = ('\n## Editorial provenance\n\nThe displayed issue descriptions and recommendation prose received a deterministic factual presentation review after model generation. '
                  'Original model outputs, original displayed artifacts, exact field edits, and file hashes are preserved in `editorial-review.json` and `editorial-review/v1/`. '
                  'Classification labels, membership, ranking, numerical claims, and independent verification remain unchanged.\n')

def digest(path: Path) -> str:
    h=hashlib.sha256();count=0
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block);count+=len(block)
    if count != path.stat().st_size or not count:raise ValueError(f'Empty or short read: {path}')
    return h.hexdigest()

def read_json(path: Path):
    b=path.read_bytes()
    if not b or len(b)!=path.stat().st_size:raise ValueError(f'Empty or short read: {path}')
    return json.loads(b)

def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()

def atomic_bytes(path:Path,value:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.editorial-tmp')
    with tmp.open('wb') as f:f.write(value);f.flush();os.fsync(f.fileno())
    tmp.replace(path)

def build_corrections(issues,document,ranking,evidence):
    """Fail closed when the reviewed source or supporting arithmetic differs."""
    issues=copy.deepcopy(issues);document=copy.deepcopy(document);changes=[]
    assert {x['issue_id'] for x in issues}=={'issue-'+t for t in TOPICS}
    assert len(issues)==8
    counts=sorted(ranking,key=lambda r:(-int(r['complaint_count']),r['issue_id']))
    scores=sorted(ranking,key=lambda r:(-int(r['priority_score']),r['issue_id']))
    assert counts[0]['issue_id']=='issue-other' and counts[1]['issue_id']=='issue-usability'
    assert scores[0]['issue_id']=='issue-usability'
    for issue in issues:
        iid=issue['issue_id'];topic=iid.removeprefix('issue-')
        assert len(evidence[iid])==5
        for field,new in [('title',topic.capitalize()),('description',f"All complaint and cancellation reviews labeled {topic} are members of this issue. The following description summarizes five examples prioritized by severity; these examples do not establish subtopic prevalence. "+issue['description'])]:
            changes.append({'artifact':'issues.json','issue_id':iid,'field':field,'before':issue[field],'after':new})
            issue[field]=new
    def replace(path,old,new):
        obj=document
        for key in path[:-1]:obj=obj[key]
        value=obj[path[-1]]
        if value.count(old)!=1:raise ValueError(f'Expected reviewed text once at {path}')
        updated=value.replace(old,new)
        changes.append({'artifact':'recommendations.json','field_path':path,'before':value,'after':updated})
        obj[path[-1]]=updated
    replace(['summary'],OLD_SUMMARY,NEW_SUMMARY)
    replace(['recommendations',0,'rationale'],OLD_VOLUME,NEW_VOLUME)
    replace(['recommendations',0,'rationale'],OLD_INTERVENTION,NEW_INTERVENTION)
    replace(['limitations',2],OLD_LIMIT,NEW_LIMIT)
    return issues,document,changes

def apply_review(run:Path,apply:bool=False):
    manifest_path=run/'editorial-review.json'
    if manifest_path.exists():
        manifest=read_json(manifest_path)
        assert manifest['version']==VERSION
        for name,entry in manifest['artifacts'].items():
            assert digest(run/name)==entry['after_sha256'],f'Accepted artifact changed: {name}'
            assert digest(run/entry['original_path'])==entry['before_sha256'],f'Original backup changed: {name}'
        for name,h in manifest['protected_sha256'].items():assert digest(run/name)==h,f'Protected evidence changed: {name}'
        return {'status':'already_applied_verified','manifest':str(manifest_path)}
    checkpoint=read_json(run/'completed-stage.json')
    assert checkpoint['label_config']==EXPECTED_CONFIG and checkpoint['run_id']==EXPECTED_RUN
    assert (checkpoint['completed'],checkpoint['quarantined'],checkpoint['pending'])==(200000,13,0)
    assert checkpoint['stages']['verify']['completed']==40000 and checkpoint['stages']['verify']['failed']==0
    with (run/'ranking.csv').open(newline='') as f:ranking=list(csv.DictReader(f))
    with (run/'claims.csv').open(newline='') as f:claims=list(csv.DictReader(f))
    original_issues=read_json(run/'issues.json');original_document=read_json(run/'recommendations.json')
    raw_group=read_json(run/'handoffs/group.output.json');raw_memo=read_json(run/'handoffs/memo.output.json')
    evidence=read_json(run/'handoffs/group.input.json')['evidence']
    assert sorted(original_issues,key=lambda x:x['issue_id'])==sorted(raw_group['issues'],key=lambda x:x['issue_id'])
    assert original_document==raw_memo
    assert (run/'memo.md').read_text()==render_memo(original_document,{'claims':claims})
    original_bytes={name:(run/name).read_bytes() for name in ARTIFACTS}
    before={name:digest(run/name) for name in ARTIFACTS}
    protected={name:digest(run/name) for name in PROTECTED}
    new_issues,new_document,changes=build_corrections(original_issues,original_document,ranking,evidence)
    validate_recommendations(new_document,{'ranking':ranking,'claims':claims},evidence)
    accepted={'issues.json':encoded(new_issues),'recommendations.json':encoded(new_document),
              'memo.md':(render_memo(new_document,{'claims':claims})+EDITORIAL_NOTE).encode()}
    manifest={'version':VERSION,'run_id':EXPECTED_RUN,'label_config':EXPECTED_CONFIG,'created_at_utc':datetime.now(timezone.utc).isoformat(),
              'authorization':'User-authorized autonomous final publication; root explicitly authorized factual editorial correction after read-only audit.',
              'scope':'Presentation only; preserves original model handoffs and all classification, membership, ranking, claim and independent verification evidence.',
              'reason':'Correct false largest-volume claim, distinguish empty quarantines from review flags, avoid subtopic ranking and prevalence implications from severity-prioritized examples.',
              'changes':changes,'rendered_memo_note':EDITORIAL_NOTE.strip(),'protected_sha256':protected,
              'artifacts':{name:{'before_sha256':before[name],'after_sha256':hashlib.sha256(accepted[name]).hexdigest(),'original_path':'editorial-review/v1/original/'+name} for name in ARTIFACTS}}
    if not apply:return {'status':'validated_dry_run','changes':len(changes),'artifacts':manifest['artifacts']}
    for name,b in original_bytes.items():
        backup=run/manifest['artifacts'][name]['original_path']
        if backup.exists():assert digest(backup)==before[name],f'Conflicting original backup: {name}'
        else:atomic_bytes(backup,b)
    for name,h in protected.items():assert digest(run/name)==h
    for name,b in accepted.items():atomic_bytes(run/name,b)
    for name,h in protected.items():assert digest(run/name)==h
    atomic_bytes(manifest_path,encoded(manifest))
    for name,entry in manifest['artifacts'].items():assert digest(run/name)==entry['after_sha256']
    return {'status':'applied_verified','changes':len(changes),'manifest':str(manifest_path),'artifacts':manifest['artifacts'],'protected_files_unchanged':len(protected)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Apply reviewed presentation corrections; otherwise validate only.')
    args=parser.parse_args();print(json.dumps(apply_review(args.run_dir,args.apply),indent=2))
if __name__=='__main__':main()
