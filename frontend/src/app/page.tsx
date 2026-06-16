"use client";

import { useEffect, useRef, useState } from "react";

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

// sessionStorage key for the chat / tool-log / map-anchor state. Versioned
// so a future shape change can ignore old payloads instead of crashing.
const STORAGE_KEY = "devpath:chat:v1";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Restore validators. The persisted JSON is untyped at runtime — a corrupt
// or schema-skewed snapshot must not be allowed to flow into props that
// expect specific shapes (ClusterMap reads `userPoint.x`/`p.commonNewTech`,
// ToolLog reads `entry.call.name`). Each validator returns the value if
// it matches the expected shape, otherwise null/empty so we fall back to
// defaults instead of crashing the render.
function validateUserPoint(v: unknown): UserPoint | null {
  if (!isRecord(v)) return null;
  if (typeof v.x !== "number" || typeof v.y !== "number") return null;
  return {
    x: v.x,
    y: v.y,
    clusterId: typeof v.clusterId === "number" ? v.clusterId : null,
    archetype: typeof v.archetype === "string" ? v.archetype : null,
  };
}

function validateLogEntries(v: unknown): LogEntry[] {
  if (!Array.isArray(v)) return [];
  return v.filter((entry): entry is LogEntry =>
    isRecord(entry) &&
    typeof entry.id === "string" &&
    isRecord(entry.call) &&
    typeof entry.call.name === "string"
  );
}

function validateRecommendedPaths(v: unknown): RecommendedPath[] {
  if (!Array.isArray(v)) return [];
  return v.filter((p): p is RecommendedPath =>
    isRecord(p) &&
    typeof p.role === "string" &&
    typeof p.x === "number" &&
    typeof p.y === "number" &&
    typeof p.supportCount === "number" &&
    Array.isArray(p.commonNewTech) &&
    p.commonNewTech.every((t) => typeof t === "string") &&
    (p.sampleTrajectory === null || typeof p.sampleTrajectory === "string")
  );
}

interface PersistedChatState {
  // userId is part of the lookup key the agent uses to resume a session
  // (`get_session(user_id, session_id)` in agent/server.py). If we restore
  // session_id but mint a fresh user_id on every remount, the server
  // silently starts a new session and the restored history detaches from
  // future turns — the UI shows old turns but follow-ups don't continue.
  // So userId is persisted as part of the same snapshot.
  userId: string;
  messages: ChatMessage[];
  logEntries: LogEntry[];
  sessionId: string | null;
  userPoint: UserPoint | null;
  highlightEmployees: string[];
  recommendedPaths: RecommendedPath[];
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

  // userId is `useState` (not `useMemo`) so the restore effect below can
  // swap it for the persisted id when one is available. The lazy
  // initialiser still gives us a stable random id for fresh tabs.
  const [userId, setUserId] = useState<string>(
    () => `web-${Math.random().toString(36).slice(2, 10)}`,
  );

  useEffect(() => {
    fetchMap()
      .then(setMapData)
      .catch((e) => setMapError(String(e)));
  }, []);

  // Restore chat / tool-log / map-anchor state from sessionStorage on mount
  // so navigating to /dashboard and back via `← マップに戻る` doesn't wipe
  // the conversation. sessionStorage (not localStorage) keeps it per-tab
  // which matches the demo flow — a fresh tab starts fresh.
  //
  // Run once per actual mount; under React Strict Mode dev the effect
  // double-fires, but the second pass just re-reads the same JSON and
  // re-applies the same setState (React bails on identical values).
  // Corrupt JSON or shape mismatches fall back to the default empty state.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let saved: PersistedChatState | null = null;
    try {
      const raw = window.sessionStorage.getItem(STORAGE_KEY);
      if (raw) saved = JSON.parse(raw) as PersistedChatState;
    } catch {
      // corrupted entry — ignore, leave defaults in place
    }
    if (!saved || typeof saved !== "object") return;
    if (typeof saved.userId === "string" && saved.userId) setUserId(saved.userId);
    if (Array.isArray(saved.messages)) setMessages(saved.messages);
    setLogEntries(validateLogEntries(saved.logEntries));
    if (saved.sessionId === null || typeof saved.sessionId === "string") {
      setSessionId(saved.sessionId);
    }
    setUserPoint(validateUserPoint(saved.userPoint));
    if (Array.isArray(saved.highlightEmployees)) {
      setHighlightEmployees(
        saved.highlightEmployees.filter((id): id is string => typeof id === "string"),
      );
    }
    setRecommendedPaths(validateRecommendedPaths(saved.recommendedPaths));
  }, []);

  // Persist whenever any restored field changes. `busy` and map fixtures
  // are deliberately excluded — `busy` is transient and map data refetches
  // on mount, so neither belongs in the saved snapshot.
  //
  // Skip the very first run so it can't race the restore effect: on mount
  // both effects fire after Render 1 (state = defaults). Without the skip,
  // we'd briefly overwrite the saved snapshot with defaults before the
  // restore-triggered Render 2 wrote it back. With the skip, the first
  // write only happens on Render 2 — when state reflects the restored
  // values (or the user's first action on a fresh tab).
  const persistSkippedFirstRef = useRef(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!persistSkippedFirstRef.current) {
      persistSkippedFirstRef.current = true;
      return;
    }
    try {
      const isEmpty =
        messages.length === 0 &&
        logEntries.length === 0 &&
        sessionId === null &&
        userPoint === null &&
        highlightEmployees.length === 0 &&
        recommendedPaths.length === 0;
      if (isEmpty) {
        // Fully cleared state (e.g. after リセット) — remove the key
        // entirely instead of writing an empty snapshot back. Avoids
        // leaving stale-looking data in storage and means a future page
        // load with this empty key short-circuits the restore branch.
        window.sessionStorage.removeItem(STORAGE_KEY);
        return;
      }
      const snapshot: PersistedChatState = {
        userId,
        messages,
        logEntries,
        sessionId,
        userPoint,
        highlightEmployees,
        recommendedPaths,
      };
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
      // Quota exceeded / disabled storage — silently drop the write; the
      // app still works in-memory for the current navigation.
    }
  }, [userId, messages, logEntries, sessionId, userPoint, highlightEmployees, recommendedPaths]);

  function resetConversation() {
    // Mint a fresh user id so the agent treats the next message as a new
    // session, not as a continuation of the just-cleared one. The persist
    // effect detects the fully-empty state and removes the storage key.
    setUserId(`web-${Math.random().toString(36).slice(2, 10)}`);
    setMessages([]);
    setLogEntries([]);
    setSessionId(null);
    setUserPoint(null);
    setHighlightEmployees([]);
    setRecommendedPaths([]);
  }

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
        {messages.length > 0 && (
          <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900/40 px-3 py-1 text-xs text-slate-400">
            <span>会話履歴</span>
            <button
              type="button"
              onClick={resetConversation}
              disabled={busy}
              className="rounded px-2 py-0.5 text-emerald-300 hover:bg-slate-800 disabled:opacity-50"
              title="会話・推論ログ・マップ上の現在地と推薦をすべて初期化します"
            >
              リセット
            </button>
          </div>
        )}
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
