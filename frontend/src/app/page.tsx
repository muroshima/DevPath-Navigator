"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import ChatPanel from "@/components/ChatPanel";
import ClusterMap from "@/components/ClusterMap";
import ProfileForm from "@/components/ProfileForm";
import ResizeHandle from "@/components/ResizeHandle";
import ToolLog from "@/components/ToolLog";
import { useResizableSidebar } from "@/hooks/useResizableSidebar";
import { useViewport } from "@/hooks/useViewport";
import { fetchMap, postChat } from "@/lib/api";
import type {
  ChatMessage,
  MapResponse,
  RecommendedPath,
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

// Shape we expect from the recommend_next_steps tool. The cast is from
// `unknown` (the tool result is JSON the agent produced), so TypeScript
// cannot actually verify any of this at runtime — the type is a
// *declaration of contract*, not a guarantee. The fields are split as:
//
//   - next_role / support_count: required by contract. The downstream
//     loop uses them directly; if the agent ever returned a row without
//     them, TypeScript would not catch it (the assertion bypasses the
//     check) but the rendered output would silently be `undefined` /
//     `NaN`, which we'd notice in QA. If we later add runtime validation
//     (e.g. zod), these are the fields it must demand.
//   - common_new_tech / representative_trajectories: optional even by
//     contract. computeRecommendedPaths already guards both with
//     `?? []` / optional chaining, and the agent may legitimately
//     return cohorts where one or both are empty.
interface RecommendNextStepsRow {
  next_role: string;
  support_count: number;
  common_new_tech?: Array<{ tech: string; count: number }>;
  representative_trajectories?: Array<{ employee_id: string; trajectory: string }>;
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

  const { isMobile } = useViewport();
  const sidebar = useResizableSidebar({
    defaultWidth: 440,
    minWidth: 320,
    maxWidth: 720,
    enabled: !isMobile,
  });
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // Auto-close the drawer when the viewport widens past the mobile breakpoint
  // (e.g. rotate to landscape). Without this the drawer state would silently
  // persist into the desktop layout where it's irrelevant.
  useEffect(() => {
    if (!isMobile && mobileSidebarOpen) setMobileSidebarOpen(false);
  }, [isMobile, mobileSidebarOpen]);

  // Escape closes the mobile drawer — standard overlay/dialog UX.
  useEffect(() => {
    if (!mobileSidebarOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileSidebarOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileSidebarOpen]);

  // When the modal drawer opens, move focus into it so keyboard / SR users
  // land inside the dialog (otherwise focus stays on the FAB behind the
  // backdrop, which contradicts `aria-modal`). On close, restore focus to
  // whatever triggered the open — usually the FAB — so the user doesn't
  // land on document.body.
  const mobileDrawerRef = useRef<HTMLElement>(null);
  const triggerBeforeDrawerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (mobileSidebarOpen) {
      triggerBeforeDrawerRef.current =
        (document.activeElement as HTMLElement | null) ?? null;
      mobileDrawerRef.current?.focus();
    } else if (triggerBeforeDrawerRef.current) {
      triggerBeforeDrawerRef.current.focus();
      triggerBeforeDrawerRef.current = null;
    }
  }, [mobileSidebarOpen]);

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
        const recs = (resp.recommendations as RecommendNextStepsRow[]) ?? [];
        setRecommendedPaths(computeRecommendedPaths(recs));
      }
    }
  }

  // Anchor each recommendation at the centroid of its representative
  // cohort's map positions, so the arrow points at the actual engineers
  // that exemplify the move (not an abstract cluster center).
  function computeRecommendedPaths(
    recs: RecommendNextStepsRow[],
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

  const sidebarContent = (
    <>
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
    </>
  );

  return (
    <div className="flex h-screen overflow-hidden text-slate-100">
      {/* Map */}
      <section className="relative flex-1 min-w-0 border-r border-slate-700">
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

      {/* Desktop / tablet: in-flow resizable sidebar */}
      {!isMobile && (
        <>
          <ResizeHandle
            width={sidebar.width}
            minWidth={sidebar.minWidth}
            maxWidth={sidebar.maxWidth}
            onPointerDown={sidebar.startDrag}
            onDoubleClick={sidebar.resetWidth}
            onWidthChange={sidebar.setWidth}
            isDragging={sidebar.isDragging}
          />
          <aside
            className="flex shrink-0 flex-col"
            style={{ width: `${sidebar.width}px` }}
          >
            {sidebarContent}
          </aside>
        </>
      )}

      {/* Mobile: drawer overlay + FAB toggle */}
      {isMobile && (
        <>
          <button
            type="button"
            onClick={() => setMobileSidebarOpen((v) => !v)}
            className="fixed bottom-4 right-4 z-30 rounded-full bg-emerald-500 px-4 py-3 text-sm font-medium text-slate-900 shadow-lg shadow-emerald-900/40 hover:bg-emerald-400 active:scale-95"
            aria-label={mobileSidebarOpen ? "サイドバーを閉じる" : "サイドバーを開く"}
            aria-expanded={mobileSidebarOpen}
            aria-controls="mobile-sidebar"
          >
            {mobileSidebarOpen ? "閉じる" : "チャット"}
          </button>
          {mobileSidebarOpen && (
            <>
              <button
                type="button"
                aria-label="サイドバーを閉じる"
                onClick={() => setMobileSidebarOpen(false)}
                className="fixed inset-0 z-10 bg-slate-950/60"
              />
              <aside
                ref={mobileDrawerRef}
                id="mobile-sidebar"
                role="dialog"
                aria-modal="true"
                aria-label="キャリアサイドバー"
                tabIndex={-1}
                className="fixed inset-y-0 right-0 z-20 flex w-[min(92vw,420px)] flex-col border-l border-slate-700 bg-slate-950 shadow-2xl focus:outline-none"
              >
                {sidebarContent}
              </aside>
            </>
          )}
        </>
      )}
    </div>
  );
}
