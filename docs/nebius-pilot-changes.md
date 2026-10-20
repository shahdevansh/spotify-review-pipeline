# Nebius pilot changes: archived v2 observations

**The revised 100-review pipeline fixed several clear labeling mistakes but introduced others. Its memo stage failed validation, so this run is not a completed cold pilot.** Preserve it as development evidence and run the new frozen configuration through the full cold/warm sequence. Confidence: high on saved counts and failure details; moderate on qualitative label judgments; unknown on a causal prompt-only improvement.

This supplement compares the Lightning screening (`runs/nebius-screening-v2/lightning/`) with archived v2 cold output (`runs/experiment-v2-cold-memo-failure/100-cold/`). The same 100 original IDs are present, but the task changed from source-only verification to compact first-pass enrichment, the batching/order differed, and five records received a GPT-OSS fallback. Therefore differences cannot be attributed solely to the added prompt examples. These are AI-assisted development observations, not human golden labels or an accuracy estimate.

## Saved state and comparison

The archived run `100-cold-e3671496` completed 100/100 enrichments, independently verified 10/10 selected reviews, and saved grouping, membership, ranking and claims. It recorded nine model attempts, including two failed memo attempts, at ledger usage value $0.007027801 over 29.404 seconds. The execution status is explicitly `failed`; no accepted recommendations.json or memo.md was produced.

| Field | Original IDs whose final label changed from screening |
|---|---:|
| topic | 16 |
| intent | 17 |
| severity | 22 |
| sentiment | 10 |
| needs_review | 13 |

At least one of topic, intent or severity changed on 35/100 IDs. These are change counts, not improvements. Five unique texts used fallback; the examples below show whether fallback affected the final output. Full structured comparison evidence is in [nebius-pilot-changes.json](nebius-pilot-changes.json).

## Improvements, regressions and unresolved cases

Labels are topic/intent/severity. Unless stated otherwise, assessment confidence is moderate to high because the source directly states the relevant behavior. Ambiguous functional impact remains a range rather than a manufactured precise human label.

| Assessment | Original review ID | Screening → archived final | Fallback | Evidence-based interpretation |
|---|---|---|---|---|
| improvement | `178c3b49-b689-4fe4-92a2-2257a58e6d95` | other/complaint/1 → other/complaint/2 | False | Generic “Worst app” now receives severity 2, matching the stated generic-criticism rule. |
| improvement | `916d1cb1-3a9f-42c0-9c36-fee4b1983c68` | other/unclear/1 → other/praise/1 | False | The obvious “love the music” typo is now recognized as praise. |
| improvement | `ebc64fe2-9553-4528-87d5-cb4bb9783be6` | usability/cancellation/2 → usability/complaint/3 | False | A skip restriction no longer invents personal cancellation; restricted functionality supports severity 3. |
| improvement | `035213ba-b1b9-411c-b028-70296e5f0e73` | billing/cancellation/2 → usability/cancellation/2 | False | Premium advertisements are classified as usability; explicit uninstallation is preserved. |
| improvement | `21915fcd-9a35-48ba-b277-6296c4154603` | billing/cancellation/2 → billing/complaint/2 | False | Mentioning a rival no longer implies personal cancellation; complaint is the supported intent. |
| regression | `23d905f8-8684-41b3-8faa-42571f3eaeee` | other/praise/1 → billing/praise/1 | False | Incidental paid-subscriber status moves generic praise from other to billing, contradicting the paid-plan-mention boundary. The independent verifier returns other. |
| regression | `0658feaa-5bec-416e-b6b0-3de2a4c14580` | catalog/complaint/2 → catalog/request/1 | False | “Many songs are not present” is a reported catalog limitation, not a pure request without a problem. Complaint was better supported; severity remains a 2–3 boundary. |
| regression | `618d1dbb-0186-4537-923a-7b4dabf19afb` | usability/cancellation/4 → billing/complaint/4 | False | The explicit “I’ll start using” rivals threat loses cancellation. Billing is unsupported by membership alone, and severity 4 remains unsupported by unwanted recommendations. |
| regression | `1807cc68-ba99-4edc-b6f1-2a1478e69109` | catalog/complaint/2 → catalog/praise/1 | False | Preference for the former recommendation behavior plus fewer/newer songs is treated as praise; the comparison reports deterioration and better supports complaint. |
| mixed | `2ffdf599-a0d5-4c01-bf26-025215d44c06` | usability/cancellation/4 → downloads/cancellation/2 | False | Topic improves to downloads. Severity moves from unsupported total blockage to 2, but a stuck background download with an opening-app workaround more directly fits restricted functionality at 3. |
| mixed | `88439ec2-7c49-4c57-bedb-c5e098692aff` | billing/cancellation/4 → billing/cancellation/2 | False | Billing and cancellation remain supported. Severity drops from 4 to 2; restricted premium-gated controls more naturally fit 3, so the revision crosses past the supported middle level. |
| mixed | `9e5f9745-f8be-48d3-b9de-4d118507d94a` | usability/complaint/4 → playback/cancellation/4 | False | Explicit deletion threat now receives cancellation, but the seeking-control problem shifts to playback and remains severity 4 despite no established total playback blockage. |
| unresolved | `d455c11e-c530-4c03-a395-38f5a5cdb8d3` | other/praise/1 → other/request/1 | False | Opening praise changes to request, but the later complaint about unwanted autoplay still fails to take precedence. Usability/complaint/2 is the better-supported interpretation. |
| stable_supported | `4ab2089a-ffa8-49e7-a8a3-aeb583a96796` | playback/complaint/3 → playback/complaint/3 | False | The Wi-Fi failure with working mobile data correctly stays playback/complaint/3. |
| unresolved | `e25cf0b6-0285-4cc9-9a4a-5a8a05be929e` | other/praise/1 → other/praise/1 | False | Specific praise for personalized categories still maps to other; catalog is better supported and the independent verifier selects it. |

The most persistent boundary is severity 2 versus 3 versus 4 for partial controls, downloads and listening. Merely stating “workaround” examples has not made this boundary reliable. Another persistent error is reading early praise or polite wording as the final intent while missing a later reported complaint. Conversely, a subscription mention still sometimes overrides the actual subject despite the explicit rubric. These patterns should remain visible in the 1,000-review inspection rather than being hidden by aggregate agreement.

## Exact memo failures and why rejection was correct

Attempt one, request `f5e4b23ba1ca4c188c960f85de4907a3`, cost $0.001426500. The returned rationale embedded raw review UUIDs in prose, for example `89ea2c30‑db8b‑459d‑8ab7‑bbcb7f92c774`. UUID digits triggered the explicit numeral-free-prose guard: `Memo prose contains unchecked numerals; cite claim IDs and let the renderer insert numbers.` Its eight structured review_ids used ASCII hyphens, but the duplicate prose references still violated the bounded citation/rendering contract. Source: saved response (`runs/experiment-v2-cold-memo-failure/100-cold/handoffs/f5e4b23ba1ca4c188c960f85de4907a3.response.json`).

Attempt two, request `b45dbe558d2f4459ae6bc5f27bc84929`, cost $0.001504500. All 17 structured review IDs replaced ASCII hyphen-minus `-` (U+002D) with nonbreaking hyphen `‑` (U+2011), for example `89ea2c30‑db8b‑459d‑8ab7‑bbcb7f92c774`. These strings are not the original IDs, so the validator reported `Recommendation contains ungrounded review IDs.` UUIDs also remained in prose; resolving the first validation error would not make the response compliant. Source: saved response (`runs/experiment-v2-cold-memo-failure/100-cold/handoffs/b45dbe558d2f4459ae6bc5f27bc84929.response.json`).

The appropriate repair is to constrain each citation field to exact allowed identifiers and keep identifiers/numerals out of free prose, with code rendering cited claims and review links. Do not silently accept Unicode lookalikes or relax source-ID validation. Dynamic per-run citation enums and clearer output instructions address the observed failure; their successful behavior must be measured in the next actual run.

The rejected prose also needs semantic scrutiny: it described severity as “user-reported” even though severity is model-assigned, suggested that frustration could translate to churn, and introduced audience descriptions such as “power-users” without supporting source metadata. Correct formatting alone would not establish a grounded memo. Any accepted memo must remain about historical self-selected reviews and expressed departure intent, with no fabricated customer segmentation or causal retention claim.

## Next inspection checkpoint

- Confirm the new complete cold run saves an accepted memo, then verify unchanged warm replay makes no new enrichment calls and disclose all downstream calls.
- At the actual 1,000-review checkpoint, inspect the seeded development sample plus targeted disagreements and failures. Preserve both first-pass and final-after-fallback predictions; a shared fallback/verifier model can inflate final agreement.
- Revisit the cases above, especially mixed praise/complaints, premium mentions, missing content, restricted controls, and severity with remaining use. Report improvements and regressions together.
- Keep human golden-set answers isolated. This inspection has neither created nor consumed them.
- Do not infer success from 100 completed labels alone: the archived memo failures demonstrate why the full stage chain and honest execution status matter.

The final 1,000-review inspection is pending actual output. No additional API calls, engine edits, prompt edits or configuration edits were made for this supplement.
