# Final hero business and trace audit

**Assessment: share with caveats after the authorized editorial correction.** Accounting and reference joins pass with high confidence. Label semantics remain uncertain; the independent verifier is a comparator, not human ground truth. No remaining factual-presentation blocker was found in the accepted memo. Hosted/API/release validation is a separate check.

## Accounting and numerical claims

- Independently streamed all **200,013** final records: **200,000 completed**, **13 empty quarantines**, one frozen configuration.
- Verified **87,897** unique complaint/cancellation memberships, all **8** ranking rows, and all **32** aggregate claims against independent recomputation. Exact scores and six-decimal half-up means match.
- Confirmed all recommendation, alternative, issue, review and claim references join; every bounded source quote matches its frozen record.
- Confirmed **40,000 distinct original IDs** match the seeded audit selection, all completed, with full Nebius GLM-5.3 successful-call evidence for the traced cases.
- Topic agreement **36,187/40,000 = 90.4675%**; intent **37,220/40,000 = 93.05%**; severity **36,341/40,000 = 90.8525%**. These are model-agreement rates, not human accuracy.

| Rank | Primary topic | Complaint/cancellation count | Severity sum / priority | Mean severity |
|---:|---|---:|---:|---:|
| 1 | issue-usability | 25,563 | 68,258 | 2.670187 |
| 2 | issue-other | 25,992 | 51,774 | 1.991921 |
| 3 | issue-playback | 12,548 | 39,445 | 3.143529 |
| 4 | issue-billing | 12,794 | 35,437 | 2.769814 |
| 5 | issue-catalog | 6,033 | 17,573 | 2.912813 |
| 6 | issue-access | 2,917 | 10,985 | 3.765855 |
| 7 | issue-downloads | 1,912 | 6,042 | 3.160042 |
| 8 | issue-support | 138 | 343 | 2.485507 |

The accepted memo correctly prioritizes usability by the required baseline score and compares playback, billing, and access alternatives. Usability has the second-largest eligible count; `other` has the largest. Access has the highest mean severity overall. Playback has the highest mean among the four largest issue groups; the memo’s phrase “high-volume topics” is descriptive rather than a registered threshold.

## Disagreement counters use different definitions

All counters use the same **40,000 unique verified IDs**. They do not count duplicate attempts.

| Definition | Count |
|---|---:|
| Any topic, intent, or severity disagreement | 8,565 |
| Sentiment absolute difference greater than 0.25 | 14,175 |
| Both categorical and sentiment disagreement | 4,169 |
| Sentiment-only disagreement | 10,006 |
| Either categorical or sentiment disagreement | 18,571 |

`evaluation.disagreement_count` reports the categorical count. `run_summary.stages.verify.disagreements` uses the union because `engine.verify()` retains a disagreement when categorical fields differ **or** sentiment differs by more than 0.25. The retained successful verifier-call total includes earlier checkpoints and must not be confused with the final audited-ID denominator.

## Actual source-to-memo trace with a disagreement

Review: `07f60ec3-2a42-4903-862a-4de5265803d6`. Source-row SHA: `041f78ab0cf597fee206532d79665b3666f11471ad8a723ae3f370558425f135`.

> Everything was fine until I couldn't play the song i want to by tapping it, there is no more lists of your playlist showing up and you can't select the song you want to play at that particular time ,also all my playlists and old account were deleted idk how, either way pls bring back the old playlist features where you could listen to whatever song you wanted and also take song back and forth to wherever you want!

1. The logged Decisions request `a67721cfaced4d4782bc2a96c11c2d0d` classified the review as **usability / complaint / severity 5**, with `needs_review=true`.
2. The independent full-GLM request `3b35008194c34bd8a9b8daad26dcb801` saw original text and returned **playback / complaint / severity 4**. The saved verifier records both disagreements; it did not overwrite production.
3. The saved membership places the original review ID in `issue-usability`. Its frozen severity contributes **5 points** to **68,258** and one review to **25,563**.
4. `claim-usability-severity-sum`, `claim-usability-priority-score`, `claim-usability-complaint-count`, and `claim-usability-mean-severity` reproduce those aggregate metrics.
5. Actual group request `b501e979618346f59f783db8c2f36c12` and memo request `4ada7d0430bd41779f6d79a0c4553637` include this review in their bounded evidence. Both accepted recommendations explicitly cite it: “Protect and restore user-curated library state” and “Instrument and triage library-loss reports across issue boundaries.”

Interpretation confidence is moderate. The author reports unavailable controls and alleged account/playlist deletion, but the text cannot establish permanence or root cause. This is a transparent uncertain trace, not a clean success claim.

## Qualitative error and agreement cases

| Review | Production → independent verifier | Memo relationship | Inspection |
|---|---|---|---|
| `424a25d7-50ab-4971-8128-c68821cc5d25` | usability/complaint/3 → billing/complaint/3 | Aggregate contributor; not a quoted example | Explicit Premium-only shuffle restriction supports billing/3 over ad-annoyance usability/2 under highest-severity same-problem rule. Production usability/3 likely miscombines topic and severity; independent billing/3 and two assistant reads agree. Provider .99 topic confidence and false needs_review did not prevent this error. It contributes to the memo aggregate but is not one of its quoted examples. |
| `34a66ccd-e1f9-482b-b370-86d24b6f735c` | playback/complaint/4 → playback/complaint/4 | Aggregate contributor; not a quoted example | Both models give playback/complaint/4. Explicit inability to play liked songs supports a blocked task; playlist-opening usability boundary remains plausible. Agreement is not human accuracy. |
| `82928fd7-ae00-4aaf-b381-b3c9444db38a` | billing/cancellation/5 → billing/complaint/5 | Explicitly cited | Production cancellation versus verifier complaint. Text explicitly says the author tried to cancel; cancellation is defensible under the precedence rule, so verifier disagreement does not establish that production is wrong. Both labels remain eligible and the billing/5 score contribution is unchanged. |
| `98c4bc2c-f115-4a39-977a-06c58b8e53d1` | access/complaint/5 → access/complaint/4 | Explicitly cited | Both models choose access/complaint; production5 versus verifier4. An inability to sign back in can explain lost access to saved songs without proving permanent data loss. Production review flag is appropriate. |

The globally hash-selected Premium example is a high-confidence likely topic error: the stronger functional restriction explicitly requires Premium, but production selected the ad-related usability topic. The independent verifier and two assistant inspections agree on billing. Conversely, the attempted-cancellation case shows why verifier disagreement cannot automatically be treated as production error. No verifier labels were copied into production.

## Factual editorial repairs and preserved evidence

The original memo claimed that usability had the largest complaint volume. That was false: `other` has 25,992 eligible reviews versus usability’s 25,563. The accepted prose now says second-largest complaint/cancellation volume and highest severity sum. The review also separated empty quarantines from review flags, replaced all issue titles with their primary-topic labels, qualified each description as a summary of severity-prioritized examples, and clarified that library-state work is a candidate intervention rather than a quantitatively ranked subtopic.

Exactly **20 field-level edits** were recorded in `runs/hero-v1/run/editorial-review.json`. Original display artifacts are preserved byte-for-byte in `editorial-review/v1/original/`; raw group and memo handoffs are unchanged. **Nine protected artifacts** retain identical hashes: classifications, verifier results, membership, ranking, claims, and the four raw handoffs.

`tools/review_hero_editorial.py` performed the guarded postprocessing. Five focused synthetic tests passed; a live dry run passed; application passed; repeated application verified idempotence. `memo.md` includes an editorial provenance note. No new provider calls, classifier changes, human-label changes or database writes were made by this audit.

## Remaining limitations

- **51,293/200,000 completed records (25.6465%)** remain `needs_review`; structural completion does not imply semantic resolution.
- The bounded group/memo pack contains **40 examples**, **30 flagged for review** and **35 severity-5 labels**, because selection prioritizes severity. It is not representative and cannot establish a subtopic’s prevalence.
- The primary topic is the unit of the numerical ranking. The specific library-loss intervention is grounded in examples but has no saved subtopic membership or measured causal effect.
- One completed complaint/severity-1 inconsistency remains explicitly flagged by deterministic review. The frozen classification was preserved.
- The source is historical, self-selected app-store feedback. Review cancellation language is not observed churn; product outcomes, revenue effects and current product-state claims remain unmeasured.
- These case judgments are assistant inspections, not new human annotations. Full human-reference evaluation and its sampling/adjudication caveats are reported separately.

## Reproduction and evidence

The published [README](../../README.md#inspect-and-reproduce-the-final-evidence-without-api-calls) provides credential-free reranking and unmodified course-checker commands for the final evidence ZIP. [business-audit.json](business-audit.json) contains the saved bounded case inspections, actual request identifiers, source hashes, accepted editorial manifest and artifact hashes, together with the independent arithmetic and selection checks. Qualitative case judgments are saved assistant inspections; they are not newly supplied human labels and are not reproduced by the numerical reranker. No unpublished working script is required by the documented reproduction commands.

Run: `run-07e2cb4b0e3d9be0`. Configuration: `spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a`. Audit completed: `2026-10-21T06:05:29.774625+00:00`.
