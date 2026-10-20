import "server-only";
import type { Pool, PoolClient } from "pg";

let poolPromise: Promise<Pool> | undefined;

export function databaseConfigured(): boolean {
  return Boolean(process.env.DATABASE_READONLY_URL || process.env.DATABASE_URL);
}

function connectionPool(): Promise<Pool> {
  if (!poolPromise) {
    const connectionString = process.env.DATABASE_READONLY_URL || process.env.DATABASE_URL;
    if (!connectionString) throw new Error("DATABASE_NOT_CONFIGURED");
    poolPromise = import("pg").then(({ Pool: PgPool }) => {
      const pool = new PgPool({
        connectionString,
        max: 2,
        idleTimeoutMillis: 10_000,
        connectionTimeoutMillis: 10_000,
        allowExitOnIdle: true,
      });
      // Pool errors are intentionally generic: never log a connection URL or credentials.
      pool.on("error", () => console.error("Database pool connection failed."));
      return pool;
    }).catch((error) => {
      poolPromise = undefined;
      throw error;
    });
  }
  return poolPromise;
}

export async function readTransaction<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await (await connectionPool()).connect();
  try {
    await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    await client.query("SET LOCAL statement_timeout = '8000ms'");
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

export async function currentRun(client: PoolClient) {
  const result = await client.query(
    `SELECT run_id, created_at, imported_at, summary, source_profile, evaluation, imported_rows
       FROM spotify_runs WHERE is_current = true LIMIT 1`,
  );
  return result.rows[0] ?? null;
}

export const publicReviewColumns = `
  r.review_id, r.review_text, r.review_rating, r.review_likes, r.app_version,
  r.review_timestamp, r.source_sha256, r.status, r.reason, r.topic, r.intent,
  r.sentiment, r.severity, r.entities, r.evidence_quote, r.needs_review,
  r.label_config, r.cache_source_id, r.provenance`;
