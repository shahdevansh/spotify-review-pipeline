# Spotify review intelligence

## Recommendation

Prioritize making everyday listening easier, with playback reliability and clearer Premium billing as the next two areas of work. Across **200,000 Spotify reviews**, usability produced the highest combined frequency and severity score, while playback complaints described more serious disruption on average. Billing feedback adds a distinct concern about what customers receive, what they pay, and how they cancel.

The analysis identifies where to investigate first and gives each team concrete customer experiences to work from. The next step is to connect those reports to product telemetry, confirm the underlying failures, and test improvements against measures that matter to listeners.

| Recommended focus | Complaint or cancellation reviews | Average severity, out of 5 | Combined severity score |
|---|---:|---:|---:|
| Make everyday listening easier | **25,563** | **2.67** | **68,258** |
| Keep playback uninterrupted | **12,548** | **3.14** | **39,445** |
| Make Premium value and billing clear | **12,794** | **2.77** | **35,437** |

Counts refer to reviews assigned to each broad topic. The score adds the severity of every complaint or cancellation review, giving weight to both how often a problem appears and how much it disrupts the experience. The broad Other category ranks second overall, with 25,992 reviews and a score of 51,774, but it combines feedback that needs further categorization before it can guide a specific product team. The three priorities above are the highest-scoring actionable product areas.

## What Spotify should change

### Make everyday listening easier

Start with the controls listeners use to choose songs, manage playlists, and preserve their saved music. The inspected usability reviews describe difficulty selecting songs, confusing controls, and unwanted changes to playlists and liked-song collections. One reviewer describes accidentally removing songs after mistaking a control for the back button, while another describes unwanted shuffle adding songs outside their playlist.

Review song-selection and queue behavior across the free and Premium experiences, make the effect of library controls clear, and give listeners a way to recover accidental changes. Investigate reports of missing saved music across usability, playback, and account access together, because one underlying problem can appear under several topic labels. Library recovery is a specific opportunity suggested by the examples; the 25,563-review count covers the entire usability topic.

Measure whether people can complete common listening tasks, how often they reverse an unintended library change, and whether reports of missing saved content decline after a fix. These are proposed success measures for the next phase, not results already established by this analysis.

### Keep playback uninterrupted

Playback deserves the second product workstream because its average severity is higher than usability's, even though it has roughly half as many complaint or cancellation reviews. The evidence includes playback stopping, crashes, failed device connections, and unresponsive controls. One reviewer reports audio cutting out when the screen has been locked for a while; another reports a connected Bluetooth speaker producing no sound.

Prioritize reproducing interruptions and connection failures across app versions and listening devices, then use session-level telemetry to separate application defects from network or device problems. Track unexpected stops, failed playback starts, and successful device handoffs so fixes can be evaluated against the experience that generated the complaint.

### Make Premium value and billing clear

Billing reviews point to confusion and frustration around paid access, charges, and cancellation. The inspected examples include a Premium account without access to paid features, continued deductions after an attempted cancellation, and difficulty getting a payment problem resolved. The full topic also covers subscription restrictions and value, so its 12,794 reviews should guide a broader assessment of the paid experience.

Make subscription status, plan benefits, the next charge, and cancellation confirmation easy to understand. Check that cancellation and entitlement changes reach the systems that control access and payment, and provide a clear resolution path for unexpected charges. Evaluate this work through cancellation completion, disputed charges, and entitlement-related contacts rather than assuming that a clearer flow will produce a particular retention gain.

## How the analysis was built

The pipeline profiled all 660,622 source reviews and selected a reproducible cohort of 200,000 nonempty reviews from the historical May 2022 to November 2023 extract. It classified topic, intent, severity, and sentiment, then grouped the 87,897 complaint or cancellation reviews into eight topics. Exact duplicate text reused a saved classification for 47,637 reviews while preserving each review's individual contribution to the totals.

OpenAI Decisions with GPT-6 Luna handled the first classification pass. Nebius GLM-5.3-Flash reconsidered up to 15% of distinct texts selected by a weighted uncertainty score and contradiction checks. Full GLM-5.3 independently classified a seeded sample of 40,000 original review IDs without seeing production answers. Separate model roles summarized examples and drafted recommendations, while code controlled membership, calculated every score, and checked the supporting numerical claims. The [live dashboard](https://spotify-review-observatory.vercel.app) reads the saved database without making new model calls.

### What improved during testing

The work began with fixed 100-review checkpoints and a 1,000-review learning run. The matched development comparison used the same 200 verifier judgments for each candidate, allowing the effect of routing changes to be assessed on the same records.

| Experiment | Topic agreement | Intent agreement |
|---|---:|---:|
| Earlier Lightning configuration | 78.0% | 89.5% |
| Earlier Decisions configuration | 89.5% | 92.5% |
| Initial hero configuration, 5% fallback | 89.0% | 93.0% |
| Selected configuration, 15% fallback | **91.0%** | **93.5%** |
| Fresh 1,000-review confirmation, 200 audited | **94.0%** | **93.5%** |
| Final 200,000-review run, 40,000 audited | **90.47%** | **93.05%** |

Increasing fallback, broadening uncertainty eligibility, and weighting topic, intent, and severity confidence together improved the matched development result by two percentage points for topic and half a point for intent. Fresh confirmation and final-run results use different samples. The final independent audit also reached 90.85% severity agreement.

A separate comparison with the completed golden 50 matched 36 topic labels, 44 intent labels, and 40 severity labels, giving agreement of 72%, 88%, and 80%. Sentiment mean absolute error was 0.1974. These lower topic results make classification boundaries and confidence calibration the clearest areas for improvement. A future development cycle should use fresh labels to test the boundaries among usability, billing, playback, and generic criticism before revising the classifier.

The fixed cold 100-review run took 41.9 seconds and cost about $0.024; its cached repeat took 0.21 seconds and made no paid calls. Recorded project usage through the completed hero snapshot was $35.32, with $1.56 held for uncertain charges, within the $50 budget. The workflow through the first public release took approximately 4 hours 10 minutes, including recovery and the audit. [Pilot evidence](../evals/hero-pilot/report.md) and the [reproduction guide](hero-reproduction-and-evidence.md) preserve the exact measurements and scope.

### How to interpret the findings

These historical, self-selected reviews describe reported experiences, and topic counts do not measure the prevalence of a narrower problem such as library loss or incorrect charging. Severity is assigned under the course rubric. The large audit measures agreement between models, including models from a shared family, while the golden reference was finalized after earlier comparisons; its [versioned methods](../evals/human-reference-v3/report.md) explain how the labels were prepared. Cancellation language expresses intent rather than measured churn. Confidence in the proposed product direction is moderate, and current telemetry and controlled tests should determine the eventual scope and impact of each change.

## Evidence appendix

The following values come from the saved ranking. Exact means are retained here for reproduction, while the leadership summary rounds them to two decimal places.

| Topic | Review count | Severity sum and priority score | Exact mean severity |
|---|---:|---:|---:|
| Usability | 25,563 | 68,258 | 2.670187 |
| Other | 25,992 | 51,774 | 1.991921 |
| Playback | 12,548 | 39,445 | 3.143529 |
| Billing | 12,794 | 35,437 | 2.769814 |
| Access | 2,917 | 10,985 | 3.765855 |

The [business audit](../evals/hero/business-audit.md) independently reproduced all eight ranking rows, all 87,897 memberships, and all 32 claims. The exact claim identifiers for the figures used here are:

| Topic | Saved claim IDs |
|---|---|
| Usability | `claim-usability-complaint-count`, `claim-usability-severity-sum`, `claim-usability-priority-score`, `claim-usability-mean-severity` |
| Other | `claim-other-complaint-count`, `claim-other-severity-sum`, `claim-other-priority-score`, `claim-other-mean-severity` |
| Playback | `claim-playback-complaint-count`, `claim-playback-severity-sum`, `claim-playback-priority-score`, `claim-playback-mean-severity` |
| Billing | `claim-billing-complaint-count`, `claim-billing-severity-sum`, `claim-billing-priority-score`, `claim-billing-mean-severity` |
| Access | `claim-access-complaint-count`, `claim-access-severity-sum`, `claim-access-priority-score`, `claim-access-mean-severity` |

The revised product summary also inspected the first 50 API records per priority topic in source-ID order, broadening the original severity-prioritized evidence. These qualitative examples support the concrete experiences described above; no new subtopic counts were calculated.

| Additional examples used in this summary | Original review IDs |
|---|---|
| Unwanted shuffle and difficulty finding music | [003e336c-5580-48f6-9ad3-986bbca4f9b8](https://spotify-review-observatory.vercel.app/api/reviews/003e336c-5580-48f6-9ad3-986bbca4f9b8), [00522fc8-c978-477d-a1e4-6de53458fcec](https://spotify-review-observatory.vercel.app/api/reviews/00522fc8-c978-477d-a1e4-6de53458fcec) |
| Background interruptions, crashes, and speaker silence | [0021f5c8-6a24-4eaf-8173-14a41e6f6b1a](https://spotify-review-observatory.vercel.app/api/reviews/0021f5c8-6a24-4eaf-8173-14a41e6f6b1a), [00aaf668-a2f8-4ad5-90cb-b6b5d2c8d345](https://spotify-review-observatory.vercel.app/api/reviews/00aaf668-a2f8-4ad5-90cb-b6b5d2c8d345), [001082d6-de00-4a8d-a3b8-c3e3720280c1](https://spotify-review-observatory.vercel.app/api/reviews/001082d6-de00-4a8d-a3b8-c3e3720280c1) |
| Plan restrictions and unavailable paid features | [007c7722-46ea-4d1c-bcff-47ae71824581](https://spotify-review-observatory.vercel.app/api/reviews/007c7722-46ea-4d1c-bcff-47ae71824581), [002e1349-46a5-4616-9a8a-f0c8df17a6a1](https://spotify-review-observatory.vercel.app/api/reviews/002e1349-46a5-4616-9a8a-f0c8df17a6a1) |

The examples cited in the original recommendation remain available through the read-only review API:

| Evidence used in the saved recommendation | Original review IDs |
|---|---|
| Listening controls and saved music | [07f60ec3-2a42-4903-862a-4de5265803d6](https://spotify-review-observatory.vercel.app/api/reviews/07f60ec3-2a42-4903-862a-4de5265803d6), [d6d8ae96-786c-4dbe-aec4-2fca1d5c2431](https://spotify-review-observatory.vercel.app/api/reviews/d6d8ae96-786c-4dbe-aec4-2fca1d5c2431), [40484260-50c5-4a14-b4fd-0983b1e7e16a](https://spotify-review-observatory.vercel.app/api/reviews/40484260-50c5-4a14-b4fd-0983b1e7e16a), [287edc86-4071-416c-a82f-a207ce3d1340](https://spotify-review-observatory.vercel.app/api/reviews/287edc86-4071-416c-a82f-a207ce3d1340) |
| Playback and device connections | [d29c1b8a-2f02-4487-9744-b70a93a75eca](https://spotify-review-observatory.vercel.app/api/reviews/d29c1b8a-2f02-4487-9744-b70a93a75eca), [578a612b-d952-4a1a-83ff-038233c64335](https://spotify-review-observatory.vercel.app/api/reviews/578a612b-d952-4a1a-83ff-038233c64335), [609f825a-ae2d-420b-93fd-961464d26740](https://spotify-review-observatory.vercel.app/api/reviews/609f825a-ae2d-420b-93fd-961464d26740) |
| Billing and cancellation | [50456d9f-a97a-4f89-aa89-e90df29d68f0](https://spotify-review-observatory.vercel.app/api/reviews/50456d9f-a97a-4f89-aa89-e90df29d68f0), [82928fd7-ae00-4aaf-b381-b3c9444db38a](https://spotify-review-observatory.vercel.app/api/reviews/82928fd7-ae00-4aaf-b381-b3c9444db38a), [fec3a3e9-fa17-4475-be11-bfbd7d84dda5](https://spotify-review-observatory.vercel.app/api/reviews/fec3a3e9-fa17-4475-be11-bfbd7d84dda5) |
| Account access and cross-topic library investigation | [98c4bc2c-f115-4a39-977a-06c58b8e53d1](https://spotify-review-observatory.vercel.app/api/reviews/98c4bc2c-f115-4a39-977a-06c58b8e53d1), [b5064ac3-36ea-40af-ab05-de031fcf9791](https://spotify-review-observatory.vercel.app/api/reviews/b5064ac3-36ea-40af-ab05-de031fcf9791), [ffbfcf7d-38ef-4cb5-b5f6-b9d356c3e103](https://spotify-review-observatory.vercel.app/api/reviews/ffbfcf7d-38ef-4cb5-b5f6-b9d356c3e103), [56422275-adf5-44c2-9fbb-d8710f67b70b](https://spotify-review-observatory.vercel.app/api/reviews/56422275-adf5-44c2-9fbb-d8710f67b70b) |

This document is an editorial leadership summary of the frozen analysis, with proposed product measures added for decision-making. It does not replace the saved model recommendation or change any prediction, membership, score, or reference label. The [hero evidence release](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1) preserves `handoffs/memo.input.json`, `handoffs/memo.output.json`, the original grouping handoffs, and `editorial-review/v1/`. The [editorial history](../evals/hero/editorial-review.json) records the earlier factual corrections, including the correction that usability has the second-largest review count and the highest priority score.
