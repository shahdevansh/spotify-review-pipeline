"""Fail-closed presentation guards; all fixtures are synthetic."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('hero_editorial',Path(__file__).parents[1]/'tools/review_hero_editorial.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class HeroEditorialGuards(unittest.TestCase):
    def fixture(self):
        issues=[{'issue_id':'issue-'+t,'title':'Illustrative title','description':'Illustrative description.','review_ids':[t+'-0']} for t in sorted(module.TOPICS)]
        document={'summary':module.OLD_SUMMARY,'recommendations':[{'rationale':module.OLD_VOLUME+'. '+module.OLD_INTERVENTION}],
                  'limitations':['unchanged','unchanged',module.OLD_LIMIT]}
        ranking=[{'issue_id':'issue-'+t,'complaint_count':300 if t=='other' else 250 if t=='usability' else 100,
                  'priority_score':700 if t=='usability' else 500 if t=='other' else 200} for t in sorted(module.TOPICS)]
        evidence={'issue-'+t:[{'review_id':t+'-'+str(i)} for i in range(5)] for t in module.TOPICS}
        return issues,document,ranking,evidence

    def test_only_accepted_presentation_fields_change(self):
        source=self.fixture();before=copy.deepcopy(source)
        issues,document,changes=module.build_corrections(*source)
        self.assertEqual(source,before)
        self.assertEqual(len(changes),20)
        self.assertIn(module.NEW_VOLUME,document['recommendations'][0]['rationale'])
        self.assertIn(module.NEW_INTERVENTION,document['recommendations'][0]['rationale'])
        self.assertEqual([x['review_ids'] for x in issues],[x['review_ids'] for x in source[0]])
        self.assertEqual({x['title'].lower() for x in issues},module.TOPICS)

    def test_rejects_changed_source_phrase(self):
        source=self.fixture();source[1]['summary']='Different model output.'
        with self.assertRaises(ValueError):module.build_corrections(*source)

    def test_rejects_false_replacement_arithmetic(self):
        source=self.fixture()
        next(x for x in source[2] if x['issue_id']=='issue-usability')['complaint_count']=400
        with self.assertRaises(AssertionError):module.build_corrections(*source)

    def test_rejects_wrong_evidence_count(self):
        source=self.fixture();source[3]['issue-other'].pop()
        with self.assertRaises(AssertionError):module.build_corrections(*source)

    def test_rejects_missing_topic(self):
        source=self.fixture();source[0].pop()
        with self.assertRaises(AssertionError):module.build_corrections(*source)

if __name__=='__main__':unittest.main()
