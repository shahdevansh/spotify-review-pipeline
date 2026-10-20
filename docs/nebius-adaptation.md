# Nebius pilot adaptation

The account owner supplied an existing Nebius Token Factory key and requested
using its credits for the fast classifier and the reasoning roles. The
authenticated model-list request succeeded on October 19, 2026, and contained
28 model IDs. It did not contain TypeSafe Jev. Account billing was active.
No new credit purchase was made.

The selected configuration is [`config/nebius-pilot.json`](../config/nebius-pilot.json),
with prompt version `pilot-v5-nebius`. It uses
`nvidia/Nemotron-3_5-Lightning` with thinking disabled for first-pass enrichment.
The Nebius adapter translates the configuration's `enrich: none` into
`chat_template_kwargs: {"enable_thinking": false}`.
`openai/gpt-oss-120b` with `reasoning_effort: low` performs fallback
classification, independent verification and issue description.
`zai-org/GLM-5.3-Flash` with `reasoning_effort: low` performs memo generation
after a successful isolated probe using the saved 500-review evidence.

The first pass is an autoregressive LLM serving a System-1-style classification
role. It is not TypeSafe Jev and supplies no Jev-calibrated confidence
probabilities. GPT-OSS and GLM serve the System-2 roles. GPT-OSS is an open-weight
model served by Nebius, distinct from the OpenAI API's `gpt-6-luna`.
Cross-family verification can reveal disagreements, but agreement
between these models is not ground truth.

The original Jev and OpenAI adapters remain available. At setup time, Vercel's
free Gateway credits did not admit Jev, and the OpenAI inference check returned
an exhausted-credit error. Those access failures are retained separately from
model-quality results. A successful model-list request does not prove inference
or billing access.

## Historical two-review contract checks

Before screening and the Lightning selection, two original development reviews
were sent independently to Qwen and GPT-OSS.
These checks validated request compatibility, ID coverage, schema validity,
quote substring support and source-matched entities. They do not measure
classification accuracy and are excluded from the fixed cold/warm measurements.

| Model | Valid records | Prompt tokens | Completion tokens | Wall time | Economic usage cost |
|---|---:|---:|---:|---:|---:|
| Qwen 30B Instruct | 2 / 2 | 906 | 202 | 3.504 s | $0.0001512 |
| GPT-OSS 120B, low | 2 / 2 | 946 | 359 | 1.695 s | $0.0003573 |

The historical Qwen calculation uses $0.10 input and $0.30 output per million
tokens; Qwen remains screening evidence rather than the selected primary.
Raw request, response, predictions and summaries are retained in
`runs/nebius-contract-qwen/` and
`runs/nebius-contract-gptoss/`.

## Screening evidence and selection

The [v1 screening report](nebius-screening-v1.md) preserves a rejected Qwen
22-review response with a source-unsupported Arabic entity and an interrupted
retry whose usage was unavailable. It was not a completed 100-review comparison.
The resulting repair moved classification to compact label-only responses;
code now attaches the source quote and explicitly matched entities.

The [v2 screening report](nebius-screening-v2.md) compares all three models on
the same original 100-review course checkpoint:

| Model | Completed IDs | Attempted calls / failed attempts | Nominal API usage | Process wall time |
|---|---:|---:|---:|---:|
| Nemotron Lightning, thinking disabled | 100 / 100 | 4 / 0 | $0.00237228 | 25.517 s |
| Qwen 30B Instruct | 100 / 100 | 5 / 1 | $0.00419240 | 213.778 s |
| GPT-OSS 120B, low | 75 / 100 | 5 / 2 | $0.01175055 | 48.646 s |

Lightning was the least expensive and fastest completed candidate in this
screening, with no retry. That supports its **operational selection**, not
superior label quality. Qualitative inspection found substantive mistakes in
all three models. Lightning sometimes assigned severity 1 to complaints,
misread personal departure intent, or missed a complaint after initial praise.
Qwen and GPT-OSS also overstated impacts and missed intent. The
[inspection CSV](nebius-screening-v2-inspection.csv) preserves 20 seeded random
cases and 10 targeted cases; the
[metrics file](nebius-screening-v2-metrics.json) preserves comparison denominators.

Qwen recovered from an invalid ID set. GPT-OSS's final batch failed after output
truncation and then an invalid ID set. Its comparisons therefore exclude 25
uncompleted IDs and may be selection-biased. The processes overlapped, used the
verification-role schema, and excluded grouping and memo work. Their times are
not isolated sustained-throughput benchmarks, and their costs are not full
pipeline costs. V2 did not establish human-label accuracy or justify expansion.
Confidence is high in the saved operational measurements; model-quality
superiority remains unproved.

## Historical v3 and v4 memo experiments

The v3 cold run is preserved in
`runs/experiment-v3-cold-memo-failure/`.
It completed enrichment for 100 reviews and verification for the requested 10,
but the complete pipeline failed at memo generation. Both memo attempts consumed
the 6,000-token completion cap and ended with `finish_reason: length`; neither
produced an accepted memo. Their combined nominal usage was $0.00887250.
The saved failure is not a successful complete cold measurement or a completed
learning package.

Passing a schema through `response_format` alone did not ensure compliant
output in these observed requests. V4 therefore places the same JSON schema
both in the system prompt and in `response_format`, following Nebius's
[structured-output guidance](https://docs.tokenfactory.nebius.com/ai-models-inference/json).
The isolated inline-schema memo probe (`runs/nebius-inline-schema-memo-probe/run_summary.json`)
subsequently passed local validation on its first call: 7,816 input tokens,
933 completion tokens, 3.137 seconds total wall time and $0.00173220 nominal
usage. This establishes one successful repaired request, not a general quality
improvement or a guarantee of provider-enforced schema compliance. Local
validation remains the hard acceptance gate.

The v4 configuration was frozen with label identity
`spotify-db5cf770dc2cb6b5b75b04cf22ace00e3f6ecad6331c702adfc0efb8ab2d8a84`.
The v4 100-review cold run (`runs/experiment-v4-gptoss-memo-failure/100-cold/run_summary.json`)
completed, and the unchanged
warm replay (`runs/experiment-v4-gptoss-memo-failure/100-warm/run_summary.json`)
made zero new model calls. However, the later
500-review checkpoint (`runs/experiment-v4-gptoss-memo-failure/500/run_summary.json`)
again failed at GPT-OSS memo generation despite the inline schema. All 500
enrichment records and all 50 requested verifier records were completed; two
memo attempts each exhausted 6,000 completion tokens without an accepted
structured result. Those two attempts consumed $0.01004400 nominal usage.
The complete v4 history is preserved in
`runs/experiment-v4-gptoss-memo-failure/`.
The isolated v4 success did not establish reliable memo behavior.

## GLM memo selection and current v5 run

Repeated GPT-OSS memo failures motivated an isolated GLM-5.3-Flash low-effort
probe using the saved 500-review evidence. The
probe summary (`runs/nebius-glm-memo-probe/run_summary.json`) records one call
with no failed attempt: 9,768 input tokens, 1,743 completion tokens, 13.613
seconds total wall time and $0.00233670 nominal usage. Its
validated memo (`runs/nebius-glm-memo-probe/validated_memo.json`) passed local
JSON, schema and reference checks.

Qualitative inspection found an explicit distinction between model-assigned
severity and reviewer statements, plus comparisons between the saved priorities
and alternatives. This supported **operational selection for the memo role**.
It is not a human quality benchmark, proof of general superiority, or assurance
that every interpretation is correct. The catalog does not supply a GLM-specific
JSON-mode tag; this successful request does not establish a provider-enforced
schema guarantee. Local validators remain essential.

The current `pilot-v5-nebius` configuration is frozen with label identity
`spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb`.
Lightning enrichment and GPT-OSS fallback, verification and issue-description
settings are unchanged; only the memo model is GLM at low effort. The complete
bounded pilot sequence was started afresh with `data/pilot_v5_cache.sqlite3`.
This note records that start and the historical probes, not completion of the
v5 pilot or permission to expand beyond the 1,000-review learning gate.

## Current prompt and validation contract

`pilot-v5-nebius` identifies the current configuration. Its actual prompt
sources are the shared [`labels.md`](../prompts/labels.md) rubric and the
[`enrich`](../prompts/enrich.md), [`fallback`](../prompts/fallback.md),
[`verify`](../prompts/verify.md), [`group`](../prompts/group.md) and
[`memo`](../prompts/memo.md) role instructions. The shared rubric file retains
the heading `pilot-v2`; the run configuration and prompt-content fingerprint
identify the complete current version. Earlier screening outputs do not prove
that the current prompts improved accuracy.

The rubric incorporates the screening diagnoses: read the entire review before
applying intent precedence; distinguish a personal departure threat from advice
to other users; keep generic criticism at severity 2; require supported
functional restriction for severity 3 and a blocked core task for severity 4.
An explicit workaround is evidence of remaining use. A premium-plan mention
alone does not make a problem billing-related. These are prompt rules, not
guarantees that the model will follow them.

The classifier and blind verifier receive original review text without star
ratings or other metadata. Topic, intent, sentiment and severity are
**model-assigned labels**, not facts or severity scores supplied by reviewers.
Code attaches the original text as the evidence quote and extracts only literal
source-matched entities. It validates the response schema, exact requested ID
set, field types/ranges, source quote, entities and completed-record provenance.
Temporary request aliases map back to the exact original review IDs.
These checks establish structural/source integrity; they do not prove that a
label is semantically correct.

For enrichment, deterministic checks flag complaint/severity-1 contradictions,
other intent/severity inconsistencies, strongly positive complaint sentiment
and possible injected instructions, alongside the model's `needs_review` flag.
The stored uncertainty score is unavailable, not a fabricated probability.
Checks flag cases for bounded fallback; they do not silently rewrite the
model's judgments. Fallback remains capped at 5% of distinct texts, so flagged
cases beyond that cap remain visible.

Issue membership and numerical claims are computed in code. The issue-description
role may describe the supplied evidence but cannot change membership or totals.
The memo prompt keeps identifiers in dedicated arrays and prohibits numerical
claims in prose; code checks identifiers and renders saved values with citations.
The prompts distinguish expressed cancellation intent from observed churn,
model labels from reviewer statements, and proposed benefits from measured
causal effects. A broad topic's count does not establish a specific subtopic's
prevalence.

## Pricing and accounting

The [official public catalog](https://tokenfactory.nebius.com/api/public/models_info),
checked October 19, 2026, lists these exact selected model IDs and rates:

| Exact Nebius model ID | Input USD / million tokens | Output USD / million tokens |
|---|---:|---:|
| `nvidia/Nemotron-3_5-Lightning` | $0.06 | $0.24 |
| `openai/gpt-oss-120b` | $0.15 | $0.60 |
| `zai-org/GLM-5.3-Flash` | $0.15 | $0.50 |

The same rates are recorded in [`rates.csv`](../config/rates.csv) and the
selected configuration. These are published catalog rates, with no separately
verified cache discount. Cost uses reported total input and completion tokens,
including cached input at the standard input rate. This is a
conservative economic usage calculation, not a reconciled credit debit or
invoice. Reasoning tokens, where present, are included in completion tokens and
must not be billed a second time. Missing token-detail fields stay unknown.
Existing credits do not make model consumption zero-cost.

The shared ledger preserves unresolved reservations for interrupted or failed
attempts whose billing was not independently reconciled. Catalog prices,
nominal measured API usage, reserved unknown charges, credit debits and new cash
purchases remain distinct.

## Experiment and decision rules

1. Keep the existing 1,000-review learning sample and the untouched course
   checkpoints. Human golden labels remain outside prompt development.
2. Retain v1/v2 screening as separate development evidence. Independent
   verification receives source reviews without enrichment predictions.
3. Freeze the selected configuration and run the full required 100 cold/warm,
   500 and 1,000 sequence. Every provider, exact model, request setting, prompt,
   schema and routing choice contributes to cache identity. The GLM memo probe
   passed before the v5 sequence began with a fresh cache; do not relabel
   historical v3/v4 runs as the current benchmark.
4. Use at most 25 reviews per enrichment request and at most 10 for fallback
   and verification, with a 6,000-token completion cap including reasoning.
   Preserve failures and bounded retries rather than relaxing the ID contract.
5. Use explicit ambiguity and consistency signals for capped fallback routing.
   Do not relabel self-reported confidence as a calibrated probability.
6. Inspect 30 seeded random development examples and up to 30 disagreements or
   failures. Report model agreement separately from human-label accuracy.
7. Stop after the learning package. The 10,000 and 210,000 expansions require
   measured quality, cost, sustained throughput and database-size gates.

The pilot retains its $1.50 admission cap; the project retains the $18 operating
ceiling and $2 reserve. No dedicated GPU endpoint or fine-tuning job is required.

## Additional opportunities

Further comparison should follow inspection of the bounded learning package,
using matched inputs and saved source-only verification. Model size,
agreement or promotional credits alone do not establish better quality.

Nebius's `Qwen/Qwen3-Embedding-8B` could support a later, bounded subtopic
exploration within broad topics and a check of evidence diversity. **This
embedding experiment has not run.** The catalog input price is $0.01 per million
tokens; actual cost would depend on measured usage. Keep an initial sample's
vectors local: 159,657 full 4,096-dimensional float32 vectors alone would occupy
2,615,820,288 bytes, before database overhead, exceeding the provisioned 1 GiB
database allowance. Embedding similarity must never authorize label reuse for
nonidentical texts. Any claimed subtopic prevalence requires explicit saved
review membership and validation across the relevant cohort. The first milestone
continues to use the auditable topic-level baseline.

The hosted one-token decision approach described in Nebius's Jev-style cookbook
is deferred. Repeated questions and option rotations may multiply input costs
and requests. Its output probabilities would require development-set calibration
and should not be presented as Jev's calibration.

## Sources

- [Course calculator contract](../vendor/course/COST_CALCULATOR.md), which permits alternative classifiers and models.
- [Selected configuration](../config/nebius-pilot.json) and [candidate evidence registry](../config/nebius_candidates.json).
- [Nebius public model catalog and exact rates](https://tokenfactory.nebius.com/api/public/models_info).
- [NVIDIA Nemotron Lightning publisher card and thinking control](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16).
- [Official GPT-OSS model documentation](https://developers.openai.com/api/docs/models/gpt-oss-120b).
- [GLM-5.3-Flash publisher card and supported reasoning levels](https://huggingface.co/zai-org/GLM-5.3-Flash).
- [Historical Qwen model card](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507).
- [Nebius structured output API](https://docs.tokenfactory.nebius.com/ai-models-inference/json).
- [Nebius Chat Completions contract and token usage](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion).
- [Qwen embedding dimensions](https://huggingface.co/Qwen/Qwen3-Embedding-8B).
- [Nebius Jev-style decision example](https://dev.nebius.com/cookbook/jev-style-decision-model-glm).
