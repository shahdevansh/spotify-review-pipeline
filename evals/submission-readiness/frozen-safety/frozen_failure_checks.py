"""Deterministic transport simulations, not live provider or accuracy evidence."""
import asyncio,json,tempfile,unittest
from pathlib import Path
from spotify_pipeline.engine import Engine,load_config,fingerprint
from spotify_pipeline.decisions import DecisionsProvider
from spotify_pipeline.providers import ProviderResponse,TransientProviderError
FROZEN='spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a'
ROOT=Path('/private/tmp/spotify-hero-stable-runtime')

class ControlledDecisions:
    build_request=staticmethod(DecisionsProvider.build_request)
    endpoint='deterministic-test-only:no-network'
    def __init__(self,events):self.events=list(events);self.inputs=[]
    async def classify(self,text,prompt):
        self.inputs.append(text);event=self.events.pop(0) if self.events else 'ok'
        if event=='temporary':raise TransientProviderError('Injected temporary error; no network request actually sent',usage_unknown=True)
        result={'topic':'invalid-test-label' if event=='malformed' else 'playback','intent':'complaint','severity':4,'sentiment':-1.0,'confidence':dict(topic=.99,intent=.99,severity=.99,sentiment=.99)}
        return ProviderResponse(result,{'synthetic':True,'simulation':event,'output':result},{'input_tokens':100,'output_tokens':0},'gpt-6-luna')

class FrozenFailureChecks(unittest.TestCase):
    def check_scenario(self,events,kind,budget=.75):
        async def scenario():
            with tempfile.TemporaryDirectory(prefix='spotify-frozen-failure-') as d:
                p=Path(d);config=load_config(ROOT/'config/hero.json')
                config.update(ledger_path=str(p/'SIMULATED-spend.sqlite3'),retry_backoff_seconds=0,requests_per_second=1e6,tokens_per_second={'decisions':1e9,'nebius':1e9})
                self.assertEqual(fingerprint(config),FROZEN)
                provider=ControlledDecisions(events)
                e=Engine(config,p/'synthetic.sqlite3',p/'run',budget_usd=budget,workers=1,providers={'decisions':provider})
                try:
                    row=dict(review_id='synthetic-controlled-'+kind,review_text='Every song fails to start.',review_rating='',review_likes='',app_version='SYNTHETIC',review_timestamp='')
                    if kind=='empty':row['review_text']=''
                    records=await e.enrich([row]);summary=e.finish();calls=e.store.calls()
                    if kind=='malformed':
                        self.assertEqual(len(calls),2);self.assertEqual(records[0]['status'],'quarantined');self.assertTrue(all(c['outcome']=='failed' for c in calls))
                    elif kind=='temporary':
                        self.assertEqual(len(calls),2);self.assertEqual(records[0]['status'],'completed');self.assertGreater(summary['spending']['unknown_charge_hold_usd'],0);self.assertIsNone(calls[0]['input_tokens'])
                    elif kind=='exhaustion':
                        self.assertEqual(len(calls),3);self.assertEqual(records[0]['status'],'quarantined');self.assertTrue(all(c['cost_usd'] is None for c in calls));self.assertGreater(summary['spending']['unknown_charge_hold_usd'],0)
                    elif kind=='budget':
                        self.assertEqual(len(calls),0);self.assertEqual(len(provider.inputs),0);self.assertEqual(summary['spending']['committed_usd'],0);self.assertEqual(records[0]['status'],'pending');self.assertTrue(any('budget' in x for x in summary['limitations']))
                    elif kind=='empty':
                        self.assertEqual(len(calls),0);self.assertEqual(records[0]['status'],'quarantined');self.assertEqual(records[0]['reason'],'empty_review_text')
                    self.assertEqual(summary['label_config'],FROZEN)
                finally:await e.close()
        asyncio.run(scenario())
    def test_one_malformed_repair_then_quarantine(self):self.check_scenario(['malformed','malformed'],'malformed')
    def test_transient_retry_retains_unknown_hold(self):self.check_scenario(['temporary','ok'],'temporary')
    def test_transient_retry_exhaustion(self):self.check_scenario(['temporary']*3,'exhaustion')
    def test_budget_stops_before_dispatch(self):self.check_scenario([],'budget',budget=.000000001)
    def test_empty_text_uses_no_call(self):self.check_scenario([],'empty')

if __name__=='__main__':unittest.main(verbosity=2)
