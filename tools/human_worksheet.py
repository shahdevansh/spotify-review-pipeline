"""Generate standalone, blind human-labeling worksheets using only the stdlib.

This module does not load predictions, human answers, provider libraries, or
network resources. Callers supply source-only rows and the applicable rubric.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")
EVIDENCE_SUPPORT = ("supported", "partial", "unsupported", "unclear")
SCHEMA_VERSION = "spotify-human-labels-v2"
ALLOWED_SOURCE_KEYS = frozenset({"review_id", "review_text", "row_sha"})


def _script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _rubric_content(rubric: str | Mapping[str, Any], rubric_version: str | None, version: str) -> dict[str, Any]:
    if isinstance(rubric, str):
        title, sections = "Human-labeling rubric", [{"title": "Definitions and decision rules", "text": rubric}]
        rubric_version = rubric_version or version
    elif isinstance(rubric, Mapping):
        title = rubric.get("title", "Human-labeling rubric")
        rubric_version = rubric_version or rubric.get("version") or version
        raw_sections = rubric.get("sections")
        if raw_sections is None:
            raw_sections = [{"title": "Definitions and decision rules", "text": rubric.get("text", "")}]
        if isinstance(raw_sections, Mapping):
            raw_sections = [{"title": key, "text": value} for key, value in raw_sections.items()]
        if not isinstance(raw_sections, (list, tuple)):
            raise ValueError("rubric.sections must be a list of {title, text} sections or a mapping")
        sections = []
        for section in raw_sections:
            if not isinstance(section, Mapping):
                raise ValueError("Each rubric section must contain title and text")
            sections.append({"title": section.get("title", ""), "text": section.get("text", "")})
    else:
        raise TypeError("rubric must be plain text or a mapping")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Rubric title must be nonempty text")
    if not isinstance(rubric_version, str) or not rubric_version.strip():
        raise ValueError("Rubric version must be nonempty text")
    if not sections or any(
        not isinstance(section["title"], str)
        or not isinstance(section["text"], str)
        or not section["text"].strip()
        for section in sections
    ):
        raise ValueError("Rubric must contain nonempty textual instructions")
    return {"title": title, "version": rubric_version, "sections": sections}


def generate_html(
    rows: Iterable[Mapping[str, Any]],
    output_path: str | Path,
    *,
    cohort_id: str,
    rubric: str | Mapping[str, Any],
    seed: str | int | None = None,
    version: str = "1",
    rubric_version: str | None = None,
) -> Path:
    """Write a blank worksheet and return its path.

    ``rows`` accepts only review_id/review_text and optional row_sha. Extra
    columns are rejected, including ratings, predictions and existing labels.
    ``rubric`` accepts plain text or {version, title, sections}; sections may be
    [{title, text}, ...] or a title-to-text mapping. Neither rubric nor source
    text is interpreted as HTML.

    JSON exports contain provenance metadata and a ``labels`` array. CSV
    exports repeat provenance columns for independent use. Answers are saved
    by the browser only, never by this generator.
    """
    if not isinstance(cohort_id, str) or not cohort_id.strip():
        raise ValueError("cohort_id must be nonempty text")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version must be nonempty text")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, (str, int))):
        raise ValueError("seed must be text, an integer, or None")
    source_rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Source row {index} must be a mapping")
        unexpected = set(raw) - ALLOWED_SOURCE_KEYS
        if unexpected:
            raise ValueError(f"Source row {index} has disallowed columns: {', '.join(sorted(unexpected))}")
        review_id, review_text = raw.get("review_id"), raw.get("review_text")
        if not isinstance(review_id, str) or not review_id.strip() or review_id in seen:
            raise ValueError(f"Source row {index} has a missing, invalid, or duplicate review_id")
        if not isinstance(review_text, str) or not review_text.strip():
            raise ValueError(f"Source row {index} must have nonempty original review_text")
        row = {"review_id": review_id, "review_text": review_text}
        if "row_sha" in raw:
            if not isinstance(raw["row_sha"], str) or not re.fullmatch(r"[a-f0-9]{64}", raw["row_sha"]):
                raise ValueError(f"Source row {index} has an invalid row_sha")
            row["row_sha"] = raw["row_sha"]
        source_rows.append(row)
        seen.add(review_id)
    if not source_rows:
        raise ValueError("At least one source review is required")
    rubric_data = _rubric_content(rubric, rubric_version, version)
    digest = lambda value: hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "worksheet_version": version,
        "cohort_id": cohort_id,
        "rubric_version": rubric_data["version"],
        "rubric_sha256": digest(rubric_data),
        "source_digest": digest(source_rows),
        "seed": seed,
    }
    payload = {"metadata": metadata, "rows": source_rows, "rubric": rubric_data}
    # Replace payload last so source text cannot introduce a template directive.
    document = _HTML.replace("__PAGE_TITLE__", html.escape(f"{cohort_id} · Blind human labels", quote=True))
    document = document.replace("__WORKSHEET_PAYLOAD__", _script_json(payload))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return output_path


_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; form-action 'none'; base-uri 'none'">
<title>__PAGE_TITLE__</title>
<style>
:root{color-scheme:light;--ink:#15231b;--muted:#52645a;--line:#cfdcd2;--green:#155d39;--bg:#f3f6f1}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1160px;padding:28px 24px 64px;margin:auto}h1{font-size:32px;line-height:1.15;margin:10px 0}h2{font-size:19px;margin:0 0 12px}
p{margin:8px 0 16px}.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--green);font-weight:750}
.muted,.help{color:var(--muted)}.help{font-size:13px}.card{border:1px solid var(--line);border-radius:14px;padding:23px;background:#fff;margin-top:18px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.push{margin-left:auto}
button,input,select,textarea{font:inherit}input,select,textarea{width:100%;border:1px solid #aabfaf;border-radius:6px;padding:9px;color:var(--ink);background:#fff}
textarea{min-height:84px;resize:vertical}button{border:1px solid #aabfaf;border-radius:7px;padding:9px 13px;background:white;color:var(--ink);cursor:pointer}
button.primary{background:var(--green);color:white;border-color:var(--green)}button:disabled{opacity:.45;cursor:not-allowed}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #84b797;outline-offset:2px}
label{display:block;font-weight:650}fieldset{border:0;padding:0;margin:0;min-width:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.full{grid-column:1/-1}
.source{white-space:pre-wrap;overflow-wrap:anywhere;background:#eff4ee;border-left:4px solid var(--green);padding:18px;font-size:18px;line-height:1.65;border-radius:4px}
.review-id{font:12px ui-monospace,monospace;overflow-wrap:anywhere}.compact{width:auto;max-width:100%}.rubric-text{white-space:pre-wrap;font-size:14px}
.message{font-size:14px;white-space:pre-wrap;border-left:3px solid #829e89;padding-left:12px;margin:12px 0}.message.error{color:#91381e;border-color:#b75133}
.badge{background:#e8efe8;border-radius:16px;padding:5px 10px;font-size:13px}progress{width:100%;height:11px;accent-color:var(--green)}
summary{font-weight:700;cursor:pointer}.rubric-section{margin-top:18px}input[type=file]{width:auto;font-size:13px}footer{font-size:12px;color:var(--muted);margin-top:20px}
@media(max-width:700px){main{padding:20px 12px 40px}.card{padding:17px}.grid{grid-template-columns:1fr}.push{margin-left:0}h1{font-size:27px}.source{font-size:16px}}
</style></head><body><main>
<div class="eyebrow">Independent human evaluation</div><h1>Label the text before seeing predictions.</h1>
<p class="muted">Every judgment starts blank. Read each original review, apply the rubric, and record uncertainty explicitly. No rating, model answer, or other review metadata is shown.</p>
<section class="card"><h2>Your private annotator workspace</h2>
<div class="bar"><div style="flex:1;min-width:220px"><label for="annotator">Human labeler / annotator ID</label><input id="annotator" autocomplete="off" maxlength="120" placeholder="Your name or agreed annotator ID"></div><button id="openWorkspace" type="button" class="primary">Open / switch workspace</button></div>
<p class="help">Choose your identifier explicitly. Browser autosave is separate for each cohort, rubric, source selection, and annotator. Changing the identifier opens a different workspace.</p>
<p id="workspaceStatus" class="help" role="status"></p>
<div class="bar"><strong id="progressLabel">0 complete</strong><span id="ambiguityCount" class="badge">0 ambiguous</span><span id="saveStatus" class="help push"></span></div><progress id="progress" max="1" value="0" aria-label="Completed judgments"></progress>
<div class="bar" style="margin-top:14px"><button id="downloadJson" type="button" class="primary" disabled>Download JSON</button><button id="downloadCsv" type="button" disabled>Download CSV</button><button id="checkAll" type="button" disabled>Check all labels</button><label for="restore" class="help">Restore JSON</label><input id="restore" type="file" accept=".json,application/json" disabled></div>
<p class="help"><strong>Save answer downloads under <code>private/human-labels/</code>.</strong> Move browser downloads there manually; this page cannot choose that folder. Never commit or publish answer files. Filenames include <code>PRIVATE__save-in-private-human-labels__</code>. Download a backup whenever you stop.</p>
<div id="message" class="message" role="status" aria-live="polite"></div></section>
<section class="card"><details open><summary id="rubricHeading">Versioned labeling rubric</summary><div id="rubricSections"></div>
<div class="rubric-section"><h2>Recording answers</h2>
<p class="rubric-text">Evidence quote: copy an exact nonempty substring. “Use full original text” is optional and only fills it after you click.
Entities: enter a JSON list of source terms, such as ["offline"], or explicitly choose [] if there are none.
Alternatives: optional JSON lists of defensible labels, such as ["playback","downloads"] or [3,4]. Explain alternatives in the notes.
Optional evidence support: supported = your selected quote supports your selected labels; partial = it supports only part; unsupported = it does not support them; unclear = you cannot tell. This is your judgment about your own quote and labels. Auditing model quote entailment is a separate task after human labels and predictions are locked.
Needs review and ambiguous are independent judgments. Neither defaults to “no.” A valid form does not establish correctness.</p></div></details></section>
<section class="card"><div class="bar"><button id="previous" type="button" disabled>← Previous</button><label class="help" for="jump">Review</label><select id="jump" class="compact" disabled></select><button id="next" type="button" disabled>Next →</button><button id="nextIncomplete" type="button" class="push" disabled>Next incomplete</button></div>
<p id="reviewId" class="review-id"></p><div id="sourceText" class="source"></div>
<form id="labelForm"><fieldset id="answerFields" disabled><div class="grid" style="margin-top:20px">
<div><label for="topic">Primary topic</label><select id="topic"></select></div>
<div><label for="intent">Intent</label><select id="intent"></select></div>
<div><label for="severity">Severity</label><select id="severity"></select></div>
<div><label for="sentiment">Sentiment · −1 to 1</label><input id="sentiment" type="number" min="-1" max="1" step="any" placeholder="Enter a value"></div>
<div><label for="needs_review">Needs review?</label><select id="needs_review"></select></div>
<div><label for="ambiguous">Ambiguous interpretation?</label><select id="ambiguous"></select></div>
<div class="full"><div class="bar"><label for="evidence_quote">Evidence quote</label><button id="copySource" type="button" class="push">Use full original text</button></div><textarea id="evidence_quote" placeholder="Exact source substring"></textarea></div>
<div class="full"><div class="bar"><label for="entities">Explicit entities · JSON list</label><button id="noEntities" type="button" class="push">No explicit entities: []</button></div><textarea id="entities" placeholder='["offline"] or []'></textarea></div>
<details class="full"><summary>Optional diagnostics: alternative labels and evidence support</summary><p class="help">You may leave these blank. Add them when a review has multiple plausible interpretations.</p><div class="grid">
<div class="full"><label for="evidence_support">Does your selected quote support your labels?</label><select id="evidence_support"></select></div>
<div><label for="alternative_topics">Alternative topics · optional JSON list</label><textarea id="alternative_topics" placeholder='["downloads","playback"]'></textarea></div>
<div><label for="alternative_intents">Alternative intents · optional JSON list</label><textarea id="alternative_intents" placeholder='["complaint","request"]'></textarea></div>
<div><label for="alternative_severities">Alternative severities · optional JSON list</label><textarea id="alternative_severities" placeholder="[3,4]"></textarea></div>
<div><label for="alternative_notes">Reason for alternatives</label><textarea id="alternative_notes" placeholder="Optional explanation"></textarea></div>
</div></details>
<div class="full"><label for="notes">Notes / uncertainty / interpretation</label><textarea id="notes" placeholder="Optional explanation"></textarea></div>
</div></fieldset></form><div id="recordStatus" class="message" aria-live="polite"></div></section>
<footer>Standalone and local only. No provider calls, analytics, remote assets, or network requests. The page writes browser storage after you open an annotator workspace; answers leave the page only through your explicit download action.</footer>
</main><script>
"use strict";
const payload=__WORKSHEET_PAYLOAD__;
const metadata=payload.metadata,sourceRows=payload.rows;
const topics=["access","usability","playback","downloads","catalog","billing","support","other"];
const intents=["cancellation","complaint","request","praise","unclear"];
const evidenceSupports=["supported","partial","unsupported","unclear"];
const fields=["topic","intent","severity","sentiment","entities","evidence_quote","needs_review","ambiguous","notes","alternative_topics","alternative_intents","alternative_severities","evidence_support","alternative_notes"];
const listFields=["entities","alternative_topics","alternative_intents","alternative_severities"];
const $=id=>document.getElementById(id);
let labels=blankLabels(),current=0,activeAnnotator=null,activeStorageKey=null;
function blankLabel(){return Object.fromEntries(fields.map(field=>[field,""]));}
function blankLabels(){return Object.fromEntries(sourceRows.map(row=>[row.review_id,blankLabel()]));}
function storageKey(annotator){return ["spotify-human-worksheet",metadata.schema_version,metadata.cohort_id,metadata.rubric_version,metadata.rubric_sha256,metadata.source_digest,metadata.worksheet_version,JSON.stringify(metadata.seed),annotator].map(encodeURIComponent).join(":");}
function message(text,error=false){$("message").textContent=text;$("message").className="message"+(error?" error":"");}
function parsed(raw){
 const record={...raw};
 for(const key of ["severity","sentiment"])record[key]=raw[key]===""?null:Number(raw[key]);
 for(const key of ["needs_review","ambiguous"])record[key]=raw[key]===""?null:raw[key]==="true"?true:raw[key]==="false"?false:raw[key];
 for(const key of listFields){if(raw[key].trim()===""){record[key]=null;continue;}try{record[key]=JSON.parse(raw[key]);}catch{record[key]=raw[key];}}
 for(const key of ["topic","intent","evidence_quote","evidence_support"])if(record[key]==="")record[key]=null;
 return record;
}
function errorsFor(raw,source){
 const row=parsed(raw),errors=[];
 if(!topics.includes(row.topic))errors.push("Choose a topic.");
 if(!intents.includes(row.intent))errors.push("Choose an intent.");
 if(!Number.isInteger(row.severity)||row.severity<1||row.severity>5)errors.push("Choose severity 1–5.");
 if(typeof row.sentiment!=="number"||!Number.isFinite(row.sentiment)||row.sentiment < -1||row.sentiment > 1)errors.push("Enter sentiment between −1 and 1.");
 if(typeof row.needs_review!=="boolean")errors.push("Choose needs review yes/no.");
 if(typeof row.ambiguous!=="boolean")errors.push("Choose ambiguous yes/no.");
 if(typeof row.evidence_quote!=="string"||!row.evidence_quote||!source.includes(row.evidence_quote))errors.push("Supply an exact source quote.");
 if(row.evidence_support!==null&&!evidenceSupports.includes(row.evidence_support))errors.push("Choose a valid evidence-support option or leave it blank.");
 if(!Array.isArray(row.entities)||row.entities.some(value=>typeof value!=="string"||!value.trim()||!source.toLowerCase().includes(value.toLowerCase())))errors.push("Enter a JSON list of explicit source entities, or explicitly enter [].");
 for(const [key,allowed] of [["alternative_topics",topics],["alternative_intents",intents],["alternative_severities",[1,2,3,4,5]]]){
  if(row[key]!==null&&(!Array.isArray(row[key])||row[key].some(value=>!allowed.includes(value))))errors.push(`${key} must be a JSON list of allowed labels.`);
 }
 return errors;
}
function capture(){
 if(!activeAnnotator)return;
 const raw={};for(const key of fields)raw[key]=$(key).value;
 const original=sourceRows[current].review_text;
 if(raw.evidence_quote===original.replace(/\r\n?/g,"\n"))raw.evidence_quote=original;
 labels[sourceRows[current].review_id]=raw;
}
function persist(){
 if(!activeStorageKey)return;
 try{localStorage.setItem(activeStorageKey,JSON.stringify({metadata,annotator_id:activeAnnotator,current,labels}));$("saveStatus").textContent="Saved locally for "+activeAnnotator;}
 catch{$("saveStatus").textContent="Browser save unavailable — download a backup.";message("Browser storage is unavailable or full. Your visible answers remain in this page; download JSON before closing it.",true);}
}
function updateProgress(){
 const completed=sourceRows.filter(row=>errorsFor(labels[row.review_id],row.review_text).length===0).length;
 $("progressLabel").textContent=`${completed} / ${sourceRows.length} complete`;$("progress").max=sourceRows.length;$("progress").value=completed;
 $("ambiguityCount").textContent=`${sourceRows.filter(row=>labels[row.review_id].ambiguous==="true").length} ambiguous`;
 sourceRows.forEach((row,index)=>{$("jump").options[index].textContent=`${index+1}${errorsFor(labels[row.review_id],row.review_text).length?"":" ✓"}`;});
 const errors=errorsFor(labels[sourceRows[current].review_id],sourceRows[current].review_text);
 $("recordStatus").textContent=activeAnnotator?(errors.length?errors.join(" "):"This review is complete."):"Open an annotator workspace to enter judgments.";
}
function render(){
 const row=sourceRows[current],raw=labels[row.review_id];$("reviewId").textContent=row.review_id;$("sourceText").textContent=row.review_text;
 for(const key of fields)$(key).value=raw[key];
 $("jump").value=String(current);$("answerFields").disabled=!activeAnnotator;
 for(const id of ["downloadJson","downloadCsv","checkAll","restore","jump","nextIncomplete"])$(id).disabled=!activeAnnotator;
 $("previous").disabled=!activeAnnotator||current===0;$("next").disabled=!activeAnnotator||current===sourceRows.length-1;
 updateProgress();
}
function matchingMetadata(other){
 if(!other||typeof other!=="object")return false;
 return ["schema_version","worksheet_version","cohort_id","rubric_version","rubric_sha256","source_digest"].every(key=>other[key]===metadata[key])&&other.seed===metadata.seed;
}
function validateRawLabels(candidate){
 if(!candidate||typeof candidate!=="object"||Array.isArray(candidate)||Object.keys(candidate).length!==sourceRows.length)throw new Error("Saved labels do not match this review selection.");
 const normalized={};
 for(const row of sourceRows){
  const raw=candidate[row.review_id];if(!raw||typeof raw!=="object"||fields.some(field=>typeof raw[field]!=="string"))throw new Error("Saved answer format is invalid.");
  normalized[row.review_id]=Object.fromEntries(fields.map(field=>[field,raw[field]]));
 }
 return normalized;
}
function openWorkspace(){
 const requested=$("annotator").value.trim();if(!requested||requested.length>120){message("Enter your own annotator ID (1–120 characters).",true);return;}
 capture();persist();
 const key=storageKey(requested);let nextLabels=blankLabels(),nextCurrent=0,saved=null,storageWarning=false;
 try{saved=localStorage.getItem(key);}catch{storageWarning=true;}
 try{if(saved){const state=JSON.parse(saved);if(!matchingMetadata(state.metadata)||state.annotator_id!==requested)throw new Error("Stored provenance does not match this workspace.");nextLabels=validateRawLabels(state.labels);if(Number.isInteger(state.current)&&state.current>=0&&state.current<sourceRows.length)nextCurrent=state.current;}}
 catch(error){message("Workspace could not be restored. Existing browser data was not overwritten. "+error.message,true);return;}
 activeAnnotator=requested;activeStorageKey=key;labels=nextLabels;current=nextCurrent;
 $("workspaceStatus").textContent=`Active annotator: ${requested} · Cohort: ${metadata.cohort_id} · Rubric: ${metadata.rubric_version}`;
 render();persist();message(storageWarning?"Annotator workspace opened without browser autosave. Download JSON before closing the page.":"Annotator workspace opened. Download backups to private/human-labels/.",storageWarning);
}
function makeExport(){
 capture();persist();updateProgress();
 const rows=sourceRows.map(row=>({...row,...parsed(labels[row.review_id]),human_labeler:activeAnnotator}));
 const validation=sourceRows.map(row=>({review_id:row.review_id,errors:errorsFor(labels[row.review_id],row.review_text)})).filter(row=>row.errors.length);
 return {...metadata,annotator_id:activeAnnotator,exported_at:new Date().toISOString(),complete:validation.length===0,validation_errors:validation,labels:rows};
}
function download(format){
 if(!activeAnnotator)return;const data=makeExport();let content,type;
 if(format==="json"){content=JSON.stringify(data,null,2)+"\n";type="application/json";}
 else{
  const columns=["review_id","review_text","row_sha",...fields,"human_labeler","cohort_id","rubric_version","rubric_sha256","worksheet_version","source_digest","seed"];
  const quote=value=>'"'+String(value??"").replaceAll('"','""')+'"';
  content=[columns.map(quote).join(","),...data.labels.map(row=>columns.map(key=>{
   const value=Object.prototype.hasOwnProperty.call(row,key)?row[key]:metadata[key];
   return quote(Array.isArray(value)?JSON.stringify(value):value);
  }).join(","))].join("\r\n")+"\r\n";type="text/csv;charset=utf-8";
 }
 const safe=value=>String(value).replace(/[^A-Za-z0-9._-]+/g,"_").slice(0,80);
 const link=document.createElement("a"),url=URL.createObjectURL(new Blob([content],{type}));
 link.href=url;link.download=`PRIVATE__save-in-private-human-labels__${safe(metadata.cohort_id)}__${safe(activeAnnotator)}__${data.complete?"complete":"DRAFT"}.${format}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 message(`Downloaded ${data.complete?"completed labels":"a draft with incomplete or invalid labels"}. Move the file to private/human-labels/; never publish it.`);
}
function restoreExport(data){
 if(!activeAnnotator)throw new Error("Open your annotator workspace first.");
 if(!matchingMetadata(data))throw new Error("The file belongs to a different cohort, rubric, selection, or worksheet version.");
 if(data.annotator_id!==activeAnnotator)throw new Error("The file belongs to a different annotator. Open that annotator’s workspace first.");
 if(!Array.isArray(data.labels)||data.labels.length!==sourceRows.length)throw new Error("Expected every original review exactly once.");
 const sources=new Map(sourceRows.map(row=>[row.review_id,row])),candidate={},seen=new Set();
 for(const row of data.labels){
  if(!row||typeof row!=="object"||!sources.has(row.review_id)||seen.has(row.review_id))throw new Error("Unknown, missing, or duplicate review ID.");
  const source=sources.get(row.review_id);
  if(row.review_text!==source.review_text||row.row_sha!==source.row_sha||row.human_labeler!==activeAnnotator)throw new Error("Source text, row hash, or labeler changed.");
  const raw=blankLabel();
  for(const key of fields){
   const value=row[key];if(value===undefined)throw new Error("Missing field: "+key);
   if(value===null){raw[key]="";continue;}
   if(listFields.includes(key)){if(!Array.isArray(value)&&typeof value!=="string")throw new Error("Invalid list field: "+key);raw[key]=Array.isArray(value)?JSON.stringify(value):value;}
   else if(["needs_review","ambiguous"].includes(key)){if(typeof value!=="boolean")throw new Error("Invalid boolean: "+key);raw[key]=String(value);}
   else if(["severity","sentiment"].includes(key)){if(typeof value!=="number"||!Number.isFinite(value))throw new Error("Invalid number: "+key);raw[key]=String(value);}
   else{if(typeof value!=="string")throw new Error("Invalid text field: "+key);raw[key]=value;}
  }
  for(const [key,allowed] of [["topic",topics],["intent",intents],["evidence_support",evidenceSupports]])if(raw[key]&&!allowed.includes(raw[key]))throw new Error("Invalid choice: "+key);
  candidate[row.review_id]=raw;seen.add(row.review_id);
 }
 labels=validateRawLabels(candidate);render();persist();
}
function populate(id,values){
 const empty=document.createElement("option");empty.value="";empty.textContent="Choose…";$(id).append(empty);
 for(const [value,label] of values){const option=document.createElement("option");option.value=String(value);option.textContent=label;$(id).append(option);}
}
populate("topic",topics.map(value=>[value,value]));populate("intent",intents.map(value=>[value,value]));
populate("severity",[1,2,3,4,5].map(value=>[value,String(value)]));populate("evidence_support",evidenceSupports.map(value=>[value,value]));
for(const id of ["needs_review","ambiguous"])populate(id,[["false","No"],["true","Yes"]]);
sourceRows.forEach((row,index)=>{const option=document.createElement("option");option.value=String(index);option.textContent=String(index+1);$("jump").append(option);});
$("rubricHeading").textContent=`${payload.rubric.title} · version ${payload.rubric.version}`;
for(const section of payload.rubric.sections){const block=document.createElement("section"),heading=document.createElement("h2"),text=document.createElement("p");block.className="rubric-section";heading.textContent=section.title;text.className="rubric-text";text.textContent=section.text;block.append(heading,text);$("rubricSections").append(block);}
$("workspaceStatus").textContent=`Cohort: ${metadata.cohort_id} · Rubric: ${metadata.rubric_version} · No annotator selected`;
$("openWorkspace").onclick=openWorkspace;
$("labelForm").addEventListener("submit",event=>event.preventDefault());
$("labelForm").addEventListener("input",()=>{capture();persist();updateProgress();});
$("previous").onclick=()=>{capture();current--;render();persist();};$("next").onclick=()=>{capture();current++;render();persist();};
$("jump").onchange=()=>{capture();current=Number($("jump").value);render();persist();};
$("nextIncomplete").onclick=()=>{capture();for(let offset=1;offset<=sourceRows.length;offset++){const index=(current+offset)%sourceRows.length,row=sourceRows[index];if(errorsFor(labels[row.review_id],row.review_text).length){current=index;render();persist();return;}}message("All reviews are complete. Download your labels.");};
$("copySource").onclick=()=>{$("evidence_quote").value=sourceRows[current].review_text;capture();persist();updateProgress();};
$("noEntities").onclick=()=>{$("entities").value="[]";capture();persist();updateProgress();};
$("downloadJson").onclick=()=>download("json");$("downloadCsv").onclick=()=>download("csv");
$("checkAll").onclick=()=>{const data=makeExport();message(data.complete?"All reviews are structurally complete. Download the labels to private/human-labels/.":`${data.validation_errors.length} incomplete review(s). First: ${data.validation_errors[0].review_id}\n${data.validation_errors[0].errors.join("\n")}`,!data.complete);};
$("restore").onchange=async event=>{const file=event.target.files[0];if(!file)return;try{const data=JSON.parse(await file.text());restoreExport(data);message("JSON restored to this annotator workspace. Source and rubric identity matched.");}catch(error){message("Restore rejected; current answers were preserved. "+error.message,true);}event.target.value="";};
render();
</script></body></html>
"""
