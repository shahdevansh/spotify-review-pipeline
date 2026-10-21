"""Synthetic-only validation tests. No actual annotations or provider access."""
import argparse
import contextlib
import copy
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import import_course_supplement as importer


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n").encode()


def fixture():
    sources, labels = [], []
    for i in range(200):
        row = dict(zip(importer.SOURCE_FIELDS, (f"synthetic-{i:03}", f"Synthetic music review {i} — café", "5", "0", "1.0", "2026-01-01")))
        sources.append(row)
        label = {"review_id": row["review_id"], "review_text": row["review_text"],
                 "row_sha": importer.sha(importer.canonical([row[f] for f in importer.SOURCE_FIELDS]).encode()),
                 "topic": None if i < 3 else "other", "intent": None if i < 3 else "praise",
                 "severity": None, "sentiment": None, "entities": None,
                 "evidence_quote": row["review_text"], "needs_review": False, "ambiguous": False,
                 "notes": "PRIVATE_NOTE_SENTINEL", "human_labeler": "PRIVATE_ID_SENTINEL",
                 "alternative_notes": "PRIVATE_ALTERNATIVE_SENTINEL", "alternative_topics": ["usability"]}
        label["annotation_provenance"] = {f: "not_assessed" if label[f] is None else "annotated" for f in ("topic", "intent", "severity", "sentiment", "entities")}
        label["annotation_provenance"].update(evidence_quote="default_full_source", needs_review="default_false", ambiguous="default_false")
        labels.append(label)
    identity = [{key: row[key] for key in ("review_id", "review_text", "row_sha")} for row in labels]
    reference = {"annotation_protocol": "human-partial-v3", "labels": labels, "source_digest": importer.sha(importer.canonical(identity).encode()),
                 "raw_labels": copy.deepcopy(labels), "complete": False, "revision_history": []}
    raw_reference = encoded(reference)
    buf = io.StringIO(); writer = csv.DictWriter(buf, fieldnames=importer.SOURCE_FIELDS);writer.writeheader();writer.writerows(sources[:50]);golden = buf.getvalue().encode()
    meta = {"schema_version": "spotify-course-golden-completion-v1", "source_annotation_sha256": importer.sha(raw_reference),
            "golden_source_sha256": importer.sha(golden), "rubric_sha256": "a" * 64, "evaluation_status": importer.STATUS, "items": []}
    for i, row in enumerate(labels[:50], 1):
        meta["items"].append({"review_id": row["review_id"], "row_sha": row["row_sha"], "review_text": row["review_text"],
                              "golden_position": i, "worksheet_position": i, "initial": {f: row[f] for f in importer.FIELDS},
                              "initial_provenance": copy.deepcopy(row["annotation_provenance"])})
    meta["snapshot_sha256"] = importer.sha(importer.canonical(meta).encode())
    supplement = {key: meta[key] for key in importer.IDENTITY_KEYS}
    supplement.update(evaluation_status=importer.STATUS, exported_at="2026-10-21T20:00:00.000Z", complete=True, labels=[], changes=[], validation_errors=[])
    for i, item in enumerate(meta["items"]):
        human = {"review_id": item["review_id"], "row_sha": item["row_sha"], **copy.deepcopy(item["initial"])}
        human.update(topic="other", intent="praise", severity=1, sentiment=0.5)
        if i == 0:
            human.update(notes="NEW_PRIVATE_NOTE_SENTINEL — multiline\nUnicode ✓", entities=["music"], evidence_quote="music", needs_review=True)
        human.update(status="complete", missing_fields=[], annotation_provenance={})
        for field in importer.FIELDS:
            same = importer.strict_equal(human[field], item["initial"][field])
            human["annotation_provenance"][field] = (item["initial_provenance"].get(field) or "preserved_original") if same else ("not_assessed" if human[field] is None else "supplemental_human")
            if not same:
                supplement["changes"].append({"review_id": human["review_id"], "row_sha": human["row_sha"], "field": field, "before": item["initial"][field], "after": human[field]})
        supplement["labels"].append(human)
    worksheet = ('<script id="worksheet-data" type="application/json">' + json.dumps(meta, ensure_ascii=False) + '</script>').encode()
    return reference, supplement, meta, raw_reference, worksheet, golden, sources


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.reference, self.supplement, self.meta, self.raw_reference, self.worksheet, self.golden, self.sources = fixture()

    def validate(self, supplement=None, **overrides):
        raw = encoded(supplement if supplement is not None else self.supplement)
        kwargs = {"reference_sha256": importer.sha(self.raw_reference), "supplement_sha256": importer.sha(raw), "snapshot_sha256": self.meta["snapshot_sha256"]}
        kwargs.update(overrides)
        return importer.validate_inputs(self.raw_reference, raw, self.worksheet, self.golden, **kwargs)

    def test_valid_preserves_other150_raw_labels_and_defaults(self):
        new, changes, _, _ = self.validate()
        self.assertEqual(new["labels"][50:], self.reference["labels"][50:])
        self.assertEqual(new["raw_labels"], self.reference["raw_labels"])
        self.assertEqual(new["source_digest"], self.reference["source_digest"])
        self.assertEqual(new["labels"][0]["annotation_provenance"]["severity"], "annotated")
        self.assertEqual(new["labels"][1]["annotation_provenance"]["needs_review"], "default_false")
        self.assertEqual(new["labels"][0]["annotation_provenance"]["needs_review"], "annotated")
        self.assertEqual(len(changes), len(self.supplement["changes"]))

    def test_duplicate_foreign_missing_and_wrong_hash_rejected(self):
        for mutation in (lambda s: s["labels"].__setitem__(1, copy.deepcopy(s["labels"][0])),
                         lambda s: s["labels"][0].__setitem__("review_id", "foreign"),
                         lambda s: s["labels"].pop(), lambda s: s["labels"][0].__setitem__("row_sha", "0" * 64)):
            with self.subTest(mutation=mutation):
                s = copy.deepcopy(self.supplement);mutation(s)
                with self.assertRaises(ValueError):self.validate(s)

    def test_invalid_values_rejected(self):
        for field, value in (("topic", "wrong"), ("intent", "wrong"), ("severity", True), ("severity", 0), ("severity", 6),
                             ("severity", 1.5), ("sentiment", True), ("sentiment", 1.01), ("sentiment", None),
                             ("entities", [""]), ("entities", "music"), ("evidence_quote", "not in source"),
                             ("needs_review", 1), ("ambiguous", "false"), ("notes", "x" * 10001)):
            with self.subTest(field=field, value_type=type(value).__name__):
                s = copy.deepcopy(self.supplement);s["labels"][0][field] = value
                with self.assertRaises(ValueError):self.validate(s)

    def test_partial_and_fake_completion_rejected(self):
        for key, value in (("complete", False), ("validation_errors", [{"review_id": "synthetic-000"}])):
            s = copy.deepcopy(self.supplement);s[key] = value
            with self.assertRaises(ValueError):self.validate(s)
        for key, value in (("status", "pending"), ("missing_fields", ["topic"])):
            s = copy.deepcopy(self.supplement);s["labels"][0][key] = value
            with self.assertRaises(ValueError):self.validate(s)

    def test_hashes_and_identity_metadata_rejected(self):
        for key in ("reference_sha256", "supplement_sha256", "snapshot_sha256"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):self.validate(**{key: "0" * 64})
        for key in importer.IDENTITY_KEYS:
            s = copy.deepcopy(self.supplement);s[key] = "wrong"
            with self.assertRaises(ValueError):self.validate(s)

    def test_forged_provenance_changes_and_extra_fields_rejected(self):
        for mutation in (lambda s: s["labels"][0]["annotation_provenance"].__setitem__("severity", "not_assessed"),
                         lambda s: s["changes"].pop(), lambda s: s.__setitem__("private_extra", "no"),
                         lambda s: s["labels"][0].__setitem__("model_prediction", "no")):
            s = copy.deepcopy(self.supplement);mutation(s)
            with self.assertRaises(ValueError):self.validate(s)

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):importer.loads(raw)

    def test_boolean_numeric_change_list_confusion_rejected(self):
        s = copy.deepcopy(self.supplement)
        change = next(row for row in s["changes"] if row["field"] == "severity")
        self.assertEqual(change["after"], 1)
        change["after"] = True
        with self.assertRaises(ValueError):self.validate(s)

    def test_bad_source_and_snapshot_rejected(self):
        raw = encoded(self.supplement)
        for worksheet, golden in ((self.worksheet + self.worksheet, self.golden), (self.worksheet, self.golden.replace(b"music", b"wrong", 1))):
            with self.assertRaises(ValueError):
                importer.validate_inputs(self.raw_reference, raw, worksheet, golden, reference_sha256=importer.sha(self.raw_reference), supplement_sha256=importer.sha(raw), snapshot_sha256=self.meta["snapshot_sha256"])

    def make_args(self, root):
        p = root / "private" / "human-labels";p.mkdir(parents=True)
        data = {"reference": self.raw_reference, "supplement": encoded(self.supplement), "worksheet": self.worksheet, "golden_source": self.golden}
        paths = {}
        for name, value in data.items():
            paths[name] = p / (name + ".json");paths[name].write_bytes(value)
        args = argparse.Namespace(**paths, reference_sha256=importer.sha(self.raw_reference), supplement_sha256=importer.sha(data["supplement"]), snapshot_sha256=self.meta["snapshot_sha256"], version="synthetic-v3", out=p/"synthetic-v3")
        return args

    def test_atomic_private_version_originals_unchanged_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.make_args(Path(temp))
            with contextlib.redirect_stdout(io.StringIO()):validation = importer.run(args)
            self.assertTrue(validation["passed"])
            self.assertEqual(args.reference.read_bytes(), self.raw_reference)
            self.assertEqual((args.out / "parent.original.json").read_bytes(), self.raw_reference)
            self.assertEqual((args.out / "supplement.original.json").read_bytes(), encoded(self.supplement))
            self.assertFalse(validation["public_exports_written"])
            with self.assertRaises(ValueError):importer.run(args)

    def test_public_output_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.make_args(Path(temp));args.out = Path(temp) / "public" / "evals"
            with self.assertRaises(ValueError):importer.run(args)
            self.assertFalse(args.out.exists())

    def test_synthetic_public_export_never_leaks_private_notes(self):
        spec = importlib.util.spec_from_file_location("export_golden_grader", Path(__file__).with_name("export_golden_grader.py"))
        exporter = importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);args = self.make_args(root)
            with contextlib.redirect_stdout(io.StringIO()):validation = importer.run(args)
            source = root/"source.csv"; selected = root/"selected.csv"
            for path, rows in ((source,self.sources),(selected,self.sources[:99])):
                with path.open("w",newline="") as f:
                    writer=csv.DictWriter(f,fieldnames=importer.SOURCE_FIELDS);writer.writeheader();writer.writerows(rows)
            preds=[]
            for row in self.sources[:99]:
                preds.append({**row,"source_sha256":importer.sha(importer.canonical([row[f] for f in importer.SOURCE_FIELDS]).encode()),"topic":"other","intent":"praise","severity":1,"sentiment":0.5,"entities":[],"evidence_quote":row["review_text"],"needs_review":False,"status":"completed","label_config":"synthetic-config"})
            predictions=root/"predictions.jsonl";predictions.write_bytes(b"".join(encoded(row) for row in preds))
            out=root/"private"/"public-candidate"
            export_args=argparse.Namespace(evaluator=Path(__file__).with_name('evaluate_hero_humans.py'),annotations=args.out/"annotations.corrected.json",annotation_sha256=validation["corrected_sha256"],source=source,selected=selected,golden_source=args.golden_source,predictions=predictions,prediction_sha256=importer.sha(predictions.read_bytes()),label_config="synthetic-config",run_id="synthetic-run",baseline_report=None,out=out,scope="all",publication_approved=True)
            with contextlib.redirect_stdout(io.StringIO()):exporter.main(export_args)
            for path in out.iterdir():
                self.assertNotIn(b"PRIVATE_NOTE_SENTINEL",path.read_bytes())
                self.assertNotIn(b"PRIVATE_ID_SENTINEL",path.read_bytes())
                self.assertNotIn(b"PRIVATE_ALTERNATIVE_SENTINEL",path.read_bytes())
            aggregate=json.loads((out/"aggregate.json").read_bytes())
            self.assertEqual(aggregate["groups"]["mandatory_golden_50"]["fields"]["topic"]["explicitly_annotated"],50)
            self.assertIn("topic: 50/50",(out/"README.md").read_text())
            self.assertNotIn("47 explicit labels",(out/"README.md").read_text())


class AIReviewImporterTests(unittest.TestCase):
    setUp = ImporterTests.setUp
    validate = ImporterTests.validate
    make_args = ImporterTests.make_args
    def ai_fixture(self):
        meta = copy.deepcopy(self.meta)
        meta.pop("snapshot_sha256")
        meta.update(schema_version="spotify-course-golden-ai-review-v1",evaluation_status=importer.AI_STATUS,
                    parent_human_worksheet_snapshot_sha256=self.meta["snapshot_sha256"])
        suggestions=[]
        for item, human in zip(meta["items"], self.supplement["labels"]):
            fields=[field for field in importer.REQUIRED if item["initial"][field] is None]
            draft={"review_id":item["review_id"],"row_sha":item["row_sha"],"golden_position":item["golden_position"],
                   "suggestions":{field:human[field] for field in fields},"rationales":{field:"Synthetic source-only draft" for field in fields},
                   "confidence":{field:"moderate" for field in fields},"caveat":"Synthetic only"} if fields else None
            item.update(draft_fields=fields,ai_draft=draft)
            if fields:suggestions.append(draft)
        meta["draft_document"]={"schema_version":"synthetic-ai-draft","generation_context":"synthetic","parts":[],"suggestions":suggestions}
        meta["ai_draft_sha256"]=importer.sha(importer.canonical(meta["draft_document"]).encode())
        meta["snapshot_sha256"]=importer.sha(importer.canonical(meta).encode())
        raw=copy.deepcopy(self.supplement)
        for key in (*importer.IDENTITY_KEYS,"ai_draft_sha256","parent_human_worksheet_snapshot_sha256"):
            raw[key]=meta[key]
        raw["evaluation_status"]=importer.AI_STATUS
        for item,row in zip(meta["items"],raw["labels"]):
            fields=item["draft_fields"]
            row.update(draft_fields=fields,reviewed=bool(fields),reviewed_at="2026-10-21T19:59:00.000Z" if fields else None,
                       reviewed_values={field:copy.deepcopy(row[field]) for field in importer.FIELDS} if fields else None,
                       review_status="ai_assisted_human_confirmed" if fields else "preserved_existing_human")
            row["annotation_provenance"].update({field:"ai_assisted_human_confirmed" for field in fields})
        return meta,raw

    def validate_ai(self,meta,raw):
        raw_bytes=encoded(raw)
        return importer.validate_ai_inputs(self.raw_reference,raw_bytes,self.worksheet,self.golden,encoded(meta),
            reference_sha256=importer.sha(self.raw_reference),supplement_sha256=importer.sha(raw_bytes),snapshot_sha256=meta["snapshot_sha256"])

    def test_ai_confirmed_values_keep_explicit_assistance_provenance(self):
        meta,raw=self.ai_fixture();new,changes,validated,_=self.validate_ai(meta,raw)
        self.assertEqual(new['labels'][50:],self.reference['labels'][50:])
        self.assertEqual(new['labels'][0]['course_annotation_methods']['severity'],'ai_assisted_human_confirmed')
        self.assertEqual(new['labels'][0]['annotation_provenance']['severity'],'annotated')
        self.assertTrue(any(c['source']=='ai_assisted_human_confirmed' for c in changes))
        self.assertEqual(validated['human_confirmed_ai_rows'],50)

    def test_ai_unreviewed_mismatched_or_fake_confirmation_rejected(self):
        for mutation in (lambda r:r['labels'][0].__setitem__('reviewed',False),
                         lambda r:r['labels'][0].__setitem__('reviewed_at',None),
                         lambda r:r['labels'][0].__setitem__('reviewed_at','tomorrow'),
                         lambda r:r['labels'][0].__setitem__('reviewed_at','2026-10-22T19:59:00.000Z'),
                         lambda r:r['labels'][0]['reviewed_values'].__setitem__('sentiment',-.5),
                         lambda r:r['labels'][0]['reviewed_values'].__setitem__('extra','wrong'),
                         lambda r:r['labels'][0].__setitem__('review_status','ai_draft_unreviewed'),
                         lambda r:r['labels'][0]['annotation_provenance'].__setitem__('severity','ai_draft_unreviewed'),
                         lambda r:r['labels'][0].__setitem__('draft_fields',[])):
            meta,raw=self.ai_fixture();mutation(raw)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):self.validate_ai(meta,raw)

    def test_ai_snapshot_draft_hash_and_parent_mutations_rejected(self):
        for mutation in (lambda m:m.__setitem__('ai_draft_sha256','0'*64),
                         lambda m:m.__setitem__('parent_human_worksheet_snapshot_sha256','0'*64),
                         lambda m:m['items'][0]['initial'].__setitem__('topic','billing')):
            meta,raw=self.ai_fixture();mutation(meta)
            meta['snapshot_sha256']=importer.sha(importer.canonical({k:v for k,v in meta.items() if k!='snapshot_sha256'}).encode())
            raw['snapshot_sha256']=meta['snapshot_sha256']
            for key in ('ai_draft_sha256','parent_human_worksheet_snapshot_sha256'):raw[key]=meta[key]
            with self.assertRaises(ValueError):self.validate_ai(meta,raw)

    def test_manual_importer_rejects_ai_schema(self):
        _,raw=self.ai_fixture()
        with self.assertRaises(ValueError):self.validate(raw)

    def test_ai_import_writes_private_snapshot_and_disclosed_new_version(self):
        meta,raw=self.ai_fixture()
        with tempfile.TemporaryDirectory() as temp:
            args=self.make_args(Path(temp));args.supplement.write_bytes(encoded(raw));args.supplement_sha256=importer.sha(encoded(raw));args.snapshot_sha256=meta['snapshot_sha256']
            args.ai_snapshot=args.reference.parent/'synthetic-ai-snapshot.json';args.ai_snapshot.write_bytes(encoded(meta))
            with contextlib.redirect_stdout(io.StringIO()):importer.run(args)
            result=json.loads((args.out/'annotations.corrected.json').read_bytes())
            self.assertEqual(result['evaluation_status'],importer.AI_STATUS)
            self.assertEqual(result['course_supplement']['raw_ai_suggestions_counted_without_human_confirmation'],0)
            self.assertEqual((args.out/'parent.original.json').read_bytes(),self.raw_reference)
            self.assertEqual((args.out/'ai-draft-snapshot.private.json').read_bytes(),encoded(meta))
            self.assertFalse(result['course_supplement']['frozen_hero_predictions_consulted'])
            self.assertNotIn('model_predictions_consulted',result['course_supplement'])
            import export_course_reference as course_export
            source=Path(temp)/'sources.csv';selected=Path(temp)/'selected.csv'
            for path,rows in ((source,self.sources),(selected,self.sources[:99])):
                with path.open('w',newline='') as handle:
                    writer=csv.DictWriter(handle,fieldnames=importer.SOURCE_FIELDS);writer.writeheader();writer.writerows(rows)
            predictions=Path(temp)/'predictions.jsonl'
            pred_rows=[{**row,'source_sha256':importer.sha(importer.canonical([row[f] for f in importer.SOURCE_FIELDS]).encode()),'topic':'other','intent':'praise','severity':1,'sentiment':0.5,'entities':[],'evidence_quote':row['review_text'],'needs_review':False,'status':'completed','label_config':'synthetic-config'} for row in self.sources[:99]]
            predictions.write_bytes(b''.join(encoded(row) for row in pred_rows))
            corrected=args.out/'annotations.corrected.json';out=Path(temp)/'private'/'sanitized-course-export'
            ea=argparse.Namespace(evaluator=Path(__file__).with_name('evaluate_hero_humans.py'),annotations=corrected,annotation_sha256=importer.sha(corrected.read_bytes()),source=source,selected=selected,golden_source=args.golden_source,predictions=predictions,prediction_sha256=importer.sha(predictions.read_bytes()),label_config='synthetic-config',run_id='synthetic-run',baseline_report=None,out=out,scope='all',publication_approved=True)
            with contextlib.redirect_stdout(io.StringIO()):course_export.main(ea)
            exported=[json.loads(line) for line in (out/'all200-comparison.jsonl').read_text().splitlines()]
            self.assertEqual(exported[0]['expected']['severity']['annotation_method'],'ai_assisted_human_confirmed')
            self.assertEqual(exported[0]['provenance']['evaluation_status'],importer.AI_STATUS)
            aggregate=json.loads((out/'aggregate.json').read_bytes())
            self.assertEqual(aggregate['evaluation_status'],importer.AI_STATUS)
            self.assertEqual(aggregate['reference_completion']['human_confirmed_ai_rows'],50)
            for path in out.iterdir():
                self.assertNotIn(b'PRIVATE_NOTE_SENTINEL',path.read_bytes())
                self.assertNotIn(b'PRIVATE_ID_SENTINEL',path.read_bytes())
                self.assertNotIn(b'PRIVATE_ALTERNATIVE_SENTINEL',path.read_bytes())
            self.assertIn('drafted with AI',(out/'index.html').read_text())
            self.assertIn('expected_severity_annotation_method',(out/'all200-comparison.csv').read_text())
            for name in ('report.md','README.md'):
                opening=(out/name).read_text().splitlines()[:5]
                self.assertTrue(any('AI-assisted, human-confirmed posthoc' in line for line in opening))
                self.assertNotIn('All 200 worksheet labels',(out/name).read_text())
            # Parse the actual HTML and bind every displayed field back to its
            # authoritative public JSON row, rather than checking a global slogan.
            class Fields(HTMLParser):
                def __init__(self):
                    super().__init__();self.review=None;self.field=None;self.in_cell=False;self.current='';self.values=[];self.rows={}
                def handle_starttag(self,tag,attrs):
                    attrs=dict(attrs)
                    if tag=='section':self.review=attrs['data-review-id']
                    elif tag=='tr' and 'data-field' in attrs:self.field=attrs['data-field'];self.values=[]
                    elif tag=='td' and self.field is not None:self.in_cell=True;self.current=''
                def handle_data(self,value):
                    if self.in_cell:self.current+=value
                def handle_endtag(self,tag):
                    if tag=='td' and self.in_cell:self.values.append(self.current);self.in_cell=False
                    elif tag=='tr' and self.field is not None:self.rows[(self.review,self.field)]=self.values;self.field=None
                    elif tag=='section':self.review=None
            parsed=Fields();parsed.feed((out/'index.html').read_text())
            self.assertEqual(len(parsed.rows),sum(len(row['expected']) for row in exported))
            for row in exported:
                for field,expected in row['expected'].items():
                    cells=parsed.rows[(row['review_id'],field)]
                    self.assertEqual(len(cells),7)
                    self.assertEqual(cells[2],expected['origin'])
                    self.assertEqual(cells[3],expected['annotation_method'])

    def test_html_field_methods_are_escaped_and_source_bound(self):
        import export_course_reference as course_export
        row={'review_id':'id<"&','worksheet_position':1,'reference_group':'mandatory_golden_50',
             'review_text':'<img src=x onerror=alert(1)> & café','source_row_sha256':'0'*64,'inside_selected_cohort':True,
             'expected':{'topic':{'value':'other','origin':'annotated','explicitly_annotated':True,'annotation_method':'ai_assisted_human_confirmed'}},
             'prediction':{'topic':'other'},'comparison':{'topic':{'exact_match':True,'absolute_error':None}}}
        page=course_export.render_course_html([row],'<script>alert(1)</script>')
        self.assertNotIn('<img ',page);self.assertNotIn('<script>',page)
        self.assertIn('&lt;img src=x',page);self.assertIn('&lt;script&gt;',page)
        self.assertIn('<th>Annotation method</th>',page)
        self.assertIn('<td>ai_assisted_human_confirmed</td>',page)


if __name__ == "__main__":
    unittest.main()
