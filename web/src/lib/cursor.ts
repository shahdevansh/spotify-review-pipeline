export interface ReviewCursor {
  run_id: string;
  issue_id: string;
  review_id: string;
}

export function encodeCursor(cursor: ReviewCursor): string {
  return Buffer.from(JSON.stringify(cursor), "utf8").toString("base64url");
}

export function decodeCursor(value: string | null): ReviewCursor | null {
  if (!value) return null;
  if (value.length > 2048 || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("Invalid review cursor");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
  } catch {
    throw new Error("Invalid review cursor");
  }
  if (!parsed || typeof parsed !== "object") throw new Error("Invalid review cursor");
  const cursor = parsed as Record<string, unknown>;
  for (const key of ["run_id", "issue_id", "review_id"]) {
    if (typeof cursor[key] !== "string" || !cursor[key] || (cursor[key] as string).length > 512) {
      throw new Error("Invalid review cursor");
    }
  }
  return cursor as unknown as ReviewCursor;
}
