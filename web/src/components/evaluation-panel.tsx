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
  ? `$${value.toFixed(6)}` : "Not published";
const title = (value: string) => value.replace(/^issue-/, "").replaceAll("_", " ").replaceAll("-", " ");

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
    <div className={`quality-notice quality-${quality.tone}`} role="status">
      <div>
        <strong>{quality.label}{quality.provisional ? " · Recommendations provisional" : ""}</strong>
        <p>{quality.summary}</p>
        {!compact && !!report?.quality_gate.reasons.length && (
          <ul>{report.quality_gate.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
        )}
        <p className="quality-scope">Processing completion and API availability are separate from this quality decision.</p>
      </div>
      {compact && <a className="text-button" href="#evaluation">View evaluation →</a>}
    </div>
  );
}

export function CostSnapshotContext({ report, globalSpending = null }: { report: PilotAuditReport | null; globalSpending?: unknown }) {
  if (!report) {
    const snapshot = savedProjectSpending(globalSpending);
    return snapshot ? <>
      <p><strong>Project ledger at saved run snapshot</strong></p>
      <dl className="cost-snapshot-grid">
        <div><dt>Recorded nominal usage</dt><dd>{money(snapshot.spent)}</dd></div>
        <div><dt>Unknown-charge hold</dt><dd>{money(snapshot.unknownHold)}</dd></div>
        <div><dt>In-flight reservations</dt><dd>{money(snapshot.reserved)}</dd></div>
        <div><dt>Committed total</dt><dd>{money(snapshot.committed)}</dd></div>
      </dl>
      <p>Saved project-wide accounting includes other experiments and uncertain-charge holds. These are nominal usage estimates at the saved snapshot, not a current provider balance or reconciled cash bill.</p>
    </> : <p>Project ledger amounts are not available in this API response. Consult the final release evidence for project accounting. The saved-run amount above is separate from full-project totals.</p>;
  }
  const snapshot = report.cost_snapshot;
  return (
    <>
      <p><strong>Project ledger snapshot as of {utcTimestamp(snapshot.as_of)}</strong></p>
      <dl className="cost-snapshot-grid">
        <div><dt>Known nominal usage</dt><dd>{money(snapshot.known_usd)}</dd></div>
        <div><dt>Unknown-charge hold</dt><dd>{money(snapshot.unknown_hold_usd)}</dd></div>
        <div><dt>In-flight reservations</dt><dd>{money(snapshot.reserved_usd)}</dd></div>
        <div><dt>Committed total</dt><dd>{money(snapshot.committed_usd)}</dd></div>
      </dl>
      <p>{count(snapshot.attempts)} attempts at this snapshot. Experiment-level coverage is not supplied by this report; later activity is not represented. Nominal usage repricing is not a reconciled cash payment or provider credit balance.</p>
    </>
  );
}

function ComparisonTable({ metrics }: { metrics: DisplayComparisonMetric[] }) {
  return (
    <div className="table-scroll">
      <table className="comparison-table">
        <caption className="sr-only">Initial and final labels compared with independent model predictions</caption>
        <thead><tr><th scope="col">Model comparison metric</th><th scope="col">Initial labels</th><th scope="col">Final labels</th></tr></thead>
        <tbody>{metrics.map((metric) => {
          const initial = comparisonMetricDisplay(metric, "initial");
          const final = comparisonMetricDisplay(metric, "final");
          return (
            <tr key={metric.id}>
              <th scope="row"><strong>{metric.label}</strong><details className="metric-definition"><summary>Definition & denominator</summary><p>{metric.definition}</p><p>Declared denominator: {metric.denominator === null ? "not published" : `${count(metric.denominator)} original review IDs`}.</p></details></th>
              <td><strong>{initial.value}</strong><span className="metric-denominator">{initial.detail}</span></td>
              <td><strong>{final.value}</strong><span className="metric-denominator">{final.detail}</span></td>
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
  const human = humanBenchmarkSummary(report?.human || null);
  const humanDisclosure = humanReference ? humanReferenceDisclosure(humanReference) : null;
  const legacy = report ? null : legacyModelComparison(legacyEvaluation);
  const comparison = report?.model_comparison;
  const confidence = confidencePresentation(report?.routing.numeric_signal_available ?? null);
  const operational = (id: string) => id === "categorical_or_sentiment_gt_025";
  const disagreements = report?.model_comparison.disagreements.slice().sort((a, b) =>
    Number(operational(b.id)) - Number(operational(a.id))) || [];

  return (
    <section id="evaluation" className="section-block evaluation-section" aria-labelledby="evaluation-title">
      <div className="section-heading">
        <div><p className="eyebrow section-eyebrow">03 / EVALUATION</p><h2 id="evaluation-title">What has actually been established</h2><p>Human labels, model comparisons, development inspection, and integrity checks answer different questions.</p></div>
        <span className="subtle-label">{report ? "Versioned, run-matched report" : legacy ? "Saved model comparison available" : "Evaluation report not published"}</span>
      </div>
      <QualityGateNotice report={report} legacyEvaluation={legacyEvaluation} humanReference={humanReference} />
      {warning && <p className="evaluation-publication-warning" role="status">{warning}</p>}
      {report && <p className="evaluation-identity"><span className="mono">{report.report_id}</span><span>Generated {utcTimestamp(report.generated_at)}</span><span>Run <span className="mono">{report.run_id}</span></span></p>}

      {humanReference ? <article className="panel evaluation-card">
        <div className="panel-heading"><h3>{humanDisclosure!.heading}</h3><span className="outcome outcome-unknown">{humanDisclosure!.badge}</span></div>
        <div className="evaluation-card-body">
          <p className="evaluation-lead">Agreement with the versioned reference is published separately. <strong>This is not blind population accuracy.</strong></p>
          <p>{humanDisclosure!.context}</p>
          <p>{humanReferenceCoverage(humanReference)}</p>
          <p>{count(humanReference.selected_reference_rows)} worksheet records are inside the selected hero cohort. {humanDisclosure!.scope}</p>
          <p><a className="text-button" href={humanReference.report_url} target="_blank" rel="noopener noreferrer">Read the verified reference evaluation →</a></p>
          <p className="evaluation-note">{humanDisclosure!.note}</p>
        </div>
      </article> : <article className="panel evaluation-card">
        <div className="panel-heading"><h3>Human benchmark</h3><span className="outcome outcome-unknown">{human.label}</span></div>
        <div className="evaluation-card-body">
          <p className="evaluation-lead">Accuracy against human labels: <strong>{human.metric.toLowerCase()}.</strong></p>
          {report ? <>
            <div className="human-cohorts">{report.human.cohorts.map((cohort) => <div key={cohort.id}><strong>{count(cohort.expected_count)} planned reviews</strong><h4>{cohort.label}</h4><span className="tag">Labels pending</span><p>{cohort.sampling_note}</p></div>)}</div>
            <p>{report.human.interpretation}</p>
          </> : <p>Human label counts and results are not published in a matched versioned report. Model agreement cannot substitute for human accuracy.</p>}
          <p className="evaluation-note">No human answer rows are exposed here. Pending labels are not zero errors, and no accuracy score has been inferred.</p>
        </div>
      </article>}

      <article className="panel evaluation-card">
        <div className="panel-heading"><h3>Blind model comparison</h3><span className="tag">Agreement, not accuracy</span></div>
        <div className="evaluation-card-body">
          {comparison ? <>
            <p>Verifier: <strong>{comparison.verifier_provider} · {comparison.verifier_model}</strong>. Answer-blind protocol: <strong>{comparison.answer_blind ? "reported" : "not established"}</strong>. {count(report?.coverage.compared)} original review IDs compared.</p>
            {comparison.shared_fallback_verifier_model && <p className="evaluation-caution">Escalation and verification use the same model, {comparison.verifier_model}. Their errors may be correlated; increased agreement after escalation does not establish increased accuracy.</p>}
          </> : legacy ? <p>{legacy.format === "hero_categorical" ? "Compact saved model comparison" : "Legacy saved comparison"}: {count(legacy.verified)} returned verifier entries; {count(legacy.comparable)} comparable completed reviews. {legacy.format === "hero_categorical" ? <>Methodology and the saved quality decision are in the <a href="https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1" target="_blank" rel="noopener noreferrer">published hero evidence</a>.</> : "A versioned definition and quality decision have not been published."}</p> : <p>No recognized model comparison has been published for this run.</p>}
        </div>
        {comparison?.status === "compared" ? <ComparisonTable metrics={comparison.metrics} /> : legacy ? <ComparisonTable metrics={legacy.metrics} /> : <p className="evaluation-empty">No model-comparison measurements available.</p>}
        <p className="method-note">{legacy?.format === "hero_categorical" ? "This compact summary publishes final topic, intent, and severity agreement only, with saved match counts and denominators. Sentiment and review-flag agreement are not measured in this summary. Initial labels are not reported here." : "Initial labels precede escalation; final labels include any escalated answers. Exact sentiment agreement means exact numeric equality. Mean absolute differences use comparable entries; each metric retains its published denominator."}</p>
        {disagreements.length > 0 && <div className="disagreement-list">
          <h4>Disagreement definitions</h4>
          {disagreements.map((metric) => <div key={metric.id} className={operational(metric.id) ? "primary-disagreement" : ""}><div><strong>{operational(metric.id) ? "Operational disagreements" : metric.label}</strong><span>{formatRatio(metric.count, metric.denominator)}</span></div><p>{metric.definition}</p></div>)}
        </div>}
        {legacy && <div className="disagreement-list"><h4>{legacy.format === "hero_categorical" ? "Categorical model disagreement" : "Legacy flag-inclusive disagreement"}</h4><p>{legacy.format !== "hero_categorical" && <>Initial: {legacy.initialDisagreements === null ? "Not published" : `${count(legacy.initialDisagreements)}/${count(legacy.verified)}`}. </>}Final: {legacy.finalDisagreements === null ? "Not published" : `${count(legacy.finalDisagreements)}/${count(legacy.verified)}`}.</p><p>{legacy.format === "hero_categorical" ? "Any exact topic, intent, or severity difference, including a missing enrichment when recorded in the saved differences. This count excludes sentiment and review flags. The broader stage audit also counts sentiment absolute error above 0.25 and is a different measure." : "Any exact topic, intent, severity, sentiment, or review-flag difference; non-comparable entries count as differences in this legacy export. These are not human errors or the operational sentiment-threshold metric."}</p><p>Fallback and verifier may share a model family; check the saved model table. Correlated model errors can conceal quality problems.</p><p>Calibrated confidence has not been published. Review flags are uncalibrated; an absent flag does not establish correctness.</p></div>}
      </article>

      {report && <>
        <div className="evaluation-grid">
          <article className="panel evaluation-card">
            <div className="panel-heading"><h3>Routing & review flags</h3><span className="outcome outcome-unknown">Uncalibrated</span></div>
            <div className="evaluation-card-body">
              <dl className="evaluation-facts">
                <div><dt>Initial review flags</dt><dd>{count(report.routing.initial_flagged)} / {count(report.coverage.selected)} original IDs</dd></div>
                <div><dt>Final review flags</dt><dd>{count(report.routing.final_flagged)} / {count(report.coverage.selected)} original IDs</dd></div>
                <div><dt>Fallback routing</dt><dd>{count(report.routing.fallback_count)} / {count(report.routing.unique_text_denominator)} unique texts</dd></div>
                <div><dt>Fallback cap</dt><dd>{count(report.routing.fallback_cap)} unique texts</dd></div>
              </dl>
              <p className="evaluation-caution"><strong>{confidence.label}.</strong> {confidence.detail}</p>
              <p>{report.routing.interpretation}</p>
              <p className="evaluation-note"><strong>No flag does not establish correctness.</strong> Flag precision and recall against human labels have not been measured.</p>
            </div>
          </article>
          <article className="panel evaluation-card">
            <div className="panel-heading"><h3>AI-assisted development inspection</h3><span className="tag">Not human ground truth</span></div>
            <div className="evaluation-card-body">
              <p>{report.inspection.interpretation}</p>
              {report.inspection.cohorts.map((cohort) => <div className="inspection-cohort" key={cohort.id}>
                <h4>{cohort.label} <span>· {count(cohort.count)} cases</span></h4>
                <p>{cohort.selection_method}</p>
                <dl><div><dt>Supported</dt><dd>{count(cohort.supported)}</dd></div><div><dt>Concerns</dt><dd>{count(cohort.concerns)}</dd></div><div><dt>Ambiguous</dt><dd>{count(cohort.ambiguous)}</dd></div></dl>
                <p>{count(cohort.concerns_flagged)} of {count(cohort.concerns)} concerns flagged; <strong>{count(cohort.concerns - cohort.concerns_flagged)} concerns unflagged.</strong></p>
              </div>)}
              <p className="evaluation-note">Random and targeted cohorts stay separate. Targeted cases are diagnostic and must not be pooled into a prevalence or human error rate.</p>
            </div>
          </article>
        </div>

        <div className="evaluation-grid">
          <article className="panel evaluation-card">
            <div className="panel-heading"><h3>Source & structural integrity</h3><Outcome status={report.structural.status} /></div>
            <div className="evaluation-card-body">
              <dl className="integrity-checks">{report.structural.checks.map((check) => <div key={check.id}><dt>{check.label}</dt><dd>{count(check.passed_count)} / {count(check.total)} passed</dd></div>)}</dl>
              <p className="evaluation-caution"><strong>Semantic support is not established by these checks.</strong> Preserved hashes, contained quotes, and literal entities do not validate topic, intent, or severity judgments.</p>
            </div>
          </article>
          <article className="panel evaluation-card">
            <div className="panel-heading"><h3>Synthetic tests</h3><span className="tag">{count(report.synthetic.case_count)} synthetic cases</span></div>
            <div className="evaluation-card-body">
              <dl className="synthetic-outcomes"><div><dt>Operational outcome</dt><dd><Outcome status={report.synthetic.operational_status} /></dd></div><div><dt>Model-behavior outcome</dt><dd><Outcome status={report.synthetic.model_behavior_status} /></dd></div><div><dt>Saved overall outcome</dt><dd><Outcome status={report.synthetic.status} /></dd></div></dl>
              <p>{report.synthetic.scope}</p>
              <p className="evaluation-note">Synthetic cases are excluded from business metrics. Passing requests or structural checks cannot override a failed behavior assertion.</p>
            </div>
          </article>
        </div>

        <article className="panel evaluation-card">
          <div className="panel-heading"><h3>Ranking sensitivity</h3><span className="tag">Model comparison, not ground truth</span></div>
          <div className="evaluation-card-body"><p>{report.ranking_sensitivity.interpretation}</p><p>Compared cohort: {count(report.ranking_sensitivity.compared_count)} original review IDs. Score in both columns is the sum of model-assigned severity for complaint/cancellation records.</p></div>
          {report.ranking_sensitivity.status === "available" ? <div className="table-scroll"><table><caption className="sr-only">Published final-label ranking and blind-verifier model ranking on the same cohort</caption><thead><tr><th scope="col">Issue</th><th scope="col">Final rank</th><th scope="col">Final score</th><th scope="col">Verifier rank</th><th scope="col">Verifier score</th></tr></thead><tbody>{report.ranking_sensitivity.rows.map((row) => <tr key={row.issue_id}><th scope="row" className="issue-name">{title(row.issue_id)}</th><td>{count(row.final_rank)}</td><td>{count(row.final_score)}</td><td>{row.comparison_rank === null ? "Not ranked" : count(row.comparison_rank)}</td><td>{count(row.comparison_score)}</td></tr>)}</tbody></table></div> : <p className="evaluation-empty">Ranking sensitivity not available.</p>}
          <p className="method-note">Verifier labels are another model judgment, not a corrected ranking or confidence interval. The published ranking remains unchanged.</p>
        </article>

        <details className="evaluation-provenance">
          <summary>Evaluation identity, coverage & limitations</summary>
          <dl className="evaluation-facts">
            <div><dt>Selected / completed original IDs</dt><dd>{count(report.coverage.selected)} / {count(report.coverage.completed)}</dd></div>
            <div><dt>Distinct texts / exact-text aliases</dt><dd>{count(report.coverage.unique_texts)} / {count(report.coverage.exact_text_aliases)}</dd></div>
            <div><dt>Saved results reused</dt><dd>{count(report.coverage.cache_hits)}</dd></div>
            <div><dt>Configuration</dt><dd className="mono">{report.label_config}</dd></div>
            <div><dt>Record-set SHA-256</dt><dd className="mono">{report.records_sha256}</dd></div>
          </dl>
          <p>Each original review ID retains its weight even when text is reused. These counts are not counts of unique users.</p>
          <ul>{report.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>
          <p>{count(report.artifact_refs.length)} hashed artifact references recorded in the report.</p>
          <p><a className="text-button" href={`/api/evaluation?run_id=${encodeURIComponent(report.run_id)}`} target="_blank" rel="noreferrer">Open matched evaluation JSON →</a></p>
        </details>
      </>}
    </section>
  );
}
