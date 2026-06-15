"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "devpath:sidebarWidth";

export interface ResizableSidebar {
  width: number;
  setWidth: (w: number) => void;
  resetWidth: () => void;
  startDrag: (e: React.PointerEvent<HTMLElement>) => void;
  isDragging: boolean;
}

interface Options {
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  enabled?: boolean;
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

export function useResizableSidebar({
  defaultWidth,
  minWidth,
  maxWidth,
  enabled = true,
}: Options): ResizableSidebar {
  const [width, setWidthState] = useState<number>(defaultWidth);
  const [isDragging, setIsDragging] = useState(false);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        const n = Number.parseInt(saved, 10);
        if (Number.isFinite(n)) setWidthState(clamp(n, minWidth, maxWidth));
      }
    } catch {
      // localStorage may be unavailable (private mode etc.) — fall back to default
    }
  }, [enabled, minWidth, maxWidth]);

  const setWidth = useCallback(
    (w: number) => {
      const clamped = clamp(w, minWidth, maxWidth);
      setWidthState(clamped);
      try {
        window.localStorage.setItem(STORAGE_KEY, String(clamped));
      } catch {
        // ignore
      }
    },
    [minWidth, maxWidth],
  );

  const resetWidth = useCallback(() => {
    setWidth(defaultWidth);
  }, [defaultWidth, setWidth]);

  const startDrag = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!enabled) return;
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = width;
      dragStateRef.current = { startX, startWidth };
      setIsDragging(true);

      const onMove = (ev: PointerEvent) => {
        const state = dragStateRef.current;
        if (!state) return;
        const delta = state.startX - ev.clientX;
        setWidth(state.startWidth + delta);
      };
      const onUp = () => {
        dragStateRef.current = null;
        setIsDragging(false);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    },
    [enabled, width, setWidth],
  );

  return { width, setWidth, resetWidth, startDrag, isDragging };
}
