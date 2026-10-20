import publicSchema from "../../database/dashboard-evaluation.schema.json" with { type: "json" };
import type { PilotAuditReport } from "./evaluation-report.ts";

type Schema = Record<string, unknown>;
const supported = new Set(["$defs", "$ref", "additionalProperties", "anyOf", "const",
  "enum", "exclusiveMinimum", "items", "maxItems", "minimum", "pattern", "properties",
  "required", "title", "type"]);
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/**
 * Validate the exact emitted Pydantic JSON-schema vocabulary, failing closed on
 * unknown keywords. This runs before serialization, independently of UI guards.
 */
function schemaMatches(value: unknown, schema: Schema, depth = 0): boolean {
  if (!object(schema) || depth > 40 || Object.keys(schema).some((key) => !supported.has(key))) return false;
  if (schema.type !== undefined && !["null", "boolean", "number", "integer", "string", "array", "object"].includes(String(schema.type))) return false;
  if (typeof schema.$ref === "string") {
    const match = /^#\/\$defs\/([A-Za-z0-9_]+)$/.exec(schema.$ref);
    const definitions = publicSchema.$defs as Record<string, Schema>;
    return Boolean(match && definitions[match[1]] && schemaMatches(value, definitions[match[1]], depth + 1));
  }
  if (Array.isArray(schema.anyOf) &&
      !schema.anyOf.some((option) => object(option) && schemaMatches(value, option, depth + 1))) return false;
  if ("const" in schema && value !== schema.const) return false;
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) return false;
  if (schema.type === "null" && value !== null) return false;
  if (schema.type === "boolean" && typeof value !== "boolean") return false;
  if (schema.type === "number" &&
      (typeof value !== "number" || !Number.isFinite(value))) return false;
  if (schema.type === "integer" &&
      (typeof value !== "number" || !Number.isSafeInteger(value))) return false;
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) return false;
    if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) return false;
  }
  if (schema.type === "string") {
    if (typeof value !== "string") return false;
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value)) return false;
  }
  if (schema.type === "array") {
    if (!Array.isArray(value)) return false;
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) return false;
    if (!object(schema.items) || !value.every((item) => schemaMatches(item, schema.items as Schema, depth + 1))) return false;
  }
  if (schema.type === "object") {
    if (!object(value) || !object(schema.properties) || schema.additionalProperties !== false) return false;
    const properties = schema.properties as Record<string, Schema>;
    if (!Array.isArray(schema.required) || schema.required.some((key) => !Object.hasOwn(value, String(key)))) return false;
    if (Object.keys(value).some((key) => !Object.hasOwn(properties, key))) return false;
    if (!Object.entries(value).every(([key, item]) => schemaMatches(item, properties[key], depth + 1))) return false;
  }
  return true;
}

const close = (a: number, b: number) => Math.abs(a - b) <= 1e-10;
const dated = (value: string) => /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const relativePath = (value: string) => Boolean(value) && !value.startsWith("/") &&
  !/[\\:]/.test(value) && value.split("/").every((part) => part && ![".", "..", "~"].includes(part));
const unique = (values: string[]) => values.length === new Set(values).size;
function safeStrings(value: unknown): boolean {
  if (typeof value === "string") return !/\/Users\/|\/home\/|file:\/\/|postgres(?:ql)?:\/\/|[A-Za-z]:\\/.test(value);
  if (Array.isArray(value)) return value.every(safeStrings);
  if (object(value)) return Object.values(value).every(safeStrings);
  return true;
}

/** Strict aggregate-only public boundary, including cross-field arithmetic. */
export function validatePilotAudit(value: unknown): value is PilotAuditReport {
  if (!schemaMatches(value, publicSchema as Schema) || !safeStrings(value)) return false;
  const r = value as PilotAuditReport;
  const c = r.coverage;
  if (!dated(r.generated_at) || !dated(r.cost_snapshot.as_of) ||
      c.unique_texts + c.exact_text_aliases !== c.selected ||
      [c.completed, c.cache_hits, c.compared].some((n) => n > c.selected)) return false;
  if (r.quality_gate.status !== "hold" || r.quality_gate.recommendations_provisional !== true) return false;
  if (r.human.cohorts.length !== 2 ||
      !r.human.cohorts.some((x) => x.id === "mandatory_golden_50" && x.expected_count === 50) ||
      !r.human.cohorts.some((x) => x.id === "fresh_text_disjoint_150" && x.expected_count === 150)) return false;
  for (const metric of r.model_comparison.metrics) {
    if (metric.denominator !== c.compared) return false;
    for (const side of ["initial", "final"] as const) {
      const numerator = metric[`${side}_numerator`], measured = metric[`${side}_value`];
      if (metric.unit === "fraction") {
        if (numerator === null || measured === null || numerator > metric.denominator ||
            !close(measured, numerator / metric.denominator)) return false;
      } else if (numerator !== null || (measured !== null && measured < 0)) return false;
    }
  }
  if (r.model_comparison.disagreements.some((x) => x.denominator !== c.compared || x.count > x.denominator)) return false;
  const route = r.routing;
  if (route.fallback_count > route.fallback_cap || route.fallback_cap > route.unique_text_denominator ||
      route.unique_text_denominator !== c.unique_texts ||
      [route.initial_flagged, route.final_flagged, route.numeric_signal_available].some((x) => x > c.selected)) return false;
  if (r.inspection.cohorts.some((x) => x.supported + x.concerns + x.ambiguous !== x.count ||
      x.concerns_flagged > x.concerns)) return false;
  if (r.synthetic.status === "passed" &&
      (r.synthetic.operational_status !== "passed" || r.synthetic.model_behavior_status !== "passed")) return false;
  if (r.synthetic.artifact_path !== null && !relativePath(r.synthetic.artifact_path)) return false;
  if (r.ranking_sensitivity.compared_count !== c.compared ||
      r.structural.checks.some((x) => x.passed_count > x.total)) return false;
  const cost = r.cost_snapshot;
  if (!close(cost.committed_usd, cost.known_usd + cost.unknown_hold_usd + cost.reserved_usd) ||
      !relativePath(cost.source) || r.artifact_refs.some((x) => !relativePath(x.path))) return false;
  return [
    r.artifact_refs.map((x) => x.path), r.model_comparison.metrics.map((x) => x.id),
    r.model_comparison.disagreements.map((x) => x.id), r.inspection.cohorts.map((x) => x.id),
    r.ranking_sensitivity.rows.map((x) => x.issue_id), r.structural.checks.map((x) => x.id),
  ].every(unique);
}
