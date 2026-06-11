import { NextResponse } from "next/server";

const AGENT_URL = process.env.AGENT_URL ?? "http://127.0.0.1:8088";

export const dynamic = "force-dynamic";

export async function GET() {
  const upstream = await fetch(`${AGENT_URL}/eval-history`, { cache: "no-store" });
  if (!upstream.ok) {
    return NextResponse.json(
      { error: `agent /eval-history returned ${upstream.status}` },
      { status: 502 },
    );
  }
  const data = await upstream.json();
  return NextResponse.json(data);
}
