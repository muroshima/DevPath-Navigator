"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "devpath:sidebarWidth";

export interface ResizableSidebar {
  width: number;
  minWidth: number;
  maxWidth: number;
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

function persistWidth(w: number) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(w));
  } catch {
    // localStorage may be unavailable (private mode etc.) — silently ignore
  }
}

export function useResizableSidebar({
  defaultWidth,
  minWidth,
  maxWidth,
  enabled = true,
}: Options): ResizableSidebar {
  const [width, setWidthState] = useState<number>(defaultWidth);
  const [isDragging, setIsDragging] = useState(false);
  const dragAbortRef = useRef<AbortController | null>(null);
  const widthRef = useRef(width);
  widthRef.current = width;

  useEffect(() => {
    if (!enabled) return;
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        const n = Number.parseInt(saved, 10);
        if (Number.isFinite(n)) setWidthState(clamp(n, minWidth, maxWidth));
      }
    } catch {
      // ignore
    }
  }, [enabled, minWidth, maxWidth]);

  // Abort any in-flight drag listeners when the hook unmounts. Without this,
  // a route change while the user is still holding the pointer down would
  // leave window-level `pointermove` listeners running against a dead React
  // tree.
  useEffect(() => {
    return () => {
      dragAbortRef.current?.abort();
    };
  }, []);

  const setWidth = useCallback(
    (w: number) => {
      const clamped = clamp(w, minWidth, maxWidth);
      setWidthState(clamped);
      persistWidth(clamped);
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
      const startWidth = widthRef.current;
      setIsDragging(true);

      // Abort previous drag listeners if a new drag starts while one is
      // still in flight (defensive: shouldn't happen, but guards against
      // listener leaks if it does).
      dragAbortRef.current?.abort();
      const ctrl = new AbortController();
      dragAbortRef.current = ctrl;

      let currentWidth = startWidth;
      const onMove = (ev: PointerEvent) => {
        const delta = startX - ev.clientX;
        currentWidth = clamp(startWidth + delta, minWidth, maxWidth);
        // Update React state for the visual; defer the localStorage write
        // until pointerup so we don't hit storage on every frame.
        setWidthState(currentWidth);
      };
      const onUp = () => {
        setIsDragging(false);
        persistWidth(currentWidth);
        ctrl.abort();
        dragAbortRef.current = null;
      };

      const signal = ctrl.signal;
      window.addEventListener("pointermove", onMove, { signal });
      window.addEventListener("pointerup", onUp, { signal });
      window.addEventListener("pointercancel", onUp, { signal });
    },
    [enabled, minWidth, maxWidth],
  );

  return { width, minWidth, maxWidth, setWidth, resetWidth, startDrag, isDragging };
}
