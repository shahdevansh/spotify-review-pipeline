# Pilot quality review: 1,000 original reviews

**Decision: hold expansion for a focused repair and remeasurement.** The pipeline completed all 1,000 reviews, preserved their source evidence, and reproduced its saved ranking. Its classifications still contain material violations of the frozen rubric. In the seeded random inspection, seven of 30 cases raised a substantive concern; six of those seven were not marked `needs_review`. The capped fallback therefore misses observed problems. Confidence is high that these problems warrant repair; human benchmark accuracy remains unknown.

This is **AI-assisted development inspection**, not human labeling or a measured accuracy result. The user's isolated golden 50 remain pending. Ambiguous cases are reported separately from concerns. No saved predictions, model settings, recommendations, or runtime outputs were changed during this review.

## Evidence and sampling

The reviewed run is `runs/pilot/1000`, configuration `spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb`. Its first pass uses Nebius-hosted Nemotron Lightning; fallback and independent verification use GPT-OSS-120B. The memo uses GLM-5.3-Flash. There are 1,000 original IDs and 926 distinct texts.

The 30 random IDs were frozen before inspection using the lowest SHA-256 hashes of `pilot-inspection-v1:` plus original review ID. Selection is without replacement across all 1,000 IDs. The additional 30 cases exclude those IDs and deliberately select ten severity disagreements, ten intent disagreements, and ten topic disagreements. The severity group takes the largest absolute differences, with a seeded hash tie-break; the other groups use seeded hash order. This targeted group diagnoses failure modes and cannot estimate their frequency.

Selection manifests, exact record snapshots, and per-case annotations are in [`evals/pilot-inspection`](../evals/pilot-inspection). The complete, joined inspection is available as [CSV](../evals/pilot_inspection.csv) and [JSON](../evals/pilot_inspection_report.json). The JSON records source-file hashes and definitions.

| Inspection group | Supported | Concern | Ambiguous | Concerns flagged by pipeline | Ambiguous cases flagged |
|---|---:|---:|---:|---:|---:|
| Seeded random, 30 | 15 | 7 | 8 | 1 of 7 | 3 of 8 |
| Targeted disagreements, 30 | 4 | 23 | 3 | 3 of 23 | 0 of 3 |

These categories are qualitative assessments against the original text and supplied rubric. They are not a human confusion matrix, and the two groups are not pooled into an error-rate estimate.

## Source integrity passes; semantic support needs repair

All 1,000 final records preserve all six original source fields and match the supplied `row_sha` convention. All 1,000 evidence quotes equal the complete original review. Every extracted entity occurs literally in its source, with case-insensitive matching. No invented quote or unsupported extracted term was detected by these checks. Empty entity lists are allowed, so this does not measure entity recall.

An authentic quote can still accompany a wrong label. The random cases expose several different failures:

| Original ID and text | Saved classification | Inspection finding |
|---|---|---|
| `b0d0660d-b859-4d87-97e8-7420f05d1f94`: “Time to uninstall” | other / unclear / 1; flagged | Explicit personal departure supports cancellation. Severity 1 can remain defensible because no underlying impact is stated. |
| `bd277589-d872-482b-9c6f-1b7dbc415c96`: “No hifi” | catalog / request / 1; unflagged | Audio quality belongs to playback. Request versus complaint and impact are underspecified; the topic error is clearer than the intent boundary. |
| `23685af6-de32-4187-91d8-9471fd69fc20`: removal of the repeat option | usability / complaint / 2; unflagged | Loss of an identified control supports restricted function, severity 3, rather than only an annoyance. |
| `988406bb-d06a-43a8-a37c-f8d9dd3f8a14`: praises old songs, then reports a limited collection and requests more | catalog / request / 1; unflagged | The reported shortfall precedes the request; complaint precedence applies. |
| `b9a3e661-0eac-4cc9-a30e-7b1e11ef1315`: previously preferred Pandora, now uses only Spotify | other / unclear / 1; unflagged | The expressed comparative preference supports praise. |
| `94dfde2f-2a0a-48e2-8c01-ff60753f1bce`: praise of audiobooks, songs, and languages | other / praise / 1; unflagged | The first specific praised feature supports catalog rather than generic other. |

The remaining random concern involves primary-topic choice in a review that first complains about advertisements and then price. The eight ambiguous cases include sparse wording, garbled language, a bare name, and an allegation combining hacking, lost playlists, and large charges. Ambiguity does not establish that an allegation happened or that a particular label is correct.

The targeted cases reinforce the same boundaries and show that the verifier also makes mistakes:

| Case | Finding |
|---|---|
| `ef8ed0f7-b6bb-4398-824c-d8fe1a8ee78c`: “Way better than Amazon music” | Final complaint / −1 / severity 2 reverses clear comparative praise. Verifier praise is better supported. |
| `74135a47-3232-441f-a2c5-8050d3e820fa`: advises installed users to delete the app | Final cancellation invents the writer's own departure. Advice to others does not establish personal cancellation. |
| `47ab8a7e-e9da-45ef-bcfd-036fff3896a3`: forced shuffle unless Premium, now using YouTube Music | Final playback and verifier billing disagree. Billing follows the explicit Premium-controls rule, but both miss personal departure and overstate restricted selection as a total playback block. |
| `e5e362d7-1057-43bf-a3ca-8ffd93f80789`: “The new Lyrics font is so bad.” | Font presentation is usability, not lyrics availability/catalog. |
| `db73c4f7-2c81-4992-b9ea-95cf52c37233`: queue, repeat, and previous-song controls require Premium | Explicitly Premium-only controls are billing; final usability misses the rubric's boundary. |
| `6524068a-cff5-45b9-bd37-b91a6cb71475`: “Good music and selection is good too.” | Final catalog follows specific-feature praise; verifier other discards that evidence. |
| `0ea3b30d-23a6-4c70-a191-ec0fa67cfd36`: “Boring che” | The intelligible criticism supports final complaint/2. Verifier unclear/1 is not a correction. |
| `065c418e-7f18-42a3-b241-fe693b7a2b0c`: uninstall/reinstall after a black screen | Troubleshooting differs from abandonment, but the literal rubric also lists uninstalling under cancellation. This needs a documented clarification rather than declaring either model uniquely correct. |

## Independent agreement and fallback behavior

The independent verifier completed all 1,000 original IDs. It received source text without enrichment answers. Agreement improves after fallback, but fallback and verifier use the same model family and can make correlated mistakes.

| Field | First-pass agreement with verifier | Final agreement with verifier |
|---|---:|---:|
| Topic | 82.5% | 82.8% |
| Intent | 89.8% | 90.6% |
| Severity, exact | 82.7% | 83.8% |
| Sentiment, exact | 89.7% | 90.2% |
| `needs_review` | 93.1% | 94.8% |

Final severity mean absolute difference is **0.201**, and sentiment mean absolute difference is **0.0843**. These are differences between model outputs, not errors against human answers.

The saved files use two disagreement definitions. Neither number should be described without its definition:

- **310** reviews differ on topic, intent, or severity.
- **339** differ on those categorical fields or have sentiment distance **greater than 0.25**. This is the engine's `run_summary` and root `disagreements.jsonl` definition.
- **341** differ on any exact topic, intent, severity, or sentiment value. Two additional cases have only sentiment −0.8 versus −1.
- **354** differ on any exact field including `needs_review`, adding 13 flag-only differences. This is `evals/verifier_report.json`.

Fallback was applied to **46 unique texts / 46 original records**, within the floor of the 5% cap on 926 texts. It changed at least one topic, intent, severity, or sentiment field in 27 records. Among the 46 routed cases, agreement with the independent verifier changed as follows:

| Field | Before fallback | After fallback |
|---|---:|---:|
| Topic | 41/46 | 44/46 |
| Intent | 31/46 | 39/46 |
| Severity | 32/46 | 43/46 |
| Sentiment | 34/46 | 39/46 |
| `needs_review` | 21/46 | 38/46 |

Only four random inspection cases used fallback. “Disappointing” provides one supported improvement: the fallback changes generic complaint severity from 1 to 2. Three sparse or uninterpretable cases retain uncertainty, appropriately. None of the 30 targeted cases had fallback, even though 23 raised concerns. This shows a selection weakness; it does not prove that GPT-OSS would repair all those cases.

The final run flags 60 of 1,000 records. No numeric confidence signal exists for these model outputs. Its absence remains unknown; `needs_review` is an uncalibrated ambiguity/consistency flag. Its observed failure to flag six random concerns prevents treating it as a reliable error detector.

## Ranking and memo inspection

Independent offline recomputation reproduces all eight saved issue rows, scores, six-decimal half-up means, and order. Complaint/cancellation membership is deterministic. The memo's 14 distinct claim IDs and 14 distinct review IDs resolve to saved claims and original records.

The final memo correctly states that severity is model-assigned and that human benchmark accuracy is unestablished. This repairs the earlier cold-run wording that incorrectly described the labels as assigned by reviewers. It also distinguishes expressed cancellation from observed churn, and bounded examples from prevalence or causal retention effects.

However, the memo inherits classification errors. Its top usability recommendation cites `2b855f9f-b1c2-42e2-bc67-f45bd98fbcb4` (app crashes after a new interface) and `f11035b1-51b7-4bca-be50-7c17deb6ff53` (no sound and bad sound quality). The frozen rubric maps crashes and audio quality to playback. Its selected Premium-control examples also cross billing/playback/usability boundaries. The raw statements are real, but the category totals cannot safely establish the prevalence of these subtopics.

One comparative phrase also needs tightening: downloads are called the smallest-volume actionable topic, but support has one complaint versus nine downloads. “Actionable” is not defined to justify excluding support. The numerical ranking remains correct conditional on saved labels; the substantive quarterly recommendation remains provisional.

The original AI memo is preserved unchanged. These semantic concerns are recorded as review findings.

## Two reviews traced through the pipeline

The following traces illustrate how to audit a decision. They are explanatory examples, not additions to the 60-case inspection sample.

**Supported first-pass case:** `16929558-ce1e-4b87-8738-a1de3f557f66` says, “I paid my subscription and im still getting a pause subscription screen and can't access my music...... help me”. The payment/entitlement context supports billing; the blocked music access supports severity 4. The question for help does not override complaint precedence.

| Stage | Saved evidence and interpretation |
|---|---|
| Prepare | Original row is in `data/learning_1000.csv`; official row hash is `d5b748cfaf8d9d9980825fbcad7dfd54c1141185b60c59733b701ac81359b73c`. |
| Enrich | First classified at the 500 checkpoint by Lightning, request `ed0655472602478ab752cbc8c1bc0f92`, with short ID `r10` mapped to this original ID. Its saved request (`runs/pilot/500/handoffs/ed0655472602478ab752cbc8c1bc0f92.request.json`) and response preserve the handoff. Final labels are billing/complaint/4, sentiment −1, no fallback. The complete original text is the evidence quote. |
| Verify | GPT-OSS request `2b19fc28b29b4603a164fb4471646eda` independently selects access rather than billing; intent, severity and sentiment agree. This is an example where the first pass better follows the payment-entitlement boundary, so disagreement alone does not establish an enrichment error. |
| Group | `membership.csv` assigns the review to `issue-billing`; the review is one of the bounded examples in group request `7583de7a8a0645498667ac09748c53d9`. Code, not the grouping model, determines membership. |
| Rank | The record contributes one of 83 billing complaint/cancellation records and four of the issue's 239 severity points. `claim-billing-complaint-count`, `claim-billing-severity-sum`, `claim-billing-mean-severity`, and `claim-billing-priority-score` resolve to 83, 239, 2.879518, and 239. |
| Recommend | Memo request `346dd332b6534a14a858a40b928b112d` receives those saved claims and bounded evidence. The review is cited in the subscription-state diagnostic recommendation and the billing alternative. The recommendation is a hypothesis, not a measured retention benefit. |

The historical first-pass request appears in the 1,000 checkpoint's `evidence_calls.jsonl`, while its cost remains attributed to the 500 run. Cache reuse does not manufacture a new classification call.

**Appropriately unresolved case:** `284a011f-14b8-4b00-b9a3-6fa2bd209213` contains only “Mobile over head app”. Its row hash is `8585fe7d91d31ab68ddf1792b749b22d429e551691f08f41aad2187961f5fad5`. The text does not establish a specific feature or problem. Lightning request `13e87da1417f4203952fa535462f7fd3` returns other/unclear/1, sentiment 0 and `needs_review=true`. GPT-OSS fallback request `08dd74a8c5bd4a90aef4a43de371a43e` preserves those labels and uncertainty. Blind verification request `ba24abac67f6436bbc7f50b8fce331c9` agrees.

The record remains completed but explicitly uncertain; “completed” describes structural processing, not resolved meaning. It has no complaint/cancellation membership, contributes nothing to issue severity sums, and is not evidence for a product recommendation. Both models agreeing on an unclear label does not turn sparse text into a known experience.

## Next decision gate

The pilot establishes functioning execution, traceable evidence, and exact arithmetic. It does **not** yet establish classification quality sufficient to justify the large expansion.

1. Create a separately versioned development configuration that reinforces the existing rubric boundaries illustrated above. Clarify uninstall/reinstall troubleshooting explicitly. Do not change the taxonomy silently.
2. Compare candidates on the saved development failure cases and a fresh seeded development sample. Treat both the fast model and verifier as fallible; raw agreement alone must not select the winner.
3. Replace reliance on an uncalibrated self-flag with a measured routing proposal. Retain the cost cap and explicit unresolved statuses. Broadening escalation is a proposal to measure, not an assumption that a larger model fixes everything.
4. If prompts or settings change, invalidate the affected cache namespace and repeat the supplied 100-review cold/warm checkpoint. Preserve this 1,000-review run as the measured baseline.
5. Evaluate the isolated 50-review human set only after the user supplies those labels. Keep it out of prompt tuning and routing development.
6. Reassess the 10,000-review gate using the repaired configuration's quality, cost, throughput, recovery, and deployment evidence. A 210,000-review launch remains gated.

This review made no paid requests. Actual measured cost and runtime are maintained in the run's calculator and learning artifacts; the 1,000 run reuses earlier checkpoints and must not be described as a fresh cold 1,000-review cost.
