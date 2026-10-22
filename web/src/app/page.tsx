"use client";

import { useEffect, useRef, useState } from "react";
import type { EvaluationResponse } from "../lib/evaluation-report";
import type { HumanReferenceLink } from "../lib/human-reference";
import { matchedEvaluation, publicPredictionProvenance, responseMatchesRun } from "../lib/evaluation-view";
import EvaluationPanel from "../components/evaluation-panel";
import { publishedProductPriorities } from "../lib/product-priorities";

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
  human_reference?: HumanReferenceLink | null;
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
    ? `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
const humanize = (value: string) =>
  value.replace(/^issue-/, "").replace(/[_-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
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

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <article className="metric"><p className="metric-label">{label}</p><p className="metric-value">{value}</p>{detail && <p className="metric-detail">{detail}</p>}</article>;
}

function ReviewCard({ review, onOpen }: { review: Review; onOpen: (id: string) => void }) {
  return <button className="review-card" onClick={() => onOpen(review.review_id)} aria-label={`Open ${humanize(review.intent || review.status)} review: ${review.review_text}`}>
    <span className="review-card-top"><span>{humanize(review.intent || review.status)}</span><span>Severity <b>{review.severity ?? "—"}</b><span className="text-muted"> / 5</span></span></span>
    <span className="review-excerpt">{review.review_text}</span>
  </button>;
}

type View = "priorities" | "recommendations" | "quality";
type SortMetric = "priority_score" | "complaint_count" | "mean_severity";
const views: { id: View; label: string }[] = [{ id: "priorities", label: "Priorities" }, { id: "recommendations", label: "Recommendations" }, { id: "quality", label: "How we analyzed" }];
const reviewPageSize = 8;
const firstSentence = (text: string) => text.split(/(?<=[.!?])\s+/)[0];
const claimLabel = (claim: Claim) => {
  const labels: Record<string, string> = { complaint_count: "reviews", count: "reviews", severity_sum: "severity total", priority_score: "priority", mean_severity: "mean severity" };
  const numericValue = typeof claim.value === "number" ? claim.value : /^-?\d+(\.\d+)?$/.test(claim.value) ? Number(claim.value) : null;
  const value = numericValue !== null && Number.isFinite(numericValue) ? numericValue.toLocaleString("en-US", { maximumFractionDigits: 2 }) : claim.value;
  return `${value} ${labels[claim.metric] || humanize(claim.metric).toLowerCase()}`;
};

export default function Dashboard() {
  const [exploring, setExploring] = useState(false);
  const explorerRef = useRef<HTMLDetailsElement>(null);
  const [view, setView] = useState<View>("priorities");
  const [sortMetric, setSortMetric] = useState<SortMetric>("priority_score");
  const [reviewQuery, setReviewQuery] = useState("");
  const [reviewPage, setReviewPage] = useState(0);
  const [reviewRetry, setReviewRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  const reviewGeneration = useRef(0);
  const morePending = useRef(false);
  const tabsRef = useRef<(HTMLButtonElement | null)[]>([]);
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
      if (controller.signal.aborted) return;
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
      if (!controller.signal.aborted && failure.name !== "AbortError") setError(failure.message || "The saved run could not be loaded.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [loadVersion]);

  useEffect(() => {
    const expectedRun = overview?.run;
    reviewGeneration.current += 1;
    morePending.current = false;
    setReviewPage(0);
    setReviewQuery("");
    if (!selectedIssue || !expectedRun) return;
    const controller = new AbortController();
    setReviews([]);
    setNextCursor(null);
    setReviewError(null);
    setReviewLoading(true);
    fetchJSON<ReviewPage>(`/api/issues/${encodeURIComponent(selectedIssue)}/reviews`, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        if (data.issue_id !== selectedIssue || !responseMatchesRun(data, expectedRun) ||
            (data.reviews || []).some((review) => !responseMatchesRun(review, expectedRun))) {
          throw new Error("A different run or configuration supplied these reviews. Refresh the dashboard to load matching evidence.");
        }
        setReviews(data.reviews || []);
        setNextCursor(data.next_cursor);
        if (data.status === "unavailable") setReviewError(data.message || "Review evidence is unavailable.");
      })
      .catch((failure) => {
        if (!controller.signal.aborted && failure.name !== "AbortError") setReviewError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setReviewLoading(false);
      });
    return () => controller.abort();
  }, [selectedIssue, loadVersion, reviewRetry, overview?.run?.run_id, overview?.run?.label_config]);

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
        if (controller.signal.aborted) return;
        if (expectedRun && (!responseMatchesRun(data, expectedRun) ||
            (data.review && !responseMatchesRun(data.review, expectedRun)))) {
          throw new Error("This review belongs to a different published run or configuration. Refresh the dashboard before inspecting it.");
        }
        setActiveReview(data.review);
        if (!data.review) setDetailError(data.message || "This review is not available in the saved run.");
      })
      .catch((failure) => {
        if (!controller.signal.aborted && failure.name !== "AbortError") setDetailError(failure.message);
      });
    return () => controller.abort();
  }, [activeReviewId, detailRetry, overview?.run?.run_id, overview?.run?.label_config]);

  async function loadMore() {
    const expectedRun = overview?.run;
    if (!selectedIssue || !nextCursor || reviewLoading || morePending.current || !expectedRun) return;
    const issueId = selectedIssue;
    const generation = reviewGeneration.current;
    morePending.current = true;
    const stillCurrent = () => reviewGeneration.current === generation && selectedRef.current === issueId &&
      runRef.current?.run_id === expectedRun.run_id &&
      runRef.current?.label_config === expectedRun.label_config;
    setReviewLoading(true);
    setReviewError(null);
    try {
      const data = await fetchJSON<ReviewPage>(`/api/issues/${encodeURIComponent(issueId)}/reviews?cursor=${encodeURIComponent(nextCursor)}`);
      if (!stillCurrent()) return;
      if (data.issue_id !== issueId || !responseMatchesRun(data, expectedRun) ||
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
      if (stillCurrent()) { morePending.current = false; setReviewLoading(false); }
    }
  }

  const ready = !loading && !error && overview?.status === "ready" && !!overview.run;
  const run = ready ? overview.run : null;
  const visibleIssues = ready ? issues : [];
  const selected = visibleIssues.find((issue) => issue.issue_id === selectedIssue);
  const orderedIssues = visibleIssues.slice().sort((a, b) => Number(b[sortMetric]) - Number(a[sortMetric]) || a.issue_id.localeCompare(b.issue_id));
  const maxScore = Math.max(1, ...visibleIssues.map((issue) => issue.priority_score));
  const productInsights = publishedProductPriorities(run, overview?.human_reference, visibleIssues);
  const complaintCount = visibleIssues.reduce((sum, issue) => sum + issue.complaint_count, 0);
  const evaluation = matchedEvaluation(evaluationResponse, run);
  const activeProvenance = publicPredictionProvenance(activeReview?.provenance);
  const filteredReviews = (ready ? reviews : []).filter((review) => review.review_text.toLocaleLowerCase().includes(reviewQuery.toLocaleLowerCase()));
  const totalReviewPages = Math.max(1, Math.ceil(filteredReviews.length / reviewPageSize));
  const currentReviewPage = Math.min(reviewPage, totalReviewPages - 1);
  const displayedReviews = filteredReviews.slice(currentReviewPage * reviewPageSize, (currentReviewPage + 1) * reviewPageSize);
  const limits = Array.from(new Set([...(run?.limitations || []), ...(recommendations?.limitations || [])]));

  function changeTab(event: React.KeyboardEvent, index: number) {
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % views.length;
    if (event.key === "ArrowLeft") next = (index + views.length - 1) % views.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = views.length - 1;
    if (next === null) return;
    event.preventDefault();
    setView(views[next].id);
    tabsRef.current[next]?.focus();
  }

  function exploreIssue(id: string) {
    setSelectedIssue(id);
    setReviewQuery("");
    setReviewPage(0);
    setView("priorities");
    setExploring(true);
    requestAnimationFrame(() => {
      explorerRef.current?.scrollIntoView({ block: "start", behavior: "instant" });
      explorerRef.current?.querySelector("summary")?.focus({ preventScroll: true });
    });
  }

  function productCards(detailed = false) {
    if (!productInsights) return null;
    const maxReviews = Math.max(...productInsights.priorities.map((item) => visibleIssues.find((issue) => issue.issue_id === item.issue_id)!.complaint_count));
    return <div className={`product-priorities ${detailed ? "product-priorities-detailed" : ""}`}>{productInsights.priorities.map((item, index) => {
      const issue = visibleIssues.find((candidate) => candidate.issue_id === item.issue_id)!;
      return <article className="product-priority" key={item.issue_id}>
        <div className="product-priority-category"><span>{String(index + 1).padStart(2, "0")}</span>{humanize(item.issue_id)}</div>
        <h2>{item.title}</h2>
        <p className="product-problem">{item.problem}</p>
        <dl className="product-metrics"><div><dt>Topic reviews</dt><dd>{count(issue.complaint_count)}</dd><div className="product-bar" aria-hidden="true"><span style={{ width: `${issue.complaint_count / maxReviews * 100}%` }} /></div></div><div><dt>Average severity</dt><dd>{Number(issue.mean_severity).toFixed(1)}<span> / 5</span></dd><div className="product-bar impact-bar" aria-hidden="true"><span style={{ width: `${Number(issue.mean_severity) / 5 * 100}%` }} /></div></div></dl>
        <p className="product-action"><strong>Recommended action</strong>{item.action}</p>
        {detailed && <p className="product-success"><strong>Measure success</strong>{item.success_measure}</p>}
        <div className="product-priority-actions"><button className="text-button" onClick={() => exploreIssue(item.issue_id)}>Explore reviews <Icon name="arrow" size={14} /></button><button className="text-button secondary" onClick={() => setActiveReviewId(item.evidence[0].review_id)}>See an example</button></div>
        {detailed && <details className="compact-details"><summary>Source examples</summary><div className="source-examples">{item.evidence.map((example) => <button key={example.review_id} onClick={() => setActiveReviewId(example.review_id)}><strong>{example.label}</strong><q>{example.quote}</q><span>Open original review ↗</span></button>)}</div></details>}
      </article>;
    })}</div>;
  }

  function recommendationCard(recommendation: Recommendation, index: number, alternative = false) {
    const claims = (recommendation.claim_ids || []).map((id) => overview?.claims.find((claim) => claim.claim_id === id)).filter((claim): claim is Claim => !!claim);
    return <article className="recommendation-card" key={`${recommendation.title}-${index}`}>
      <div className="recommendation-card-heading"><span className="recommendation-number">{String(index + 1).padStart(2, "0")}</span><h3>{recommendation.title}</h3></div>
      <div className="recommendation-metrics">{claims.slice(0, 4).map((claim) => <span key={claim.claim_id} className="metric-chip" title={`${humanize(claim.issue_id)} · ${humanize(claim.metric)}`}>{claimLabel(claim)}</span>)}</div>
      <p className="recommendation-preview">{firstSentence(recommendation.rationale)}</p>
      <div className="recommendation-actions">{(recommendation.issue_ids || []).map((id) => <button className="text-button" key={id} onClick={() => exploreIssue(id)}>{humanize(id)} reviews <Icon name="arrow" size={14} /></button>)}{(recommendation.review_ids || []).slice(0, 3).map((id, reviewIndex) => <button className="text-button secondary" key={id} onClick={() => setActiveReviewId(id)}>Example {reviewIndex + 1}</button>)}</div>
      <details className="compact-details"><summary>{alternative ? "Why this alternative" : "Full rationale"}</summary><p>{recommendation.rationale}</p></details>
    </article>;
  }

  return <>
    <a href="#main" className="skip-link">Skip to analysis</a>
    <header className="site-header">
      <a className="brand" href="#main"><span className="brand-icon"><Icon name="headphones" size={19} /></span><span>Spotify</span></a>
      <a className="header-link" href="https://github.com/shahdevansh/spotify-review-pipeline" target="_blank" rel="noreferrer">Project evidence <Icon name="arrow" size={15} /></a>
    </header>
    <main id="main" className="dashboard-shell">
      <div className="page-heading"><h1>Spotify review intelligence</h1>{productInsights && <span className="analysis-period">Google Play reviews · {productInsights.source_period.label}</span>}</div>
      {error && <div className="notice notice-error" role="alert"><div><strong>Unable to load results</strong><p>{error}</p></div><button className="button" onClick={() => setLoadVersion((version) => version + 1)}>Try again</button></div>}
      {!loading && !error && overview?.status !== "ready" && <div className="notice" role="status"><div><strong>No published results</strong><p>{overview?.message || "Check back after a run is published."}</p></div><button className="button" onClick={() => setLoadVersion((version) => version + 1)}>Refresh</button></div>}
      {loading && <p className="loading-message" role="status">Loading analysis…</p>}
      <section className="metrics-grid" aria-label="Analysis coverage">
        <Metric label="Reviews analyzed" value={count(run?.completed)} />
        <Metric label="Complaints & cancellations" value={ready ? count(complaintCount) : "—"} />

      </section>
      <div className="view-tabs" role="tablist" aria-label="Analysis views">{views.map((item, index) => <button key={item.id} ref={(element) => { tabsRef.current[index] = element; }} id={`tab-${item.id}`} role="tab" aria-selected={view === item.id} aria-controls={`view-${item.id}`} tabIndex={view === item.id ? 0 : -1} onClick={() => setView(item.id)} onKeyDown={(event) => changeTab(event, index)}>{item.label}</button>)}</div>

      <section id="view-priorities" role="tabpanel" aria-labelledby="tab-priorities" hidden={view !== "priorities"} tabIndex={0}>
        {productInsights && <><p className="priority-recommendation">{productInsights.recommendation}</p>{productCards()}</>}
        <details className="explore-details" ref={explorerRef} open={exploring || (ready && !productInsights)} onToggle={(event) => setExploring(event.currentTarget.open)}><summary>Explore all {visibleIssues.length || ""} topics & source reviews</summary>
        <div className="priority-layout">
          <section className="panel ranking-panel" aria-labelledby="ranking-title">
            <div className="panel-heading"><h2 id="ranking-title">Topic comparison</h2><label className="sort-control"><span>Sort by</span><select aria-label="Sort by" value={sortMetric} onChange={(event) => setSortMetric(event.target.value as SortMetric)}><option value="priority_score">Priority</option><option value="complaint_count">Review count</option><option value="mean_severity">Mean severity</option></select></label></div>
            <div className="table-scroll"><table className="ranking-table"><caption>Priority = sum of severity. Select a topic to explore its reviews.</caption><thead><tr><th scope="col">Topic</th><th scope="col" className="numeric">Reviews</th><th scope="col" className="numeric">Mean severity</th><th scope="col" className="numeric">Priority</th></tr></thead><tbody>{orderedIssues.map((issue) => <tr key={issue.issue_id} className={selectedIssue === issue.issue_id ? "selected" : ""} onClick={() => setSelectedIssue(issue.issue_id)}><th scope="row"><button className="topic-button" onClick={() => setSelectedIssue(issue.issue_id)} aria-pressed={selectedIssue === issue.issue_id} aria-label={`Show ${humanize(issue.issue_id)} reviews`}><span className="topic-indicator" />{humanize(issue.issue_id)}</button></th><td className="numeric">{count(issue.complaint_count)}</td><td className="numeric">{Number(issue.mean_severity).toFixed(2)}<span className="severity-denominator"> / 5</span></td><td className="numeric priority-cell"><span className="score-bar" style={{ width: `${Math.max(0, issue.priority_score / maxScore * 100)}%` }} /><strong>{count(issue.priority_score)}</strong></td></tr>)}</tbody></table></div>
            {!orderedIssues.length && <EmptyState title={loading ? "Loading priorities" : "No ranked issues"}>{loading ? "Reading saved results…" : "Ranked issues will appear after analysis is published."}</EmptyState>}
          </section>
          <section className="panel evidence-panel" aria-labelledby="evidence-title">
            <div className="panel-heading"><h2 id="evidence-title">{selected ? `${humanize(selected.issue_id)} reviews` : "Review explorer"}</h2><span className="subtle-label">{selected ? `${count(selected.complaint_count)} total` : ""}</span></div>
            <div className="review-toolbar"><label className="review-search"><Icon name="search" size={17} /><span className="sr-only">Search loaded reviews</span><input type="search" placeholder="Search loaded reviews" value={reviewQuery} onChange={(event) => { setReviewQuery(event.target.value); setReviewPage(0); }} /></label></div>
            <div className="review-list" aria-live="polite" aria-busy={reviewLoading}>
              {reviewError && <div className="inline-error" role="alert"><p>{reviewError}</p><button className="text-button" onClick={() => nextCursor ? loadMore() : setReviewRetry((value) => value + 1)}>Try again</button></div>}
              {displayedReviews.map((review) => <ReviewCard key={review.review_id} review={review} onOpen={setActiveReviewId} />)}
              {reviewLoading && <p className="loading-message" role="status">Loading reviews…</p>}
              {!reviewLoading && !displayedReviews.length && !reviewError && <EmptyState title={reviewQuery ? "No matching loaded reviews" : "No reviews available"} icon="search">{reviewQuery ? "Try another search or load more reviews." : "Select a topic to explore its reviews."}</EmptyState>}
            </div>
            <div className="review-pagination"><span>{filteredReviews.length ? `${currentReviewPage * reviewPageSize + 1}–${Math.min((currentReviewPage + 1) * reviewPageSize, filteredReviews.length)} of ${count(filteredReviews.length)}${reviewQuery ? " matches" : " loaded"}` : `${count(reviews.length)} loaded`}</span><div><button className="icon-button pagination-button" aria-label="Previous reviews" disabled={currentReviewPage === 0} onClick={() => setReviewPage((page) => Math.max(0, page - 1))}>‹</button><button className="icon-button pagination-button" aria-label="Next reviews" disabled={currentReviewPage + 1 >= totalReviewPages} onClick={() => setReviewPage((page) => page + 1)}>›</button></div>{nextCursor && <button className="text-button" onClick={loadMore} disabled={reviewLoading}>Load 50 more</button>}</div>
          </section>
        </div></details>
      </section>

      <section id="view-recommendations" role="tabpanel" aria-labelledby="tab-recommendations" hidden={view !== "recommendations"} tabIndex={0}>
        {ready && recommendations ? <>
          <div className="recommendation-heading"><h2>Next-quarter priorities</h2><a className="text-button" href="https://github.com/shahdevansh/spotify-review-pipeline/blob/main/docs/hero-decision-memo.md" target="_blank" rel="noreferrer">Read decision memo <Icon name="arrow" size={15} /></a></div>
          {productInsights ? productCards(true) : <div className="recommendation-grid">{recommendations.recommendations.map((recommendation, index) => recommendationCard(recommendation, index))}</div>}
          {!productInsights && recommendations.summary && <details className="compact-details recommendation-context"><summary>Decision summary</summary><p>{recommendations.summary}</p></details>}
          {!productInsights && !!recommendations.alternatives?.length && <details className="compact-details alternatives"><summary>Alternatives considered <span className="count-badge">{recommendations.alternatives.length}</span></summary><div className="alternative-grid">{recommendations.alternatives.map((alternative, index) => typeof alternative === "string" ? <p className="alternative" key={index}>{alternative}</p> : recommendationCard(alternative, index, true))}</div></details>}
        </> : <div className="panel"><EmptyState title={loading ? "Loading recommendations" : "No saved recommendations"}>Recommendations will appear once the analysis is published.</EmptyState></div>}
      </section>

      <section id="view-quality" role="tabpanel" aria-labelledby="tab-quality" hidden={view !== "quality"} tabIndex={0}>
        {view === "quality" && <EvaluationPanel report={evaluation.report} legacyEvaluation={ready ? overview.evaluation : null} humanReference={ready ? overview.human_reference : null} warning={loading ? null : evaluation.warning} />}
        <details className="run-details"><summary>Run details</summary>
          {productInsights && <p className="run-context">{productInsights.selection_reason} {productInsights.metric_note}</p>}
          <dl className="run-facts"><div><dt>Full source / analyzed</dt><dd>{count(overview?.source?.total_rows)} / {count(run?.completed)}</dd></div><div><dt>Estimated API cost for this run</dt><dd>{dollars(run?.api_cost_usd)}{run?.api_cost_complete === false ? " (incomplete)" : ""}</dd></div><div><dt>Distinct texts / saved results reused</dt><dd>{count(run?.unique_texts)} / {count(run?.cache_hits)}</dd></div><div><dt>Database</dt><dd>{bytes(overview?.storage?.bytes)}</dd></div></dl>
          {!!limits.length && <details className="compact-details"><summary>Scope & interpretation</summary><ul>{limits.map((limit, index) => <li key={index}>{limit}</li>)}</ul></details>}
          <div className="evidence-links"><a href="https://github.com/shahdevansh/spotify-review-pipeline" target="_blank" rel="noreferrer">Repository</a><a href="https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1" target="_blank" rel="noreferrer">Download evidence</a></div>
        </details>
      </section>
    </main>

    <dialog ref={dialogRef} className="review-dialog" aria-labelledby="review-dialog-title" onClose={() => setActiveReviewId(null)} onClick={(event) => { if (event.target === event.currentTarget) setActiveReviewId(null); }}>
      <div className="dialog-inner"><div className="dialog-heading"><h2 id="review-dialog-title">Review details</h2><button className="icon-button" aria-label="Close review details" onClick={() => setActiveReviewId(null)} autoFocus><Icon name="close" /></button></div>
        {detailError && <div className="inline-error" role="alert"><p>{detailError}</p><button className="text-button" onClick={() => setDetailRetry((value) => value + 1)}>Try again</button></div>}
        {!activeReview && !detailError && <p className="loading-message" role="status">Loading original review…</p>}
        {activeReview && <><blockquote className="detail-quote">{activeReview.review_text}</blockquote><div className="detail-tags"><span className="tag">{humanize(activeReview.topic || "unclassified")}</span><span className="tag">{humanize(activeReview.intent || activeReview.status)}</span>{activeReview.needs_review && <span className="flag">Flagged for review</span>}</div><dl className="detail-metrics"><div><dt>Severity</dt><dd>{activeReview.severity ?? "—"}<span> / 5</span></dd></div><div><dt>Sentiment</dt><dd>{activeReview.sentiment?.toFixed(2) ?? "—"}</dd></div><div><dt>Store rating</dt><dd>{activeReview.review_rating || "—"}<span> / 5</span></dd></div></dl>
          {activeReview.evidence_quote && activeReview.evidence_quote !== activeReview.review_text && <details className="compact-details"><summary>Selected evidence</summary><blockquote>{activeReview.evidence_quote}</blockquote></details>}
          <details className="compact-details source-details"><summary>Source & classification details</summary>
            {activeReview.provenance && <div className="prediction-provenance"><p>{activeProvenance.classifier || "Classifier not published"}</p><p>{activeProvenance.fallback}</p>{activeProvenance.reasons.length > 0 && <p>Routing: {activeProvenance.reasons.join("; ")}</p>}{activeProvenance.initial.length > 0 && <details className="compact-details"><summary>Initial labels</summary><dl>{activeProvenance.initial.map(([label, value]) => <div key={label}><dt>{humanize(label)}</dt><dd>{value}</dd></div>)}</dl></details>}</div>}
            <dl className="provenance-list"><div><dt>Review ID</dt><dd className="mono">{activeReview.review_id}</dd></div><div><dt>Date</dt><dd>{activeReview.review_timestamp || "—"}</dd></div><div><dt>App version</dt><dd>{activeReview.app_version || "—"}</dd></div><div><dt>Entities</dt><dd>{activeReview.entities?.length ? activeReview.entities.join(", ") : "None extracted"}</dd></div><div><dt>Configuration</dt><dd className="mono">{activeReview.label_config || "—"}</dd></div><div><dt>Source hash</dt><dd className="mono">{activeReview.source_sha256 || "—"}</dd></div><div><dt>Classification source</dt><dd>{activeReview.cache_source_id ? <button className="text-button mono" onClick={() => setActiveReviewId(activeReview.cache_source_id || null)}>{activeReview.cache_source_id}<Icon name="arrow" size={14} /></button> : "Original classification"}</dd></div></dl>
          </details>
        </>}
      </div>
    </dialog>
  </>;
}
