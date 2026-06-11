"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

interface EvalRun {
  run_id: string;
  run_at: string | null;
  batches: string[];
  recall_at_10: number;
  n_clusters: number;
  mean_archetype_purity: number;
  archetypes_covered: string[];
  vocab_size: number;
  decision: string;
  decision_reasons: string[];
}

const DECISION_STYLE: Record<string, string> = {
  pass: "bg-emerald-500/20 border-emerald-500 text-emerald-200",
  baseline: "bg-sky-500/20 border-sky-500 text-sky-200",
  fail: "bg-rose-500/20 border-rose-500 text-rose-200",
};

export default function DashboardPage() {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/eval-history", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => setRuns(d.runs ?? []))
      .catch((e) => setError(String(e)));
  }, []);

  // Chronological order for the chart (API returns newest first)
  const chrono = useMemo(() => (runs ? [...runs].reverse() : []), [runs]);

  return (
    <div className="min-h-screen px-6 py-5 text-slate-100">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">再学習ダッシュボード</h1>
          <p className="text-xs text-slate-400">
            eval_results の履歴 — 再学習のたびに評価ゲートの判定がここに記録されます
          </p>
        </div>
        <Link
          href="/"
          className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800"
        >
          ← マップに戻る
        </Link>
      </div>

      {error && <div className="text-rose-400 text-sm">読み込みエラー: {error}</div>}
      {!runs && !error && <div className="text-slate-500 text-sm">読み込み中…</div>}

      {runs && runs.length === 0 && (
        <div className="text-slate-500 text-sm">
          まだ評価履歴がありません。`pipelines/retrain.sh` を実行すると記録されます。
        </div>
      )}

      {chrono.length > 0 && (
        <>
          <RecallChart runs={chrono} />
          <RunsTable runs={runs!} />
        </>
      )}
    </div>
  );
}

function RecallChart({ runs }: { runs: EvalRun[] }) {
  const W = 720;
  const H = 220;
  const PAD = 36;

  const xs = runs.map((_, i) =>
    runs.length === 1 ? W / 2 : PAD + (i * (W - 2 * PAD)) / (runs.length - 1),
  );
  const yOf = (v: number) => H - PAD - v * (H - 2 * PAD);

  const linePath = runs
    .map((r, i) => `${i === 0 ? "M" : "L"} ${xs[i]},${yOf(r.recall_at_10)}`)
    .join(" ");

  const decisionColor = (d: string) =>
    d === "fail" ? "#fb7185" : d === "baseline" ? "#38bdf8" : "#34d399";

  return (
    <div className="mb-6 rounded-lg border border-slate-700 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Recall@10 の推移</h2>
        <div className="flex gap-3 text-[11px] text-slate-400">
          <span><span className="inline-block h-2 w-2 rounded-full bg-sky-400 mr-1" />baseline</span>
          <span><span className="inline-block h-2 w-2 rounded-full bg-emerald-400 mr-1" />pass（デプロイ）</span>
          <span><span className="inline-block h-2 w-2 rounded-full bg-rose-400 mr-1" />fail（ブロック）</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {[0, 0.25, 0.5, 0.75, 1.0].map((v) => (
          <g key={v}>
            <line x1={PAD} y1={yOf(v)} x2={W - PAD} y2={yOf(v)} stroke="#1e293b" />
            <text x={PAD - 6} y={yOf(v) + 3} fontSize={9} textAnchor="end" fill="#64748b">
              {v.toFixed(2)}
            </text>
          </g>
        ))}
        <path d={linePath} fill="none" stroke="#34d399" strokeWidth={2} opacity={0.7} />
        {runs.map((r, i) => (
          <g key={r.run_id}>
            <circle
              cx={xs[i]}
              cy={yOf(r.recall_at_10)}
              r={5}
              fill={decisionColor(r.decision)}
              stroke="#0b1020"
              strokeWidth={1.5}
            />
            <text
              x={xs[i]}
              y={yOf(r.recall_at_10) - 10}
              fontSize={9}
              textAnchor="middle"
              fill="#cbd5e1"
            >
              {r.recall_at_10.toFixed(3)}
            </text>
            <text x={xs[i]} y={H - PAD + 14} fontSize={8} textAnchor="middle" fill="#64748b">
              {r.batches.join("+")}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function RunsTable({ runs }: { runs: EvalRun[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700">
      <table className="w-full text-xs">
        <thead className="bg-slate-900 text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left">実行日時</th>
            <th className="px-3 py-2 text-left">バッチ</th>
            <th className="px-3 py-2 text-right">recall@10</th>
            <th className="px-3 py-2 text-right">クラスタ数</th>
            <th className="px-3 py-2 text-right">平均純度</th>
            <th className="px-3 py-2 text-left">archetypes</th>
            <th className="px-3 py-2 text-center">判定</th>
            <th className="px-3 py-2 text-left">理由</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id} className="border-t border-slate-800 align-top">
              <td className="px-3 py-2 font-mono text-slate-300 whitespace-nowrap">
                {r.run_at ? new Date(r.run_at).toLocaleString("ja-JP") : "—"}
              </td>
              <td className="px-3 py-2 text-slate-300">{r.batches.join(", ")}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-200">
                {r.recall_at_10.toFixed(3)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">{r.n_clusters}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                {r.mean_archetype_purity.toFixed(3)}
              </td>
              <td className="px-3 py-2 text-slate-400">
                {r.archetypes_covered.length}種
                <span className="block text-[10px] text-slate-500">
                  {r.archetypes_covered.join(", ")}
                </span>
              </td>
              <td className="px-3 py-2 text-center">
                <span
                  className={`inline-block rounded border px-2 py-0.5 font-semibold ${
                    DECISION_STYLE[r.decision] ?? "border-slate-600 text-slate-300"
                  }`}
                >
                  {r.decision}
                </span>
              </td>
              <td className="px-3 py-2 text-slate-400">
                <ul className="list-disc pl-4 space-y-0.5">
                  {r.decision_reasons.map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
