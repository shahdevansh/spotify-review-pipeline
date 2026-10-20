-- Only the importer writes. Public routes use read-only transactions.
CREATE TABLE IF NOT EXISTS spotify_runs (
    run_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    imported_at timestamptz NOT NULL DEFAULT now(),
    is_current boolean NOT NULL DEFAULT false,
    summary jsonb NOT NULL,
    source_profile jsonb,
    evaluation jsonb,
    imported_rows integer NOT NULL CHECK (imported_rows >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS spotify_one_current_run
    ON spotify_runs (is_current) WHERE is_current;

CREATE TABLE IF NOT EXISTS spotify_reviews (
    run_id text NOT NULL REFERENCES spotify_runs(run_id) ON DELETE CASCADE,
    review_id text NOT NULL,
    review_text text NOT NULL,
    review_rating text NOT NULL,
    review_likes text NOT NULL,
    app_version text NOT NULL,
    review_timestamp text NOT NULL,
    source_sha256 text NOT NULL,
    status text NOT NULL,
    reason text,
    topic text,
    intent text,
    sentiment double precision CHECK (sentiment BETWEEN -1 AND 1),
    severity smallint CHECK (severity BETWEEN 1 AND 5),
    entities jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidence_quote text,
    needs_review boolean,
    label_config text,
    cache_source_id text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, review_id)
);
CREATE INDEX IF NOT EXISTS spotify_reviews_status ON spotify_reviews(run_id, status);

CREATE TABLE IF NOT EXISTS spotify_issues (
    run_id text NOT NULL REFERENCES spotify_runs(run_id) ON DELETE CASCADE,
    issue_id text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    rank integer NOT NULL CHECK (rank > 0),
    complaint_count integer NOT NULL CHECK (complaint_count >= 0),
    severity_sum integer NOT NULL CHECK (severity_sum >= 0),
    mean_severity numeric(12,6) NOT NULL,
    priority_score bigint NOT NULL,
    PRIMARY KEY (run_id, issue_id),
    UNIQUE (run_id, rank)
);

CREATE TABLE IF NOT EXISTS spotify_membership (
    run_id text NOT NULL,
    issue_id text NOT NULL,
    review_id text NOT NULL,
    PRIMARY KEY (run_id, review_id),
    FOREIGN KEY (run_id, issue_id) REFERENCES spotify_issues(run_id, issue_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, review_id) REFERENCES spotify_reviews(run_id, review_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS spotify_membership_cursor
    ON spotify_membership(run_id, issue_id, review_id COLLATE "C");

CREATE TABLE IF NOT EXISTS spotify_claims (
    run_id text NOT NULL REFERENCES spotify_runs(run_id) ON DELETE CASCADE,
    claim_id text NOT NULL,
    issue_id text,
    metric text NOT NULL,
    value text NOT NULL,
    PRIMARY KEY (run_id, claim_id)
);

CREATE TABLE IF NOT EXISTS spotify_recommendations (
    run_id text PRIMARY KEY REFERENCES spotify_runs(run_id) ON DELETE CASCADE,
    document jsonb NOT NULL
);
