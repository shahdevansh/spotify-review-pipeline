# Nebius screening v1: rejected entity and interrupted retry

The planned matched 100-review screening did not complete. Qwen's first
22-review response returned the requested IDs, but one entity failed the exact
source-grounding check. The batch was rejected, its retry was cancelled in
flight, and the original evidence was retained. This is a real provider failure
case, not a completed cold/warm pilot or an accuracy result.

## First rejected response

| Field | Observed value |
|---|---|
| Run ID | `qwen-042dff20` |
| Provider / model | Nebius / `Qwen/Qwen3-30B-A3B-Instruct-2507` |
| Role / purpose | `verify` / `verify`, used for independent screening |
| Request ID | `9f25578fc86240c7a72b6bdfbbbf5352` |
| Input and returned IDs | 22 each; sets match exactly |
| First failing review ID | `33526c6f-7a49-4b3d-bd20-d1bc191c494c` |
| Response position | Fifth review |
| Original source phrase | `تطبيق سيء` |
| Unsupported returned entity | `تطبيقات سيئة` |
| Validator error | `invalid_output: Unsupported entity in classification` |

The returned entity is a different string from the phrase in the original
review. It is absent even under the validator's case-insensitive substring
comparison. The source text itself was preserved. The exact original review is
in the saved request (`runs/nebius-screening/qwen/handoffs/9f25578fc86240c7a72b6bdfbbbf5352.request.json`);
the unsupported entity and remaining candidate predictions are in the saved
response (`runs/nebius-screening/qwen/handoffs/9f25578fc86240c7a72b6bdfbbbf5352.response.json`).
The response records `finish_reason: stop`, so the observed rejection was an
entity-grounding failure rather than output truncation.

The whole response was rejected; its other candidate predictions are not counted
as accepted screening results. This check establishes a structural grounding
failure. It does not establish whether the candidate topic, intent, sentiment,
or severity labels were correct.

## Attempts and cost accounting

The call log (`runs/nebius-screening/qwen/calls.jsonl`) contains two attempts on
the same 22 IDs. The first returned a response and usage; the second
(`9bb44d3e118941b5a24b344134435093`) was cancelled in flight with no returned usage.

| Measurement | Saved value |
|---|---:|
| First attempt input tokens | 2,201 |
| First attempt output tokens | 2,886 |
| Reported cached input tokens, within total input | 816 |
| First attempt API duration | 58.15373025 seconds |
| Known nominal usage-based API cost | $0.0010859 |
| Cancelled retry's unknown-charge hold | $0.0029315 |
| Run known cost plus unresolved hold | $0.0040174 |
| Run wall time | 118.90172058 seconds |
| Attempts / failed attempts | 2 / 2 |

The recorded cost applies standard input/output rates to all reported tokens:

```text
(2,201 × $0.10 + 2,886 × $0.30) / 1,000,000 = $0.0010859
```

The cached-input count is metadata inside total input; it is not billed again.
No cache discount, verified credit debit, or verified incremental cash cost is
claimed. The retry hold is a conservative reservation, not a known charge.

At the saved summary (`runs/nebius-screening/qwen/run_summary.json`) snapshot,
the shared ledger reports $0.0015944 known nominal usage-based cost and
$0.0141941 unknown-charge holds, totaling $0.0157885 committed. These include
the earlier two successful Nebius probes and $0.0112626 retained from the failed
OpenAI contract check. They are historical ledger values, not a current account
balance or invoice.

This screening used the model-task interface directly. Accordingly, its generic
summary shows zero ingestion/completed/pending records and an empty stages map;
those fields do not mean no review text was sent. The call log establishes the
22 input IDs and the failed attempts. No complete 100-review comparison exists
for v1.

## Change before v2

Verification and fallback are being changed to a compact label-only response
schema. Code will provide the original evidence text and explicitly matched
entities. The original v1 artifacts and charges remain intact; the revised
configuration must have separate provenance and must pass software validation
and a new bounded screening before any 1,000-review run.

Human golden labels have not been generated or evaluated here. The 221-passed,
1-skipped software snapshot predates this repair and does not certify v2.
