import assert from "node:assert/strict";
import test from "node:test";
import { decodeCursor, encodeCursor } from "../src/lib/cursor.ts";

test("pagination preserves exact Unicode and punctuation in IDs", () => {
  const cursor = { run_id: "synthetic-run", issue_id: "issue-playback", review_id: "review+日本語/9" };
  assert.deepEqual(decodeCursor(encodeCursor(cursor)), cursor);
});

test("empty cursor starts a page and malformed cursors are rejected", () => {
  assert.equal(decodeCursor(null), null);
  assert.equal(decodeCursor(""), null);
  for (const malformed of ["$$", "e30", "bnVsbA", "a".repeat(2049)]) {
    assert.throws(() => decodeCursor(malformed), /Invalid review cursor/);
  }
});
