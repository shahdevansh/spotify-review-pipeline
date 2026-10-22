import manifest from "./product-priorities.json" with { type: "json" };
import type { HumanReferenceLink } from "./human-reference.ts";

type RunIdentity = { run_id: string; label_config: string; completed: number; input_count: number; quarantined: number };
type IssueIdentity = { issue_id: string; complaint_count: number; priority_score: number; mean_severity: number | string };

/** Editorial product insights are valid only for the exact published hero snapshot. */
export function publishedProductPriorities(run: RunIdentity | null | undefined, reference: HumanReferenceLink | null | undefined, issues: IssueIdentity[]) {
  if (!run || !reference || run.run_id !== manifest.run_id || run.label_config !== manifest.label_config ||
      run.completed !== manifest.completed || run.input_count !== manifest.completed + 13 || run.quarantined !== 13 ||
      reference.run_id !== manifest.run_id || reference.label_config !== manifest.label_config ||
      reference.prediction_sha256 !== manifest.prediction_sha256 || reference.source_sha256 !== manifest.source_sha256) return null;
  if (manifest.priorities.some((priority) => {
    const matches = issues.filter((issue) => issue.issue_id === priority.issue_id);
    if (matches.length !== 1) return true;
    const issue = matches[0];
    return !Number.isSafeInteger(issue.complaint_count) || issue.complaint_count <= 0 ||
      !Number.isSafeInteger(issue.priority_score) || issue.priority_score < issue.complaint_count ||
      !Number.isFinite(Number(issue.mean_severity)) || Number(issue.mean_severity) < 1 || Number(issue.mean_severity) > 5;
  })) return null;
  return manifest;
}
