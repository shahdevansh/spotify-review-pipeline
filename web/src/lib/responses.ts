import { NextResponse } from "next/server";
import { databaseConfigured } from "./database";

export function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export async function apiResponse(
  empty: Record<string, unknown>,
  fn: () => Promise<Response>,
): Promise<Response> {
  if (!databaseConfigured()) {
    return json({
      ...empty,
      status: "unavailable",
      message: "The results database is not configured. No analysis results are being displayed.",
    });
  }
  try {
    return await fn();
  } catch (error) {
    const code = typeof error === "object" && error !== null && "code" in error
      ? String(error.code) : "";
    if (code === "42P01") {
      return json({
        ...empty,
        status: "empty",
        message: "The database is connected. Analysis results have not been imported yet.",
      });
    }
    console.error("Read-only dashboard query failed.", { code: /^[0-9A-Z]{5}$/.test(code) ? code : "unavailable" });
    return json({
      ...empty,
      status: "unavailable",
      message: "The results database is temporarily unavailable. Please try again.",
    }, 503);
  }
}

export function noRun(empty: Record<string, unknown>) {
  return json({ ...empty, status: "empty", message: "No completed analysis run has been published yet." });
}
