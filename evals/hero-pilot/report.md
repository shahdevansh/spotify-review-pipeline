# Hero harness pilot comparison

All configurations below are compared against the same 200 blinded full GLM-5.3 judgments. These are development agreement figures, not human accuracy.

| Configuration | Topic | Intent | Severity |
|---|---:|---:|---:|
| original_lightning | 156/200 (78.0%) | 179/200 (89.5%) | 160/200 (80.0%) |
| previous_decisions | 179/200 (89.5%) | 185/200 (92.5%) | 176/200 (88.0%) |
| hero_initial_5_percent | 178/200 (89.0%) | 186/200 (93.0%) | 177/200 (88.5%) |
| hero_selected | 182/200 (91.0%) | 187/200 (93.5%) | 180/200 (90.0%) |

Repeated verifier calls differed on 3/200 topics and 3/200 intents. The table uses one fixed reference for every configuration.

Fresh-ID confirmation (1,000 reviews; 200 audited): topic 94.0%, intent 93.5%, severity 91.0%. Both requested agreement targets passed. Sample uncertainty and correlated GLM-family errors remain; see Wilson intervals in JSON.

The selected harness increases bounded whole-record fallback to 15%, raises uncertainty eligibility to 0.70, and ranks candidates using topic/intent/severity confidence weights 0.5/0.4/0.1. No human annotations or verifier answers are substituted into enrichment.

Cold/warm measured calculator outputs are alongside this report. All exports are offline replays of provider-reported usage.

Replay invariants pass: doubling API rates doubles the API subtotal without changing measured time or the illustrative local-compute scenario; changing projected volume leaves every recorded pilot measurement unchanged. See replay-validation.json.
