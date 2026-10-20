"""Blind human labeling tools; this module never reads model predictions."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .models import INTENTS, TOPICS

LABEL_FIELDS = (
    "topic",
    "intent",
    "sentiment",
    "severity",
    "entities",
    "evidence_quote",
    "needs_review",
    "ambiguous",
    "notes",
)
TOPIC_DESCRIPTIONS = {
    "access": "Login, signup, password or account access.",
    "usability": "Navigation, controls, layout, queue/playlist management, ad interruptions.",
    "playback": "Playback failure, crashes, lag, connection failures, audio quality, resource use.",
    "downloads": "Downloading, saved music, offline listening, disappearing downloads.",
    "catalog": "Missing songs/artists, search/discovery, recommendations, lyrics availability.",
    "billing": "Price, charges, subscriptions, paywalls, premium entitlement; explicitly premium-only controls.",
    "support": "Contacting support and the support response.",
    "other": "General praise/criticism, unrelated content, or no supported specific topic.",
}
SEVERITY_DESCRIPTIONS = {
    "1": "No reported problem: praise, neutral/unclear content, or a pure feature request.",
    "2": "Dislike, generic criticism, minor annoyance or cosmetic issue; no supported functional loss.",
    "3": "Degraded or restricted function; some use or a workaround remains.",
    "4": "A clearly blocked core task, such as inability to log in or play music.",
    "5": "Explicit serious financial, privacy or data harm. Price, crashes or anger alone do not qualify.",
}


def _golden_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"review_id", "review_text"}.issubset(reader.fieldnames or []):
            raise ValueError("Golden CSV must have review_id and review_text columns")
        rows = [
            {"review_id": row["review_id"], "review_text": row["review_text"]}
            for row in reader
        ]
    if not rows:
        raise ValueError("Golden CSV contains no reviews")
    ids = [row["review_id"] for row in rows]
    if any(not review_id for review_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Golden CSV contains missing or duplicate review IDs")
    if any(not isinstance(row["review_text"], str) for row in rows):
        raise ValueError("Golden CSV contains a missing review_text field")
    return rows


def _script_json(value: Any) -> str:
    """JSON embedded in HTML must not permit closing the script element."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def generate_labeling_html(golden_csv: Path, output_path: Path) -> Path:
    """Write a standalone worksheet containing source texts and blank labels.

    Ratings, metadata and any populated label columns from the input are
    deliberately discarded. Progress is saved only in the browser until the
    human explicitly downloads a file.
    """
    rows = _golden_rows(golden_csv)
    digest = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    document = (
        _WORKSHEET.replace("__SOURCE_ROWS__", _script_json(rows))
        .replace("__TOPICS__", _script_json(list(TOPICS)))
        .replace("__INTENTS__", _script_json(list(INTENTS)))
        .replace("__TOPIC_DESCRIPTIONS__", _script_json(TOPIC_DESCRIPTIONS))
        .replace("__SEVERITY_DESCRIPTIONS__", _script_json(SEVERITY_DESCRIPTIONS))
        .replace("__STORAGE_KEY__", _script_json(f"spotify-human-labels-v1-{digest}"))
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return output_path


def _load_labels(path: Path) -> tuple[list[dict[str, Any]], bool]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return rows, True
    with path.open(encoding="utf-8-sig") as handle:
        if path.suffix.lower() == ".jsonl":
            data: Any = [json.loads(line) for line in handle if line.strip()]
        else:
            data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("labels")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("Human labels must be a CSV, a JSON array, a {'labels': [...]} object, or JSONL")
    return data, False


def _boolean(value: Any, field: str, from_csv: bool) -> bool:
    if type(value) is bool:
        return value
    if from_csv and isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{field} must be explicitly true or false")


def _number(value: Any, field: str, from_csv: bool) -> float:
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{field} must be a number")
    if from_csv and isinstance(value, str):
        try:
            value = float(value)
        except ValueError as error:
            raise ValueError(f"{field} must be a number") from error
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def validate_human_labels(path: Path, golden_csv: Path) -> list[dict]:
    """Validate a completed human file and return normalized, source-ordered labels.

    All golden IDs must occur exactly once. No missing answer is filled in.
    Ambiguity is an explicit diagnostic, and is required even when false.
    """
    golden = _golden_rows(golden_csv)
    sources = {row["review_id"]: row["review_text"] for row in golden}
    rows, from_csv = _load_labels(path)
    errors: list[str] = []
    seen: set[str] = set()
    labels: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, 1):
        review_id = row.get("review_id")
        prefix = f"Row {index} ({review_id!r})"
        if not isinstance(review_id, str) or review_id not in sources:
            errors.append(f"{prefix}: unknown or missing golden review_id")
            continue
        if review_id in seen:
            errors.append(f"{prefix}: duplicate review_id")
            continue
        seen.add(review_id)
        source = sources[review_id]
        try:
            if "review_text" in row and row["review_text"] != source:
                raise ValueError("review_text differs from the original golden source")
            missing = [field for field in LABEL_FIELDS if field != "notes" and field not in row]
            if missing:
                raise ValueError(f"missing required fields: {', '.join(missing)}")
            topic, intent = row["topic"], row["intent"]
            if topic not in TOPICS:
                raise ValueError(f"topic must be one of {', '.join(TOPICS)}")
            if intent not in INTENTS:
                raise ValueError(f"intent must be one of {', '.join(INTENTS)}")
            sentiment = _number(row["sentiment"], "sentiment", from_csv)
            severity = _number(row["severity"], "severity", from_csv)
            if not -1 <= sentiment <= 1:
                raise ValueError("sentiment must be between -1 and 1 inclusive")
            if not severity.is_integer() or not 1 <= severity <= 5:
                raise ValueError("severity must be an integer between 1 and 5 inclusive")
            if not from_csv and type(row["severity"]) is not int:
                raise ValueError("severity must be an integer, not a float or string")
            entities = row["entities"]
            if from_csv:
                try:
                    entities = json.loads(entities)
                except (TypeError, json.JSONDecodeError) as error:
                    raise ValueError('entities must be a JSON list, for example [] or ["offline"]') from error
            if not isinstance(entities, list) or any(
                not isinstance(entity, str) or not entity.strip() for entity in entities
            ):
                raise ValueError("entities must be a list of nonempty strings (or [])")
            if any(entity.casefold() not in source.casefold() for entity in entities):
                raise ValueError("every entity must appear explicitly in the original review text")
            quote = row["evidence_quote"]
            if not isinstance(quote, str) or not quote or quote not in source:
                raise ValueError("evidence_quote must be a nonempty exact original-text substring")
            needs_review = _boolean(row["needs_review"], "needs_review", from_csv)
            ambiguous = _boolean(row["ambiguous"], "ambiguous", from_csv)
            notes = row.get("notes", "")
            if not isinstance(notes, str):
                raise ValueError("notes must be text")
            human_labeler = row.get("human_labeler", "")
            if not isinstance(human_labeler, str):
                raise ValueError("human_labeler must be text")
            labels[review_id] = {
                "review_id": review_id,
                "review_text": source,
                "topic": topic,
                "intent": intent,
                "sentiment": sentiment,
                "severity": int(severity),
                "entities": entities,
                "evidence_quote": quote,
                "needs_review": needs_review,
                "ambiguous": ambiguous,
                "notes": notes,
                "human_labeler": human_labeler,
            }
        except (ValueError, TypeError) as error:
            errors.append(f"{prefix}: {error}")
    missing_ids = set(sources) - seen
    if missing_ids:
        errors.append(f"Missing {len(missing_ids)} golden ID(s): {', '.join(sorted(missing_ids)[:10])}")
    if errors:
        message = "\n".join(errors[:30])
        if len(errors) > 30:
            message += f"\n... and {len(errors) - 30} additional validation errors"
        raise ValueError(f"Human labels are incomplete or invalid:\n{message}")
    return [labels[row["review_id"]] for row in golden]


_WORKSHEET = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Spotify · Blind human labels</title>
<style>
:root{color-scheme:light;--ink:#14231c;--muted:#53655a;--line:#d4ddd6;--green:#14663c;--bg:#f3f6f1}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1180px;margin:auto;padding:30px 24px 70px}h1{font-size:32px;line-height:1.15;margin:8px 0 12px}
h2{font-size:19px;margin:0 0 12px}p{margin:8px 0 16px}.eyebrow{font-size:12px;font-weight:750;letter-spacing:.13em;text-transform:uppercase;color:var(--green)}
.muted,.help{color:var(--muted)}.help{font-size:13px;margin:5px 0 0}
.card{background:white;border:1px solid var(--line);border-radius:14px;padding:23px;margin-top:18px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.bar .push{margin-left:auto}
button,select,input,textarea{font:inherit}button{border:1px solid #acbfb1;border-radius:7px;background:#fff;color:var(--ink);padding:9px 13px;cursor:pointer}
button.primary{background:var(--green);border-color:var(--green);color:white}button:hover{filter:brightness(.96)}button:disabled{opacity:.4;cursor:not-allowed}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #80b291;outline-offset:2px}
select,input,textarea{border:1px solid #aebfb3;border-radius:6px;background:white;color:var(--ink);padding:9px;width:100%}
textarea{resize:vertical;min-height:88px}input[type=file]{width:auto;max-width:100%;font-size:13px}.compact{width:auto;max-width:100%}
label{font-weight:650;display:block}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.full{grid-column:1/-1}
.source{white-space:pre-wrap;overflow-wrap:anywhere;font-size:18px;line-height:1.65;padding:18px;background:#f1f5f0;border-left:4px solid var(--green);border-radius:4px;margin:12px 0 18px}
.id{font:12px ui-monospace,monospace;overflow-wrap:anywhere}.badge{font-size:13px;background:#e7eee8;padding:5px 10px;border-radius:20px}
progress{height:10px;width:100%;accent-color:var(--green)}details summary{cursor:pointer;font-weight:700}details p,details li{font-size:14px}
.rubric{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:16px}dl{margin:0}dt{font-weight:700;font-size:14px}dd{margin:0 0 10px;font-size:14px;color:var(--muted)}
.message{white-space:pre-wrap;font-size:14px;border-left:3px solid #829e89;padding-left:12px;margin:12px 0;min-height:20px}
.message.error{border-color:#a13e24;color:#8b311b}.success{color:var(--green)}footer{font-size:12px;color:var(--muted);margin-top:20px}
@media(max-width:720px){main{padding:20px 14px 45px}.grid,.rubric{grid-template-columns:1fr}.card{padding:17px}h1{font-size:27px}.bar .push{margin-left:0}.source{font-size:16px}}
</style>
</head>
<body><main>
<div class="eyebrow">Held-out evaluation · Human worksheet</div>
<h1>Read the review. Make your own judgment.</h1>
<p class="muted">All labels start blank. This worksheet shows original text only: no stars, metadata, or model predictions. Complete it before inspecting the model’s golden-set answers.</p>
<section class="card" aria-label="Progress and file controls">
<div class="bar"><strong id="progressLabel">0 complete</strong><span class="badge" id="ambiguousCount">0 ambiguous</span><span class="push help" id="saveStatus" role="status" aria-live="polite"></span></div>
<progress id="progress" max="50" value="0" aria-label="Completed reviews"></progress>
<div class="bar" style="margin-top:14px">
<button type="button" id="downloadJson" class="primary">Download JSON</button>
<button type="button" id="downloadCsv">Download CSV</button>
<button type="button" id="checkAll">Check all labels</button>
<label class="help" for="importFile">Restore downloaded JSON</label>
<input id="importFile" type="file" accept=".json,application/json">
</div>
<p class="help">Progress saves automatically in this browser. Download a backup when you stop; local browser storage is not a submission file. Draft downloads retain blank answers. Complete downloads contain only explicit human choices.</p>
<label class="help" for="humanLabeler">Your name or initials · human labeler</label>
<input id="humanLabeler" placeholder="Enter your name or initials" autocomplete="name" style="max-width:360px">
<p class="help">This records who made the judgments. If omitted, evaluation requires an explicit CLI confirmation that the labels are human-authored.</p>
<div id="message" class="message" role="status" aria-live="polite"></div>
</section>
<section class="card">
<details><summary>Label definitions, precedence, and examples</summary>
<p>Interpret the text itself. Choose the <strong>highest-severity supported specific problem</strong>; on a tie, choose the first one mentioned. For praise, choose the first specific praised feature. General praise or criticism uses <code>other</code>.</p>
<div class="rubric"><div><h2>Primary topic</h2><dl id="topicRubric"></dl></div><div><h2>Severity</h2><dl id="severityRubric"></dl></div></div>
<p><strong>Intent precedence:</strong> cancellation → complaint → request → praise → unclear. Cancellation means explicitly leaving, uninstalling, cancelling, or threatening to do so. Mixed praise/criticism is a complaint unless personal departure is expressed. A desired change without a reported failure is a request. Bare boycott slogans are unclear unless they state a product complaint or personal departure.</p>
<p><strong>Do not infer impact:</strong> stars, anger, or cancellation alone do not increase severity. “Bad app” is other / complaint / severity 2. “I wish there were more themes” is usability / request / severity 1. “I cannot log in at all” is access / complaint / severity 4. “Downloaded songs stop when I am offline” concerns downloads; apply severity to the explicitly reported impact.</p>
<p><strong>Paid-plan boundary:</strong> “I pay, and music keeps crashing” is playback. A paid subscription that never activates is billing. A paid-plan mention alone is not billing.</p>
<p><strong>Sentiment:</strong> −1 is strongly negative, −0.5 negative, 0 neutral or genuinely balanced, 0.5 positive, and 1 strongly positive. Intermediate values are allowed. Do not use stars.</p>
<p><strong>Evidence and uncertainty:</strong> copy an exact, meaningful source substring; the full original text is allowed. List only entities explicitly present in the review, one per line, or leave the entity list empty. Mark <em>needs review</em> for insufficient context or unsupported language. Mark <em>ambiguous</em> if more than one interpretation is defensible, choose your best label, and explain alternatives in notes.</p>
</details>
</section>
<section class="card" aria-label="Human labeling form">
<div class="bar">
<button id="previous" type="button">← Previous</button>
<label for="jump" class="help">Review</label><select id="jump" class="compact"></select>
<button id="next" type="button">Next →</button>
<button id="nextIncomplete" type="button" class="push">Next incomplete</button>
</div>
<p id="reviewId" class="id"></p>
<div id="sourceText" class="source"></div>
<form id="labelForm" novalidate>
<div class="grid">
<div><label for="topic">Primary topic</label><select id="topic"></select><p class="help" id="topicHelp">Choose the supported primary topic.</p></div>
<div><label for="intent">Intent</label><select id="intent"></select><p class="help">Apply the precedence in the rubric.</p></div>
<div><label for="severity">Severity</label><select id="severity"></select><p class="help" id="severityHelp">Rate the reported impact, not intensity of language.</p></div>
<div><label for="sentiment">Sentiment · −1 to 1</label><input id="sentiment" type="number" min="-1" max="1" step="any" placeholder="Enter a value"><p class="help">Use 0 for neutral or balanced text.</p></div>
<div><label for="needs_review">Needs review?</label><select id="needs_review"><option value="">Choose…</option value="false">No</option><option value="true">Yes</option></select><p class="help">Missing context, unsupported language, or insufficient evidence.</p></div>
<div><label for="ambiguous">Ambiguous interpretation?</label><select id="ambiguous"><option value="">Choose…</option><option value="false">No</option><option value="true">Yes</option></select><p class="help">Multiple defensible readings or labels.</p></div>
<div class="full"><div class="bar"><label for="evidence_quote">Evidence quote</label><button id="copySource" type="button" class="push">Use full original text</button></div><textarea id="evidence_quote" placeholder="Paste an exact source substring"></textarea><p class="help">Exact spelling, punctuation, accents, and whitespace must match the source.</p></div>
<div class="full"><label for="entities">Explicit entities · one per line</label><textarea id="entities" placeholder="Leave empty when none are explicitly present"></textarea><p class="help">Source terms only. An empty field exports as [].</p></div>
<div class="full"><label for="notes">Notes / ambiguity / alternative labels</label><textarea id="notes" placeholder="Optional explanation of your judgment"></textarea></div>
</div>
</form>
<div id="recordStatus" class="message" aria-live="polite"></div>
</section>
<footer>Blind worksheet generated from the course golden input. No network requests or API calls are made. Downloaded labels remain separate from enrichment prompts, routing thresholds, and grouping inputs.</footer>
</main>
<script>
"use strict";
const sourceRows=__SOURCE_ROWS__;
const topics=__TOPICS__,intents=__INTENTS__;
const topicDescriptions=__TOPIC_DESCRIPTIONS__,severityDescriptions=__SEVERITY_DESCRIPTIONS__;
const storageKey=__STORAGE_KEY__;
const fields=["topic","intent","sentiment","severity","entities","evidence_quote","needs_review","ambiguous","notes"];
const $=id=>document.getElementById(id);
let current=0, labels={}, storageAvailable=true, humanLabeler="";
const blank=()=>({topic:"",intent:"",sentiment:"",severity:"",entities:[],evidence_quote:"",needs_review:"",ambiguous:"",notes:""});
for(const row of sourceRows)labels[row.review_id]=blank();
function message(text,error=false){$("message").textContent=text;$("message").className="message"+(error?" error":"");}
function issues(label,source){
 const errors=[];
 if(!topics.includes(label.topic))errors.push("Choose a primary topic.");
 if(!intents.includes(label.intent))errors.push("Choose an intent.");
 if(typeof label.sentiment!=="number"||!Number.isFinite(label.sentiment)||label.sentiment < -1||label.sentiment > 1)errors.push("Enter sentiment between −1 and 1.");
 if(!Number.isInteger(label.severity)||label.severity<1||label.severity>5)errors.push("Choose severity 1–5.");
 if(typeof label.needs_review!=="boolean")errors.push("Choose yes or no for needs review.");
 if(typeof label.ambiguous!=="boolean")errors.push("Choose yes or no for ambiguity.");
 if(typeof label.evidence_quote!=="string"||!label.evidence_quote||!source.includes(label.evidence_quote))errors.push("Supply an exact nonempty source quote.");
 if(!Array.isArray(label.entities)||label.entities.some(entity=>typeof entity!=="string"||!entity.trim()||!source.toLowerCase().includes(entity.toLowerCase())))errors.push("Use only explicit source terms for entities.");
 if(typeof label.notes!=="string")errors.push("Notes must be text.");
 return errors;
}
function readForm(){
 const label={};for(const field of fields)label[field]=$(field).value;
 const originalText=sourceRows[current].review_text;
 if(label.evidence_quote===originalText.replace(/\r\n?/g,"\n"))label.evidence_quote=originalText;
 for(const field of ["sentiment","severity"])label[field]=label[field].trim()===""?"":Number(label[field]);
 for(const field of ["needs_review","ambiguous"])label[field]=label[field]===""?"":label[field]==="true";
 label.entities=label.entities.split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
 labels[sourceRows[current].review_id]=label;
}
function save(){
 try{localStorage.setItem(storageKey,JSON.stringify({version:1,labels,current,humanLabeler}));$("saveStatus").textContent="Saved in this browser";storageAvailable=true;}
 catch(error){storageAvailable=false;$("saveStatus").textContent="Browser storage unavailable — download a backup";}
}
function progress(){
 const done=sourceRows.filter(row=>issues(labels[row.review_id],row.review_text).length===0).length;
 const ambiguous=sourceRows.filter(row=>labels[row.review_id].ambiguous===true).length;
 $("progressLabel").textContent=`${done} / ${sourceRows.length} complete`;
 $("ambiguousCount").textContent=`${ambiguous} ambiguous`;
 $("progress").max=sourceRows.length;$("progress").value=done;
 for(let index=0;index<sourceRows.length;index++){
  const row=sourceRows[index],complete=issues(labels[row.review_id],row.review_text).length===0;
  $("jump").options[index].textContent=`${index+1} ${complete?"✓":""}`;
 }
 const errors=issues(labels[sourceRows[current].review_id],sourceRows[current].review_text);
 $("recordStatus").textContent=errors.length?`${errors.length} item(s) remaining: ${errors.join(" ")}`:"This review is complete.";
 $("recordStatus").className="message"+(errors.length?"":" success");
}
function show(index){
 current=index;const row=sourceRows[current],label=labels[row.review_id];
 $("reviewId").textContent=row.review_id;$("sourceText").textContent=row.review_text;
 for(const field of fields)$(field).value=field==="entities"?label[field].join("\n"):String(label[field]);
 $("jump").value=String(index);$("previous").disabled=index===0;$("next").disabled=index===sourceRows.length-1;
 $("topicHelp").textContent=topicDescriptions[label.topic]||"Choose the supported primary topic.";
 $("severityHelp").textContent=severityDescriptions[label.severity]||"Rate the reported impact, not intensity of language.";
 progress();save();
}
function populateSelect(id,values){
 const initial=document.createElement("option");initial.value="";initial.textContent="Choose…";$(id).append(initial);
 for(const value of values){const option=document.createElement("option");option.value=value;option.textContent=value;$(id).append(option);}
}
function addRubric(id,definitions){
 for(const [term,definition] of Object.entries(definitions)){
  const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=term;dd.textContent=definition;$(id).append(dt,dd);
 }
}
function normalizedImport(rows){
 if(!Array.isArray(rows))throw new Error("Expected an array of labels.");
 const imported={},seen=new Set(),sources=new Map(sourceRows.map(row=>[row.review_id,row.review_text]));
 for(const row of rows){
  if(!row||typeof row!=="object"||!sources.has(row.review_id)||seen.has(row.review_id))throw new Error("File has an unknown, missing, or duplicate review ID.");
  if("review_text" in row&&row.review_text!==sources.get(row.review_id))throw new Error("File changes an original review text.");
  const label=blank();
  for(const field of fields)if(field in row)label[field]=row[field];
  if(!Array.isArray(label.entities)||label.entities.some(entity=>typeof entity!=="string"))throw new Error("Entities must be an array of text strings.");
  for(const field of ["topic","intent","evidence_quote","notes"])if(typeof label[field]!=="string")throw new Error(`${field} must be text.`);
  for(const field of ["severity","sentiment"])if(label[field]!==""&&typeof label[field]!=="number")throw new Error(`${field} must be a number or blank.`);
  for(const field of ["needs_review","ambiguous"])if(label[field]!==""&&typeof label[field]!=="boolean")throw new Error(`${field} must be a boolean or blank.`);
  imported[row.review_id]=label;seen.add(row.review_id);
 }
 if(seen.size!==sourceRows.length)throw new Error(`Expected all ${sourceRows.length} original review IDs.`);
 return imported;
}
function exportRows(){return sourceRows.map(row=>({...row,...labels[row.review_id],human_labeler:humanLabeler}));}
function download(format){
 readForm();save();progress();const rows=exportRows(),complete=rows.every(row=>issues(row,row.review_text).length===0);
 let content,type;
 if(format==="json"){content=JSON.stringify(rows,null,2)+"\n";type="application/json";}
 else{
  const columns=["review_id","review_text",...fields,"human_labeler"],quote=value=>'"'+String(value).replaceAll('"','""')+'"';
  content=[columns.map(quote).join(","),...rows.map(row=>columns.map(field=>quote(field==="entities"?JSON.stringify(row[field]):row[field])).join(","))].join("\r\n")+"\r\n";
  type="text/csv;charset=utf-8";
 }
 const link=document.createElement("a"),url=URL.createObjectURL(new Blob([content],{type}));
 link.href=url;link.download=`golden-human-labels${complete?"":"-DRAFT"}.${format}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 message(complete?"Downloaded completed human labels. Keep them isolated until final evaluation.":"Downloaded a draft. Blank or invalid answers still need completion.");
}
populateSelect("topic",topics);populateSelect("intent",intents);populateSelect("severity",["1","2","3","4","5"]);
addRubric("topicRubric",topicDescriptions);addRubric("severityRubric",severityDescriptions);
sourceRows.forEach((row,index)=>{const option=document.createElement("option");option.value=String(index);option.textContent=String(index+1);$("jump").append(option);});
try{
 const saved=localStorage.getItem(storageKey);
 if(saved){const state=JSON.parse(saved);labels=normalizedImport(sourceRows.map(row=>({...row,...state.labels[row.review_id]})));humanLabeler=typeof state.humanLabeler==="string"?state.humanLabeler:"";$("humanLabeler").value=humanLabeler;current=Number.isInteger(state.current)&&state.current>=0&&state.current<sourceRows.length?state.current:0;message("Restored your saved progress from this browser.");}
}catch(error){message(`Could not restore browser progress: ${error.message}. Use a downloaded JSON backup if available.`,true);}
$("labelForm").addEventListener("submit",event=>event.preventDefault());
$("humanLabeler").addEventListener("input",()=>{humanLabeler=$("humanLabeler").value.trim();save();});
$("labelForm").addEventListener("input",()=>{readForm();save();progress();$("topicHelp").textContent=topicDescriptions[$("topic").value]||"Choose the supported primary topic.";$("severityHelp").textContent=severityDescriptions[$("severity").value]||"Rate the reported impact, not intensity of language.";});
$("previous").onclick=()=>{readForm();show(current-1);};$("next").onclick=()=>{readForm();show(current+1);};
$("jump").onchange=()=>{readForm();show(Number($("jump").value));};
$("nextIncomplete").onclick=()=>{
 readForm();for(let offset=1;offset<=sourceRows.length;offset++){const index=(current+offset)%sourceRows.length,row=sourceRows[index];if(issues(labels[row.review_id],row.review_text).length){show(index);return;}}
 message("Every review is complete. Download your labels.");
};
$("copySource").onclick=()=>{$("evidence_quote").value=sourceRows[current].review_text;readForm();save();progress();};
$("downloadJson").onclick=()=>download("json");$("downloadCsv").onclick=()=>download("csv");
$("checkAll").onclick=()=>{
 readForm();save();progress();const incomplete=sourceRows.map((row,index)=>({index,errors:issues(labels[row.review_id],row.review_text)})).filter(row=>row.errors.length);
 message(incomplete.length?`${incomplete.length} incomplete review(s). First unfinished: review ${incomplete[0].index+1}.\n${incomplete[0].errors.join("\n")}`:"All labels are complete and structurally valid. Download JSON or CSV for the final evaluation.",!!incomplete.length);
};
$("importFile").onchange=async event=>{
 const file=event.target.files[0];if(!file)return;
 try{const data=JSON.parse(await file.text()),rows=Array.isArray(data)?data:data.labels;const imported=normalizedImport(rows);labels=imported;const authors=new Set(rows.map(row=>row.human_labeler).filter(value=>typeof value==="string"&&value.trim()));if(authors.size===1){humanLabeler=[...authors][0];$("humanLabeler").value=humanLabeler;}show(current);message("Restored downloaded labels. Existing browser progress was replaced by this file.");}
 catch(error){message(`Import rejected; your current labels were kept. ${error.message}`,true);}
 event.target.value="";
};
show(current);
</script>
</body></html>
"""
