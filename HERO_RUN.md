# Authorized 200,000-review run

The user authorized the hero run on October 20, 2026, with a **$50 total budget across providers** and **20% independent verification**. `config/hero.json` caps API admission at $48, retaining $2 for billing uncertainty. Existing expenditure and unknown-charge reservations remain in the shared ledger.

Run explicitly with:

```sh
python tools/run_hero.py --execute-paid
```

The supervisor runs as a detached operating-system process, launches each checkpoint in a separate process, and checkpoints in SQLite after every completed request. It resumes completed stages without dispatching their paid requests again. Keep the Mac powered and connected; the launcher uses `caffeinate` to prevent idle sleep while running. Status is in `runs/hero-v1/status.json`; detailed logs, immutable configuration snapshots, and source selection are alongside it.

## Model roles and bounded improvement

OpenAI Decisions / `gpt-6-luna` performs the fixed first-pass decisions. Nebius GLM-5.3-Flash performs bounded whole-record fallback, grouping, and recommendations. Full Nebius **GLM-5.3**, explicitly at low reasoning effort, independently classifies original review text for audit. It never sees first-pass predictions, confidence scores, or human labels. Both GLM models share a family, so agreement is not an unbiased human-accuracy estimate.

DeepSeek V4 Pro 0813 was tested first. A 100-review low-effort probe cost $0.12756 and required an output repair; a thinking-off request still returned reasoning tokens on this endpoint and failed 25 of 100 after bounded repairs. It was rejected. Full GLM-5.3 completed 100/100 at $0.0357884, with zero failed calls. This projects roughly $14.32 for a 40,000-review audit before contingency; the supervisor remeasures on the pilot before admission.

The harness measures cold/warm 100, 500 and 1,000 reviews. Every completed evaluation stage audits at least 20%. The first pilot compares a 5% fallback cap; if the topic >90% and intent >93% development-agreement targets are missed, it tests one versioned candidate with a 15% cap and a higher uncertainty threshold. Whole records are selected by a weighted confidence routing score (topic .5, intent .4, severity .1); this is not calibrated probability. The candidate must improve combined topic/intent agreement without >1 percentage point regression in either. Fresh 1,000-review confirmation follows. Human golden labels never enter routing, prompts, or model inputs. Targets are reported honestly and do not authorize copying verifier outputs into enrichment.

The authorized rubric-focused hero run proceeds when accounting, structural and budget gates pass; agreement targets are diagnostics rather than a claim of guaranteed accuracy. Checkpoints are saved every 10,000 reviews; the final audit selects 40,000 original IDs using seeded SHA-256 sampling. Extra development/checkpoint audits are reported separately. Exact-text cache aliases retain individual IDs and source hashes.

## Deliverables and recovery

The final stage regenerates issue membership, exact ranking, numerical claims, and the recommendation memo; runs the unmodified course checker; atomically publishes to Postgres; and uploads a GitHub release. The existing public dashboard reads the selected database run and makes no model calls. Completion is only reported after these steps succeed.

Raw request/response traces are losslessly gzip-compressed. A separate app heartbeat watches blockers and completion. The connector identifies the wrong account; it must not receive uploads. The correct Berkeley Drive is authenticated in Dia. Initial archive upload was downloaded again and SHA-256 verified. The monitor uploads additional bundles to the private Berkeley folder; `tools/bundle_traces.py` creates upload bundles. `tools/trace_guard.py` compacts raw pairs into locally readback-verified archives before removing redundant individual files. Checkpoints, the result cache, and the spending ledger must remain local. Never delete a trace archive before a remote copy's bytes/checksum are verified.

Full-source ingestion and selected-cohort classification are distinct. The hero input contains 200,000 nonempty reviews plus all 13 empty rows as explicit quarantines. The complete source contains 660,622 IDs. The course's original full-corpus clause is superseded by the user's stated reduced-scope allowance; the reduced scope remains disclosed in the export.
