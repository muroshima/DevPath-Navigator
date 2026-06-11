"use client";

import { useEffect, useState } from "react";
import { ROLES, SENIORITY, TECH_BY_CATEGORY } from "@/lib/taxonomy";
import type { RoleEntry, Step } from "@/lib/types";

type Mode = "simple" | "detailed";

interface Props {
  onSubmit: (message: string) => void;
  disabled?: boolean;
}

function emptyStep(): Step {
  return {
    roles: [{ role: "backend", years: 3 }],
    techStack: [],
    seniority: "mid",
  };
}

const SIMPLE_PLACEHOLDER =
  "例: backend を 5 年（Java / Postgres、後半は Go と Kubernetes も）。直近 2 年は ML エンジニアとして PyTorch と Vertex AI を触ってる。シニアリティは mid。SRE 寄りに進みたい。";

function buildDetailedMessage(steps: Step[]): string {
  const parts = steps.map((s, i) => {
    const rolesStr = s.roles.map((r) => `${r.role}（${r.years}年）`).join(" + ");
    const tech = s.techStack.join(", ");
    return `ステップ ${i + 1}: ${rolesStr} / シニアリティ ${s.seniority} / 技術スタック: ${tech}`;
  });
  return [
    "以下は私のキャリア履歴です（古い順）。各ステップは「ロール（経験年数）」の形式で、複数ロール兼任の場合は + で連結しています。",
    ...parts,
    "私の現在地（クラスタ）を特定し、似た軌跡のエンジニアが実際に踏んだ次の一手を 2-3 件、根拠 employee_id 付きで日本語で提案してください。normalize_profile → locate_user → find_similar_trajectories → recommend_next_steps の順で必要なツールを使ってください。多重ロールのステップは steps_roles[i] と steps_role_years[i] にそれぞれ並列で渡してください。",
  ].join("\n");
}

function buildSimpleMessage(text: string): string {
  return [
    "以下は私のキャリア履歴です（自然言語で記述）:",
    text.trim(),
    "",
    "上記をもとに私の現在地（クラスタ）を特定し、似た軌跡のエンジニアが実際に踏んだ次の一手を 2-3 件、根拠 employee_id 付きで日本語で提案してください。normalize_profile で taxonomy に整形してから locate_user → find_similar_trajectories → recommend_next_steps の順で使ってください。",
  ].join("\n");
}

export default function ProfileForm({ onSubmit, disabled }: Props) {
  const [mode, setMode] = useState<Mode>("simple");
  const [text, setText] = useState("");
  const [steps, setSteps] = useState<Step[]>([emptyStep()]);

  useEffect(() => {
    try {
      const m = window.localStorage.getItem("profileForm.mode") as Mode | null;
      if (m === "simple" || m === "detailed") setMode(m);
    } catch (err) {
      console.warn("ProfileForm: localStorage read failed", err);
    }
  }, []);

  const updateMode = (next: Mode) => {
    setMode(next);
    try { window.localStorage.setItem("profileForm.mode", next); }
    catch (err) { console.warn("ProfileForm: localStorage write failed", err); }
  };

  const updateStep = (i: number, patch: Partial<Step>) => {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  };

  const updateRole = (stepIdx: number, roleIdx: number, patch: Partial<RoleEntry>) => {
    setSteps((prev) =>
      prev.map((s, i) =>
        i === stepIdx
          ? {
              ...s,
              roles: s.roles.map((r, ri) => (ri === roleIdx ? { ...r, ...patch } : r)),
            }
          : s,
      ),
    );
  };

  const addRole = (stepIdx: number) => {
    setSteps((prev) =>
      prev.map((s, i) =>
        i === stepIdx
          ? { ...s, roles: [...s.roles, { role: "platform", years: 1 }] }
          : s,
      ),
    );
  };

  const removeRole = (stepIdx: number, roleIdx: number) => {
    setSteps((prev) =>
      prev.map((s, i) =>
        i === stepIdx ? { ...s, roles: s.roles.filter((_, ri) => ri !== roleIdx) } : s,
      ),
    );
  };

  const toggleTech = (stepIdx: number, token: string) => {
    const step = steps[stepIdx];
    updateStep(stepIdx, {
      techStack: step.techStack.includes(token)
        ? step.techStack.filter((t) => t !== token)
        : [...step.techStack, token],
    });
  };

  const detailedInvalid =
    steps.length === 0 ||
    steps.some(
      (s) =>
        s.techStack.length === 0 ||
        s.roles.length === 0 ||
        s.roles.some((r) => !r.role || r.years <= 0),
    );
  const simpleInvalid = text.trim().length < 10;
  const invalid = mode === "simple" ? simpleInvalid : detailedInvalid;

  const handleSubmit = () => {
    if (invalid) return;
    const message =
      mode === "simple" ? buildSimpleMessage(text) : buildDetailedMessage(steps);
    onSubmit(message);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-200">あなたのキャリア</div>
        <div className="inline-flex rounded border border-slate-700 bg-slate-800 text-[11px]">
          <button
            type="button"
            className={`px-2 py-0.5 ${mode === "simple" ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
            onClick={() => updateMode("simple")}
            disabled={disabled}
            title="自然言語で入力"
          >
            シンプル
          </button>
          <button
            type="button"
            className={`px-2 py-0.5 ${mode === "detailed" ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
            onClick={() => updateMode("detailed")}
            disabled={disabled}
            title="ステップごとに構造化して入力"
          >
            詳細
          </button>
        </div>
      </div>

      {mode === "simple" && (
        <div className="space-y-2">
          <textarea
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
            rows={6}
            placeholder={SIMPLE_PLACEHOLDER}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={disabled}
          />
          <div className="text-[10px] text-slate-500">
            ロール・経験年数・主要技術・進みたい方向などをそのまま日本語で。agent が taxonomy に整形します。
          </div>
        </div>
      )}

      {mode === "detailed" && (
        <div className="flex items-center justify-end">
          <button
            type="button"
            className="text-xs rounded border border-slate-600 px-2 py-0.5 text-slate-300 hover:bg-slate-700 disabled:opacity-50"
            onClick={() => setSteps((s) => [...s, emptyStep()])}
            disabled={disabled}
          >
            ＋ ステップ追加
          </button>
        </div>
      )}

      {mode === "detailed" && steps.map((step, i) => (
        <div key={i} className="rounded-md border border-slate-700 bg-slate-800/60 p-2 text-xs">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold text-slate-400">ステップ {i + 1}</span>
            {steps.length > 1 && (
              <button
                type="button"
                className="text-slate-500 hover:text-slate-300"
                onClick={() => setSteps((s) => s.filter((_, idx) => idx !== i))}
                disabled={disabled}
              >
                ✕
              </button>
            )}
          </div>

          {/* Roles (multi-role + years) */}
          <div className="space-y-1">
            {step.roles.map((r, ri) => (
              <div key={ri} className="flex items-center gap-1.5">
                <select
                  className="flex-1 rounded bg-slate-900 px-1 py-0.5 text-slate-200 border border-slate-600"
                  value={r.role}
                  onChange={(e) => updateRole(i, ri, { role: e.target.value })}
                  disabled={disabled}
                >
                  {ROLES.map((opt) => (
                    <option key={opt}>{opt}</option>
                  ))}
                </select>
                <input
                  type="number"
                  min={0.5}
                  max={15}
                  step={0.5}
                  className="w-14 rounded bg-slate-900 px-1 py-0.5 text-slate-200 border border-slate-600 tabular-nums"
                  value={r.years}
                  onChange={(e) => updateRole(i, ri, { years: Number(e.target.value) || 0 })}
                  disabled={disabled}
                />
                <span className="text-slate-500">年</span>
                {step.roles.length > 1 && (
                  <button
                    type="button"
                    className="text-slate-500 hover:text-slate-300 px-1"
                    onClick={() => removeRole(i, ri)}
                    disabled={disabled}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              className="w-full text-[10px] rounded border border-dashed border-slate-600 px-2 py-0.5 text-slate-400 hover:bg-slate-700 hover:text-slate-200 disabled:opacity-40"
              onClick={() => addRole(i)}
              disabled={disabled}
            >
              + ロール兼任を追加
            </button>
          </div>

          <div className="mt-2">
            <label className="flex items-center justify-between gap-2">
              <span className="text-slate-500">シニアリティ</span>
              <select
                className="rounded bg-slate-900 px-1 py-0.5 text-slate-200 border border-slate-600"
                value={step.seniority}
                onChange={(e) => updateStep(i, { seniority: e.target.value })}
                disabled={disabled}
              >
                {SENIORITY.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          </div>

          <details className="mt-2">
            <summary className="cursor-pointer text-slate-500">
              技術スタック ({step.techStack.length})
            </summary>
            <div className="mt-1 max-h-44 overflow-auto space-y-1 pr-1">
              {Object.entries(TECH_BY_CATEGORY).map(([cat, items]) => (
                <div key={cat}>
                  <div className="text-slate-500">{cat}.*</div>
                  <div className="flex flex-wrap gap-1">
                    {items.map((tool) => {
                      const token = `${cat}.${tool}`;
                      const on = step.techStack.includes(token);
                      return (
                        <button
                          key={token}
                          type="button"
                          className={`rounded px-1.5 py-0.5 text-[10px] border ${
                            on
                              ? "border-emerald-500 bg-emerald-500/20 text-emerald-200"
                              : "border-slate-600 text-slate-400 hover:bg-slate-700"
                          }`}
                          onClick={() => toggleTech(i, token)}
                          disabled={disabled}
                        >
                          {tool}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </details>
        </div>
      ))}

      <button
        type="button"
        className="sticky bottom-0 z-10 w-full rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-900 shadow-lg shadow-black/30 hover:bg-emerald-400 disabled:opacity-50"
        onClick={handleSubmit}
        disabled={disabled || invalid}
      >
        現在地を特定して次の一手を提案
      </button>
    </div>
  );
}
