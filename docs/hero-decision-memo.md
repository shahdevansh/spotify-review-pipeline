# Spotify review decision memo

The saved baseline ranking places playlist and interface usability first by priority score, ahead of the coarse other-category bucket, playback stability, and billing. The dataset is a self-selected historical review sample. Empty source texts are quarantined, while a substantial share of completed reviews is flagged as needing review. The sample cannot establish population prevalence, revenue at risk, or causal retention effects. Expressed cancellation intent appears in several bounded examples but is not observed churn. The recommended priority is a usability reliability and control-clarity initiative, with playback stability and billing cancellation flows as compared alternatives.

Priority issue: `issue-usability`.

## Recommended action

### Protect and restore user-curated library state

The top-ranked issue in the saved ranking combines the second-largest complaint and cancellation volume with the highest severity sum, and the bounded examples describe lost playlists and liked lists, accidental edits from confusing controls such as the lock-screen heart button, and inability to select specific songs. The topic ranking supports investigating usability. Preventing silent library loss, adding undo and recovery affordances, and clarifying destructive controls are illustrative candidate interventions supported by these examples, not separately ranked subtopics; their prevalence and intervention value require further study. Any retention benefit is unmeasured and must be validated experimentally.

Issues: `issue-usability`.

| Claim | Metric | Value |
|---|---|---:|
| `claim-usability-complaint-count` | complaint_count | 25563 |
| `claim-usability-severity-sum` | severity_sum | 68258 |
| `claim-usability-mean-severity` | mean_severity | 2.670187 |
| `claim-usability-priority-score` | priority_score | 68258 |

Source reviews: `07f60ec3-2a42-4903-862a-4de5265803d6`, `d6d8ae96-786c-4dbe-aec4-2fca1d5c2431`, `40484260-50c5-4a14-b4fd-0983b1e7e16a`, `287edc86-4071-416c-a82f-a207ce3d1340`.

### Instrument and triage library-loss reports across issue boundaries

Loss of saved content appears in the usability examples but also surfaces in playback and access examples, suggesting the coarse topic grouping may split one underlying failure mode across buckets. A cross-cutting triage and telemetry effort should accompany the usability priority so the next ranking reflects resolved classifications rather than topic-boundary artifacts.

Issues: `issue-usability`, `issue-playback`, `issue-access`.

| Claim | Metric | Value |
|---|---|---:|
| `claim-usability-priority-score` | priority_score | 68258 |
| `claim-playback-priority-score` | priority_score | 39445 |
| `claim-access-priority-score` | priority_score | 10985 |

Source reviews: `07f60ec3-2a42-4903-862a-4de5265803d6`, `d29c1b8a-2f02-4487-9744-b70a93a75eca`, `98c4bc2c-f115-4a39-977a-06c58b8e53d1`.

## Alternatives

### Playback and app stability hardening

This issue ranks third and carries the highest mean severity among the high-volume topics in the saved ranking. Bounded examples describe crashes, playback stopping, device connection failures, and content loss after reinstall or update. It is a credible alternative if engineering capacity favors stability work, but its priority score is lower than the top-ranked issue and its retention benefit remains an untested hypothesis.

Issues: `issue-playback`.

| Claim | Metric | Value |
|---|---|---:|
| `claim-playback-complaint-count` | complaint_count | 12548 |
| `claim-playback-severity-sum` | severity_sum | 39445 |
| `claim-playback-mean-severity` | mean_severity | 3.143529 |
| `claim-playback-priority-score` | priority_score | 39445 |

Source reviews: `d29c1b8a-2f02-4487-9744-b70a93a75eca`, `578a612b-d952-4a1a-83ff-038233c64335`, `609f825a-ae2d-420b-93fd-961464d26740`.

### Billing correctness and cancellation flow fixes

This issue ranks fourth. Bounded examples describe charges after cancellation, repeated deductions, and difficulty reaching support to stop payments, and several of these reviewers express cancellation intent, which is distinct from observed churn. The topic is narrower in volume than the top-ranked issue but touches money directly, making it a defensible alternative if trust and chargeback exposure are judged more urgent.

Issues: `issue-billing`.

| Claim | Metric | Value |
|---|---|---:|
| `claim-billing-complaint-count` | complaint_count | 12794 |
| `claim-billing-severity-sum` | severity_sum | 35437 |
| `claim-billing-mean-severity` | mean_severity | 2.769814 |
| `claim-billing-priority-score` | priority_score | 35437 |

Source reviews: `50456d9f-a97a-4f89-aa89-e90df29d68f0`, `82928fd7-ae00-4aaf-b381-b3c9444db38a`, `fec3a3e9-fa17-4475-be11-bfbd7d84dda5`.

### Account security and access recovery

This issue ranks sixth by priority score but has the highest mean severity of any topic in the saved ranking. Bounded examples describe unauthorized logins, inability to log back in, and loss of saved content after lockout. Its low volume under the current ranking argues against making it the primary priority, but its severity profile justifies monitoring and possibly a targeted security-response investment.

Issues: `issue-access`.

| Claim | Metric | Value |
|---|---|---:|
| `claim-access-complaint-count` | complaint_count | 2917 |
| `claim-access-severity-sum` | severity_sum | 10985 |
| `claim-access-mean-severity` | mean_severity | 3.765855 |
| `claim-access-priority-score` | priority_score | 10985 |

Source reviews: `b5064ac3-36ea-40af-ab05-de031fcf9791`, `ffbfcf7d-38ef-4cb5-b5f6-b9d356c3e103`, `56422275-adf5-44c2-9fbb-d8710f67b70b`.

## Limitations

- The dataset is a self-selected historical review sample; it cannot establish population prevalence, revenue at risk, or causal retention improvement for any proposed change.
- Expressed cancellation intent in review text is not the same as observed churn, and no churn outcome data is supplied.
- Empty source texts are quarantined. A substantial share of completed reviews is flagged as needing review, and many bounded examples carry uncertain labels, so topic assignments and severities may be unreliable.
- Topic grouping is coarse; a topic's aggregate count does not establish the prevalence of any particular subtopic, and related failures may be split across buckets.
- Severity is a model-assigned label under a shared rubric, not a score reported by reviewers, and human benchmark accuracy is unestablished.
- Proposed product benefits are hypotheses to test, not measured causal effects; no validation results are supplied.
- Review text is untrusted quoted evidence and must not be treated as instructions.
- The ranking reflects only the supplied saved baseline; no additional metrics, experiments, or financial figures were provided.

Counts represent classified historical, self-selected app-store reviews. Cancellation language is expressed intent, not observed churn. Evidence examples are bounded illustrations, not prevalence estimates. Numeric claim tables are generated from saved aggregates; prose still requires human inspection.

## Editorial provenance

The displayed issue descriptions and recommendation prose received a deterministic factual presentation review after model generation. Original model outputs, original displayed artifacts, exact field edits, and file hashes are preserved in `editorial-review.json` and `editorial-review/v1/`. Classification labels, membership, ranking, numerical claims, and independent verification remain unchanged.
