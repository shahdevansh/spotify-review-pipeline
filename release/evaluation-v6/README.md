# Public evaluation improvement — v6 overlay

This is an overlay for the Spotify review pipeline repository and the immutable
[v0.1.0 pilot release](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/v0.1.0-pilot). It does not replace that archive.

1. Obtain the repository source and `spotify-learning-1000.tar.gz` from v0.1.0.
2. Verify the old archive SHA-256 is `8675a22ee7008b0036f5e8226223a8ab65b16dfc14f6a745ff7248ccc3b988b8`.
3. Extract v0.1.0 and copy the contents of its `spotify-learning-1000/` directory
   into the repository root, preserving its pilot evidence.
4. Extract this archive and copy the contents of `spotify-evaluation-v6/` into the
   repository root. Current public code/docs overwrite earlier versions; original
   v5 records, grading, cost and recovery artifacts remain supplied by v0.1.0.
5. Verify this overlay with `python tools/package_evaluation.py verify --archive
   release/spotify-evaluation-v6.tar.gz`. Its internal inventory gives every
   public payload's size and SHA-256; it does not require credentials.

The completed business pipeline remains the 1,000-review pilot. The 210,000-review
target has not been executed. This overlay preserves development model trials,
synthetic/stress tests, stability/concurrency evidence, frozen trial implementation,
evaluation harness, public dashboard evaluation, and the blind human-evaluation kit.
Model agreement and synthetic tests are not human accuracy measurements.

Human evaluation contains the mandatory 50 and a separately sampled fresh 150
(200 total). These are distinct sampling designs; pooled metrics are descriptive,
not an unbiased full-corpus prevalence estimate. The published worksheets are blank.
The source-only prediction plan and a public aggregate/hash sealing receipt may
describe completed private inference; no sealed predictions or human answers are here.
Keep downloaded answers in an ignored private directory, and use the documented
explicit human-label attestation only after predictions/configuration are frozen.

Excluded: private/, real answers, sealed prediction values, .env/credentials,
databases/caches, node_modules/.next, the full raw source and selected 210k input.
No private directory is traversed by the packager. Known credential values from
process environment and the repository .env are used only for an in-memory scan;
scan failures reveal filenames, never credential values. No provider calls, database
queries, uploads or Git operations occur during packaging.

On macOS the snapshot uses native APFS clones to avoid observed FileProvider read
stalls. Originals are untouched. Path/symlink/size guards apply; metadata transitions
are accepted only when independent captures have identical bytes. The external
manifest records the actual snapshot method and transition count.
