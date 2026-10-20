# Nebius screening v2: operational selection and label failure analysis

**Select Nemotron Lightning as the leading operational candidate for the next frozen 100-review pilot, subject to the rubric clarifications below. This screening does not establish a quality winner.** Lightning completed every requested review without a retry and used the least nominal API value. Its outputs still contain concrete intent, topic and severity errors, including severity 1 for generic complaints. GPT-OSS and Qwen also make substantive mistakes. Confidence: **high** on measured accounting and operational outcomes; **moderate** on the qualitative model-selection judgment.

This report uses real source-only screening outputs, not simulated labels. It contains AI-assisted qualitative inspection, **not human golden-set accuracy**, and does not replace the required complete cold/warm pipeline.

## Evidence and observed execution

Input: unchanged `cost_100.csv` (`data/source/cost_100.csv`), 100 original review IDs. SHA-256: `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e`. Each model received source text and the rubric independently, in batches of 25, with one worker and a 6,000-token output cap. Their processes overlapped in time. All executions used the verification-role schema, not the final compact first-pass enrichment schema. No grouping, ranking or memo work is included in these costs.

| Model and setting | Completed IDs | Attempted calls / failed attempts | Input / output tokens, including failed attempts | Nominal usage USD | Process wall seconds |
|---|---:|---:|---:|---:|---:|
| `nvidia/Nemotron-3_5-Lightning`; none | 100/100 | 4 / 0 | 9,946 / 7,398 | $0.00237228 | 25.517 |
| `Qwen/Qwen3-30B-A3B-Instruct-2507`; none | 100/100 | 5 / 1 | 11,969 / 9,985 | $0.00419240 | 213.778 |
| `openai/gpt-oss-120b`; low | 75/100 | 5 / 2 | 11,145 / 16,798 | $0.01175055 | 48.646 |

Costs reprice saved token usage at the exact model rates in [`rates.csv`](../config/rates.csv), including retries and failures. They measure economic API consumption; provider credit debits and incremental cash purchases remain **unmeasured**. Saved ledgers round reservations/settlements to finer fixed units and differ from the direct Qwen and GPT-OSS sums by $0.000000001. That rounding difference is not a missing request.

Qwen finished after 213.778 seconds. One response returned the wrong ID set; its bounded retry succeeded. GPT-OSS completed 75 reviews and left the final 25 failed: one response exhausted the 6,000-token completion cap, and the repair then returned an invalid ID set. Lightning completed all four calls successfully. These failure modes support smaller verification batches and exact array-length/ID validation; they do not justify relaxing validation.

**Timing interpretation:** 25.517, 213.778 and 48.646 seconds are elapsed times for separate, overlapping processes. They cannot be summed as one experiment wall time or treated as isolated sustained throughput benchmarks. Lightning was operationally fastest in this observed run; a clean complete pilot must establish sustained throughput and whole-pipeline cost. No full-run timing estimate is endorsed from this screening alone.

All 100 Lightning, 100 Qwen and 75 GPT-OSS completed outputs passed exact quote-substring and literal-entity checks against the original texts. This establishes structural grounding only; examples below show that a genuine source quote can still accompany an incorrect label. Lightning flagged `needs_review` on 13/100 records, Qwen on 1/100 and GPT-OSS on 2/75. These are uncalibrated flags, not confidence scores.

## Agreement on shared successful IDs

Only IDs completed by both named models enter each pairwise denominator. The GPT-OSS comparisons exclude its 25 failed IDs and therefore may be selection-biased. Missing outputs remain explicit in coverage; they are not counted as agreements.

| Pair | Shared completed IDs | Topic exact | Intent exact | Severity exact | Severity mean absolute difference | Sentiment mean absolute difference | needs_review exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| lightning / qwen | 100 | 87/100 (87.0%) | 81/100 (81.0%) | 70/100 (70.0%) | 0.380 | 0.130 | 88/100 (88.0%) |
| lightning / gptoss | 75 | 63/75 (84.0%) | 63/75 (84.0%) | 54/75 (72.0%) | 0.320 | 0.120 | 65/75 (86.7%) |
| qwen / gptoss | 75 | 67/75 (89.3%) | 70/75 (93.3%) | 62/75 (82.7%) | 0.187 | 0.040 | 73/75 (97.3%) |

Qwen and GPT-OSS agree more frequently than either agrees with Lightning on their shared cases; that is not proof that their labels are correct. For example, both overstate the Wi-Fi-failure case despite the explicit mobile-data workaround. On the 75 Lightning/GPT-OSS shared IDs, Lightning severity is higher on 6, lower on 15 and equal on 54. A blanket claim that Lightning overstates severity is contradicted by these counts. Its failure pattern includes both understatements and overstatements.

## Seeded inspection of 20 original reviews

The sample is the 20 lowest hashes of `SHA256("nebius-screening-v2-inspection:" + review_id)` among all 100 source IDs, selected independently of model agreement. Labels below are topic/intent/severity; full text, all labels and inspection confidence are in the [inspection CSV](nebius-screening-v2-inspection.csv). This is qualitative diagnosis, not a newly hand-labeled benchmark.

| Review ID | Source excerpt | Lightning / Qwen / GPT-OSS | Inspection |
|---|---|---|---|
| `2b57a12b-bbbe-457c-83a8-1bec297a5f63` | Spotify is a very nice listening 🎧 app on music platform | other/praise/1 · other/praise/1 · missing | General music-app praise; other/praise/1 is supported. Confidence: high. |
| `797d12c7-78dd-4805-a066-342ace701805` | Kudos spotify | other/praise/1 · other/praise/1 · other/praise/1 | Generic praise; all available labels follow the rubric. Confidence: high. |
| `85383985-844d-4f9b-bcd9-d6016ac35f6b` | This app is nice but adds are too much | usability/complaint/2 · usability/complaint/3 · usability/complaint/2 | Too many ads reports annoyance, with no stated functional restriction. Severity 2 is better supported than Qwen’s 3. Confidence: high. |
| `33526c6f-7a49-4b3d-bd20-d1bc191c494c` | RUDE APP , THIS APP SUPPORT GUYS 🤮🤮🤮🤮🤮🤮🤮🤮🤮🤮. تطبيق سيء ، بدعم المثليين 🤮🤮🤮 | other/complaint/1 · other/complaint/2 · other/complaint/2 | Generic criticism mixed with unrelated political content. Complaint/2 versus unclear/1 deserves an ambiguity flag; complaint/1 is inconsistent with generic-criticism examples. Confidence: moderate. |
| `67b21b33-e6b9-4d1a-b874-86bc182b9ada` | Spotify: music and pod system | other/unclear/1 · other/praise/1 · other/unclear/1 | Bare descriptive phrase does not clearly praise or complain. Qwen’s positive sentiment is unsupported. Confidence: high. |
| `ab67a772-c3b7-42ba-9b80-8d21d3857018` | The ads are so loud :'( | usability/complaint/2 · usability/complaint/3 · usability/complaint/2 | Loud ads support usability/complaint/2. Functional loss needed for severity 3 is not stated. Confidence: high. |
| `46ff0c74-5e86-4e5b-b4cd-36201aab0f9e` | I am unable to use my Google assistant on the app.it says playing your Spotify playli… | playback/complaint/3 · playback/complaint/3 · playback/complaint/3 | Assistant-triggered playback is broken; playback/complaint/3 is defensible. The text does not establish every listening route is blocked. Confidence: moderate. |
| `7084ced1-0428-4093-9328-442f74719b4f` | I am using Spotify from past two years From last update they removed basic features o… | usability/complaint/3 · usability/complaint/3 · missing | Removed features plausibly restrict usability; severity 3 is defensible, but the exact functions remain unspecified. Confidence: moderate. |
| `486d1d7a-d6f6-41ea-81ad-ed875452729c` | Vary bad experience.i am uninstalling this app they burn quran and i will bycot this … | other/cancellation/1 · usability/cancellation/2 · other/cancellation/2 | Explicit personal uninstallation supports cancellation. No specific usability defect is stated; other is preferable. Product impact is unclear. Confidence: moderate. |
| `66a29b3c-c14d-440e-b722-b23e0c99ae82` | App is stuck on loading/logo screen | playback/complaint/4 · playback/complaint/4 · playback/complaint/4 | Stuck launch/logo screen clearly blocks use; playback/complaint/4 is supported. Confidence: high. |
| `916d1cb1-3a9f-42c0-9c36-fee4b1983c68` | L lovethemusic | other/unclear/1 · other/praise/1 · other/praise/1 | Misspelled “love the music” is interpretable praise. Lightning’s unclear/neutral output is too conservative. Confidence: high. |
| `7e91d976-20e5-40f0-a6f5-7312eadf7e78` | Love Spotify.. My music go to.. | other/praise/1 · other/praise/1 · other/praise/1 | General praise; other/praise/1 is supported. Confidence: high. |
| `a7aebec4-11e0-40d6-abf5-7a4798ebbb98` | One of the best apps in my life :) | other/praise/1 · other/praise/1 · missing | General praise; other/praise/1 is supported. Confidence: high. |
| `23d905f8-8684-41b3-8faa-42571f3eaeee` | Love this app. The developers do a good job keeping up with changes. Not a complaint … | other/praise/1 · other/praise/1 · other/praise/1 | Paid-plan mention is incidental to praise; correctly stays other, not billing. Confidence: high. |
| `a1a28752-3256-4f81-b888-3e943343529f` | It's nice but gospel music isn't much | catalog/complaint/1 · catalog/complaint/3 · missing | Reported catalog shortage is a complaint, not no-problem severity 1. Severity 3 is defensible for restricted content availability. Confidence: moderate. |
| `178c3b49-b689-4fe4-92a2-2257a58e6d95` | Worst app. | other/complaint/1 · other/complaint/2 · other/complaint/2 | “Worst app” is the rubric’s generic-criticism case: complaint/severity 2. Lightning’s severity 1 is unsupported. Confidence: high. |
| `ba274609-2cbc-4d6a-9624-276d1c8246e8` | I can't use anything else but Spotify 💯👍🏼 | other/praise/1 · other/praise/1 · other/praise/1 | Idiomatic enthusiasm, not inability to use Spotify. All models correctly classify praise. Confidence: high. |
| `3e82cf28-6b0a-4980-902c-b6aa154d353a` | Aakhir kar spotify ne bhi apni bhikaariyo vali aukaat dikha di "Gadar karbe" Chanda m… | billing/complaint/2 · billing/complaint/4 · missing | Romanized Hindi criticism of soliciting money supports annoyance; no blocked core task is stated. Qwen’s severity 4 overstates observed impact. Confidence: moderate. |
| `c1ab120a-f91f-4ee3-87f5-66f352e2d47f` | It was a good app . But now it's a trash 🗑️ | other/complaint/2 · other/complaint/2 · missing | Generic criticism despite historical praise; complaint/severity 2 is supported. Confidence: high. |
| `9c9757da-6b99-4c95-a0e7-0661ee858027` | There is some bugs like music adjustment doesn't work Perporly plz do something about… | usability/complaint/2 · playback/complaint/3 · missing | “Music adjustment” is ambiguous between controls and audio/playback. A reported nonworking function may warrant severity 3; needs_review should capture the uncertainty. Confidence: moderate. |

## Ten targeted disagreement inspections

These are deliberately selected failure/ambiguity cases, not a random estimate of error prevalence. An independent assistant inspected the same ten cases against the course rubric; the judgments below retain ambiguity rather than treating a majority vote as ground truth.

| Review ID | Lightning / Qwen / GPT-OSS | Supported interpretation |
|---|---|---|
| `618d1dbb-0186-4537-923a-7b4dabf19afb` | usability/cancellation/4 · usability/complaint/3 · catalog/request/1 | Explicit “I’ll start using” a rival is cancellation. Unwanted recommendations do not establish blocked listening: severity 2–3, topic catalog/usability ambiguous. GPTOSS request/1 and Lightning severity 4 are both problematic. Confidence: high on intent; moderate on topic/severity. |
| `2ffdf599-a0d5-4c01-bf26-025215d44c06` | usability/cancellation/4 · usability/complaint/3 · downloads/complaint/3 | Background downloads resume when opening the app: downloads/3, with an explicit workaround. Considering cancellation is an intent ambiguity, not permission to raise severity. Confidence: high on topic/severity; moderate on intent. |
| `88439ec2-7c49-4c57-bedb-c5e098692aff` | billing/cancellation/4 · usability/cancellation/2 · usability/cancellation/3 | Explicit premium-gated controls plus personal switching threat support billing/cancellation/3. Lightning’s topic is supported; GPTOSS’s lower severity is better grounded. Confidence: high. |
| `4ab2089a-ffa8-49e7-a8a3-aeb583a96796` | playback/complaint/3 · playback/complaint/4 · playback/complaint/4 | Mobile data works despite Wi-Fi failure: playback/complaint/3. Premium membership does not change the primary topic. Confidence: high. |
| `035213ba-b1b9-411c-b028-70296e5f0e73` | billing/cancellation/2 · usability/cancellation/2 · usability/cancellation/2 | Uninstallation over intrusive premium ads supports usability/cancellation/2; premium mentions do not alone establish billing. Confidence: moderate-high. |
| `e5e6c55f-3069-4b7c-9807-f8b5d5bf2726` | billing/complaint/3 · usability/complaint/3 · usability/complaint/2 | Too many ads and rhetorical “useless” favor usability/complaint/2; premium is an implied remedy, not an explicit entitlement failure. Confidence: moderate-high. |
| `cf6166ae-d71a-4839-9add-088645ad3b78` | usability/cancellation/2 · usability/complaint/3 · playback/complaint/4 | “Don’t download” is advice to others, not personal cancellation. Ads instead of songs may be rhetoric or restriction; complaint/2–3 with needs_review is more defensible than automatic severity 4. Confidence: high on intent; moderate on severity. |
| `9e5f9745-f8be-48d3-b9de-4d118507d94a` | usability/complaint/4 · playback/complaint/4 · playback/complaint/4 | All three miss the explicit threat to delete the app. Seeking restriction supports usability/cancellation/3, not complete playback blockage. Confidence: high. |
| `d455c11e-c530-4c03-a395-38f5a5cdb8d3` | other/praise/1 · usability/complaint/3 · usability/complaint/2 | Later unwanted autoplay complaint overrides initial blend praise. Usability/complaint/2 is supported; Lightning anchors on the opening praise. Confidence: high. |
| `6c257eba-3dca-49f6-b7f0-4c4484d81e26` | playback/complaint/3 · playback/complaint/3 · playback/complaint/4 | Songs stop and another song starts: degraded playback remains available. Playback/complaint/3 is better supported than GPTOSS severity 4. Confidence: high. |

## Clarifications before freezing the complete cold pilot

1. Keep the existing severity meanings. Generic criticism is severity 2. Severity 3 requires degraded or restricted functionality; it is **not limited to core tasks**. Severity 4 requires a clearly blocked core task. Anger, “useless,” cancellation and paid-plan mentions do not raise severity by themselves.
2. Apply intent precedence across the entire review. A later complaint overrides opening praise. Explicit personal deletion, uninstallation, switching or conditional departure is cancellation; advice to others not to download, a comparison with a rival, or generalized anger is insufficient.
3. Use the specific affected feature: downloads/offline failures are downloads; recommendations/lyrics are catalog; controls, ads and queue management are usability. Explicit premium-only controls are billing; a premium subscription or promotion merely mentioned alongside another problem is insufficient.
4. Treat an explicit workaround or continued playback as evidence of remaining use. Do not turn a Wi-Fi-only failure, a background download that resumes when opened, or seeking restrictions into total inability to listen.
5. Interpret obvious typos and mixed-language praise where the meaning is supported. Mark genuine language or impact ambiguity with needs_review; do not invent calibrated confidence. Preserve bounded fallback and avoid silently dropping difficult cases.
6. Keep the ID contract strict. Require the requested number of array items, validate every ID, and use smaller GPT-OSS verification batches. Any prompt, schema or batching change creates a new configuration/cache identity; the official cold/warm measurements must use that frozen configuration.

The recommended next decision is operational: try Lightning for the first-pass role and GPT-OSS at low effort for a bounded independent comparator with smaller batches. Preserve Qwen results as a useful challenger. Reassess selection after the complete 100-review cold/warm pilot and the 1,000-review learning run; there is no evidence here for automatically scaling to the final cohort.

## Reproducibility and artifact cautions

- [Machine-readable metrics and exact shared-ID lists](nebius-screening-v2-metrics.json).
- [Thirty qualitative inspection entries](nebius-screening-v2-inspection.csv): 20 seeded random plus 10 targeted.
- Original model evidence: Lightning (`runs/nebius-screening-v2/lightning/`), Qwen (`runs/nebius-screening-v2/qwen/`), GPT-OSS (`runs/nebius-screening-v2/gptoss/`). Each contains screening_report.json, verification.jsonl, calls.jsonl and saved handoffs.
- Use outer screening_report.json and verification.jsonl for screening coverage. The generic run_summary enrichment counts are zero because these were source-only verification tasks, not enrichment runs.
- The original per-model disagreements.jsonl reports missing enrichment predictions for every completed verification. Those counts are **not** cross-model disagreement counts; use this report’s explicitly paired calculations.
- Golden human labels were not read or created. No model, provider, prompt or configuration file was modified during this analysis; no additional inference was called.
