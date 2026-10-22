import type { PilotAuditReport } from "../lib/evaluation-report";
import { humanReferenceCoverage, humanReferenceDisclosure, type HumanReferenceLink } from "../lib/human-reference";
import {
  comparisonMetricDisplay,
  confidencePresentation,
  formatRatio,
  humanBenchmarkSummary,
  legacyModelComparison,
  qualityPresentation,
  savedProjectSpending,
  utcTimestamp,
  type DisplayComparisonMetric,
} from "../lib/evaluation-view";

const count = (value: unknown) => typeof value === "number" && Number.isFinite(value)
  ? value.toLocaleString("en-US") : "Not published";
const money = (value: unknown) => typeof value === "number" && Number.isFinite(value)
  ? `$${value.toFixed(2)}` : "Not published";
const title = (value: string) => value.replace(/^issue-/, "").replaceAll("_", " ").replaceAll("-", " ");

// These published experiment counts are displayed only alongside the exact frozen
// hero identity below. The final hero row is always taken from the API response.
// Source report SHA-256: 0959c79087a5a99114a892d6651e7fd37639dde3365e7eeed05a76ea8c7db57c.
const pilotEvidence = "https://github.com/shahdevansh/spotify-review-pipeline/blob/b628b7410f5585c17ec6c9a49d021cc5e93d4560/evals/hero-pilot/report.md";
const experiments = [
  { name: "Lightning baseline", n: 200, topic: 156, intent: 179, severity: 160 },
  { name: "Decisions baseline", n: 200, topic: 179, intent: 185, severity: 176 },
  { name: "5% fallback", n: 200, topic: 178, intent: 186, severity: 177 },
  { name: "15% fallback · selected", n: 200, topic: 182, intent: 187, severity: 180 },
  { name: "Fresh 1,000-review confirmation", n: 200, topic: 188, intent: 187, severity: 182 },
];
const percentage = (value: number) => `${(value * 100).toFixed(2)}%`;

export function QualityGateNotice({
  report,
  legacyEvaluation = null,
  humanReference = null,
  compact = false,
}: {
  report: PilotAuditReport | null;
  legacyEvaluation?: unknown;
  humanReference?: HumanReferenceLink | null;
  compact?: boolean;
}) {
  const quality = qualityPresentation(report?.quality_gate || null, legacyEvaluation, humanReference);
  return (
    <div className={`quality-status-row quality-${quality.tone}`}>
      <strong>{quality.label}</strong>
      {compact ? <a className="text-button" href="#evaluation">View quality</a> : <p>{quality.summary}</p>}
    </div>
  );
}

export function CostSnapshotContext({ report, globalSpending = null }: { report: PilotAuditReport | null; globalSpending?: unknown }) {
  const saved = savedProjectSpending(globalSpending);
  const snapshot = report?.cost_snapshot;
  if (!snapshot && !saved) return <p>Project accounting is available in the release evidence.</p>;
  return (
    <dl className="cost-snapshot-grid">
      <div><dt>Recorded usage</dt><dd>{money(snapshot?.known_usd ?? saved?.spent)}</dd></div>
      <div><dt>Unknown-charge hold</dt><dd>{money(snapshot?.unknown_hold_usd ?? saved?.unknownHold)}</dd></div>
      <div><dt>Reserved</dt><dd>{money(snapshot?.reserved_usd ?? saved?.reserved)}</dd></div>
      <div><dt>Committed</dt><dd>{money(snapshot?.committed_usd ?? saved?.committed)}</dd></div>
    </dl>
  );
}

function ComparisonTable({ metrics }: { metrics: DisplayComparisonMetric[] }) {
  const hasInitial = metrics.some((metric) => metric.initial_value !== null && Number.isFinite(metric.initial_value));
  const hasDifference = metrics.some((metric) => metric.unit !== "fraction");
  return (
    <div className="table-scroll">
      <table className="comparison-table">
        <caption className="sr-only">Label agreement with independent model predictions</caption>
        <thead><tr><th scope="col">Label</th>{hasInitial && <th scope="col">Before fallback</th>}<th scope="col">{hasDifference ? "Result" : "Agreement"}</th><th scope="col">{hasDifference ? "Measurement basis" : "Matched / audited"}</th></tr></thead>
        <tbody>{metrics.map((metric) => {
          const initial = comparisonMetricDisplay(metric, "initial");
          const final = comparisonMetricDisplay(metric, "final");
          const value = metric.unit === "fraction" && typeof metric.final_value === "number" &&
            Number.isFinite(metric.final_value) && metric.denominator !== null && metric.denominator > 0
            ? percentage(metric.final_value) : final.value;
          const label = ["topic", "intent", "severity"].includes(metric.id)
            ? metric.id.charAt(0).toUpperCase() + metric.id.slice(1) : metric.label;
          return (
            <tr key={metric.id}>
              <th scope="row" className="quality-metric-name">{label}</th>
              {hasInitial && <td>{initial.value}</td>}
              <td><strong>{value}</strong></td>
              <td className="metric-denominator">{final.detail}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

function Outcome({ status }: { status: "passed" | "failed" | "not_available" }) {
  const tone = status === "passed" ? "pass" : status === "failed" ? "fail" : "unknown";
  return <span className={`outcome outcome-${tone}`}>{status === "passed" ? "Passed" : status === "failed" ? "Failed" : "Not available"}</span>;
}

export default function EvaluationPanel({
  report,
  legacyEvaluation,
  warning,
  humanReference = null,
}: {
  report: PilotAuditReport | null;
  legacyEvaluation: Record<string, unknown> | null;
  warning: string | null;
  humanReference?: HumanReferenceLink | null;
}) {
  const legacy = report ? null : legacyModelComparison(legacyEvaluation);
  const comparison = report?.model_comparison;
  const metrics = comparison?.status === "compared" ? comparison.metrics : legacy?.metrics || [];
  const audited = report?.coverage.compared ?? legacy?.verified ?? null;
  const disagreement = report?.model_comparison.disagreements.find((metric) => metric.id === "categorical_or_sentiment_gt_025");
  const human = humanBenchmarkSummary(report?.human || null);
  const disclosure = humanReference ? humanReferenceDisclosure(humanReference) : null;
  const completeGolden = humanReference?.golden_topic_labels === 50 && humanReference.golden_intent_labels === 50 &&
    humanReference.golden_severity_labels === 50 && humanReference.golden_sentiment_labels === 50;
  const publicationWarning = warning && !warning.startsWith("Versioned pilot-audit overlay not published or unavailable.");
  const frozenHero = legacy?.format === "hero_categorical" && legacy.verified === 40000 &&
    humanReference?.run_id === "run-07e2cb4b0e3d9be0" &&
    humanReference.label_config === "spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a" &&
    humanReference.source_sha256 === "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6" &&
    humanReference.prediction_sha256 === "8c23941a34abf7c09e279cb6dc49f0778638b25cc7e6a2a05f83b30daee4246c";
  const heroTargetsMet = (legacy?.metrics.find((metric) => metric.id === "topic")?.final_value ?? -1) > .90 &&
    (legacy?.metrics.find((metric) => metric.id === "intent")?.final_value ?? -1) > .93;

  return (
    <section id="evaluation" className="evaluation-section" aria-label="How we analyzed">
      {publicationWarning && <p className="evaluation-publication-warning" role="status">{warning}</p>}
      {report?.quality_gate.status === "hold" && <div className="quality-status-row quality-warning"><strong>Quality hold</strong><span>{report.quality_gate.summary}</span></div>}
      <div className="quality-main-grid">
        <article className="panel quality-card">
          <div className="quality-card-header"><h3>Model agreement</h3><span>{audited === null ? "Audit unavailable" : `${count(audited)} reviews audited`}</span></div>
          {metrics.length ? <ComparisonTable metrics={metrics} /> : <p className="quality-empty">Model comparison is unavailable for this run.</p>}
          {legacy?.finalDisagreements !== null && legacy?.finalDisagreements !== undefined && <div className="quality-status-row"><strong>{count(legacy.finalDisagreements)}</strong><span>{legacy.format === "hero_categorical" ? "reviews differ on topic, intent, or severity" : "reviews differ on a label or review flag"}</span></div>}
          {disagreement && <div className="quality-status-row"><strong>{count(disagreement.count)}</strong><span>{disagreement.label}</span></div>}
        </article>

        <article className="panel quality-card quality-reference-card">
          <div className="quality-card-header"><h3>Golden review set</h3></div>
          {humanReference ? <div className="quality-reference-body">
            <div className="quality-stat-value">{count(humanReference.golden_rows)}<span> reviews</span></div>
            <p>{completeGolden ? "Topic, intent, severity, and sentiment labels complete." : `Topic: ${count(humanReference.golden_topic_labels)}/50 · Intent: ${count(humanReference.golden_intent_labels)}/50 labeled.`}</p>
            <a className="text-button" href={humanReference.report_url} target="_blank" rel="noopener noreferrer">View agreement & cases ↗</a>
          </div> : <div className="quality-reference-body"><p>{human.label}</p>{human.planned !== null && <strong>{count(human.planned)} planned reviews</strong>}</div>}
        </article>
      </div>

      {frozenHero && <>
        <article className="panel quality-card">
          <div className="quality-card-header"><h3>Test runs</h3><a className="text-button" href={pilotEvidence} target="_blank" rel="noopener noreferrer">Experiment evidence ↗</a></div>
          <div className="table-scroll"><table className="experiment-table"><caption className="sr-only">Model agreement across development tests, fresh confirmation, and the final hero run</caption><thead><tr><th scope="col">Configuration</th><th scope="col">Audited</th><th scope="col">Topic</th><th scope="col">Intent</th><th scope="col">Severity</th></tr></thead><tbody>
            {experiments.map((experiment) => <tr key={experiment.name}><th scope="row">{experiment.name}</th><td>{count(experiment.n)}</td>{(["topic", "intent", "severity"] as const).map((field) => <td key={field} title={`${experiment[field]} / ${experiment.n} matches`}>{percentage(experiment[field] / experiment.n)}</td>)}</tr>)}
            <tr className="experiment-final"><th scope="row">200,000-review hero</th><td>{count(legacy!.verified)}</td>{["topic", "intent", "severity"].map((field) => { const metric = legacy!.metrics.find((entry) => entry.id === field); return <td key={field}>{metric?.final_value === null || metric?.final_value === undefined ? "Not published" : percentage(metric.final_value)}</td>; })}</tr>
          </tbody></table></div>
          <p className="experiment-cohort-note">The first four tests share 200 verifier judgments. Confirmation and hero audits use separate samples.</p>
        </article>
        <article className="panel quality-card">
          <div className="quality-card-header"><h3>Models & verification</h3></div>
          <div className="analysis-flow">
            <div className="analysis-step"><span>01 · Classify</span><strong>GPT-6 Luna</strong><p>OpenAI Decisions assigns the initial review labels.</p></div>
            <div className="analysis-step"><span>02 · Resolve & synthesize</span><strong>GLM-5.3 Flash</strong><p>Nebius handles uncertain reviews, issue descriptions, and recommendations.</p></div>
            <div className="analysis-step"><span>03 · Verify</span><strong>GLM-5.3</strong><p>Nebius independently checks a seeded 20% sample using original text and the same rubric.</p></div>
          </div>
          <dl className="analysis-criteria">
            <div><dt>Fallback</dt><dd>At most 15% of distinct texts, replacing the whole record after uncertainty-based routing.</dd></div>
            <div><dt>Agreement</dt><dd>Exact topic, intent, and severity matches. Verifier answers never replace production labels.</dd></div>
            <div><dt>Targets</dt><dd>Above 90% topic and 93% intent agreement. {heroTargetsMet ? "The hero point estimates meet both." : "The published results do not meet both targets."}</dd></div>
            <div><dt>Ranking</dt><dd>Complaint and cancellation reviews contribute their severity to each topic's priority score.</dd></div>
          </dl>
        </article>
      </>}

      <details className="quality-methods">
        <summary>Methods & checks</summary>
        <div className="quality-method-grid">
          <div>
            <h4>Independent comparison</h4>
            {comparison ? <p>{comparison.verifier_provider} · {comparison.verifier_model}. {comparison.answer_blind ? "The verifier received original text without enrichment answers." : "An answer-blind protocol is not established in this report."}</p> : <p>Agreement compares final labels with separately generated verifier labels from original review text.</p>}
            <p>Model agreement measures consistency between models. Shared model families can make similar mistakes, and routing signals are not calibrated correctness probabilities.</p>
            {legacy?.format === "hero_categorical" && <p>Disagreement means any topic, intent, or severity difference. Sentiment and review flags are excluded from this count.</p>}
            {legacy?.format === "legacy_flag_inclusive" && <p>Disagreement includes exact differences in topic, intent, severity, sentiment, or review flags; unavailable comparisons also count as differences.</p>}
            <dl className="evaluation-facts">{metrics.map((metric) => <div key={metric.id}><dt>{metric.label}</dt><dd>{metric.definition} Denominator: {count(metric.denominator)}.</dd></div>)}</dl>
            {comparison?.disagreements.map((metric) => <p key={metric.id}>{metric.label}: {formatRatio(metric.count, metric.denominator)}. {metric.definition}</p>)}
          </div>
          <div>
            <h4>Reference labels</h4>
            {humanReference ? <><p>{disclosure!.context}</p><p>{humanReferenceCoverage(humanReference)}</p><p>{count(humanReference.selected_reference_rows)} reference records are in this run. Each field uses its own annotated denominator.</p></> : <p>{report?.human.interpretation || "A matched golden reference has not been published for this run."}</p>}
            <p><a className="text-button" href="https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1" target="_blank" rel="noopener noreferrer">Download evaluation evidence ↗</a></p>
            {!report && warning && !publicationWarning && <p>The versioned pilot overlay is unavailable; this view uses the saved comparison and linked reference for the current run.</p>}
          </div>
        </div>

        {report && <>
          <div className="quality-method-grid">
            <div>
              <h4>Routing</h4>
              <dl className="evaluation-facts">
                <div><dt>Review flags, before / after</dt><dd>{count(report.routing.initial_flagged)} / {count(report.routing.final_flagged)}</dd></div>
                <div><dt>Fallback</dt><dd>{count(report.routing.fallback_count)} / {count(report.routing.unique_text_denominator)} distinct texts</dd></div>
                <div><dt>Fallback cap</dt><dd>{count(report.routing.fallback_cap)}</dd></div>
              </dl>
              <p>{confidencePresentation(report.routing.numeric_signal_available).detail}</p>
              <p>{report.routing.interpretation}</p>
            </div>
            <div>
              <h4>Source & structure <Outcome status={report.structural.status} /></h4>
              <dl className="evaluation-facts">{report.structural.checks.map((check) => <div key={check.id}><dt>{check.label}</dt><dd>{count(check.passed_count)} / {count(check.total)}</dd></div>)}</dl>
              <h4>Synthetic checks</h4>
              <dl className="evaluation-facts"><div><dt>Operational</dt><dd><Outcome status={report.synthetic.operational_status} /></dd></div><div><dt>Model behavior</dt><dd><Outcome status={report.synthetic.model_behavior_status} /></dd></div><div><dt>Saved overall result</dt><dd><Outcome status={report.synthetic.status} /></dd></div></dl>
              <p>{count(report.synthetic.case_count)} cases. {report.synthetic.scope}</p>
            </div>
          </div>
          <h4>Development inspection</h4>
          <div className="table-scroll"><table><thead><tr><th>Sample</th><th>Cases</th><th>Supported</th><th>Concerns</th><th>Ambiguous</th><th>Concerns flagged</th></tr></thead><tbody>{report.inspection.cohorts.map((cohort) => <tr key={cohort.id}><th scope="row">{cohort.label}</th><td>{count(cohort.count)}</td><td>{count(cohort.supported)}</td><td>{count(cohort.concerns)}</td><td>{count(cohort.ambiguous)}</td><td>{count(cohort.concerns_flagged)}</td></tr>)}</tbody></table></div>
          <p>{report.inspection.interpretation}</p>
          {report.ranking_sensitivity.status === "available" && <>
            <h4>Ranking sensitivity</h4>
            <div className="table-scroll"><table><caption className="sr-only">Final and verifier rankings on the same compared cohort</caption><thead><tr><th>Issue</th><th>Final rank</th><th>Final score</th><th>Verifier rank</th><th>Verifier score</th></tr></thead><tbody>{report.ranking_sensitivity.rows.map((row) => <tr key={row.issue_id}><th scope="row" className="issue-name">{title(row.issue_id)}</th><td>{count(row.final_rank)}</td><td>{count(row.final_score)}</td><td>{row.comparison_rank === null ? "Not ranked" : count(row.comparison_rank)}</td><td>{count(row.comparison_score)}</td></tr>)}</tbody></table></div>
            <p>{report.ranking_sensitivity.interpretation}</p>
          </>}
          <h4>Report identity</h4>
          <dl className="evaluation-facts">
            <div><dt>Report / generated</dt><dd>{report.report_id} · {utcTimestamp(report.generated_at)}</dd></div>
            <div><dt>Selected / completed</dt><dd>{count(report.coverage.selected)} / {count(report.coverage.completed)}</dd></div>
            <div><dt>Distinct texts / aliases</dt><dd>{count(report.coverage.unique_texts)} / {count(report.coverage.exact_text_aliases)}</dd></div>
            <div><dt>Configuration</dt><dd className="mono">{report.label_config}</dd></div>
            <div><dt>Records SHA-256</dt><dd className="mono">{report.records_sha256}</dd></div>
          </dl>
          <ul>{report.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>
          <a className="text-button" href={`/api/evaluation?run_id=${encodeURIComponent(report.run_id)}`} target="_blank" rel="noreferrer">View evaluation JSON ↗</a>
        </>}
      </details>
    </section>
  );
}
