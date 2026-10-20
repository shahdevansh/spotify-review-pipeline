"""Synthetic-only tests for the blind worksheet generator and browser logic."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "human_worksheet.py"
SPEC = importlib.util.spec_from_file_location("human_worksheet_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
worksheet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worksheet)

RUBRIC = {
    "version": "synthetic-rubric-v1",
    "title": "Synthetic rubric for tests",
    "sections": [
        {"title": "Topic", "text": "Apply the explicit source definitions."},
        {"title": "Impact", "text": "Rate only the supported functional impact."},
    ],
}
ROWS = [
    {"review_id": "synthetic-1", "review_text": "Downloaded songs stop offline.", "row_sha": "a" * 64},
    {"review_id": "synthetic-2", "review_text": "The controls are hard to find.", "row_sha": "b" * 64},
]


def generate(tmp_path: Path, **kwargs) -> tuple[str, dict]:
    path = worksheet.generate_html(
        kwargs.pop("rows", ROWS),
        tmp_path / "synthetic.html",
        cohort_id=kwargs.pop("cohort_id", "synthetic-cohort"),
        rubric=kwargs.pop("rubric", RUBRIC),
        seed=kwargs.pop("seed", "synthetic-seed"),
        version=kwargs.pop("version", "test-v1"),
        **kwargs,
    )
    text = path.read_text()
    match = re.search(r"const payload=(.*?);\nconst metadata", text, re.S)
    assert match
    return text, json.loads(match.group(1))


def test_source_only_payload_and_deterministic_metadata(tmp_path):
    text, payload = generate(tmp_path)
    _, repeated = generate(tmp_path)
    assert payload == repeated
    assert payload["rows"] == ROWS
    assert payload["metadata"]["seed"] == "synthetic-seed"
    assert payload["metadata"]["rubric_version"] == "synthetic-rubric-v1"
    assert all(set(row) <= {"review_id", "review_text", "row_sha"} for row in payload["rows"])
    assert "textContent=row.row_sha" not in text
    assert "fetch(" not in text
    assert "XMLHttpRequest" not in text
    assert '<script src=' not in text
    assert "connect-src 'none'" in text
    assert "private/human-labels/" in text
    assert "PRIVATE__save-in-private-human-labels__" in text


@pytest.mark.parametrize("extra", ["review_rating", "topic", "prediction", "human_labeler", "metadata"])
def test_rejects_ratings_predictions_and_existing_answers(tmp_path, extra):
    with pytest.raises(ValueError, match="disallowed columns"):
        generate(tmp_path, rows=[{**ROWS[0], extra: "must never enter the worksheet"}])


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [ROWS[0], ROWS[0]],
        [{"review_id": "", "review_text": "source"}],
        [{"review_id": "x", "review_text": "   "}],
        [{"review_id": "x", "review_text": 123}],
        [{"review_id": "x", "review_text": "source", "row_sha": "not-a-hash"}],
    ],
)
def test_rejects_invalid_sources(tmp_path, rows):
    with pytest.raises(ValueError):
        generate(tmp_path, rows=rows)


def test_safe_text_embedding_and_no_html_interpretation(tmp_path):
    malicious = '</script><script>alert("synthetic")</script>&\u2028__PAGE_TITLE__'
    text, payload = generate(
        tmp_path,
        rows=[{"review_id": "synthetic-danger", "review_text": malicious}],
        cohort_id='<script>"cohort"</script>',
        rubric={"title": malicious, "version": "v1", "sections": {"Instructions": malicious}},
    )
    assert payload["rows"][0]["review_text"] == malicious
    assert payload["rubric"]["sections"][0]["text"] == malicious
    assert text.count("<script>") == 1
    assert text.count("</script>") == 1
    assert "\\u003c/script\\u003e" in text
    assert "\\u2028" in text
    assert "innerHTML" not in text
    assert "text.textContent=section.text" in text
    assert '&lt;script&gt;&quot;cohort&quot;&lt;/script&gt;' in text


def test_versioned_plain_text_rubric_and_selection_identity(tmp_path):
    _, first = generate(tmp_path, rubric="Plain rubric", rubric_version="plain-v3")
    _, second = generate(tmp_path, rows=list(reversed(ROWS)), rubric="Plain rubric", rubric_version="plain-v3")
    assert first["rubric"]["version"] == "plain-v3"
    assert first["metadata"]["source_digest"] != second["metadata"]["source_digest"]
    assert first["metadata"]["rubric_sha256"] == second["metadata"]["rubric_sha256"]
    with pytest.raises(ValueError, match="nonempty textual"):
        generate(tmp_path, rubric="")


def test_blind_evidence_support_is_not_a_model_audit(tmp_path):
    text, _ = generate(tmp_path)
    assert "Does your selected quote support your labels?" in text
    assert "Auditing model quote entailment is a separate task after human labels and predictions are locked." in text
    assert '<details class="full"><summary>Optional diagnostics:' in text


def test_browser_logic_without_a_browser(tmp_path):
    """Exercise pure JS in a fake DOM; no real labels, browser, or network."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit test")
    text, _ = generate(tmp_path)
    script = text.split("<script>", 1)[1].split("</script>", 1)[0]
    test_file = tmp_path / "worksheet-logic.cjs"
    test_file.write_text(
        _FAKE_DOM + "\n" + script + "\n" + _JS_ASSERTIONS,
        encoding="utf-8",
    )
    subprocess.run([node, "--check", str(test_file)], check=True, capture_output=True, text=True)
    result = subprocess.run([node, str(test_file)], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["passed"] is True


_FAKE_DOM = r"""
const assert=require("node:assert/strict");
class Element{
 constructor(tag="div"){this.tag=tag;this.value="";this.textContent="";this.disabled=false;this.options=[];this.children=[];this.listeners={};}
 append(...items){this.children.push(...items);for(const item of items)if(item.tag==="option")this.options.push(item);}
 addEventListener(name,callback){this.listeners[name]=callback;}
 click(){this.clicked=true;}
}
const elements=new Map(),stored=new Map(),reads=[],writes=[];
global.document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement(tag){return new Element(tag);}};
global.localStorage={getItem(key){reads.push(key);return stored.get(key)??null;},setItem(key,value){writes.push(key);stored.set(key,value);}};
global.Blob=class{constructor(parts,options){this.parts=parts;this.options=options;}};
global.URL={createObjectURL(){return "blob:synthetic";},revokeObjectURL(){}};
global.setTimeout=callback=>{callback();return 1;};
"""

_JS_ASSERTIONS = r"""
assert.equal(reads.length,0,"Initial loading must not read any annotator answers.");
assert.equal(writes.length,0,"Initial loading must not persist blank answers.");
assert.equal(activeAnnotator,null);
assert.equal($("answerFields").disabled,true);
for(const row of sourceRows)for(const field of fields)assert.equal(labels[row.review_id][field],"");
const initial=parsed(labels[sourceRows[0].review_id]);
for(const key of ["topic","intent","severity","sentiment","entities","needs_review","ambiguous","evidence_support","alternative_topics","alternative_intents","alternative_severities"])assert.equal(initial[key],null);

$("annotator").value="Synthetic annotator A";openWorkspace();
const keyA=activeStorageKey;
assert.equal(reads[0],keyA);
assert.equal($("answerFields").disabled,false);
assert.equal($("evidence_quote").value,"","Quote is blank until human action.");
$("copySource").onclick();
assert.equal(labels[sourceRows[0].review_id].evidence_quote,sourceRows[0].review_text);
const chosen={topic:"downloads",intent:"complaint",severity:"3",sentiment:"-0.5",entities:"[]",needs_review:"false",ambiguous:"true",evidence_support:"supported",alternative_topics:'["playback"]',alternative_intents:"[]",alternative_severities:"[3,4]",notes:"SYNTHETIC ONLY",alternative_notes:"Synthetic alternate interpretation"};
for(const [key,value] of Object.entries(chosen))$(key).value=value;
capture();persist();
assert.equal(errorsFor(labels[sourceRows[0].review_id],sourceRows[0].review_text).length,0);
const noDiagnostics={...labels[sourceRows[0].review_id],alternative_topics:"",alternative_intents:"",alternative_severities:"",alternative_notes:"",evidence_support:""};
assert.equal(errorsFor(noDiagnostics,sourceRows[0].review_text).length,0,"Optional diagnostics must not block completion.");
const exportA=makeExport();
assert.equal(exportA.complete,false,"Second review is intentionally unfinished.");
assert.equal(exportA.labels[0].human_labeler,"Synthetic annotator A");
assert.deepEqual(exportA.labels[0].alternative_topics,["playback"]);
assert.deepEqual(exportA.labels[0].alternative_intents,[]);
assert.equal(exportA.labels[0].needs_review,false);
assert.equal(exportA.labels[1].needs_review,null);
assert.equal(exportA.labels[1].entities,null);
assert.equal(exportA.labels[1].alternative_topics,null);

$("annotator").value="Synthetic annotator B";openWorkspace();
assert.notEqual(activeStorageKey,keyA);
assert.equal(labels[sourceRows[0].review_id].topic,"","Another annotator must start blank.");
assert.throws(()=>restoreExport(exportA),/different annotator/);
assert.equal(labels[sourceRows[0].review_id].topic,"");
$("annotator").value="Synthetic annotator A";openWorkspace();
assert.equal(labels[sourceRows[0].review_id].topic,"downloads","Own namespace must restore.");
const before=JSON.stringify(labels);
const mutated=JSON.parse(JSON.stringify(exportA));mutated.labels[0].review_text="changed";
assert.throws(()=>restoreExport(mutated),/Source text/);
assert.equal(JSON.stringify(labels),before,"Invalid restore must be atomic.");
const wrongRubric=JSON.parse(JSON.stringify(exportA));wrongRubric.rubric_version="wrong";
assert.throws(()=>restoreExport(wrongRubric),/different cohort/);
const duplicated=JSON.parse(JSON.stringify(exportA));duplicated.labels[1]=duplicated.labels[0];
assert.throws(()=>restoreExport(duplicated),/duplicate/);
restoreExport(exportA);
assert.equal(labels[sourceRows[0].review_id].topic,"downloads");
assert.equal(labels[sourceRows[1].review_id].needs_review,"");
assert.equal(labels[sourceRows[1].review_id].alternative_topics,"");
const badKey=storageKey("Synthetic corrupt workspace");stored.set(badKey,"{broken json");
$("annotator").value="Synthetic corrupt workspace";openWorkspace();
assert.equal(activeAnnotator,"Synthetic annotator A","Corrupt stored answers must not replace the active workspace.");
assert.equal(stored.get(badKey),"{broken json","Corrupt stored answers must remain recoverable.");

const invalid=blankLabel();invalid.needs_review="broken";
assert.equal(parsed(invalid).needs_review,"broken","Corrupted strings must not silently become false.");
assert(errorsFor(invalid,"source").some(message=>message.includes("needs review")));
const crlf=sourceRows[0].review_text;sourceRows[0].review_text="line one\r\nline two";
$("evidence_quote").value="line one\nline two";capture();
assert.equal(labels[sourceRows[0].review_id].evidence_quote,"line one\r\nline two");
sourceRows[0].review_text=crlf;

localStorage.getItem=()=>{throw new Error("storage disabled");};
localStorage.setItem=()=>{throw new Error("storage disabled");};
$("annotator").value="Synthetic no-storage annotator";openWorkspace();
assert.equal(activeAnnotator,"Synthetic no-storage annotator");
assert.equal($("answerFields").disabled,false,"Downloads must remain usable without localStorage.");
assert.equal(makeExport().labels[0].needs_review,null);
process.stdout.write(JSON.stringify({passed:true}));
"""
