"""Offline safeguards for the explicitly authorized hero configuration."""
import gzip,json
from pathlib import Path
import pytest
from spotify_pipeline.engine import Engine,load_config
from spotify_pipeline.nebius import NebiusProvider
ROOT=Path(__file__).resolve().parents[1]

def test_frontier_explicit_low_and_bounded_configuration():
 c=load_config(ROOT/'config/hero.json')
 assert c['models']['verify']=='zai-org/GLM-5.3'
 assert c['reasoning_effort']['verify']=='low'
 assert c['global_budget_usd']==48
 assert c['max_reviews_by_role']['verify']<=50
 assert all(c['providers'][r]=='nebius' for r in ('fallback','verify','group','memo'))
 body=NebiusProvider.build_request('zai-org/GLM-5.3','rubric',{'reviews':[]},{'type':'object','properties':{},'additionalProperties':False},reasoning_effort='low')
 assert body['reasoning_effort']=='low'
 with pytest.raises(ValueError):NebiusProvider.build_request('zai-org/GLM-5.3','rubric',{}, {'type':'object'})

def test_lossless_compressed_trace(tmp_path):
 e=object.__new__(Engine);e.config={'gzip_handoffs':True}
 value={'role':'verify','body':{'text':'Multiline\nUnicode café 音楽','reviews':[]}}
 p=tmp_path/'request.json';e._save_handoff(p,value)
 assert not p.exists()
 assert json.load(gzip.open(str(p)+'.gz','rt'))==value
 assert not list(tmp_path.glob('*.tmp'))
