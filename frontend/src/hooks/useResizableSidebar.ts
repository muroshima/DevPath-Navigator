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

// `Math.round` so the width is always an integer pixel value. Pointer
// `clientX` can be fractional on high-DPR devices, so without rounding
// `startWidth + delta` could land at e.g. 540.4, which would then be
// written into inline style (`width: 540.4px`), localStorage ("540.4"),
// and aria-valuenow (after a separate Math.round) — three different
// representations of "the same width". Normalising at the clamp boundary
// keeps the hook's contract simple: state, persistence, and ARIA all
// agree on the same integer.
function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Math.round(v)));
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
      if (saved === null) return;
      const n = Number.parseInt(saved, 10);
      if (!Number.isFinite(n)) return;
      const clamped = clamp(n, minWidth, maxWidth);
      setWidthState(clamped);
      // If the persisted value was out of the current range (min/max
      // changed across releases, or the entry was hand-edited), write the
      // clamped value back so storage and state stay in sync.
      if (clamped !== n) persistWidth(clamped);
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

  // If resizing flips off mid-drag (e.g. the viewport crosses the mobile
  // breakpoint and the handle unmounts), abort the active drag so the
  // window-level pointer listeners don't keep firing into a dead handle.
  useEffect(() => {
    if (enabled) return;
    dragAbortRef.current?.abort();
    dragAbortRef.current = null;
    setIsDragging(false);
  }, [enabled]);

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
        const next = clamp(startWidth + delta, minWidth, maxWidth);
        // Skip the state update when clamp pinned us to the same value
        // (e.g. dragging further past the min/max). Pointermove fires at
        // ~60Hz so even a cheap no-op setState costs us when the user
        // holds the pointer against an edge.
        if (next === currentWidth) return;
        currentWidth = next;
        // Update React state for the visual; defer the localStorage write
        // until pointerup so we don't hit storage on every frame.
        setWidthState(next);
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
