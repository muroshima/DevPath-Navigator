"use client";

import { useState } from "react";
import type { ToolCall, ToolResult } from "@/lib/types";

interface Entry {
  id: string;
  call: ToolCall;
  result?: ToolResult;
}

interface Props {
  entries: Entry[];
}

export default function ToolLog({ entries }: Props) {
  return (
    <div className="h-full overflow-auto p-2 space-y-2 text-xs">
      <div className="text-sm font-semibold text-slate-200">推論ログ</div>
      {entries.length === 0 && (
        <div className="text-slate-500">エージェントの推論中、ツール呼び出しがここに表示されます。</div>
      )}
      {entries.map((e) => (
        <ToolEntry key={e.id} entry={e} />
      ))}
    </div>
  );
}

function ToolEntry({ entry }: { entry: Entry }) {
  const [open, setOpen] = useState(false);
  const resultPreview = entry.result?.response
    ? summarizeResponse(entry.result.response)
    : "（実行中）";
  return (
    <div className="rounded-md border border-slate-700 bg-slate-800/70">
      <button
        type="button"
        className="flex w-full items-center justify-between px-2 py-1 text-left hover:bg-slate-700/40"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="font-mono text-emerald-300">{entry.call.name}</span>
        <span className="truncate text-slate-400 max-w-[60%] text-[10px]">{resultPreview}</span>
      </button>
      {open && (
        <div className="border-t border-slate-700 p-2 space-y-1">
          <div className="text-slate-500">引数</div>
          <pre className="overflow-auto rounded bg-slate-950 p-1 text-[10px] text-slate-300">
            {JSON.stringify(entry.call.args ?? {}, null, 2)}
          </pre>
          <div className="text-slate-500">応答</div>
          <pre className="overflow-auto rounded bg-slate-950 p-1 text-[10px] text-slate-300">
            {JSON.stringify(entry.result?.response ?? null, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function summarizeResponse(resp: Record<string, unknown>): string {
  if ("cluster_id" in resp && "dominant_archetype" in resp) {
    return `クラスタ ${resp.cluster_id}（${resp.dominant_archetype}）`;
  }
  if ("similar_trajectories" in resp && Array.isArray(resp.similar_trajectories)) {
    return `${resp.similar_trajectories.length} 件の類似軌跡`;
  }
  if ("recommendations" in resp && Array.isArray(resp.recommendations)) {
    return `${resp.recommendations.length} 件の推薦`;
  }
  if ("rows" in resp && Array.isArray(resp.rows)) {
    return `${resp.rows.length} 行返却`;
  }
  if ("corrections" in resp) {
    const c = resp.corrections as Record<string, unknown>;
    const techCorrections = Object.keys((c?.tech as Record<string, string>) ?? {}).length;
    return `正規化（${techCorrections} 件の tech 補正）`;
  }
  if ("error" in resp) return `エラー: ${String(resp.error).slice(0, 60)}`;
  return Object.keys(resp).slice(0, 3).join(", ");
}
