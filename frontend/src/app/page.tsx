"use client";

import { useEffect, useMemo, useState } from "react";

import ChatPanel from "@/components/ChatPanel";
import ClusterMap from "@/components/ClusterMap";
import ProfileForm from "@/components/ProfileForm";
import ToolLog from "@/components/ToolLog";
import { fetchMap, postChat } from "@/lib/api";
import type {
  ChatMessage,
  MapResponse,
  ToolCall,
  ToolResult,
} from "@/lib/types";

interface LogEntry {
  id: string;
  call: ToolCall;
  result?: ToolResult;
}

interface UserPoint {
  x: number;
  y: number;
  clusterId: number | null;
  archetype: string | null;
}

interface RecommendedPath {
  role: string;
  x: number;
  y: number;
  supportCount: number;
  commonNewTech: string[];
  sampleTrajectory: string | null;
}

export default function Page() {
  const [mapData, setMapData] = useState<MapResponse | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [userPoint, setUserPoint] = useState<UserPoint | null>(null);
  const [highlightEmployees, setHighlightEmployees] = useState<string[]>([]);
  const [recommendedPaths, setRecommendedPaths] = useState<RecommendedPath[]>([]);

  const userId = useMemo(() => `web-${Math.random().toString(36).slice(2, 10)}`, []);

  useEffect(() => {
    fetchMap()
      .then(setMapData)
      .catch((e) => setMapError(String(e)));
  }, []);

  function applyToolResults(calls: ToolCall[], results: ToolResult[]) {
    setLogEntries((prev) => {
      const next = [...prev];
      for (const c of calls) {
        next.push({ id: `${Date.now()}-${Math.random()}`, call: c });
      }
      for (const r of results) {
        // Attach result to the most recent matching call without a result.
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].call.name === r.name && !next[i].result) {
            next[i] = { ...next[i], result: r };
            break;
          }
        }
      }
      return next;
    });
    for (const r of results) {
      if (r.name === "locate_user" && r.response) {
        const resp = r.response as Record<string, unknown>;
        if (typeof resp.user_x === "number" && typeof resp.user_y === "number") {
          setUserPoint({
            x: resp.user_x as number,
            y: resp.user_y as number,
            clusterId: typeof resp.cluster_id === "number" ? (resp.cluster_id as number) : null,
            archetype:
              typeof resp.dominant_archetype === "string"
                ? (resp.dominant_archetype as string)
                : null,
          });
          const neighbors = (resp.nearest_neighbors as Array<{ employee_id: string }>) ?? [];
          setHighlightEmployees(neighbors.map((n) => n.employee_id));
        }
      }
      if (r.name === "find_similar_trajectories" && r.response) {
        const resp = r.response as Record<string, unknown>;
        const sims = (resp.similar_trajectories as Array<{ employee_id: string }>) ?? [];
        if (sims.length > 0) {
          setHighlightEmployees(sims.map((s) => s.employee_id));
        }
      }
      if (r.name === "recommend_next_steps" && r.response) {
        const resp = r.response as Record<string, unknown>;
        const recs = (resp.recommendations as Array<{
          next_role: string;
          support_count: number;
          common_new_tech: Array<{ tech: string; count: number }>;
          representative_trajectories: Array<{ employee_id: string; trajectory: string }>;
        }>) ?? [];
        setRecommendedPaths(computeRecommendedPaths(recs));
      }
    }
  }

  // Anchor each recommendation at the centroid of its representative
  // cohort's map positions, so the arrow points at the actual engineers
  // that exemplify the move (not an abstract cluster center).
  function computeRecommendedPaths(
    recs: Array<{
      next_role: string;
      support_count: number;
      common_new_tech: Array<{ tech: string; count: number }>;
      representative_trajectories: Array<{ employee_id: string; trajectory: string }>;
    }>,
  ): RecommendedPath[] {
    if (!mapData) return [];
    const byId = new Map(mapData.points.map((p) => [p.employee_id, p]));
    const paths: RecommendedPath[] = [];
    for (const rec of recs) {
      const coords = (rec.representative_trajectories ?? [])
        .map((t) => byId.get(t.employee_id))
        .filter((p): p is NonNullable<typeof p> => Boolean(p));
      if (coords.length === 0) continue;
      paths.push({
        role: rec.next_role,
        x: coords.reduce((s, p) => s + p.x, 0) / coords.length,
        y: coords.reduce((s, p) => s + p.y, 0) / coords.length,
        supportCount: rec.support_count,
        commonNewTech: (rec.common_new_tech ?? []).map((t) => t.tech).filter(Boolean),
        sampleTrajectory: rec.representative_trajectories?.[0]?.trajectory ?? null,
      });
    }
    return paths.slice(0, 3);
  }

  async function send(text: string) {
    setBusy(true);
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      text,
    };
    setMessages((prev) => [...prev, userMsg]);
    try {
      const resp = await postChat({
        user_id: userId,
        message: text,
        session_id: sessionId ?? undefined,
      });
      setSessionId(resp.session_id);
      applyToolResults(resp.tool_calls, resp.tool_results);
      const agentMsg: ChatMessage = {
        id: `a-${Date.now()}`,
        role: "agent",
        text: resp.response,
        toolCalls: resp.tool_calls,
        toolResults: resp.tool_results,
      };
      setMessages((prev) => [...prev, agentMsg]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "agent",
          text: `Error: ${String(e)}`,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-screen text-slate-100">
      {/* Map */}
      <section className="relative flex-1 border-r border-slate-700">
        {mapData ? (
          <ClusterMap
            points={mapData.points}
            clusters={mapData.clusters}
            userPoint={userPoint}
            highlightEmployees={highlightEmployees}
            recommendedPaths={recommendedPaths}
          />
        ) : mapError ? (
          <div className="p-4 text-rose-400">マップの読み込みに失敗しました: {mapError}</div>
        ) : (
          <div className="p-4 text-slate-500">マップを読み込み中…</div>
        )}
        <div className="absolute right-2 top-2 flex items-center gap-2">
          <a
            href="/dashboard"
            className="rounded-md bg-slate-900/80 border border-slate-700 px-2 py-1 text-xs text-emerald-300 hover:bg-slate-800"
          >
            再学習ダッシュボード →
          </a>
          <div className="rounded-md bg-slate-900/80 border border-slate-700 px-2 py-1 text-xs text-slate-300">
            DevPath Navigator · 合成データ
          </div>
        </div>
      </section>

      {/* Right column: profile + chat + log */}
      <aside className="flex w-[440px] flex-col">
        <div className="max-h-[55vh] overflow-y-auto border-b border-slate-700 bg-slate-900/60 p-3">
          <ProfileForm
            onSubmit={(message) => send(message)}
            disabled={busy}
          />
        </div>
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-hidden border-b border-slate-700">
            <ChatPanel messages={messages} onSend={send} busy={busy} />
          </div>
          <div className="h-[35%] overflow-hidden bg-slate-900/60">
            <ToolLog entries={logEntries} />
          </div>
        </div>
      </aside>
    </div>
  );
}
