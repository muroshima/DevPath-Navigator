"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { MapCluster, MapPoint, RecommendedPath } from "@/lib/types";

const PALETTE = [
  "#60a5fa", "#f472b6", "#a78bfa", "#34d399", "#fbbf24", "#f87171",
  "#22d3ee", "#fb923c", "#c084fc", "#4ade80", "#facc15", "#e879f9",
  "#94a3b8", "#fda4af", "#86efac", "#fcd34d",
];

interface UserPoint {
  x: number;
  y: number;
  clusterId: number | null;
  archetype: string | null;
}

interface Props {
  points: MapPoint[];
  clusters: MapCluster[];
  userPoint: UserPoint | null;
  highlightEmployees?: string[];
  recommendedPaths?: RecommendedPath[];
}

const PATH_COLORS = ["#fde047", "#fb923c", "#f472b6"];

// Bezier control point for a recommendation arrow: a slight perpendicular
// bend keyed by the path's index so overlapping arrows stay
// distinguishable. Shared between the SVG render path and the tooltip
// positioning so they never disagree on where the curve's midpoint is.
function pathGeometry(
  p: RecommendedPath,
  index: number,
  total: number,
  from: { cx: number; cy: number },
  project: (x: number, y: number) => { cx: number; cy: number },
): { to: { cx: number; cy: number }; ctrlX: number; ctrlY: number } {
  const to = project(p.x, p.y);
  const midX = (from.cx + to.cx) / 2;
  const midY = (from.cy + to.cy) / 2;
  const dx = to.cx - from.cx;
  const dy = to.cy - from.cy;
  const norm = Math.hypot(dx, dy) || 1;
  const bend = 24 * (index - (total - 1) / 2);
  return {
    to,
    ctrlX: midX - (dy / norm) * bend,
    ctrlY: midY + (dx / norm) * bend,
  };
}

export default function ClusterMap({
  points,
  clusters,
  userPoint,
  highlightEmployees,
  recommendedPaths,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 480 });
  const [hovered, setHovered] = useState<MapPoint | null>(null);
  // Just an index — the tooltip's screen position is derived from the
  // current projection every render, so resizing the window while a
  // path is hovered no longer leaves the tooltip pointing at a stale
  // pixel coordinate.
  const [hoveredPathIndex, setHoveredPathIndex] = useState<number | null>(null);

  // If a new chat answer arrives while a path is hovered/focused and
  // the recommendation list shrinks to where the current index no
  // longer points at anything, the tooltip's existence-guard hides it
  // — but the render loop would otherwise still treat
  // `hoveredPathIndex !== null` as "some path is active" and dim all
  // visible paths to opacity 0.55 with no highlight. Reset the index
  // so the render falls back to the neutral all-paths-bright state
  // until the user re-hovers.
  useEffect(() => {
    const len = recommendedPaths?.length ?? 0;
    if (hoveredPathIndex !== null && hoveredPathIndex >= len) {
      setHoveredPathIndex(null);
    }
  }, [recommendedPaths, hoveredPathIndex]);

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setSize({ w: Math.max(360, r.width), h: Math.max(320, r.height) });
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const bounds = useMemo(() => {
    if (points.length === 0) return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const padX = (Math.max(...xs) - Math.min(...xs)) * 0.05;
    const padY = (Math.max(...ys) - Math.min(...ys)) * 0.05;
    return {
      minX: Math.min(...xs) - padX,
      maxX: Math.max(...xs) + padX,
      minY: Math.min(...ys) - padY,
      maxY: Math.max(...ys) + padY,
    };
  }, [points]);

  const project = useMemo(() => {
    const { minX, maxX, minY, maxY } = bounds;
    const sx = (size.w - 40) / (maxX - minX);
    const sy = (size.h - 40) / (maxY - minY);
    return (x: number, y: number) => ({
      cx: 20 + (x - minX) * sx,
      cy: size.h - 20 - (y - minY) * sy,
    });
  }, [bounds, size]);

  const colorOf = (cid: number) => (cid < 0 ? "#475569" : PALETTE[cid % PALETTE.length]);
  const highlightSet = new Set(highlightEmployees ?? []);

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <svg width={size.w} height={size.h} className="block">
        <rect x={0} y={0} width={size.w} height={size.h} fill="#0b1020" />
        {[0.25, 0.5, 0.75].map((f) => (
          <g key={f} stroke="#1e293b">
            <line x1={20 + (size.w - 40) * f} y1={20} x2={20 + (size.w - 40) * f} y2={size.h - 20} />
            <line x1={20} y1={20 + (size.h - 40) * f} x2={size.w - 20} y2={20 + (size.h - 40) * f} />
          </g>
        ))}

        {points.map((p) => {
          const { cx, cy } = project(p.x, p.y);
          const isHighlight = highlightSet.has(p.employee_id);
          return (
            <circle
              key={p.employee_id}
              cx={cx}
              cy={cy}
              r={isHighlight ? 6 : 2.6}
              fill={colorOf(p.cluster_id)}
              stroke={isHighlight ? "#fff" : "none"}
              strokeWidth={isHighlight ? 1.5 : 0}
              opacity={isHighlight ? 1 : 0.75}
              onMouseEnter={() => setHovered(p)}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: "pointer" }}
            />
          );
        })}

        {clusters.filter((c) => c.cluster_id >= 0).map((c) => {
          const { cx, cy } = project(c.centroid_x, c.centroid_y);
          return (
            <g key={c.cluster_id}>
              <rect x={cx - 14} y={cy - 10} width={28} height={18} rx={4}
                fill="#0b1020" stroke={colorOf(c.cluster_id)} strokeWidth={1.5} opacity={0.92} />
              <text x={cx} y={cy + 4} fontSize={11} textAnchor="middle"
                fill="#e2e8f0" fontWeight={700}>#{c.cluster_id}</text>
            </g>
          );
        })}

        {/* Recommended path arrows: user position → representative cohort centroid */}
        {userPoint && (recommendedPaths ?? []).length > 0 && (() => {
          const from = project(userPoint.x, userPoint.y);
          return (
            <g>
              <defs>
                {(recommendedPaths ?? []).map((p, i) => (
                  <marker
                    key={`arrow-${i}`}
                    id={`arrowhead-${i}`}
                    markerWidth="8"
                    markerHeight="8"
                    refX="6"
                    refY="3"
                    orient="auto"
                  >
                    <path d="M0,0 L6,3 L0,6 Z" fill={PATH_COLORS[i % PATH_COLORS.length]} />
                  </marker>
                ))}
              </defs>
              {(recommendedPaths ?? []).map((p, i) => {
                const { to, ctrlX, ctrlY } = pathGeometry(
                  p,
                  i,
                  (recommendedPaths ?? []).length,
                  from,
                  project,
                );
                const color = PATH_COLORS[i % PATH_COLORS.length];
                const isActive = hoveredPathIndex === i;
                const activate = () => setHoveredPathIndex(i);
                const deactivate = () => setHoveredPathIndex(null);
                // If the user tabbed/clicked into the path (keyboard
                // focus is on it) and then drifts the mouse away, the
                // visual tooltip should stay until they blur — leaving
                // mouseLeave to clear it would yank the highlight out
                // from under the focused state. Defer to onBlur in that
                // case.
                const deactivateOnMouseLeave = (e: React.MouseEvent<SVGGElement>) => {
                  if (e.currentTarget !== document.activeElement) {
                    setHoveredPathIndex(null);
                  }
                };
                // Mirror the visual tooltip in aria-label so screen-reader
                // users get the same content without ever triggering the
                // hover/focus tooltip. The visible UI is Japanese (the
                // surrounding `<html lang="ja">` and the tooltip itself),
                // so this label is also Japanese — keeping the same TTS
                // voice/locale that the rest of the UI uses.
                const techHint = p.commonNewTech.length > 0
                  ? `、おすすめの技術: ${p.commonNewTech.slice(0, 3).join(",")}`
                  : "";
                const trajHint = p.sampleTrajectory
                  ? `、例の軌跡: ${p.sampleTrajectory}`
                  : "";
                const ariaLabel =
                  `推奨パス ${i + 1}: 次は${p.role}、` +
                  `似た軌跡の ${p.supportCount} 名が踏んだ一手` +
                  techHint + trajHint;
                return (
                  // Handlers live on the outer <g> so moving the pointer
                  // between the wide hit-path and the badge — both children
                  // of this group — doesn't fire leave/enter pairs (which
                  // would flicker the tooltip). tabIndex + onFocus/onBlur
                  // makes the same details reachable for keyboard and
                  // (most) touch users. No explicit role: this is a
                  // tooltip target, not a button — `role="button"` would
                  // imply Enter/Space activation that doesn't exist
                  // (focus alone reveals the tooltip).
                  <g
                    key={`path-${i}`}
                    tabIndex={0}
                    aria-label={ariaLabel}
                    onMouseEnter={activate}
                    onMouseLeave={deactivateOnMouseLeave}
                    onFocus={activate}
                    onBlur={deactivate}
                  >
                    <path
                      d={`M ${from.cx},${from.cy} Q ${ctrlX},${ctrlY} ${to.cx},${to.cy}`}
                      fill="none"
                      stroke="transparent"
                      strokeWidth={14}
                      style={{ cursor: "help" }}
                    />
                    <path
                      d={`M ${from.cx},${from.cy} Q ${ctrlX},${ctrlY} ${to.cx},${to.cy}`}
                      fill="none"
                      stroke={color}
                      strokeWidth={isActive ? 3.5 : 2.5}
                      strokeDasharray="7 5"
                      markerEnd={`url(#arrowhead-${i})`}
                      opacity={hoveredPathIndex !== null && !isActive ? 0.55 : 0.9}
                      pointerEvents="none"
                    >
                      <animate
                        attributeName="stroke-dashoffset"
                        from="24"
                        to="0"
                        dur="1.2s"
                        repeatCount="indefinite"
                      />
                    </path>
                    <g transform={`translate(${ctrlX}, ${ctrlY})`} style={{ cursor: "help" }}>
                      <circle
                        r={9}
                        fill="#0b1020"
                        stroke={color}
                        strokeWidth={1.5}
                        opacity={0.96}
                      />
                      <text
                        x={0}
                        y={3.5}
                        fontSize={9}
                        textAnchor="middle"
                        fill={color}
                        fontWeight={800}
                        pointerEvents="none"
                      >
                        {i + 1}
                      </text>
                      {isActive && (
                        <text
                          x={13}
                          y={4}
                          fontSize={10}
                          fill={color}
                          fontWeight={700}
                          pointerEvents="none"
                        >
                          {p.role}
                        </text>
                      )}
                    </g>
                  </g>
                );
              })}
            </g>
          );
        })()}

        {userPoint && (() => {
          const { cx, cy } = project(userPoint.x, userPoint.y);
          return (
            <g>
              <circle cx={cx} cy={cy} r={14} fill="none" stroke="#fde047" strokeWidth={2}>
                <animate attributeName="r" from="10" to="18" dur="1.2s" repeatCount="indefinite" />
                <animate attributeName="opacity" from="1" to="0" dur="1.2s" repeatCount="indefinite" />
              </circle>
              <circle cx={cx} cy={cy} r={6} fill="#fde047" stroke="#0b1020" strokeWidth={2} />
              <line x1={cx - 22} y1={cy} x2={cx - 10} y2={cy} stroke="#fde047" strokeWidth={1.5} />
              <line x1={cx + 10} y1={cy} x2={cx + 22} y2={cy} stroke="#fde047" strokeWidth={1.5} />
              <line x1={cx} y1={cy - 22} x2={cx} y2={cy - 10} stroke="#fde047" strokeWidth={1.5} />
              <line x1={cx} y1={cy + 10} x2={cx} y2={cy + 22} stroke="#fde047" strokeWidth={1.5} />
              <text x={cx + 16} y={cy - 16} fontSize={11} fill="#fde047" fontWeight={700}>あなた</text>
            </g>
          );
        })()}
      </svg>

      {hovered && (() => {
        const { cx, cy } = project(hovered.x, hovered.y);
        return (
          <div
            className="absolute z-10 pointer-events-none rounded-md border border-slate-700 bg-slate-900/95 px-2 py-1 text-xs shadow-lg"
            style={{ left: cx + 12, top: cy + 12 }}
          >
            <div className="font-mono text-slate-200">{hovered.employee_id}</div>
            <div className="text-slate-400">
              cluster #{hovered.cluster_id} · {hovered.archetype ?? "—"}
            </div>
          </div>
        );
      })()}

      {hoveredPathIndex !== null && userPoint && (recommendedPaths ?? [])[hoveredPathIndex] && (() => {
        // Recompute the tooltip anchor from the *current* projection so
        // it tracks the path through window resizes. State stores only
        // the index, never pixel coords.
        const paths = recommendedPaths ?? [];
        const p = paths[hoveredPathIndex];
        const from = project(userPoint.x, userPoint.y);
        const { ctrlX, ctrlY } = pathGeometry(p, hoveredPathIndex, paths.length, from, project);
        // Clamp into the visible viewport. Pin the right/bottom edges to
        // at least 12 px from the left/top so a container narrower than
        // the tooltip (size.w < 280, size.h < 150 — guarded against by
        // setSize today but worth being defensive about) doesn't push
        // the tooltip off-screen to negative coordinates.
        const maxLeft = Math.max(12, size.w - 280);
        const maxTop = Math.max(12, size.h - 150);
        return (
          <div
            // `break-all` so a comma-joined run of tech tokens
            // (no spaces, e.g. `mobile.swift_ui,infra.kubernetes,
            // mobile.flutter`) wraps inside the tooltip width
            // instead of overflowing past the right edge.
            className="absolute z-20 pointer-events-none w-64 break-all rounded-md border border-slate-700 bg-slate-950/95 p-2 text-xs shadow-xl"
            style={{
              left: Math.min(maxLeft, Math.max(12, ctrlX + 14)),
              top: Math.min(maxTop, Math.max(12, ctrlY + 14)),
            }}
          >
            <div className="font-semibold" style={{ color: PATH_COLORS[hoveredPathIndex % PATH_COLORS.length] }}>
              次にすること: {p.role}
            </div>
            <div className="mt-1 text-slate-300">
              似た軌跡の {p.supportCount} 名が次に踏んだ一手です。
            </div>
            {p.commonNewTech.length > 0 && (
              <div className="mt-1 text-slate-400">
                おすすめの技術: {p.commonNewTech.slice(0, 3).join(",")}
              </div>
            )}
            {p.sampleTrajectory && (
              <div className="mt-1 text-slate-500">
                例: {p.sampleTrajectory}
              </div>
            )}
          </div>
        );
      })()}

      <ClusterLegend clusters={clusters} colorOf={colorOf} />
    </div>
  );
}

type LegendCorner = "tl" | "tr" | "bl" | "br";

// `tr` uses top-12 (48px) instead of top-2 to clear the header bar
// pinned at `absolute right-2 top-2` in page.tsx (the
// "再学習ダッシュボード →" + "DevPath Navigator · 合成データ" pills).
// If that header changes height, bump this value too.
const CORNER_CLASSES: Record<LegendCorner, string> = {
  tl: "left-2 top-2",
  tr: "right-2 top-12",
  bl: "left-2 bottom-2",
  br: "right-2 bottom-2",
};

// Pill (collapsed) state ignores the user's corner choice and always docks
// to bottom-left. The expanded panel is what benefits from the four-corner
// move; the pill is only ~24px tall, so position-switching has no value,
// and parking it under the header bar (when corner=tr) made it look like
// part of the header.
const COLLAPSED_CLASS = "left-2 bottom-2";

const CORNER_LABEL: Record<LegendCorner, string> = {
  tl: "左上",
  tr: "右上",
  bl: "左下",
  br: "右下",
};

const NEXT_CORNER: Record<LegendCorner, LegendCorner> = {
  tl: "tr",
  tr: "br",
  br: "bl",
  bl: "tl",
};

function ClusterLegend({
  clusters,
  colorOf,
}: {
  clusters: MapCluster[];
  colorOf: (cid: number) => string;
}) {
  const real = clusters.filter((c) => c.cluster_id >= 0).sort((a, b) => b.size - a.size);
  const [corner, setCorner] = useState<LegendCorner>("tl");
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      const c = window.localStorage.getItem("clusterLegend.corner") as LegendCorner | null;
      if (c && c in CORNER_CLASSES) setCorner(c);
      const h = window.localStorage.getItem("clusterLegend.collapsed");
      if (h === "1") setCollapsed(true);
    } catch (err) {
      console.warn("ClusterLegend: localStorage read failed", err);
    }
  }, []);

  const updateCorner = (next: LegendCorner) => {
    setCorner(next);
    try { window.localStorage.setItem("clusterLegend.corner", next); }
    catch (err) { console.warn("ClusterLegend: localStorage write failed", err); }
  };
  const updateCollapsed = (next: boolean) => {
    setCollapsed(next);
    try { window.localStorage.setItem("clusterLegend.collapsed", next ? "1" : "0"); }
    catch (err) { console.warn("ClusterLegend: localStorage write failed", err); }
  };

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => updateCollapsed(false)}
        className={`absolute ${COLLAPSED_CLASS} rounded-md border border-slate-700 bg-slate-900/80 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800`}
        title="クラスタ一覧を表示"
      >
        クラスタ一覧 ({real.length})
      </button>
    );
  }

  return (
    <div className={`absolute ${CORNER_CLASSES[corner]} max-h-[60%] w-52 overflow-auto rounded-md border border-slate-700 bg-slate-900/80 p-2 text-xs`}>
      <div className="mb-1 flex items-center gap-1">
        <span className="font-semibold text-slate-300">クラスタ一覧</span>
        <button
          type="button"
          onClick={() => updateCorner(NEXT_CORNER[corner])}
          className="ml-auto rounded px-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          title={`位置を変える（現在: ${CORNER_LABEL[corner]}）`}
        >
          ⇲
        </button>
        <button
          type="button"
          onClick={() => updateCollapsed(true)}
          className="rounded px-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          title="非表示"
        >
          ×
        </button>
      </div>
      {real.map((c) => (
        <div key={c.cluster_id} className="flex items-center gap-2 py-0.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: colorOf(c.cluster_id) }} />
          <span className="font-mono text-slate-400">#{c.cluster_id}</span>
          <span className="truncate text-slate-300">{c.dominant_archetype ?? "?"}</span>
          <span className="ml-auto text-slate-500">{c.size}</span>
        </div>
      ))}
    </div>
  );
}
