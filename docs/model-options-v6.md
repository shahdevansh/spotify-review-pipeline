# Model options and a $50 full-dataset design

**Research snapshot: October 20, 2026. Catalog research was read-only; the measured appendix analyzes completed paid experiment runs.**

**Latest cost-only update, 08:20 UTC:** the sealed prediction receipt gives GLM a higher all-attempt cost, including one failed attempt. Applying that rate to the full source gives **$40.65**, or **$44.66 with an additional 10% variable-cost allowance**, leaving only **$3.34 below the $48 operating ceiling**. Private predictions and human labels remain unopened. **Full-source free hosting is also unproven:** the measured application footprint projects to approximately **985 MB**, above the conservative 700 MB gate. See the [sealed-run sensitivity and storage gate](#sealed-prediction-receipt-cost-only-sensitivity).

**Earlier matched update, 08:07 UTC:** the matched experiment supports a batch-ten full-source budget scenario of **$34.02 for GLM-Flash or $36.72 for Qwen235**, including then-current commitments, assumed 5% fallback, 1% verification, 10% additional variable retry load and a $0.25 final-stage allowance. GPT-OSS reaches **$53.26** under the same calculation. The separate GLM concurrency test observed **1.73×** first-pass speedup with four workers. Those dated results remain preserved; the later receipt is an additional operational sensitivity, not a replacement quality evaluation. The [measured appendix](#measured-appendix-completed-five-arm-experiment) and [machine-readable calculations](../evals/experiment-v6/cost-projections.json) retain both.

The $50 budget makes a full-source run plausible, but it does not make every larger model affordable. The selected comparison has **five arms: Lightning with the v5 prompt, Lightning with the v6 prompt, GPT-OSS 120B at low reasoning, GLM-5.3-Flash at low reasoning, and Qwen3-235B-A22B-Instruct-2507 without thinking**. The runner's actual allocation is **$3 total across the matched 200-review experiment, synthetic checks and batch stress checks**, with a $0.50 cap per condition. DeepSeek-V4-Flash-0731 remains an unrun optional fourth model family. Select the production route using measured quality, total tokens and runtime.

Qwen235 is a useful candidate because the publisher explicitly documents a nonthinking checkpoint, the Nebius catalog marks it for JSON mode, and its output rate is $0.60 per million tokens. This is a reason to test it, **not evidence that it labels Spotify reviews better**. Existing v5 concerns remain unresolved until reviewed against source text; model agreement is not human accuracy.

Confidence is **high** in the saved public prices and source counts, **moderate** in the feasibility of the proposed bounded experiment, and **low** in unmeasured candidate quality and full-run duration. All costs are nominal usage at published rates, not reconciled invoices or measured cash debits.

## Evidence, budget and source scope

The raw official [Nebius public catalog](https://tokenfactory.nebius.com/api/public/models_info) is saved in [catalog.json](../evals/experiment-v6/catalog.json). It was fetched without authentication at `2026-10-20T07:31:05.869868+00:00`, contains 28 model entries, and has SHA-256 `8527a31e3d6b1bbd6b8f241c95cd0f96d841b26ecdaef9f9fec2c5604c52cb8e`. Catalog status and tags are provider metadata; they do not prove that a particular account can complete inference or that every structured response will be valid.

The preceding saved snapshot, `validation/nebius_catalog_snapshot.json`, was retrieved at `2026-10-20T05:45:05.964332+00:00` and tracked four models. **Lightning, GPT-OSS 120B, Qwen30B and GLM-5.3-Flash have unchanged rates between these two snapshots.** That comparison does not establish that every catalog entry is unchanged.

The read-only ledger snapshot at `2026-10-20T07:32:34.036248+00:00` contains $0.214957094 settled nominal usage and $0.016446200 unresolved holds, with no in-flight reservation: **$0.231403294 committed**. These holds remain charged against planning headroom. Subsequent activity changes the ledger; this document is an as-of calculation.

The frozen experiment manifest uses **$48 operating allowance plus $2 reserve** within the new $50 total. With the full $3 experiment allocation and the above pre-experiment commitments, that leaves **$44.768596706 for production while retaining the $2 reserve**. The earlier planning suggestion of $45 plus $5 was not adopted. The older [scaling economics](scaling-economics.md) report's $18 allowance describes the previous budget.

| Scope | Nonempty original review IDs | Distinct exact nonempty texts | Primary batches at maximum 25 | Primary batches at maximum 10 |
|---|---:|---:|---:|---:|
| Selected cohort | 210,000 | 159,657 | 6,387 | 15,966 |
| Full source | 660,609 | 484,189 | 19,368 | 48,419 |

A fresh read of `data/source/spotify_reviews_18months.csv` confirms 660,622 physical rows, including 13 empty-text rows, which are quarantined rather than sent for enrichment. The source SHA-256 is `1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6`. Exact duplicate text can share one text-derived classification while every original ID and its multiplicity remain in analysis. Verification is sampled over original IDs. The batch counts reproduce the existing byte/output limits in source order; they exclude retries. A different prompt, output reservation or batching policy can change them.

## Candidate contracts and prices

Prices below are **USD per million tokens**, copied from exact flavor IDs in the saved public catalog. No alias, “Fast” tier or unverified cached-input discount is substituted. Price all reported input at the standard rate. Output usage includes reasoning when the provider reports it in completion tokens; do not add the reasoning count again.

| Exact Nebius model ID | Input | Output | Catalog JSON mode tag | Proposed trial setting |
|---|---:|---:|---|---|
| `openai/gpt-oss-120b` | $0.15 | $0.60 | Yes | Low reasoning; existing baseline |
| `zai-org/GLM-5.3-Flash` | $0.15 | $0.50 | No | Low reasoning; classification compatibility first |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` | $0.20 | $0.60 | Yes | Nonthinking checkpoint; omit reasoning controls |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | $0.14 | $0.28 | Yes | Optional fourth; low only after hosted compatibility probe |
| `nvidia/Nemotron-3_5-Lightning` | $0.06 | $0.24 | No | Historical v5 primary reference |
| `Qwen/Qwen3-30B-A3B-Instruct-2507` | $0.10 | $0.30 | Yes | Historical smaller Qwen reference |
| `Qwen/Qwen3.8-27B` | $0.45 | $3.00 | No | Optional tiny challenger; expensive for blanket classification |
| `deepseek-ai/DeepSeek-V4.1-Flash` | $0.30 | $1.20 | No | More expensive alternative to the 0731 checkpoint |
| `zai-org/GLM-5.3` | $1.40 | $4.40 | No | Too expensive for an assumed full-source first pass |
| `Qwen/Qwen3.5-397B-A17B` | $0.60 | $3.60 | No | Reserve for small adjudication tests if needed |

All rows above were `active` in the fresh public catalog. Active status is not an uptime guarantee. `moonshotai/Kimi-K3` was marked `error`, so it is excluded. The absence of a JSON tag means that advertised capability was not found in this catalog; it does not prove the model cannot produce JSON.

**Qwen235.** The [publisher model card](https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507) explicitly describes a nonthinking model that does not generate `<think>` blocks. `enable_thinking=False` is unnecessary; omit `reasoning_effort` and thinking flags. The catalog's JSON tag supports trying structured output, while local validation remains the acceptance gate. General benchmark claims do not establish performance on this assignment.

**GPT-OSS 120B.** The [official model documentation](https://developers.openai.com/api/docs/models/gpt-oss-120b) and [Harmony guide](https://developers.openai.com/cookbook/articles/openai-harmony) document low, medium and high reasoning, with no documented off mode. The existing Nebius adapter's low setting completed small structured review batches in v5. Its larger memo attempts also produced malformed/repeating outputs. Treat that history as evidence about these tasks and request sizes, not proof that every low-reasoning output is reliable.

**GLM-5.3-Flash.** The [publisher card](https://huggingface.co/zai-org/GLM-5.3-Flash) documents **low, high and max**. An absent or unsupported effort, including `none` or `medium`, falls back to **max**. Use the explicit low setting; `clear_thinking` clears retained history rather than disabling generation. The existing low-reasoning memo probe succeeded, but classification needs its own trial. The [Nebius GLM decision-model cookbook](https://dev.nebius.com/cookbook/jev-style-decision-model-glm) also cautions that Chat output may include reasoning even when thinking is disabled.

**DeepSeek-V4-Flash-0731.** The [exact checkpoint card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731) and its [reference encoder](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/main/encoding/README.md) distinguish `thinking_mode="thinking"` and `"chat"`, with low/high/max effort. The publisher-linked [vLLM recipe](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash) supplies thinking controls through `chat_template_kwargs`, including `thinking: true` and `reasoning_effort: "low"`. **Exact Nebius forwarding is unverified.** A small hosted probe must establish the request shape before promotion. Do not transfer the current DeepSeek-hosted API alias's `none` behavior to this Nebius checkpoint: the aliases and templates differ.

**Newer Qwen3.8.** The [publisher card](https://huggingface.co/Qwen/Qwen3.8-27B) and [chat template](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/chat_template.jinja) document low/medium/xhigh, with thinking on and xhigh as the default. Nonthinking uses `chat_template_kwargs.enable_thinking: false`; omit effort in that case. Nebius forwarding is untested. Its $3.00 output rate is five times Qwen235's; at the illustrative 100 input / 50 total output tokens per distinct text, full-source primary classification alone would cost **$94.42**. “Newer” is not a sufficient reason to use it everywhere.

**Structured-output contract.** [Nebius's JSON guide](https://docs.tokenfactory.nebius.com/ai-models-inference/json) recommends selecting a JSON-tagged model, supplying the schema in the prompt as well as `response_format`, and testing the selected model. The [Chat API reference](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion) exposes structured response fields and `max_completion_tokens`; the latter bounds visible and reasoning output together. The prior GPT-OSS memo failures show why `response_format` must not be described as a provider-enforced guarantee here. Local schema, exact-ID, range and source checks remain mandatory, with failures explicitly logged.

## The bounded matched experiment

The first decision is whether a candidate improves the actual labeling failure modes at an affordable token cost. The existing [learning report](learning-report.md) supplies those concerns. The selected five arms use the same 200 source reviews. The two Lightning arms compare the earlier prompt with the revision; the three other models provide family comparisons under the revised contract. These are five conditions across four families, not five independent model families.

The runner allocation covers matched classification, synthetic boundary cases and batch stress. Root owns the paid execution. Its saved evidence is under `evals/experiment-v6/matched-200/runs/{arm}/{matched,synthetic,batch...}`. Completed measurements appear in the appendix below; catalog research did not execute them. The actual configuration and call logs, rather than a prose proposal, govern the request caps, batches and settings used.

For interpretation, keep source text and IDs matched, with ratings and other models' predictions hidden. Compare valid coverage, per-field disagreements, known ambiguity cases, false certainty, token usage and elapsed time. Review source evidence instead of declaring the majority vote correct. Any review used to revise prompts is development evidence; do not call an evaluation held out if its labels informed development.

The **$3 shared experiment allocation includes all attempts and retries**, and each condition is capped at $0.50. The following is only a transparent admission illustration, not the measured runner budget: assume a ten-review request is bounded by **18,000 input and 6,000 total output tokens**. Before dispatch, actual prompt size and output reservations determine the charge reservation.

| Candidate condition | Maximum nominal charge per illustrated request | Twenty requests for matched 200 |
|---|---:|---:|
| Lightning v5 | $0.00252 | $0.0504 |
| Lightning v6 | $0.00252 | $0.0504 |
| GPT-OSS low | $0.0063 | $0.1260 |
| GLM-Flash low | $0.0057 | $0.1140 |
| Qwen235 nonthinking | $0.0072 | $0.1440 |
| **Five matched-200 conditions** | | **$0.4848** |

That illustration excludes synthetic checks, batch stress and additional retries. It is not permission to consume unused budget. Budget admission must stop a condition at its cap and stop the whole experiment at $3. A later 1,000-review confirmation would require its own measured projection and remaining-budget check rather than automatic expansion.

Record prompt/model identity, every paid attempt, input/output/reasoning usage, accepted IDs, actual batch sizes, validation failures and latency. Human inspection labels and model-verifier judgments must be separate. Choose production batch size from measured completeness and valid throughput: earlier large-batch GPT-OSS failures make extrapolation from ten to 25 reviews unsafe without testing. A candidate advances only if the observed labeling behavior justifies it; cheap tokens alone do not clear the quality gate.

## Pretrial full-run cost sensitivities

These are **explicit token scenarios, not measured v6 predictions**. Input totals include the amortized prompt and inline schema. Output totals include reasoning. Output caps are ceilings per request, not expected average usage.

The final v5 pilot provides two reference points: Lightning primary averaged **93.75 input / 44.70 output tokens per distinct text** at batches up to 25; GPT-OSS verification averaged **175.50 input / 94.88 output per evaluation** at batches up to ten. Those are different roles and prompts. They justify exploring the following ranges; they do not establish any candidate's future consumption.

| Primary scenario | Assumed input / total output tokens per distinct text | 210k cohort primary only | Full-source primary only |
|---|---:|---:|---:|
| Qwen235 compact, larger batches | 100 / 50 | $7.98 | $24.21 |
| Qwen235 compact, higher prompt overhead | 200 / 50 | $11.18 | $33.89 |
| GLM-Flash low, reasoning allowance | 200 / 100 | $12.77 | $38.74 |
| GPT-OSS low, reasoning allowance | 200 / 100 | $14.37 | $43.58 |
| DeepSeek0731 low, if compatible | 200 / 100 | $8.94 | $27.11 |

For a common downstream reference, retain the v5 measured fallback unit charge of `$0.0042369 / 46`, verifier unit charge of `$0.0882507 / 1060`, and one final bounded group/memo pair costing $0.0039936. Apply fallback to `floor(5% × distinct texts)` and independent verification to `ceil(1% × original IDs)`. That is 7,982 fallback / 2,100 verifier evaluations for the cohort, and 24,209 / 6,607 for the full source. These are saturated routing assumptions; a changed rubric or prompt may change unit consumption.

The resulting common downstream reference is **$0.91402415** for the cohort and **$2.78386866** for the full source, including the final pair. Then apply an **assumed 10% additional load to variable primary, fallback and verifier usage**, include the final pair once, and add the full $3 experiment allocation and the $0.231403294 prior-commitment snapshot:

```text
primary = unique_texts × (input_tokens × input_rate + output_tokens × output_rate) / 1,000,000
variable_downstream = floor(0.05 × unique_texts) × (0.0042369 / 46)
                    + ceil(0.01 × original_IDs) × (0.0882507 / 1060)
all_in = (primary + variable_downstream) × 1.10
       + 0.0039936 + 3.00 + 0.231403294
```

| Primary scenario | Cohort all-in | Full-source all-in | Full-source interpretation against $50 |
|---|---:|---:|---|
| Qwen235, 100 / 50 | **$13.02** | **$32.92** | Fits with $5 reserve |
| Qwen235, 200 / 50 | **$16.53** | **$43.58** | Fits with $5 reserve, limited extra headroom |
| GLM-Flash low, 200 / 100 | **$18.29** | **$48.90** | Fits nominal total, consumes most reserve |
| GPT-OSS low, 200 / 100 | **$20.04** | **$54.23** | Does not fit |
| DeepSeek0731 low, 200 / 100 | **$14.07** | **$36.12** | Fits if hosted compatibility and quality pass |

These totals assume one selected production model. The candidate rows are alternatives, not costs to add together. They reserve a complete fresh run, without subtracting compatible pilot cache hits. Ten percent retry load is a stress assumption, not a measured candidate failure rate or a maximum bill. If GPT-OSS is both primary and fallback, its fallback is a second pass rather than a cross-model check.

Long reasoning can erase the margin. At **250 input / 200 total output tokens** per distinct text, full-source primary alone becomes $82.31 for Qwen235, $66.58 for GLM-Flash, $76.26 for GPT-OSS and $44.06 for DeepSeek0731, before downstream roles or trials. Budget admission and measured token usage must therefore govern expansion. Free hosting is assumed; this report does not authorize paid hosting, prepaid purchases or unmeasured deployment charges.

## Where the extra budget can help

A broader verification/escalation route may be more useful than choosing the newest model for every review. Under the **unmeasured Qwen235 100/50 primary assumption**, replacing the common 5% GPT fallback with GLM-Flash escalation at 200/100 tokens and raising GPT verification to 5% of original IDs gives the following. Verification retains the empirical v5 unit charge `$0.0882507 / 1060`, rather than assuming 200/100 tokens for that role.

| Full-source alternative | GLM escalation texts | GPT verifier original IDs | All-in cost with the same 10% variable load, $3 experiment and prior snapshot |
|---|---:|---:|---:|
| Qwen primary + 10% GLM escalation + 5% verification | 48,418 | 33,031 | **$37.15** |
| Qwen primary + 20% GLM escalation + 5% verification | 96,837 | 33,031 | **$41.41** |

These alternatives **replace** the previous fallback/verification scenario; they are not additive. There is no assumed accuracy improvement. Routing should use independently reviewed ambiguity patterns and task rules, rather than trusting model confidence alone: v5's flags missed some inspected concerns. Preserve stratified random verification so that unflagged failures can be found. Multiple LLMs can share systematic errors.

Embeddings offer a separate, bounded opportunity after the classification rubric is stable. The current catalog lists `Qwen/Qwen3-Embedding-8B` at **$0.01 per million input tokens**. A targeted set of 10,000 long or disputed reviews averaging an assumed 100 tokens would cost $0.01 in embedding usage; full distinct-text coverage at that assumption would cost about $0.48. Tokenization, limits and returned dimensions still require verification. Cluster representative review text locally to discover candidate subtopics, then inspect them before revising the taxonomy. Embedding clusters do not establish subtopic prevalence, sentiment accuracy or causal explanations. No embedding request or finer-prevalence analysis was run for this report.

## Runtime design and what the trial must measure

The v5 matched 100-review test found 1.509× primary-span speedup with four workers rather than one, and 1.268× whole-run speedup. It used Lightning, a small sample and one observation per condition. **Do not transfer that throughput to Qwen, GLM or DeepSeek.** The historical evidence path is `runs/concurrency-100-w4/comparison.json`; run folders are excluded from Git and are available in the local workspace or the pilot evidence release rather than through source-file hyperlinks.

Run candidate comparisons sequentially at one worker so the first quality/token/latency comparison is interpretable. After choosing a candidate and batch size, run a matched cold-cache concurrency check before full expansion. Retain bounded queues, durable checkpoints, exact-text deduplication, retry limits and cancellation/recovery accounting.

The current implementation's local limits of two requests/second and 10,000 estimated admission tokens/second are client pacing controls, **not verified account quotas**. Only primary classification is concurrent; fallback and verification currently wait serially. Use:

```text
primary_seconds ≳ max(
    primary_requests × measured_mean_service_seconds / workers,
    estimated_admission_tokens / local_token_rate,
    primary_requests / local_request_rate
)
```

Add serial downstream service, retry waits, checkpoint/storage work and final analysis separately. The inequality is an idealized scheduling lower bound; sustained throttling and long-tail latency add time.

| Scope / batching | Primary requests | Four workers at assumed 5 s service/request | Four workers at assumed 10 s service/request |
|---|---:|---:|---:|
| 210k cohort, batches up to 25 | 6,387 | 2.22 h | 4.44 h |
| 210k cohort, batches up to 10 | 15,966 | 5.54 h | 11.09 h |
| Full source, batches up to 25 | 19,368 | 6.73 h | 13.45 h |
| Full source, batches up to 10 | 48,419 | 16.81 h | 33.62 h |

These are service-only illustrations using assumed 5/10-second latency, **not forecasts**. They exclude token pacing and downstream roles. In particular, increasing review batching can reduce fixed prompt overhead and request count, but only if completeness and quality hold. Raising concurrency cannot overcome a binding token limit.

The decision after the matched trial should report the observed quality tradeoffs, accepted coverage, tokens per distinct text, cost per accepted classification including retries, sustained valid reviews/second and a fresh full-source projection with the current ledger. Economic feasibility is separate from the quality gate, and a bounded successful trial is separate from completing or publishing full-dataset results.

## Measured appendix: completed five-arm experiment

**Evidence and budget snapshot: `2026-10-20T08:07:31.120850+00:00`.** All five matched arms completed 200 original review IDs using **195 paid distinct-text evaluations** each. Every arm sent nineteen batches of ten and one batch of five, then restored five exact-text aliases. The correct cost denominator is **195, not 200**. All 100 matched requests succeeded, with no retry and no cache hit. Fallback was disabled in these comparisons. Each arm used one worker; the additional GLM four-worker condition is reported separately.

The frozen selection was 200 seeded original IDs from the previously exposed 1,000-review development cohort. The manifest excluded 21 eligible IDs or exact-text matches related to the golden set and states that golden answers were not read. This is development evidence, not an untouched human accuracy benchmark or a representative full-corpus cost survey. Configuration identities, exact source hashes and every evidence-file hash are in [cost-projections.json](../evals/experiment-v6/cost-projections.json). The original matched source/configuration contract is in [manifest.json](../evals/experiment-v6/matched-200/manifest.json).

| Arm | Input tokens | Total output tokens | Separate reported reasoning | Nominal usage | Wall seconds | Distinct texts/second |
|---|---:|---:|---:|---:|---:|---:|
| Lightning v5 | 34,488 | 8,691 | 0 | $0.00415512 | 45.915 | 4.247 |
| Lightning v6 | 44,708 | 8,705 | 0 | $0.00477168 | 39.600 | 4.924 |
| GPT-OSS v6, low | 44,319 | 19,198 | Not reported | $0.01816665 | 56.824 | 3.432 |
| GLM-Flash v6, low | 43,104 | 9,315 | 3,524 | $0.01112310 | 71.434 | 2.730 |
| Qwen235 v6, nonthinking | 43,145 | 5,801 | Not reported | $0.01210960 | 83.134 | 2.346 |

GLM's 3,524 reasoning tokens are already included in its 9,315 output tokens. GPT-OSS and Qwen omit the separate reasoning breakdown on all 20 calls, so that field is **unknown**, not zero. Qwen is nevertheless the publisher's documented nonthinking checkpoint. All cost calculations use the complete reported output count. These successful local schema checks establish completion, not correct labels.

| Arm | Observed input / total output per paid text | Nominal USD per 1,000 distinct-text classifications |
|---|---:|---:|
| Lightning v5 | 176.86 / 44.57 | $0.02131 |
| Lightning v6 | 229.27 / 44.64 | $0.02447 |
| GPT-OSS v6 | 227.28 / 98.45 | $0.09316 |
| GLM-Flash v6 | 221.05 / 47.77 | $0.05704 |
| Qwen235 v6 | 221.26 / 29.75 | $0.06210 |

The revised Lightning prompt increased measured input consumption. Its faster observed wall time in this single sequential comparison does not prove that a longer prompt improves speed. Qwen emitted fewer output tokens than GLM, but GLM's lower input/output rates made its total nominal charge lower.

### Actual experiment consumption and budget accounting

The matched arms cost **$0.05032615** when repriced from provider token counters. Their ledger settlements total $0.050326164; the $0.000000014 difference is upward fixed-unit rounding. All matched, synthetic, stress and concurrency conditions together made **235 calls**, costing **$0.10159967** nominally and **$0.101599706** in ledger settlements. Only the original one-worker matched conditions calibrate production unit consumption. Synthetic, batch-size, repeated, shuffled and concurrency cases remain real project spend.

At the snapshot, total project settled nominal usage is **$0.316556800**, historical unresolved charge holds are **$0.016446200**, and in-flight reservations are **$0**. Thus **$0.333003000 is committed**, leaving **$47.666997000 under the $48 operating ceiling**. The separate $2 reserve remains outside that ceiling. None of these values establish invoiced cash purchases or actual credit debits.

The experiment's $3 allocation was not spent in full. The main tables below include the actual $0.101599706 trial settlement once, through the current project commitment. A separate sensitivity reserves the whole $3 allocation by replacing actual trial spending with $3; it does not add both.

### Production cost from the measured batch-ten units

For each scope, multiply observed primary cost per accepted text by 159,657 or 484,189 distinct texts. Retain the earlier measured v5 GPT-OSS proxies for the helper roles: `$0.0042369 / 46` per fallback evaluation and `$0.0882507 / 1060` per verifier evaluation. Those helper roles were **not measured under the revised v6 prompts**, so their transfer is an assumption. The routing scenario saturates 5% of distinct texts for fallback and samples 1% of original IDs for verification.

Use **one $0.25 planning allowance for final bounded grouping/memo work and possible retries**. This is an explicit allowance, not measured spending. It replaces the old $0.0039936 final pair in these calculations and is never multiplied by review count. The base estimate does not assume retry; the practical budget scenario adds 10% to variable primary/fallback/verifier usage. Zero failures were observed in the matched sample; 10% is a sensitivity assumption rather than an observed rate or maximum bill.

```text
V = distinct_texts × observed_primary_cost / 195
  + floor(.05 × distinct_texts) × (.0042369 / 46)
  + ceil(.01 × original_IDs) × (.0882507 / 1060)

project nominal mean = .316556800 + V + .25
project budget mean including holds = .333003000 + V + .25
project budget with retry allowance = .333003000 + 1.10 × V + .25
```

All scenarios reserve a fresh classification of the full chosen scope. No compatible-cache saving is deducted. Batch-ten unit estimates include the partial last calibration batch; no reduction to larger production batches is assumed.

| Arm | 210k primary only | 210k project budget, including holds and 10% retry | Full-source primary only | Full-source project nominal mean | Full-source budget including holds and 10% retry |
|---|---:|---:|---:|---:|---:|
| Lightning v5 | $3.40 | $5.33 | $10.32 | $13.66 | **$14.99** |
| Lightning v6 | $3.91 | $5.88 | $11.85 | $15.19 | **$16.67** |
| GPT-OSS v6 | $14.87 | $17.95 | $45.11 | $48.45 | **$53.26** |
| GLM-Flash v6 | $9.11 | $11.60 | $27.62 | $30.97 | **$34.02** |
| Qwen235 v6 | $9.91 | $12.49 | $30.07 | $33.41 | **$36.72** |

Full-source GLM and Qwen leave **$13.98 and $11.28** respectively below the $48 operating ceiling in the mean-plus-retry scenario. GPT-OSS exceeds $48 even in the mean budget including holds ($48.47), and reaches $53.26 with retries. If GPT-OSS is selected as primary, its configured GPT-OSS fallback is another pass through the same family, not an independent-family check.

| Full-source arm | Mean units + 10% retry, actual commitments | Empirical high units + 10% retry | Double primary output + 10% retry | Mean + retry, reserving entire $3 trial allocation |
|---|---:|---:|---:|---:|
| Lightning v5 | $14.99 | $17.49 | $20.69 | $17.89 |
| Lightning v6 | $16.67 | $19.20 | $22.38 | $19.57 |
| GPT-OSS v6 | $53.26 | $59.39 | $84.72 | $56.16 |
| GLM-Flash v6 | $34.02 | $42.09 | $46.74 | $36.92 |
| Qwen235 v6 | $36.72 | $40.72 | $46.22 | $39.61 |

The empirical-high scenario uses the nearest-rank P95 cost per accepted text across the 20 primary batches, plus the earlier v5 high-unit helper proxies, then adds the same 10% variable allowance. It is not a statistical confidence interval. The double-output scenario holds observed input constant and doubles total primary output, including reasoning where present; helper means remain unchanged. Each sensitivity is a separate alternative, not an additive charge. Both stronger candidates approach the operating ceiling in the doubled-output case, so measured consumption and admission caps still govern expansion.

### Runtime from the observed batch-ten configuration

The five-arm matched stage measured one worker. Direct linear scaling of its wall time gives primary-only full-source illustrations of 31.67 hours for Lightning v5, 27.31 for Lightning v6, 39.19 for GPT-OSS, 49.27 for GLM and 57.34 for Qwen. These are small-sample extrapolations, not observed full runs.

The additional GLM concurrency condition used the **same input hash and label configuration**, the same 195 distinct texts / 200 original IDs, and the same 20 batches. Both settings completed without failures. Fallback and verification were disabled in this experiment and remain serial in the production design.

| GLM first-pass measurement | One worker | Four workers |
|---|---:|---:|
| Wall time | 71.434 s | 41.376 s |
| Distinct texts/second | 2.730 | 4.713 |
| Mean API service time/request | 3.540 s | 4.451 s |
| Input / total output tokens | 43,104 / 9,315 | 43,104 / 9,653 |
| Nominal usage | $0.01112310 | $0.01129210 |
| Failed requests | 0 | 0 |

The observed first-pass speedup is **1.726×**, not fourfold. Mean API service time increased and the generated output varied. There was one observation per setting. Shared client limits remained two requests/second and 10,000 estimated admission tokens/second. This is evidence of a small-panel concurrency benefit, not a measured end-to-end deadline.

The v6 requests reserve roughly **2,060 estimated admission tokens per distinct text**, although billed input/output is much smaller. At the unchanged local 10,000 estimated-token/second limit, the sustained pacing term alone implies roughly **27.7 hours** for 484,189 texts. Four workers cannot bypass that client limit. A scheduling calculation takes the maximum of measured service divided by four, estimated-token pacing and request pacing, and for GLM also retains the observed four-worker span per text as a lower bound:

| Arm | 210k scope: four-worker scheduling calculation including serial helper proxies | Full source: same calculation | Full source: P95 timing/pacing terms plus 10% retry |
|---|---:|---:|---:|
| Lightning v5 | 8.81 h | 26.73 h | 32.23 h |
| Lightning v6 | 10.04 h | 30.47 h | 36.24 h |
| GPT-OSS v6 | 10.03 h | 30.42 h | 36.19 h |
| GLM-Flash v6 | 10.30 h | 31.25 h | 36.19 h |
| Qwen235 v6 | 10.02 h | 30.41 h | 36.18 h |

**These full-scope figures are planning calculations, not observed runs.** GLM incorporates its new small-panel four-worker observation; the other models still have no matched v6 concurrency observation. The figures use current pacing and the old v5 serial fallback/verifier times, with historical fixed analysis-time proxies of 16.01 seconds base and 40.77 seconds in the stress case. The similar v6 totals largely reflect pacing limits, not identical inference speed. The initial token bucket can let a small run briefly exceed sustained throughput; this explains why a linear one-worker Lightning illustration can be slightly below the steady pacing calculation.

Full ingestion, checkpoint/storage scaling, database import/indexing, deployment, human inspection and sustained provider disruption remain outside those times. **The stronger candidates fit the monetary budget under the modeled routes; end-to-end deadline feasibility is not proven.** Any batching or pacing revision needs its own measurement before a shorter completion-time claim.

### Separate batch-stress observations

The deliberate 25-text stress set contains “Love it” plus 24 seeded reviews. It is not representative enough to replace matched-200 cost calibration. All three tested models completed all 25 texts without failed requests at each batch setting:

| Model | Maximum reviews/request | Requests | Input / total output tokens | Nominal usage | Wall seconds |
|---|---:|---:|---:|---:|---:|
| Lightning v6 | 1 | 25 | 48,717 / 1,264 | $0.00322638 | 45.927 |
| Lightning v6 | 10 | 3 | 6,657 / 1,136 | $0.00067206 | 6.945 |
| Lightning v6 | 25 | 1 | 2,861 / 1,142 | $0.00044574 | 4.863 |
| Qwen235 v6 | 1 | 25 | 47,232 / 871 | $0.00996900 | 50.275 |
| Qwen235 v6 | 10 | 3 | 6,426 / 748 | $0.00173400 | 10.448 |
| Qwen235 v6 | 25 | 1 | 2,744 / 754 | $0.00100120 | 7.935 |
| GLM-Flash v6 | 1 | 25 | 47,229 / 1,660 | $0.00791435 | 47.323 |
| GLM-Flash v6 | 10 | 3 | 6,419 / 1,357 | $0.00164135 | 10.399 |
| GLM-Flash v6 | 25 | 1 | 2,709 / 1,091 | $0.00095185 | 6.874 |

Batching reduced prompt overhead in this stress set. One batch-25 success does not establish label invariance, sustained validity, representative unit cost or a safe full-source batch-25 projection. Repeated and shuffled conditions are retained in the machine-readable spending inventory. Their semantic comparisons belong to the separate quality analysis; this economics appendix makes no quality-improvement claim.

## Sealed prediction receipt: cost-only sensitivity

The public [counts-only receipt](../validation/sealed_human_predictions_v1.json), dated **`2026-10-20T08:20:11.860440+00:00`**, records completion of the sealed prediction stage. Each arm covers **200 original IDs / 197 distinct texts**. No private prediction output, model label or human answer was inspected for this supplement. The receipt is operational evidence; it does not make human accuracy available.

| Sealed arm | Completed original IDs | Distinct texts | Attempts | Failed attempts | Reported nominal API cost, all attempts |
|---|---:|---:|---:|---:|---:|
| Lightning v5 | 200 | 197 | 20 | 0 | $0.004193642 |
| GLM v6 | 200 | 197 | 21 | 1 | $0.015163551 |

The receipt updates total known nominal usage to **$0.335913993**, plus **$0.016446200** unresolved holds, for **$0.352360193 committed**, with no in-flight reservation. The earlier 08:07 snapshot and original matched-195 calibration remain unchanged in the report and JSON.

For the new GLM sensitivity, divide the complete reported charge by the 197 accepted distinct texts:

```text
GLM all-attempt unit = .015163551 / 197
                    = .0000769723401 USD per distinct text
```

This is **$0.076972 per 1,000 texts**, **34.94% higher** than the separate matched-195 unit. The numerator already includes the charged failed attempt. The public receipt does not provide a token breakdown or the failed attempt's separate charge, so the increase cannot be attributed entirely to the retry or to a particular token mechanism. The panels also differ.

Keep the same explicit helper assumptions—5% distinct-text fallback and 1% original-ID verification using the earlier v5 unit costs—and one $0.25 final-stage allowance. The base transfers the observed all-attempt GLM rate directly. The second column adds a further 10% to **all variable work**, beyond the failure already included in the GLM unit:

| Scope | Project budget using observed all-attempt unit | With additional 10% variable allowance | Headroom under $48 with additional allowance |
|---|---:|---:|---:|
| 210,000 original IDs / 159,657 distinct texts | **$13.80** | **$15.12** | $32.88 |
| 660,609 original IDs / 484,189 distinct texts | **$40.65** | **$44.66** | **$3.34** |

Both columns include the receipt's latest $0.352360193 commitment, historical unresolved holds and the stage allowance once. The extra 10% is a sensitivity assumption, **not an observed retry rate**. The full-source stress case leaves $5.34 below the $50 total, including the separate $2 reserve. The old helper-role proxies, future retries, token variation and any additional project charges can consume that margin. This higher observed unit therefore materially narrows the budget case even though the API scenario still fits. Confidence is **high** in the arithmetic and **moderate** in transferring either small panel's consumption to the full source. No quality conclusion follows.

### Free-hosting storage gate

The [read-only database receipt](../validation/dashboard_evaluation_database.json) measured **1,490,944 bytes of application storage for the 1,000-review pilot**. A simple linear projection yields:

| Target original review IDs | Linear projected application bytes | Decimal MB | Against the conservative 700 MB gate |
|---|---:|---:|---|
| 210,000 | 313,098,240 | 313.10 MB | Below |
| 660,609 | Approximately 984,931,025 | 984.93 MB | Above |

The threshold is a planning gate, not a verified provider quota. Fixed database overhead, indexes, repeated source text and the final evidence layout make linear projection uncertain; an API cost projection alone does not prove that free hosting will fit. Before committing to the full source, measure an actual **10,000-review checkpoint's table/index footprint**, update the full-source storage projection, and establish a compression/storage design that preserves required source and audit evidence. Recheck the hosting fit after that design. The 210k projection passes this preliminary gate; **full-source free-hosting fit and end-to-end deadline feasibility remain unproven**. No paid-hosting cost or compression saving is assumed in the API scenarios above.
