"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";
import Thinking from "./Thinking";

interface Props {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  busy: boolean;
}

export default function ChatPanel({ messages, onSend, busy }: Props) {
  const [draft, setDraft] = useState("");
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight });
  }, [messages.length, busy]);

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollerRef}
        className="flex-1 overflow-auto space-y-2 px-3 py-2 text-sm"
      >
        {messages.length === 0 && (
          <div className="text-xs text-slate-500">
            まずプロフィールを送ると、左のマップに現在地・近傍・推薦ルートが重なります。下の入力欄から自由に質問もできます。
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={
              m.role === "user"
                ? "ml-auto max-w-[85%] rounded-md bg-emerald-600/20 border border-emerald-700/60 px-3 py-2 text-emerald-50 whitespace-pre-wrap"
                : "max-w-[90%] rounded-md bg-slate-800 border border-slate-700 px-3 py-2 text-slate-100 whitespace-pre-wrap"
            }
          >
            {m.text || <em className="text-slate-500">(応答なし)</em>}
            {m.role === "agent" && m.toolCalls && m.toolCalls.length > 0 && (
              <div className="mt-2 text-[11px] text-slate-400 font-mono">
                ツール: {m.toolCalls.map((tc) => tc.name).join(" → ")}
              </div>
            )}
          </div>
        ))}
        {busy && <Thinking />}
      </div>

      <form
        className="flex border-t border-slate-700 bg-slate-900 p-2 gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const value = draft.trim();
          if (!value || busy) return;
          onSend(value);
          setDraft("");
        }}
      >
        <input
          className="flex-1 rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500"
          placeholder="キャリアマップについて質問してみてください..."
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={busy}
        />
        <button
          type="submit"
          className="rounded bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-emerald-400 disabled:opacity-50"
          disabled={busy || !draft.trim()}
        >
          送信
        </button>
      </form>
    </div>
  );
}
