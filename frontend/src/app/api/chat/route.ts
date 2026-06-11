import { NextRequest, NextResponse } from "next/server";

const AGENT_URL = process.env.AGENT_URL ?? "http://127.0.0.1:8088";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const upstream = await fetch(`${AGENT_URL}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    // Generous timeout — Gemini calls + tool calls can take 30-60s.
    signal: AbortSignal.timeout(120_000),
  });
  const data = await upstream.json().catch(() => ({ detail: "Invalid JSON from agent" }));
  return NextResponse.json(data, { status: upstream.status });
}
