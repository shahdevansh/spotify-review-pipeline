# Spotify review pipeline: submission guide

## Summary and recommendation

I recommend that Spotify prioritize usability reliability and clearer controls, while investigating the reports of lost playlists, accidental changes, and difficulty selecting songs that appear in the supporting reviews. Usability has the highest priority score in the completed analysis, with 25,563 complaint or cancellation reviews contributing a severity sum of 68,258. This supports choosing usability as the broad area for further product work, although the specific fixes still need validation because the pipeline measures primary topics rather than individual failure modes.

The completed hero run classified 200,000 nonempty reviews, quarantined all 13 empty source rows, and finished with zero pending records after ingesting and profiling the full 660,622-row source. An independent audit covered 40,000 original review IDs, or 20% of the classified cohort, and reached 90.4675% topic agreement and 93.05% intent agreement. The [live dashboard](https://spotify-review-observatory.vercel.app) makes these results inspectable through issue rankings, original reviews, recommendations, and evaluation evidence, while the [decision memo](docs/hero-decision-memo.md) connects the recommendation to saved calculations and review IDs.

The original project recorded $35.32 in token usage at the saved rates, with another $1.56 reserved for uncertain charges, and took approximately four hours and ten minutes from its first workflow checkpoint to its first public release. A later isolated safety check added $0.0055 to the same ledger, leaving the project within its $50 budget. These figures describe recorded usage and reserved uncertainty rather than reconciled provider invoices.

## What the results tell us

Usability leads the ranking because of its combined volume and severity, while the broad `other` category actually contains more complaint or cancellation reviews, at 25,992. Playback stability is a credible alternative, with 12,548 reviews, a priority score of 39,445, and a higher mean severity than usability. Billing and account access deserve further investigation when the product objective places greater weight on payment trust or severe access failures. The recommendation follows the assignment's severity-sum baseline, so a different objective could reasonably produce a different priority.

The completed golden review set contains all four required labels for each of its 50 reviews. Against the frozen production predictions, topic agreement is 72%, intent agreement is 88%, severity agreement is 80%, and sentiment mean absolute error is 0.1974. These results are materially weaker than the large model-to-model audit, which shows why independent model agreement should be interpreted as a diagnostic rather than human accuracy.

The [reference report](evals/human-reference-v3/report.md) documents 43 topic changes approved after earlier model comparisons and 51 remaining field values drafted by models and reviewed by the author, who made five revisions. These scores therefore measure post-review agreement rather than blind population accuracy. The public comparison preserves all 200 worksheet records; 99 belong to the hero cohort, while the other 101 have explicit null production predictions and remain outside the scoring denominators.

## Experiments and improvements

Development began with measured cold and warm runs before expanding to 1,000 reviews and then the hero cohort. The selected cold 100-review run cost $0.02360475 across 105 attempts and took 41.9034 seconds; replaying the same inputs from saved outputs made zero model calls and took 0.2137 seconds. Offline checks also confirmed that doubling API rates doubles the calculator's API subtotal, while changing projected volume leaves the recorded pilot measurements unchanged.

On the same 200 development judgments, the earlier Lightning configuration achieved 78% topic and 89.5% intent agreement, while the earlier Decisions configuration achieved 89.5% and 92.5%. Increasing bounded whole-record fallback from 5% to 15% and broadening uncertainty eligibility to 0.70, with confidence-weighted routing, brought the selected configuration to 91% and 93.5%. A separate 1,000-review confirmation run, with 200 independent audits, reached 94% and 93.5%. The final audit used a much larger sample and returned the lower figures reported above; its intent confidence interval crosses 93%, so the point estimate does not establish agreement above that threshold with 95% confidence.

The architecture uses OpenAI Decisions for initial classification, Nebius GLM-5.3-Flash for bounded fallback, grouping, and recommendations, and full GLM-5.3 for verification. The verifier sees original text without production answers, although its shared model family with fallback leaves correlated errors possible. Code handles validation, membership, arithmetic, spending limits, and checkpoints; exact-text reuse avoided repeating enrichment for 47,637 reviews while retaining their individual contributions. All selected records are accounted for, although 51,293 completed reviews retain a `needs_review` flag.

Operational improvements included compressed exports, indexed spending admission, measured enrichment concurrency, and a resident execution directory to recover from offloaded local files. When verifier latency increased, a tested timeout adjustment allowed the audit to resume from completed checkpoints and finish all 40,000 comparisons. A real interruption-and-resume recording, saved request outcomes, and separate synthetic failure checks document recovery behavior.

Inspection also exposed weaknesses that the next version should address. A confident Premium-restriction classification escaped fallback, showing that provider confidence needs calibration against observed errors. The generated memo incorrectly called usability the largest complaint-volume group, which prompted a factual editorial correction while preserving classifications and calculations. A fresh blind human sample, clearer topic and severity boundaries, and stronger checks on aggregate-backed narrative claims would therefore add more value than another unrestricted inference run.

## Evidence against the rubric

The [technical appendix](docs/hero-reproduction-and-evidence.md) provides reproducible commands, architecture details, and the complete evidence trail. The following index connects each rubric criterion to its supporting material.

| Criterion | Where to inspect the evidence |
|---|---|
| D1: Accessible code and setup | The [README](README.md), [locked dependencies](uv.lock), and [fresh installation evidence](evals/submission-readiness/) document a runnable project and credential-free reproduction. |
| D2: Architecture and provenance | The appendix, [prompts](prompts/), and [engine](src/spotify_pipeline/engine.py) explain separate roles, shared records, saved handoffs, and original source identities. |
| D3: Traceable numerical claims | The [memo](docs/hero-decision-memo.md) links its numbers to claim IDs, while the original archive contains membership, ranking, and claim tables. |
| D4: Recommendation and alternatives | The memo and [business audit](evals/hero/business-audit.md) explain the priority, competing options, and limits of example-based interventions. |
| T1: Human reference and error analysis | The [current report](evals/human-reference-v3/report.md) and [per-case comparisons](evals/human-reference-v3/) expose expected labels, predictions, differences, and documented reference provenance. |
| T2: Independent verification and adversarial checks | The archive contains all 40,000 audit comparisons, while [separate safety evidence](evals/submission-readiness/frozen-safety/) records injection, planted-error, and failure tests. |
| T3: Measured cost and recovery | The [calculator guide](cost/hero-replay.md), archived cold/warm measurements, and recovery recording support cost replay and interruption handling. |
| W1: Ingestion and classification coverage | The archive's ingestion report, selection manifest, and records account for the full source and every selected row. |
| W2: Runnable staged execution | The [supervisor](tools/run_hero.py), CLI, and [recovery notes](docs/hero-operational-recovery.md) document bounded requests, persisted stage outputs, and resume behavior. |
| W3: Ranking and deployed recommendations | The dashboard, [API](https://spotify-review-observatory.vercel.app/api/overview), and [database setup](web/README.md) expose the saved results, with all 87,897 issue memberships reconciled. |

The unchanged course checker returns `review_required` because 48 failed requests have 96 unavailable usage fields; all other source, coverage, cache, ranking, and claim checks pass. The evidence preserves those missing values and the corresponding uncertain-charge hold, alongside the separate publication decision that accepted this disclosed limitation.

## Submission materials

The [original hero archive](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-hero-evidence.zip) contains frozen run evidence, the [submission supplement](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-submission-supplement.zip) adds reproduction and safety checks, and the [current reference archive](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-course-reference-v3.zip) contains the completed golden comparison. Earlier artifacts remain available so changes can be inspected.

This 200,000-review cohort exceeds the assignment's amended 100,000-review minimum. Submit the [public repository URL](https://github.com/shahdevansh/spotify-review-pipeline) through the [course assignment form](https://bcourses.berkeley.edu/courses/1555592/assignments/9130940); publication of these materials does not confirm submission.
