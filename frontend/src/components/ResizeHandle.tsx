"use client";

import type { KeyboardEvent, PointerEvent } from "react";

interface Props {
  width: number;
  minWidth: number;
  maxWidth: number;
  onPointerDown: (e: PointerEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
  onWidthChange: (next: number) => void;
  isDragging: boolean;
}

const KEYBOARD_STEP = 24;
const KEYBOARD_STEP_LARGE = 96;

export default function ResizeHandle({
  width,
  minWidth,
  maxWidth,
  onPointerDown,
  onDoubleClick,
  onWidthChange,
  isDragging,
}: Props) {
  // Splitter (ARIA): widening the sidebar means the right pane grows, so
  // ArrowLeft / ArrowDown should increase width, ArrowRight / ArrowUp should
  // shrink it. This matches how draggable splitters intuitively behave.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    let next: number | null = null;
    const step = e.shiftKey ? KEYBOARD_STEP_LARGE : KEYBOARD_STEP;
    switch (e.key) {
      case "ArrowLeft":
      case "ArrowDown":
        next = width + step;
        break;
      case "ArrowRight":
      case "ArrowUp":
        next = width - step;
        break;
      case "Home":
        next = minWidth;
        break;
      case "End":
        next = maxWidth;
        break;
      case "Enter":
      case " ":
        // Activate = reset to default. Matches the double-click affordance
        // for pointer users.
        e.preventDefault();
        onDoubleClick();
        return;
      default:
        return;
    }
    if (next === null) return;
    e.preventDefault();
    onWidthChange(Math.max(minWidth, Math.min(maxWidth, next)));
  }

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label="サイドバーの幅を変更（ドラッグ・矢印キー・ダブルクリックで既定値）"
      aria-valuenow={Math.round(width)}
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
      // Touch devices that land in the desktop breakpoint (iPad / Surface)
      // otherwise route the pointer down event into scroll/zoom gestures
      // before our drag listeners can react. `touch-action: none` keeps the
      // gesture exclusively for the splitter.
      style={{ touchAction: "none" }}
      className={`group relative w-1.5 shrink-0 cursor-col-resize bg-slate-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 ${
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
