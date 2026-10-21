import copy
import httpx
import pytest
from spotify_pipeline.decisions import DecisionsProvider
from spotify_pipeline.providers import MalformedProviderResponse, RefusedProviderResponse
from spotify_pipeline.engine import Engine, load_config

def response():
 body=DecisionsProvider.build_request('Synthetic review','Rubric')
 answers=[]
 for q in body['questions']:
  values=[x['value'] for x in q['choices']] if q['type']=='choice' else list(range(5))
  probs=[{'value':v,'probability':float(i==0)} for i,v in enumerate(values)]
  answers.append(dict(name=q['name'],type=q['type'],confidence=.8,probabilities=probs,**({'choice':values[0]} if q['type']=='choice' else {'score':0})))
 return {'model':'gpt-6-luna','answers':answers,'usage':{'input_tokens':100,'output_tokens':0}}

@pytest.mark.asyncio
async def test_decisions_parsing_and_single_shared_input():
 raw=response();seen=[]
 def handler(req):seen.append(req);return httpx.Response(200,json=raw)
 async with DecisionsProvider(api_key='synthetic',transport=httpx.MockTransport(handler)) as p:
  r=await p.classify('Synthetic review','Rubric')
 assert r.data['severity']==1 and r.data['sentiment']==-1
 assert len(seen)==1 and len(r.data['probabilities'])==4

@pytest.mark.asyncio
@pytest.mark.parametrize('bad',['duplicate','distribution','refusal'])
async def test_reject_bad_answers(bad):
 raw=response()
 if bad=='duplicate':raw['answers'][1]['name']='topic'
 if bad=='distribution':raw['answers'][0]['probabilities'][0]['probability']=.5
 if bad=='refusal':raw['answers'][0]={'type':'refusal','name':'topic'}
 async with DecisionsProvider(api_key='synthetic',transport=httpx.MockTransport(lambda req:httpx.Response(200,json=raw))) as p:
  with pytest.raises((MalformedProviderResponse,RefusedProviderResponse)):await p.classify('Synthetic review','Rubric')

def test_input_only_billing_and_fingerprint(tmp_path):
 from spotify_pipeline.engine import fingerprint
 c=load_config('config/decisions-pilot.json');c['ledger_path']=str(tmp_path/'ledger.db')
 e=Engine(c,tmp_path/'cache.db',tmp_path/'run')
 b=e._billing('decisions',{'input_tokens':1000,'output_tokens':999},model='gpt-6-luna')
 assert b['cost_usd']==.0001 and len(b['billing_items'])==1
 assert e._reserve_cost('decisions',{'model':'gpt-6-luna','input':'x'})>0
 changed=copy.deepcopy(c);changed['uncertainty_threshold']=.9
 assert fingerprint(c)!=fingerprint(changed)
 e.store.close();e.ledger.close()

@pytest.mark.asyncio
async def test_resume_does_not_rejudge_completed_low_confidence(tmp_path):
 from spotify_pipeline.providers import ProviderResponse
 from spotify_pipeline.nebius import NebiusProvider
 class LowDecisions:
  model='gpt-6-luna'
  build_request=staticmethod(DecisionsProvider.build_request)
  async def classify(self,text,prompt):
   return ProviderResponse(dict(topic='access',intent='complaint',severity=4,sentiment=-.5,confidence={'topic':.2},probabilities={}),{},dict(input_tokens=100,output_tokens=0),self.model)
 class Fallback:
  build_request=staticmethod(NebiusProvider.build_request)
  async def structured(self,**kw):
   return ProviderResponse({'reviews':[dict(review_id=r['review_id'],topic='access',intent='complaint',severity=4,sentiment=-.5,needs_review=False) for r in kw['payload']['reviews']]},{},dict(prompt_tokens=100,completion_tokens=100),kw['model'])
 c=load_config('config/decisions-pilot.json');c.update(ledger_path=str(tmp_path/'ledger.db'),requests_per_second=1000000,tokens_per_second=1000000000)
 e=Engine(c,tmp_path/'cache.db',tmp_path/'run',providers={'decisions':LowDecisions(),'nebius':Fallback()})
 rows=[dict(review_id=f'synthetic-{i}',review_text=f'I cannot sign in, synthetic {i}',review_rating='1',review_likes='0',app_version='',review_timestamp='') for i in range(20)]
 try:
  a=await e.enrich(rows);calls=len(e.store.calls());assert calls==21
  b=await e.enrich(rows,phase='resume');assert a==b and len(e.store.calls())==calls
 finally:await e.close()

def test_provider_caps_include_reservations_unknowns_and_legacy(tmp_path):
 from spotify_pipeline.storage import BudgetLedger,BudgetExceeded
 l=BudgetLedger(tmp_path/'ledger.db')
 l.reserve('legacy','old',.2,global_cap_usd=10,run_cap_usd=10);l.settle('legacy',.1)
 l.reserve('decisions','new',.5,global_cap_usd=10,run_cap_usd=10,provider='decisions',provider_cap_usd=1)
 l.settle('decisions',None)
 with pytest.raises(BudgetExceeded):l.reserve('overflow','new',.5,global_cap_usd=10,run_cap_usd=10,provider='decisions',provider_cap_usd=1)
 l.reserve('nebius','new',.5,global_cap_usd=10,run_cap_usd=10,provider='nebius',provider_cap_usd=1)
 assert l.totals()['committed_usd']==1.1
 l.close()
