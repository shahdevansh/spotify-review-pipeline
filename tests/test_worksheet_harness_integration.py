"""Actual worksheet serializers -> harness, with synthetic answers only.

No test opens the delivered HTML, browser storage, or any private answer path.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from spotify_pipeline import harness
from spotify_pipeline.data import row_sha

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("synthetic_worksheet", ROOT / "tools/human_worksheet.py")
worksheet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worksheet)

SOURCES = [
    {"review_id": "synthetic-integration-1", "review_text": "Synthetic offline tracks stop, but online works.",
     "review_rating": "1", "review_likes": "0", "app_version": "", "review_timestamp": "2023-01-01 00:00:00"},
    {"review_id": "synthetic-integration-2", "review_text": 'Synthetic Spotify is "great".\r\nCafé music makes me happy. 🎵',
     "review_rating": "5", "review_likes": "0", "app_version": "", "review_timestamp": "2023-01-02 00:00:00"},
]
GROUPS = {"mandatory_golden_50": ["synthetic-integration-1"],
          "fresh_text_disjoint_150": ["synthetic-integration-2"]}
ANSWERS = [
    {"topic": "downloads", "intent": "complaint", "severity": "3", "sentiment": "-0.5",
     "entities": '["offline"]', "needs_review": "true", "ambiguous": "true",
     "alternative_topics": '["playback"]', "alternative_intents": "[]",
     "alternative_severities": "[4]", "evidence_support": "partial",
     "notes": "SYNTHETIC FIXTURE ONLY", "alternative_notes": "Synthetic alternative"},
    {"topic": "other", "intent": "praise", "severity": "1", "sentiment": "1",
     "entities": '["Spotify"]', "needs_review": "false", "ambiguous": "false",
     "alternative_topics": "", "alternative_intents": "", "alternative_severities": "",
     "evidence_support": "", "notes": "SYNTHETIC FIXTURE ONLY", "alternative_notes": ""},
]

FAKE_DOM = r"""
class Element{
 constructor(tag="div"){this.tag=tag;this.value="";this.textContent="";this.disabled=false;this.options=[];this.children=[];}
 append(...items){this.children.push(...items);for(const item of items)if(item.tag==="option")this.options.push(item);}
 addEventListener(){} click(){}
}
const elements=new Map(),syntheticStorage=new Map(),syntheticDownloads=[];
global.document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement(tag){return new Element(tag);}};
global.localStorage={getItem(key){return syntheticStorage.get(key)??null;},setItem(key,value){syntheticStorage.set(key,value);}};
global.Blob=class{constructor(parts,options){this.parts=parts;this.options=options;}};
global.URL={createObjectURL(blob){syntheticDownloads.push({type:blob.options.type,content:blob.parts.join("")});return "blob:synthetic";},revokeObjectURL(){}};
global.setTimeout=callback=>{callback();return 1;};
"""


@pytest.fixture
def exports(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the actual JavaScript serializers")
    html = worksheet.generate_html(
        [{"review_id": row["review_id"], "review_text": row["review_text"], "row_sha": row_sha(row)}
         for row in SOURCES],
        tmp_path / "synthetic.html", cohort_id="synthetic-integration-cohort",
        rubric={"version": "synthetic-rubric-v1", "title": "Synthetic fixture",
                "sections": [{"title": "Only synthetic labels", "text": "Never open real answers in this test."}]},
        seed="synthetic-seed", version="synthetic-test-v1",
    ).read_text()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    runner = tmp_path / "synthetic-export.cjs"
    runner.write_text(
        FAKE_DOM + "\n" + script + "\n"
        + 'const syntheticAnswers=' + json.dumps(ANSWERS) + ";\n"
        + '$("annotator").value="SYNTHETIC ANNOTATOR";openWorkspace();\n'
        + "sourceRows.forEach((row,index)=>{labels[row.review_id]={...blankLabel(),...syntheticAnswers[index],evidence_quote:row.review_text};});\n"
        + 'render();download("json");download("csv");process.stdout.write(JSON.stringify(syntheticDownloads));\n'
    )
    completed = subprocess.run([node, str(runner)], capture_output=True, text=True, check=True)
    downloaded = json.loads(completed.stdout)
    paths = {}
    for suffix, item in zip(("json", "csv"), downloaded, strict=True):
        path = tmp_path / ("SYNTHETIC_ONLY." + suffix)
        path.write_bytes(item["content"].encode("utf-8"))
        paths[suffix] = path
    return paths


def evaluate(path, *, confirmed=True):
    predictions = [
        {**SOURCES[0], "label_config": "synthetic-fixed-config", "topic": "playback", "intent": "complaint",
         "severity": 4, "sentiment": -0.5, "needs_review": True},
        {**SOURCES[1], "label_config": "synthetic-fixed-config", "topic": "other", "intent": "praise",
         "severity": 1, "sentiment": 1.0, "needs_review": False},
    ]
    return harness.evaluate_candidates(
        SOURCES, {"synthetic_candidate": predictions}, references=path,
        reference_kind="human", human_labels_confirmed=confirmed,
        evaluation_groups=GROUPS, bootstrap_repetitions=0,
    )


def test_actual_json_csv_exports_preserve_types_source_and_annotator(exports):
    wrapper = json.loads(exports["json"].read_text())
    assert wrapper["complete"] is True
    assert wrapper["validation_errors"] == []
    assert wrapper["annotator_id"] == "SYNTHETIC ANNOTATOR"
    assert wrapper["cohort_id"] == "synthetic-integration-cohort"
    assert wrapper["rubric_version"] == "synthetic-rubric-v1"
    for suffix in ("json", "csv"):
        rows = harness._load(exports[suffix])
        assert [r["review_text"] for r in rows] == [r["review_text"] for r in SOURCES]
        assert [r["row_sha"] for r in rows] == [row_sha(r) for r in SOURCES]
        assert all(r["human_labeler"] == wrapper["annotator_id"] for r in rows)
        assert rows[0]["needs_review"] is True and rows[1]["needs_review"] is False
        assert rows[0]["ambiguous"] is True and rows[1]["ambiguous"] is False
        assert rows[0]["severity"] == 3 and type(rows[0]["severity"]) is int
        assert rows[0]["alternative_topics"] == ["playback"]
        assert rows[0]["alternative_severities"] == [4]
        assert rows[0]["entities"] == ["offline"]


def test_json_and_csv_produce_identical_separate_primary_and_alternative_metrics(exports):
    reports = [evaluate(exports[suffix]) for suffix in ("json", "csv")]
    assert reports[0]["candidates"] == reports[1]["candidates"]
    assert reports[0]["evaluation_groups"] == reports[1]["evaluation_groups"]
    for report in reports:
        reference = report["reference"]
        assert reference["labeled_count"] == 2
        assert reference["ambiguous_count"] == 1
        assert reference["accepted_alternatives_count"] == 1
        assert reference["annotator_evidence_support_counts"] == {"partial": 1, "not_supplied": 1}
        candidate = report["candidates"]["synthetic_candidate"]
        assert candidate["reference_metrics"]["topic"]["accuracy"]["successes"] == 1
        assert candidate["acceptable_set_reference_metrics"]["field_matches"]["topic"]["successes"] == 2
        assert candidate["reference_metrics"]["severity"]["exact"]["successes"] == 1
        assert candidate["acceptable_set_reference_metrics"]["field_matches"]["severity"]["successes"] == 2
        assert report["group_accounting"]["grouped_ids"] == 2


def test_export_wrapper_never_replaces_explicit_human_attestation(exports):
    with pytest.raises(ValueError, match="human_labels_confirmed"):
        evaluate(exports["json"], confirmed=False)


@pytest.mark.parametrize("field,value", [("needs_review", None), ("ambiguous", "false"),
                                       ("alternative_severities", ["4"]), ("entities", ["invented"])])
def test_invalid_or_unfinished_synthetic_answers_fail(exports, field, value):
    wrapper = json.loads(exports["json"].read_text())
    wrapper["labels"][0][field] = value
    exports["json"].write_text(json.dumps(wrapper))
    with pytest.raises(ValueError):
        evaluate(exports["json"])


@pytest.mark.parametrize("field,value", [("review_text", "changed synthetic text"), ("row_sha", "0" * 64)])
def test_exported_source_identity_is_enforced(exports, field, value):
    wrapper = json.loads(exports["json"].read_text())
    wrapper["labels"][0][field] = value
    exports["json"].write_text(json.dumps(wrapper))
    with pytest.raises(ValueError):
        evaluate(exports["json"])


def test_wrapper_annotator_must_match_exported_rows(exports):
    wrapper = json.loads(exports["json"].read_text())
    wrapper["annotator_id"] = "DIFFERENT SYNTHETIC ANNOTATOR"
    exports["json"].write_text(json.dumps(wrapper))
    with pytest.raises(ValueError):
        evaluate(exports["json"])


@pytest.mark.parametrize("field,value", [("source_digest", "0" * 64), ("complete", False),
                                       ("validation_errors", [{"review_id": "synthetic-integration-1",
                                                               "errors": ["synthetic unfinished answer"]}])])
def test_wrapper_identity_and_completion_claims_are_enforced(exports, field, value):
    wrapper = json.loads(exports["json"].read_text())
    wrapper[field] = value
    exports["json"].write_text(json.dumps(wrapper))
    with pytest.raises(ValueError):
        evaluate(exports["json"])


def test_csv_provenance_cannot_mix_cohorts(exports):
    with exports["csv"].open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    rows[1]["cohort_id"] = "DIFFERENT-SYNTHETIC-COHORT"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    exports["csv"].write_text(buffer.getvalue())
    with pytest.raises(ValueError):
        evaluate(exports["csv"])
