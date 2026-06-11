"use client";

import { useEffect, useState } from "react";

const STAGE_MESSAGES = [
  "Gemini に問い合わせ中…",
  "ツールを呼び出し中…",
  "類似軌跡を BigQuery から検索中…",
  "応答を整形中…",
];

const STAGE_INTERVAL_MS = 2500;

export default function Thinking() {
  const [elapsed, setElapsed] = useState(0);
  const [stageIndex, setStageIndex] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const tick = setInterval(() => {
      setElapsed(Math.floor((performance.now() - start) / 1000));
    }, 250);
    const stageTick = setInterval(() => {
      setStageIndex((i) => (i + 1) % STAGE_MESSAGES.length);
    }, STAGE_INTERVAL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(stageTick);
    };
  }, []);

  return (
    <div className="relative overflow-hidden rounded-md border border-emerald-600/60 bg-slate-800 px-3 py-2.5">
      <div className="absolute inset-0 -z-0 animate-pulse bg-gradient-to-r from-emerald-600/10 via-emerald-500/20 to-emerald-600/10" />
      <div className="relative z-10 flex items-center gap-3">
        <Spinner />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-emerald-100 font-semibold truncate">
            {STAGE_MESSAGES[stageIndex]}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-emerald-200/70">
            <span className="font-mono tabular-nums">{elapsed.toString().padStart(2, "0")}s 経過</span>
            <ProgressDots count={3} active={stageIndex % 3} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-6 w-6 shrink-0 animate-spin text-emerald-300"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path
        d="M22 12a10 10 0 0 1-10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function ProgressDots({ count, active }: { count: number; active: number }) {
  return (
    <span className="flex items-center gap-1">
      {Array.from({ length: count }, (_, i) => (
        <span
          key={i}
          className={`inline-block h-1 w-1 rounded-full transition-all ${
            i === active ? "bg-emerald-300 scale-125" : "bg-emerald-500/40"
          }`}
        />
      ))}
    </span>
  );
}
