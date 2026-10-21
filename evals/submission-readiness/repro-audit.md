# Independent submission reproducibility and accessibility audit

Checked October 21, 2026. This is an offline/read-only audit of the published submission, using committed main `f135fe5b8b22da06cbe9075414909ded94b13289` and hero-v1 ZIP SHA `950fe1f6fcb1b53a3cc6ce634b071411669b930e5aba05f0c623ea871947049d`. No model calls, label changes, source changes, deployment, or repository mutations were made.

## Outcome

**High confidence:** a fresh locked Python installation, credential-free hero cost replay, and full saved-result reranking work. Public entrypoints respond anonymously. The final saved analysis outputs are accessible in the release, rather than repository-root historical grading/cost folders.

**Material outstanding evaluation deliverable:** the assignment explicitly requests the human-labeled golden set, expected labels, predictions, and per-case results. The public report currently provides only aggregates and intentionally excludes all individual labels and IDs. This is a substantive artifact-availability gap in addition to the three missing golden topic/intent annotations. Prepare a minimal grader-only export without private notes and obtain explicit sharing authorization; do not infer labels, publish private worksheets silently, or change predictions. Golden severity/sentiment/entity fields remain sparsely annotated and should be disclosed rather than filled by a model.

## Actual fresh-environment verification

A committed-source export was installed in `/private/tmp/spotify-submission-clean-20261021`, outside iCloud, using the exact documented command:

```sh
uv sync --frozen --extra dev --link-mode copy
```

It created a NEW `.venv` with CPython 3.13.11 and installed all 21 locked packages including the editable pipeline. There was no `PYTHONPATH` override. The full install log is `fresh-resident-install.log`.

The README calculator call was executed twice with the final release's cold/warm paths and explicit hero projection parameters. API/database credentials were unset; `socket.create_connection` and `socket.socket.connect` were replaced with a function that raises, so network access would fail. Both passed:

| Measurement | Cold | Warm |
|---|---:|---:|
| Completed fixed input reviews | 100 | 100 |
| Attempts | 105 | 0 |
| Repriced API subtotal | $0.02360475 | $0 |
| Preserved measured seconds | 41.90341787500074 | 0.2137402079970343 |
| Result cache hits | 0 | 100 |

The deterministic `spotify-pipeline rerank --run work/hero-rerank` command was invoked through the installed CLI entry function, with the same arguments as the README and connection blocking still active. It consumed the release's `records.jsonl.gz` and `membership.csv`. New `ranking.csv` and `claims.csv` matched the released bytes exactly:

- ranking SHA256: `9e0952b616c37faf297cf977c2ec5a881c20a495205d9562c5dd0097b6299f27`
- claims SHA256: `1fe408f1e7da701f8b2595962a4e20a747272b712b40427c26fd403e1f860dd5`

Proof: `fresh-resident-repro.json`. The recorded 6.668-second timer includes reranking and both replays; it is not model runtime. The CLI currently prints the entire 87,897-row membership, so a grader should redirect stdout to `work/hero-rerank/replay.log` to avoid an approximately 8 MB terminal dump. This is usability friction, not an arithmetic failure.

An initial fresh install in the Documents/iCloud work directory succeeded and its first calculator replay passed. Subsequent fresh interpreter starts omitted the editable `.pth` path despite the file bytes and target existing; exact-file hydration did not fix it. The identical clean install in resident `/private/tmp` passed without adjustments. This is evidence of an environment/location-dependent import problem; the precise filesystem mechanism was not established. Do not describe the initial failed import as a pipeline logic error or silently substitute a `PYTHONPATH` workaround.

## Fixed-100 identity supplement prepared

The hero report has `measurements.input_sha256: null`, and its saved run summary has `input_path: null`. Both are preserved. All 100 result IDs and source-row hashes were nevertheless validated against the public repository's byte-identical instructor `cost_100.csv` and its original course manifest:

- input bytes: 15,466
- input SHA256: `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e`
- exact manifest byte/checksum match
- exactly 100 unique input IDs
- both cold and warm contain exactly those 100 IDs, no extras/missing/duplicates, all completed
- all 100 source-row hashes match the shared course row-hash implementation
- cold/warm record exports byte-identical (SHA `d693d94357af52ace49be2e4d225c7a95945124d99931028f8421bfbcee0caec`)
- 105 cold call rows; zero warm call rows

Publish `hero-cost-source-validation.json` as a **post-run validation sidecar**. It contains all IDs/hashes/status checks and avoids inventing historical runtime metadata. Existing reports and measurements remain unchanged. The source input itself is already public at `cost/measured-100/source/cost_100.csv`; the hero ZIP does not contain a source CSV.

## Public access and release layout

All seven anonymous HTTP GET checks passed with 200: current README, pyproject, GitHub public release metadata, live `/api/overview`, publication receipt, cost README, and grading README. Proof: `readonly-access-check.json`; the exact fetched contents are retained beside it. No auth header or API key was used. The release metadata remains public. The local previously downloaded final ZIP was rehashed to the published checksum and inspected: 118 members. `archive-member-audit.json` records the complete inventory.

Required final grading files are present, including gzip records/calls permitted by the live assignment and the unmodified checker. The checker explicitly handles gzip. The ZIP contains root `cost/`, `cost/warm100/`, role handoffs, independent evaluation, human aggregates, and recovery evidence. The real resume proof is accessible at `recovery.cast`, with `recovery/recovery-validation.json`, before/after checkpoints, calls, configuration, and summary. The recovery receipt shows 10 completed before, 40 after, no completed ID reprocessing, and a real separate-process restart. No change to that proof was necessary.

The source-generation/checker commands were not rerun because prior byte-exact selection proof is unchanged. Prior proof `work/hero-release-replay-validation/selection-validation.json` and immutable release validation establish exact regeneration from the full source; this audit independently revalidated the code and current public archive and does not claim a new 660,622-row source read.

## Grader entrypoint improvements recommended before submission

1. Add a compact **Start here / grader steps** near the top of README: live dashboard; final ZIP; fixed input validation; cost replay; rerank with stdout redirection; human-reference export/access link and limitations. The existing README contains the information but is almost 40 KB.
2. Preserve the clear historical banners in repository-root `grading/` and `cost/`. Add a direct current-cost link instead of expecting graders to follow an old experiment README. Final ZIP `cost/` is current; repository `cost/measured-100` is historical v5.
3. Publish the new fresh-install/replay/rerank receipt and fixed-input validation sidecar without replacing frozen measurements.
4. Resolve grader access to the individual expected-label/prediction comparisons and complete the three outstanding human labels if the user supplies them. These are substantive evaluation gaps; more model runs do not address them.
5. Keep the original `review_required` checker result visible: 48 failed requests have unknown usage. Do not make up zeros or imply a full checker pass.
6. Submit the public repository URL through the actual course portal; repository publication alone does not submit.

## Assignment ambiguity

The live document now explicitly accepts at least 100,000 classified nonempty reviews in its deliverable list and definition of done, so 200,000 satisfies that stated amended threshold. Its coverage formula and several copied workflow paragraphs still refer to all 660,622 rows. Preserve both the amendment and declared subset scope; do not guarantee a numeric rubric score or spend more to compensate for ambiguous prose. The assignment expressly has no accuracy minimum, provider requirement, or spending bonus.

## Additional executable-entrypoint and web setup findings

At audited commit `f135fe5b8b22da06cbe9075414909ded94b13289`, the documented arbitrary-input hero command had a provider admission defect: CLI `_require_paid` accepted jev/openai/nebius but omitted Decisions, although the engine and actual supervisor supported Decisions. A no-network regression reproduced `Unsupported provider; no calls made.` with fake valid credential availability. This did not alter the completed hero inference, whose supervisor bypassed the stale CLI guard.

A two-line CLI-only repair adds Decisions to the allowlist and maps it to `OPENAI_API_KEY`, the actual provider credential. Eleven offline regression cases passed, covering frozen hero acceptance, both missing keys, paid-flag protection, unknown roles/providers, existing provider mappings, and the engine enrichment-only constraint. An actual installed CLI invocation without credentials then correctly reported missing OpenAI/Nebius keys and created no run/database. No model call, prompt, engine, dataset, prediction, or frozen configuration changed. The repair was prepared separately for parent integration; this report alone does not prove a later GitHub commit. See `hero-cli-guard-reproduction.json` and `cli-decisions-credentials-repair.json`.

The audited web README also retained legacy pilot paths and a command for untracked `web/scripts/publish_evaluation.py`. The importer, SQL schema and read-only role instructions exist, but hero-specific saved-artifact import instructions and removal/labeling of the obsolete command are needed. A separate documentation repair is being integrated. These reproducibility issues are in addition to, and do not erase, the human-label availability gaps.
