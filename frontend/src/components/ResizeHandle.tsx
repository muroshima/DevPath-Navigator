"use client";

import type { PointerEvent } from "react";

interface Props {
  onPointerDown: (e: PointerEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
  isDragging: boolean;
}

export default function ResizeHandle({ onPointerDown, onDoubleClick, isDragging }: Props) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="サイドバーの幅を変更（ダブルクリックで既定値に戻す）"
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      className={`group relative w-1.5 shrink-0 cursor-col-resize bg-slate-700 transition-colors ${
        isDragging ? "bg-emerald-400" : "hover:bg-emerald-500/70"
      }`}
    >
      <div
        className={`pointer-events-none absolute left-1/2 top-1/2 h-10 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${
          isDragging ? "bg-emerald-200" : "bg-slate-500 group-hover:bg-emerald-200"
        }`}
      />
    </div>
  );
}
