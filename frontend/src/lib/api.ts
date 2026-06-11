import type { ChatResponse, MapResponse } from "./types";

export async function fetchMap(): Promise<MapResponse> {
  const res = await fetch("/api/map", { cache: "no-store" });
  if (!res.ok) throw new Error(`/api/map failed: ${res.status}`);
  return res.json();
}

export async function postChat(args: {
  user_id: string;
  message: string;
  session_id?: string;
}): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`/api/chat failed: ${res.status} ${detail}`);
  }
  return res.json();
}
