"use client";

import { useEffect, useRef, useState } from "react";
import { savedModelRoles } from "../lib/run-display";
import type { EvaluationResponse } from "../lib/evaluation-report";
import { matchedEvaluation, publicPredictionProvenance, responseMatchesRun } from "../lib/evaluation-view";
import EvaluationPanel, { CostSnapshotContext, QualityGateNotice } from "../components/evaluation-panel";

type Status = "ready" | "empty" | "unavailable";
type Envelope = { status: Status; message?: string; run_id?: string | null; label_config?: string | null };
type Claim = {
  claim_id: string;
  issue_id: string;
  metric: string;
  value: string | number;
};
type Run = {
  run_id: string;
  input_count: number;
  completed: number;
  quarantined: number;
  unique_texts: number;
  cache_hits: number;
  requests: number;
  attempts: number;
  api_cost_usd: number | null;
  api_cost_complete?: boolean;
  global_spending?: {
    spent_usd?: number;
    unknown_charge_hold_usd?: number;
    reserved_usd?: number;
  };
  wall_seconds: number | null;
  label_config: string;
  model_settings?: Record<string, unknown>;
  stages?: Record<string, unknown> | string[];
  limitations?: string[];
  created_at?: string;
};
type Overview = Envelope & {
  run: Run | null;
  source: {
    total_rows: number | null;
    nonempty_rows: number | null;
    empty_rows: number | null;
  } | null;
  evaluation: Record<string, unknown> | null;
  claims: Claim[];
  storage?: { bytes: number | null; projected_bytes_210k: number | null };
  scope?: string;
};
type Issue = {
  issue_id: string;
  name: string;
  description: string;
  rank: number;
  complaint_count: number;
  severity_sum: number;
  mean_severity: number | string;
  priority_score: number;
};
type Review = {
  review_id: string;
  review_text: string;
  review_rating: string;
  review_likes: string;
  app_version: string;
  review_timestamp: string;
  source_sha256: string;
  status: string;
  topic?: string;
  intent?: string;
  severity?: number;
  sentiment?: number;
  entities?: string[];
  evidence_quote?: string;
  needs_review?: boolean;
  label_config?: string;
  cache_source_id?: string | null;
  provenance?: Record<string, unknown> | null;
};
type Recommendation = {
  title: string;
  rationale: string;
  issue_ids?: string[];
  claim_ids?: string[];
  review_ids?: string[];
};
type RecommendationDocument = {
  summary: string;
  priority_issue_id: string | null;
  recommendations: Recommendation[];
  alternatives: (Recommendation | string)[];
  limitations: string[];
};
type ReviewPage = Envelope & {
  reviews: Review[];
  next_cursor: string | null;
  issue_id: string;
};
type IconName = "arrow" | "headphones" | "search" | "shield" | "close" | "check" | "database";

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    headphones: <><path d="M4 14v-3a8 8 0 0 1 16 0v3" /><rect x="3" y="12" width="5" height="9" rx="2" /><rect x="16" y="12" width="5" height="9" rx="2" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    check: <path d="m5 12 4 4L19 6" />,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

const count = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US")
    : "—";
const dollars = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 3 })}`
    : "—";
const percent = (numerator: number | undefined, denominator: number | undefined | null) =>
  numerator !== undefined && denominator && denominator > 0
    ? `${((numerator / denominator) * 100).toFixed(1)}%`
    : "—";
const humanize = (value: string) =>
  value.replace(/^issue-/, "").replace(/[_-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const duration = (seconds: number | undefined | null) => {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
};
const bytes = (value: number | undefined | null) =>
  typeof value === "number" ? `${(value / 1024 / 1024).toFixed(1)} MiB` : "Not reported";

async function fetchJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(30_000);
  const response = await fetch(url, {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    cache: "no-store",
  }).catch((failure) => {
    if (timeout.aborted && !signal?.aborted) {
      throw new Error("The data service took too long to respond. Please try again.");
    }
    throw failure;
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.message === "string") message = body.message;
    } catch {}
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function EmptyState({ title, children, icon = "database" }: {
  title: string;
  children: React.ReactNode;
  icon?: IconName;
}) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={25} /></span><h3>{title}</h3><p>{children}</p></div>;
}

function Metric({ label, value, detail, accent = false }: {
  label: string;
  value: string;
  detail: string;
  accent?: boolean;
}) {
  return <article className={`metric ${accent ? "metric-accent" : ""}`}><p className="metric-label">{label}</p><p className="metric-value">{value}</p><p className="metric-detail">{detail}</p></article>;
}

function ReviewCard({ review, onOpen }: { review: Review; onOpen: (id: string) => void }) {
  return (
    <article className="review-card">
      <div className="review-card-top">
        <span className="tag">{humanize(review.intent || review.status)}</span>
        <span className="review-severity">Severity <b>{review.severity ?? "—"}</b><span>/ 5</span></span>
      </div>
      <blockquote>{review.evidence_quote || review.review_text}</blockquote>
      <div className="review-card-bottom">
        <div className="review-flags">
          {review.needs_review && <span className="flag">Uncalibrated review flag</span>}
          {review.cache_source_id && <span className="text-muted">Exact-text reuse</span>}
          {!review.needs_review && !review.cache_source_id && <span className="text-muted">Original record</span>}
        </div>
        <button className="text-button" onClick={() => onOpen(review.review_id)}>Inspect source <Icon name="arrow" size={15} /></button>
      </div>
    </article>
  );
}

export default function Dashboard() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [evaluationResponse, setEvaluationResponse] = useState<EvaluationResponse | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);
  const [selectedIssue, setSelectedIssue] = useState<string | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<Review | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const selectedRef = useRef(selectedIssue);
  selectedRef.current = selectedIssue;
  const runRef = useRef(overview?.run);
  runRef.current = overview?.run;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setEvaluationResponse(null);
    Promise.all([
      fetchJSON<Overview>("/api/overview", controller.signal),
      fetchJSON<Envelope & { issues: Issue[] }>("/api/issues", controller.signal),
      fetchJSON<Envelope & { document: RecommendationDocument | null }>("/api/recommendations", controller.signal),
      fetchJSON<EvaluationResponse>("/api/evaluation", controller.signal).catch((failure) => {
        if (controller.signal.aborted) throw failure;
        return null;
      }),
    ]).then(([overviewData, issueData, recommendationData, evaluationData]) => {
      const identity = overviewData.run;
      if (identity && [issueData, recommendationData].some((data) => !responseMatchesRun(data, identity))) {
        throw new Error("The result responses belong to different saved runs. Refresh to load a consistent snapshot.");
      }
      setOverview(overviewData);
      setEvaluationResponse(evaluationData);
      const sorted = (issueData.issues || []).slice().sort((a, b) => a.rank - b.rank);
      setIssues(sorted);
      setRecommendations(recommendationData.document);
      setSelectedIssue((current) => sorted.some((issue) => issue.issue_id === current) ? current : sorted[0]?.issue_id || null);
    }).catch((failure) => {
      if (failure.name !== "AbortError") setError(failure.message || "The saved run could not be loaded.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [loadVersion]);

  useEffect(() => {
    const expectedRun = overview?.run;
    if (!selectedIssue || !expectedRun) return;
    const controller = new AbortController();
    setReviews([]);
    setNextCursor(null);
    setReviewError(null);
    setReviewLoading(true);
    fetchJSON<ReviewPage>(`/api/issues/${encodeURIComponent(selectedIssue)}/reviews`, controller.signal)
      .then((data) => {
        if (!responseMatchesRun(data, expectedRun) ||
            (data.reviews || []).some((review) => !responseMatchesRun(review, expectedRun))) {
          throw new Error("A different run or configuration supplied these reviews. Refresh the dashboard to load matching evidence.");
        }
        setReviews(data.reviews || []);
        setNextCursor(data.next_cursor);
        if (data.status === "unavailable") setReviewError(data.message || "Review evidence is unavailable.");
      })
      .catch((failure) => {
        if (failure.name !== "AbortError") setReviewError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setReviewLoading(false);
      });
    return () => controller.abort();
  }, [selectedIssue, loadVersion, overview?.run?.run_id, overview?.run?.label_config]);

  useEffect(() => {
    const expectedRun = overview?.run;
    if (!activeReviewId) {
      dialogRef.current?.close();
      return;
    }
    if (!dialogRef.current?.open) dialogRef.current?.showModal();
    const controller = new AbortController();
    setActiveReview(null);
    setDetailError(null);
    fetchJSON<Envelope & { review: Review | null }>(`/api/reviews/${encodeURIComponent(activeReviewId)}`, controller.signal)
      .then((data) => {
        if (expectedRun && (!responseMatchesRun(data, expectedRun) ||
            (data.review && !responseMatchesRun(data.review, expectedRun)))) {
          throw new Error("This review belongs to a different published run or configuration. Refresh the dashboard before inspecting it.");
        }
        setActiveReview(data.review);
        if (!data.review) setDetailError(data.message || "This review is not available in the saved run.");
      })
      .catch((failure) => {
        if (failure.name !== "AbortError") setDetailError(failure.message);
      });
    return () => controller.abort();
  }, [activeReviewId, overview?.run?.run_id, overview?.run?.label_config]);

  async function loadMore() {
    const expectedRun = overview?.run;
    if (!selectedIssue || !nextCursor || reviewLoading || !expectedRun) return;
    const issueId = selectedIssue;
    const stillCurrent = () => selectedRef.current === issueId &&
      runRef.current?.run_id === expectedRun.run_id &&
      runRef.current?.label_config === expectedRun.label_config;
    setReviewLoading(true);
    setReviewError(null);
    try {
      const data = await fetchJSON<ReviewPage>(`/api/issues/${encodeURIComponent(issueId)}/reviews?cursor=${encodeURIComponent(nextCursor)}`);
      if (!stillCurrent()) return;
      if (!responseMatchesRun(data, expectedRun) ||
          (data.reviews || []).some((review) => !responseMatchesRun(review, expectedRun))) {
        throw new Error("A different run or configuration supplied these reviews. Refresh the dashboard to continue.");
      }
      setReviews((previous) => {
        const seen = new Set(previous.map((review) => review.review_id));
        return [...previous, ...(data.reviews || []).filter((review) => !seen.has(review.review_id))];
      });
      setNextCursor(data.next_cursor);
    } catch (failure) {
      if (stillCurrent()) setReviewError(failure instanceof Error ? failure.message : "More reviews could not be loaded.");
    } finally {
      if (stillCurrent()) setReviewLoading(false);
    }
  }

  const run = overview?.run;
  const selected = issues.find((issue) => issue.issue_id === selectedIssue);
  const maxScore = Math.max(1, ...issues.map((issue) => issue.priority_score));
  const completedPercent = run?.input_count ? Math.min(100, (run.completed / run.input_count) * 100) : 0;
  const evaluation = matchedEvaluation(evaluationResponse, run);
  const activeProvenance = publicPredictionProvenance(activeReview?.provenance);
  const ready = !loading && !error && overview?.status === "ready" && !!run;
  const exactTextDuplicates = run?.stages && !Array.isArray(run.stages) && typeof run.stages.exact_text_aliases === "number"
    ? run.stages.exact_text_aliases : undefined;
  const scopeLabel = overview?.scope === "pilot" ? "Pilot run" : overview?.scope === "development" ? "Development run" : overview?.scope === "selected-cohort" ? "Selected cohort" : "Saved analysis";
  const statusLabel = loading ? "Loading saved run" : error ? "Connection unavailable" : ready ? scopeLabel : "Awaiting saved run";
  const limits = Array.from(new Set([...(run?.limitations || []), ...(recommendations?.limitations || [])]));
  const modelRoles = savedModelRoles(run?.model_settings);
  const roleLabels: Record<string, string> = { enrich: "Enrichment", fallback: "Escalation", verify: "Blind verification", group: "Issue descriptions", memo: "Recommendations" };

  return (
    <>
      <a href="#main" className="skip-link">Skip to analysis</a>
      <header className="site-header">
        <a className="brand" href="#main" aria-label="Listening Room home"><span className="brand-icon"><Icon name="headphones" size={23} /></span><span>Listening Room<span className="brand-subtitle">SPOTIFY REVIEW INTELLIGENCE</span></span></a>
        <nav aria-label="Main navigation"><a href="#priorities">Priorities</a><a href="#evaluation" className="evaluation-nav-link">Evaluation</a><a href="#recommendations">Recommendations</a><a href="#method">Method & evidence</a></nav>
        <div className="header-note"><span className="small-dot" /> Read-only analysis</div>
      </header>

      <main id="main" className="dashboard-shell">
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line" /> FROM REVIEWS TO PRODUCT DECISIONS</div><h1 id="page-title">Hear the signal.<br /><span>See the evidence.</span></h1><p>A transparent view of what listeners report, which issues rise to the top, and the evidence behind every recommendation.</p></div>
          <div className="run-panel">
            <div className="run-panel-top"><span className={`status-pill ${ready ? "is-ready" : ""}`}><span />{statusLabel}</span><span className="mono run-panel-label">RUN SNAPSHOT</span></div>
            <div className="run-panel-count">{count(run?.completed)}<span>reviews classified</span></div>
            <div className="completion-row"><span>Selected input processed</span><strong>{percent(run?.completed, run?.input_count)}</strong></div>
            <div className="progress-track" role="progressbar" aria-label="Selected reviews completed" aria-valuemin={0} aria-valuemax={100} aria-valuenow={run ? completedPercent : undefined}><div style={{ width: `${completedPercent}%` }} /></div>
            <p className="run-panel-foot">{run ? `${count(run.quarantined)} quarantined · ${count(Math.max(0, run.input_count - run.completed - run.quarantined))} remaining` : "Metrics appear when a real pipeline run is published."}</p>
          </div>
        </section>

        {error && <div className="notice notice-error" role="alert"><div><strong>We couldn’t load this run.</strong><p>{error}</p></div><button className="button button-small" onClick={() => setLoadVersion((version) => version + 1)}>Try again</button></div>}
        {!loading && !error && overview?.status !== "ready" && <div className="notice" role="status"><Icon name="database" /><div><strong>No results have been published yet.</strong><p>{overview?.message || "This dashboard displays saved pipeline results. No review counts or model outcomes are simulated."}</p></div><button className="text-button" onClick={() => setLoadVersion((version) => version + 1)}>Refresh <Icon name="arrow" size={16} /></button></div>}
        {loading && <p className="loading-message" role="status">Reading saved analysis…</p>}
        {ready && <QualityGateNotice report={evaluation.report} compact />}

        <section className="metrics-grid" aria-label="Run measurements">
          <Metric label="Selected input" value={count(run?.input_count)} detail="Records in this run’s analysis scope" accent />
          <Metric label="API usage · incremental this run" value={dollars(run?.api_cost_usd)} detail={run?.api_cost_complete === false ? "Nominal USD · incomplete; uncertain charges excluded" : "Nominal USD at saved rates · cash spend unverified"} />
          <Metric label="Exact-text duplicates" value={count(exactTextDuplicates)} detail={run ? `${count(run.unique_texts)} distinct texts · ${count(run.cache_hits)} saved results reused` : "Duplicates within this selected input"} />
          <Metric label="Pipeline wall time" value={duration(run?.wall_seconds)} detail={run ? `${count(run.requests)} requests · ${count(run.attempts)} attempts` : "Measured execution time"} />
        </section>
        {run && <div className="cost-context"><p>Earlier cached results add no new model usage to this run. Their original cost belongs to the earlier experiment.</p><CostSnapshotContext report={evaluation.report} /></div>}

        <section className="coverage-strip" aria-label="Source and analysis coverage">
          <div className="coverage-heading"><Icon name="database" size={19} /><span>Coverage at a glance</span></div>
          <div><strong>{count(overview?.source?.total_rows)}</strong><span>full-source rows</span></div><span className="coverage-arrow" aria-hidden="true">→</span>
          <div><strong>{count(run?.input_count)}</strong><span>selected for this run</span></div><span className="coverage-arrow" aria-hidden="true">→</span>
          <div><strong>{count(run?.completed)}</strong><span>classified records</span></div>
          <p>Full-source profiling and selected-cohort analysis are tracked separately.</p>
        </section>

        <section id="priorities" className="section-block" aria-labelledby="priorities-title">
          <div className="section-heading"><div><p className="eyebrow section-eyebrow">01 / LISTENER SIGNALS</p><h2 id="priorities-title">Where the friction lives</h2><p>Provisional ranking from model labels for complaint and cancellation reviews.</p></div><span className="formula-label"><span className="small-dot" /> Score = sum of model-assigned severity</span></div>
          <div className="priority-layout">
            <div className="panel ranking-panel">
              <div className="panel-heading"><h3>Provisional ranking from model labels</h3><span className="subtle-label">{issues.length ? `${issues.length} issues` : "Baseline method"}</span></div>
              {issues.length ? <div className="issue-list">{issues.map((issue) => <button key={issue.issue_id} className={`issue-row ${selectedIssue === issue.issue_id ? "selected" : ""}`} onClick={() => setSelectedIssue(issue.issue_id)} aria-pressed={selectedIssue === issue.issue_id} aria-label={`Show evidence for ${issue.name || humanize(issue.issue_id)}`}><span className="issue-rank">{String(issue.rank).padStart(2, "0")}</span><span className="issue-main"><span className="issue-title-row"><span className="issue-title">{issue.name || humanize(issue.issue_id)}</span><strong>{count(issue.priority_score)}</strong></span><span className="issue-bar"><span style={{ width: `${Math.max(0, (issue.priority_score / maxScore) * 100)}%` }} /></span><span className="issue-meta"><span>{count(issue.complaint_count)} reviews</span><span>{Number(issue.mean_severity).toFixed(2)} mean severity</span></span></span><span className="issue-arrow"><Icon name="arrow" size={17} /></span></button>)}</div> : <EmptyState title="The ranking starts with evidence">Issue scores will appear after classification and deterministic aggregation are complete.</EmptyState>}
              <div className="panel-foot"><Icon name="shield" size={15} /><span>Calculated from saved records. Ties resolve by issue ID.</span></div>
            </div>
            <div className="panel evidence-panel">
              <div className="panel-heading"><div><span className="evidence-kicker">REVIEW EXPLORER</span><h3>{selected?.name || "The voice behind the score"}</h3></div><span className="icon-box"><Icon name="search" /></span></div>
              {selected?.description && <p className="issue-description">{selected.description}</p>}
              <div className="evidence-scroll" aria-live="polite" aria-busy={reviewLoading}>
                {reviewError && <div className="inline-error" role="alert">{reviewError}</div>}
                {reviews.map((review) => <ReviewCard key={review.review_id} review={review} onOpen={setActiveReviewId} />)}
                {reviewLoading && <p className="loading-message" role="status">Loading review evidence…</p>}
                {!reviewLoading && !reviews.length && !reviewError && <EmptyState icon="search" title={selected ? "No review evidence available" : "Explore the original reviews"}>{selected ? "No matching evidence was returned for this issue." : "Choose a ranked issue to inspect original text, model labels, and record provenance."}</EmptyState>}
                {nextCursor && <button className="button load-more" onClick={loadMore} disabled={reviewLoading}>{reviewLoading ? "Loading…" : "Load more reviews"}<Icon name="arrow" size={16} /></button>}
              </div>
              <div className="panel-foot"><span>Original-text evidence in ID order, not a representative sample. No review flag does not establish correctness.</span></div>
            </div>
          </div>
        </section>

        <section id="recommendations" className="section-block" aria-labelledby="recommendations-title">
          <div className="section-heading"><div><p className="eyebrow section-eyebrow">02 / THE PRODUCT READOUT</p><h2 id="recommendations-title">What deserves attention next</h2><p>Saved AI recommendations, connected to measurable claims and source reviews.</p></div><span className="subtle-label">No live model calls</span></div>
          {ready && <QualityGateNotice report={evaluation.report} compact />}
          {recommendations ? <>
            {recommendations.summary && <div className="recommendation-summary"><span className="summary-marker"><Icon name="arrow" size={24} /></span><div><p className="eyebrow">THE READOUT</p><p>{recommendations.summary}</p></div></div>}
            <div className="recommendation-grid">{recommendations.recommendations.map((recommendation, index) => <article className="recommendation-card" key={`${recommendation.title}-${index}`}><div className="recommendation-number">{String(index + 1).padStart(2, "0")}</div><h3>{recommendation.title}</h3><p>{recommendation.rationale}</p><div className="recommendation-links">{(recommendation.claim_ids || []).map((id) => <a className="claim-link" key={id} href={`#claim-${id}`}>{id}<Icon name="arrow" size={12} /></a>)}{(recommendation.review_ids || []).slice(0, 3).map((id, reviewIndex) => <button className="claim-link review-link" key={id} onClick={() => setActiveReviewId(id)}>Review {reviewIndex + 1}<Icon name="arrow" size={12} /></button>)}</div></article>)}</div>
            {!!recommendations.alternatives?.length && <details className="alternatives"><summary>Alternatives considered <span>{recommendations.alternatives.length}</span></summary><div>{recommendations.alternatives.map((alternative, index) => <div key={index} className="alternative">{typeof alternative === "string" ? <p>{alternative}</p> : <><h4>{alternative.title}</h4><p>{alternative.rationale}</p></>}</div>)}</div></details>}
          </> : <div className="panel"><EmptyState icon="arrow" title="Recommendations follow the analysis">The recommendation stage will use ranked issues and a bounded evidence pack. Its saved conclusions will appear here.</EmptyState></div>}
        </section>

        <EvaluationPanel report={evaluation.report} legacyEvaluation={overview?.evaluation || null} warning={loading ? null : evaluation.warning} />

        <section id="method" className="section-block" aria-labelledby="method-title">
          <div className="section-heading"><div><p className="eyebrow section-eyebrow">04 / SHOW THE WORK</p><h2 id="method-title">Built to be checked</h2><p>Model judgments, numerical calculations, and human evaluation remain distinct.</p></div><Icon name="shield" size={26} /></div>
          <div className="method-grid method-grid-single">

            <article className="panel method-card"><div className="panel-heading"><h3>How this analysis works</h3><span className="tag">Reproducible</span></div><ol className="method-steps"><li><span>01</span><div><strong>Preserve & select</strong><p>Source fields stay intact. Seeded selection, row hashes, and a scope ledger establish coverage.</p></div></li><li><span>02</span><div><strong>Classify & verify</strong><p>The enrichment model assigns structured labels. A separate blind pass compares original texts; bounded escalation handles difficult cases. Saved model IDs and providers appear below.</p></div></li><li><span>03</span><div><strong>Group & rank</strong><p>Complaint and cancellation records form topic issues. Code sums severity and retains each original review.</p></div></li><li><span>04</span><div><strong>Recommend with evidence</strong><p>A separate model role receives aggregates and source examples. Every material claim can be traced.</p></div></li></ol></article>
          </div>
          {!!modelRoles.length && <div className="panel model-panel"><div className="panel-heading"><h3>Models in this saved configuration</h3><span className="subtle-label">Provider and model ID are recorded separately</span></div><div className="table-scroll"><table><caption className="sr-only">Saved model configuration by pipeline role</caption><thead><tr><th scope="col">Role</th><th scope="col">Provider</th><th scope="col">Model ID</th><th scope="col">Reasoning</th></tr></thead><tbody>{modelRoles.map((item) => <tr key={item.role}><th scope="row">{roleLabels[item.role] || humanize(item.role)}</th><td>{item.provider || "Not reported"}</td><td className="mono">{item.model}</td><td>{item.reasoning || "Not reported"}</td></tr>)}</tbody></table></div></div>}
          {!!limits.length && <div className="limitations"><h3>Limits of this run</h3><ul>{limits.map((limit, index) => <li key={index}>{limit}</li>)}</ul></div>}
          {!!overview?.claims?.length && <div className="panel claims-panel"><div className="panel-heading"><h3>Claim register</h3><span className="subtle-label">Saved calculation outputs</span></div><div className="table-scroll"><table><caption className="sr-only">Numerical claims cited by recommendations</caption><thead><tr><th scope="col">Claim</th><th scope="col">Issue</th><th scope="col">Metric</th><th scope="col">Value</th></tr></thead><tbody>{overview.claims.map((claim) => <tr id={`claim-${claim.claim_id}`} key={claim.claim_id}><th scope="row" className="mono">{claim.claim_id}</th><td>{humanize(claim.issue_id)}</td><td>{humanize(claim.metric)}</td><td className="numeric">{typeof claim.value === "number" ? claim.value.toLocaleString("en-US", { maximumFractionDigits: 6 }) : claim.value}</td></tr>)}</tbody></table></div></div>}
          <details className="run-details"><summary>Run details & provenance <span className="mono">{run?.run_id || "No run loaded"}</span></summary><dl><div><dt>Configuration fingerprint</dt><dd className="mono">{run?.label_config || "Not reported"}</dd></div><div><dt>Model settings</dt><dd>{run?.model_settings ? JSON.stringify(run.model_settings) : "Not reported"}</dd></div><div><dt>Full-source nonempty / empty</dt><dd>{count(overview?.source?.nonempty_rows)} / {count(overview?.source?.empty_rows)}</dd></div><div><dt>Database storage</dt><dd>{bytes(overview?.storage?.bytes)}</dd></div><div><dt>Projected storage at 210,000</dt><dd>{bytes(overview?.storage?.projected_bytes_210k)}</dd></div><div><dt>Published at</dt><dd>{run?.created_at || "Not reported"}</dd></div></dl></details>
        </section>

        <footer className="site-footer"><div><span className="footer-brand">Listening Room</span><p>Spotify review intelligence · Course research project</p></div><p>Source → classification → calculation → evidence<br /><span>Original reviews remain the source of truth.</span></p></footer>
      </main>

      <dialog ref={dialogRef} className="review-dialog" aria-labelledby="review-dialog-title" onClose={() => setActiveReviewId(null)} onClick={(event) => { if (event.target === event.currentTarget) setActiveReviewId(null); }}>
        <div className="dialog-inner">
          <div className="dialog-heading"><div><p className="eyebrow">ORIGINAL REVIEW</p><h2 id="review-dialog-title">Inspect the evidence</h2></div><button className="icon-button" aria-label="Close review details" onClick={() => setActiveReviewId(null)} autoFocus><Icon name="close" /></button></div>
          {detailError && <div className="inline-error" role="alert">{detailError}</div>}
          {!activeReview && !detailError && <p className="loading-message" role="status">Loading original record…</p>}
          {activeReview && <><blockquote className="detail-quote">{activeReview.review_text}</blockquote><div className="detail-tags"><span className="tag">{humanize(activeReview.topic || "unclassified")}</span><span className="tag">{humanize(activeReview.intent || activeReview.status)}</span>{activeReview.needs_review && <span className="flag">Uncalibrated review flag</span>}</div><dl className="detail-metrics"><div><dt>Severity</dt><dd>{activeReview.severity ?? "—"} <span>/ 5</span></dd></div><div><dt>Sentiment</dt><dd>{activeReview.sentiment?.toFixed(2) ?? "—"}</dd></div><div><dt>Original rating</dt><dd>{activeReview.review_rating || "—"}</dd></div></dl>{activeReview.evidence_quote && <div className="detail-evidence"><h3>Saved evidence quote</h3><p>{activeReview.evidence_quote}</p><span><Icon name={activeReview.review_text.includes(activeReview.evidence_quote) ? "check" : "close"} size={14} />{activeReview.review_text.includes(activeReview.evidence_quote) ? "Source integrity: exact substring" : "Source integrity: quote mismatch"}</span><p className="evaluation-note">Semantic support of the labels has not been established by this containment check.</p></div>}
          {activeReview.provenance && <div className="prediction-provenance"><h3>Prediction provenance</h3><p>{activeProvenance.classifier || "Classifier identity not published"}</p><p>{activeProvenance.fallback}</p>{activeProvenance.reasons.length > 0 && <p>Saved routing reason: {activeProvenance.reasons.join("; ")}</p>}{activeProvenance.initial.length > 0 && <details><summary>Initial labels before escalation</summary><dl>{activeProvenance.initial.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></details>}<p className="evaluation-note">No flag does not establish correctness. The public record does not provide a human semantic assessment.</p></div>}
          <dl className="provenance-list"><div><dt>Review ID</dt><dd className="mono">{activeReview.review_id}</dd></div><div><dt>Timestamp</dt><dd>{activeReview.review_timestamp || "Not supplied"}</dd></div><div><dt>App version</dt><dd>{activeReview.app_version || "Not supplied"}</dd></div><div><dt>Entities</dt><dd>{activeReview.entities?.length ? activeReview.entities.join(", ") : "None extracted"}</dd></div><div><dt>Label configuration</dt><dd className="mono">{activeReview.label_config || "Not supplied"}</dd></div><div><dt>Source SHA-256</dt><dd className="mono">{activeReview.source_sha256 || "Not supplied"}</dd></div><div><dt>Cache provenance</dt><dd>{activeReview.cache_source_id ? <button className="text-button mono" onClick={() => setActiveReviewId(activeReview.cache_source_id || null)}>{activeReview.cache_source_id}<Icon name="arrow" size={14} /></button> : "Original classification"}</dd></div></dl></>}
        </div>
      </dialog>
    </>
  );
}
