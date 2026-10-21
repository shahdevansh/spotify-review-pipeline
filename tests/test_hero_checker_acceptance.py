"""Synthetic tests: unavailable failed-call usage is disclosed, never replaced."""
import hashlib
import json
from pathlib import Path

import pytest
from test_hero_gzip_tools import load_tool, write_json, write_gzip_jsonl


def setup(tmp_path, monkeypatch, calls=None):
    hero=load_tool('run_hero')
    calls=calls or [{'request_id':'s','outcome':'succeeded','input_tokens':20,'output_tokens':5},
                   {'request_id':'f','outcome':'failed','input_tokens':None,'output_tokens':None}]
    grading=tmp_path/'grading'; grading.mkdir()
    write_gzip_jsonl(grading/'calls.jsonl',calls)
    write_json(grading/'records.jsonl',{'synthetic':True})
    reference=tmp_path/'reference.json';write_json(reference,{'synthetic':'reference'})
    checker=tmp_path/'checker.py';checker.write_text('synthetic unmodified checker')
    contract=tmp_path/'contract.md';contract.write_text(hero.UNAVAILABLE_USAGE_CONTRACT)
    monkeypatch.setattr(hero,'COURSE_CHECKER_SHA256',hero.checked_file_sha(checker))
    monkeypatch.setattr(hero,'COURSE_CONTRACT_SHA256',hero.checked_file_sha(contract))
    n=sum(e.get(k) is None for e in calls for k in ('input_tokens','output_tokens'))
    report={'audit_script_sha256':hero.COURSE_CHECKER_SHA256,
        'reference_sha256':hashlib.sha256(json.dumps({'synthetic':'reference'},ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()).hexdigest(),
        'coverage':{'expected':200013,'received_lines':200013,'unique_expected_ids':200013,'valid_completed':200000,'quarantined':13,'labelable':200000,'missing':0,'duplicate_ids':0,'invalid_or_unresolved':0,'accounted_fraction':1.0,'labelable_completion_fraction':1.0},
        'input_files_sha256':{p.name:hero.checked_file_sha(p) for p in grading.iterdir()},
        'issue_counts':{'invalid_usage':n} if n else {},'status':'review_required' if n else 'pass',
        'reported_calls':len(calls),'reported_input_tokens':sum(e.get('input_tokens') or 0 for e in calls),
        'reported_output_tokens':sum(e.get('output_tokens') or 0 for e in calls),'examples':[]}
    report_path=tmp_path/'checker.json';write_json(report_path,report)
    return hero,report,report_path,grading,reference,checker,contract


def run(fixture):
    hero,report,report_path,*paths=fixture
    write_json(report_path,report)
    return hero.publication_checker_acceptance(report_path,*paths)


def test_accepts_only_disclosed_failed_unknown_usage_and_preserves_every_byte(tmp_path,monkeypatch):
    f=setup(tmp_path,monkeypatch)
    before={p:p.read_bytes() for p in f[3].iterdir()}
    result=run(f)
    assert result['status']=='publication_eligible_with_unknown_usage'
    assert result['instructor_checker_status']=='review_required'
    assert result['unavailable_usage_attempts']==1
    assert result['unavailable_usage_fields']==2
    assert result['failed_calls_with_unavailable_usage']==[{'request_id':'f','outcome':'failed','unavailable_fields':['input_tokens','output_tokens']}]
    assert result['usage_totals_complete'] is False
    assert result['known_reported_input_tokens']==20
    assert all(p.read_bytes()==data for p,data in before.items())
    assert f[1]['status']=='review_required'


def test_real_checker_pass_stays_distinct(tmp_path,monkeypatch):
    result=run(setup(tmp_path,monkeypatch,[{'request_id':'s','outcome':'succeeded','input_tokens':20,'output_tokens':5}]))
    assert result['status']=='publication_eligible_checker_pass'
    assert result['usage_totals_complete'] is True


@pytest.mark.parametrize('value',[-1,1.2,True,'0'])
def test_rejects_malformed_numeric_usage(tmp_path,monkeypatch,value):
    f=setup(tmp_path,monkeypatch)
    write_gzip_jsonl(f[3]/'calls.jsonl',[{'request_id':'f','outcome':'failed','input_tokens':value,'output_tokens':None}])
    f[1]['input_files_sha256']['calls.jsonl.gz']=f[0].checked_file_sha(f[3]/'calls.jsonl.gz')
    with pytest.raises(ValueError,match='Malformed numeric'):run(f)


@pytest.mark.parametrize('outcome',['succeeded','pending',None])
def test_rejects_unknown_usage_on_nonfailed_calls(tmp_path,monkeypatch,outcome):
    f=setup(tmp_path,monkeypatch,[{'request_id':'f','outcome':outcome,'input_tokens':None,'output_tokens':None}])
    with pytest.raises(ValueError,match='Successful or unresolved'):run(f)


@pytest.mark.parametrize('mutation',[
    lambda r:r['issue_counts'].update({'ranking_mismatch':1}),
    lambda r:r['issue_counts'].update({'invalid_usage':3}),
    lambda r:r.update(status='pass'),
    lambda r:r.update(reported_calls=3),
    lambda r:r.update(reported_input_tokens=21),
    lambda r:r.update(reported_output_tokens=6),
    lambda r:r['coverage'].update(valid_completed=199999),
    lambda r:r['coverage'].update(duplicate_ids=1),
    lambda r:r['coverage'].update(missing=1),
    lambda r:r['coverage'].update(invalid_or_unresolved=1),
    lambda r:r['coverage'].update(quarantined=14),
    lambda r:r['coverage'].update(accounted_fraction=.99),
    lambda r:r.update(reference_sha256='0'*64),
    lambda r:r.update(audit_script_sha256='0'*64),
    lambda r:r.update(examples=[{'code':'invalid_usage','detail':'foreign'}]),
])
def test_rejects_any_unexplained_checker_or_identity_problem(tmp_path,monkeypatch,mutation):
    f=setup(tmp_path,monkeypatch);mutation(f[1])
    with pytest.raises(ValueError):run(f)


@pytest.mark.parametrize('file_index',[3,4,5,6])
def test_rejects_changed_evidence_reference_checker_or_contract(tmp_path,monkeypatch,file_index):
    f=setup(tmp_path,monkeypatch);path=f[file_index]
    if path.is_dir():path=path/'records.jsonl'
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError):run(f)


def test_missing_key_is_unavailable_not_zero(tmp_path,monkeypatch):
    result=run(setup(tmp_path,monkeypatch,[{'request_id':'f','outcome':'failed','output_tokens':8}]))
    assert result['unavailable_usage_fields']==1
    assert result['known_reported_output_tokens']==8
    assert result['usage_totals_complete'] is False


def test_rejects_inflight_placeholder(tmp_path,monkeypatch):
    f=setup(tmp_path,monkeypatch,[{'request_id':'f','outcome':'failed','input_tokens':None,'output_tokens':None,'error':'in_flight_or_interrupted'}])
    with pytest.raises(ValueError,match='placeholder'):run(f)


def test_rejects_evidence_change_while_reading_calls(tmp_path,monkeypatch):
    f=setup(tmp_path,monkeypatch);hero=f[0];reader=hero.read_jsonl
    def changing_reader(path):
        yield from reader(path)
        (f[3]/'records.jsonl').write_text('{"changed_during_validation":true}')
    monkeypatch.setattr(hero,'read_jsonl',changing_reader)
    with pytest.raises(ValueError,match='changed during'):run(f)


def test_rejects_duplicate_call_identity(tmp_path,monkeypatch):
    f=setup(tmp_path,monkeypatch,[{'request_id':'f','outcome':'failed','input_tokens':None,'output_tokens':None},{'request_id':'f','outcome':'failed','input_tokens':None,'output_tokens':None}])
    with pytest.raises(ValueError,match='duplicate call identity'):run(f)


def test_acceptance_proof_is_in_explicit_package_allowlist(tmp_path,monkeypatch):
    import zipfile
    from test_hero_gzip_tools import prepare_package_fixture
    hero,base=prepare_package_fixture(tmp_path,monkeypatch)
    payload=b'{"status":"synthetic-publication-eligible"}'
    (base/'checker-acceptance.json').write_bytes(payload)
    with zipfile.ZipFile(hero.package_evidence()) as archive:
        assert archive.read('checker-acceptance.json')==payload
