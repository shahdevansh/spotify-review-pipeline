import assert from "node:assert/strict";
import test from "node:test";
import { publicRunSummary } from "../src/lib/public-data.ts";

test("public overview excludes private local run identity paths", () => {
  assert.deepEqual(publicRunSummary({
    run_id: "synthetic-run", completed: 1, input_path: "/private/source.csv",
    cache_path: "/private/state.sqlite3", arbitrary_metadata: "not public",
  }), { run_id: "synthetic-run", completed: 1 });
});
