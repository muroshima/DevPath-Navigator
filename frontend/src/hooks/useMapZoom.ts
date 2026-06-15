"use client";

import { useEffect, useRef, useState } from "react";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 8;
const WHEEL_STEP = 1.15;

export interface MapView {
  zoom: number;
  panX: number;
  panY: number;
}

export interface MapZoom {
  view: MapView;
  reset: () => void;
  toScreen: (preZoom: { cx: number; cy: number }) => { x: number; y: number };
  bind: (svg: SVGSVGElement | null) => void;
}

function clampZoom(z: number) {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
}

// Pinch / wheel zoom anchored at the pointer (or the midpoint between the
// two touching fingers). The hook owns a single view = { zoom, panX, panY };
// graphics inside the SVG should be wrapped in a
//   <g transform={`translate(${panX}, ${panY}) scale(${zoom})`}>
// while overlay tooltips that live outside the SVG should multiply their
// projection-space coords through `toScreen()` before positioning.
export function useMapZoom(): MapZoom {
  const [view, setView] = useState<MapView>({ zoom: 1, panX: 0, panY: 0 });
  // Track the SVG element via state (not useRef) so the listener-attaching
  // effect re-runs when React first mounts the element — a ref mutation
  // does not invalidate useEffect deps, which is the bug that left the
  // listeners unattached in the initial version of this hook.
  const [svg, setSvg] = useState<SVGSVGElement | null>(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const pinchRef = useRef<
    | {
        startDist: number;
        anchorX: number;
        anchorY: number;
        baseView: MapView;
      }
    | null
  >(null);

  function anchorZoom(nextZoom: number, anchorX: number, anchorY: number, base: MapView) {
    const k = nextZoom / base.zoom;
    setView({
      zoom: nextZoom,
      panX: anchorX - (anchorX - base.panX) * k,
      panY: anchorY - (anchorY - base.panY) * k,
    });
  }

  useEffect(() => {
    if (!svg) return;
    const el = svg;

    function localXY(clientX: number, clientY: number) {
      const rect = el.getBoundingClientRect();
      return { x: clientX - rect.left, y: clientY - rect.top };
    }

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const { x, y } = localXY(e.clientX, e.clientY);
      const factor = e.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP;
      const base = viewRef.current;
      anchorZoom(clampZoom(base.zoom * factor), x, y, base);
    }

    function onTouchStart(e: TouchEvent) {
      if (e.touches.length === 2) {
        const t1 = e.touches[0];
        const t2 = e.touches[1];
        const a = localXY((t1.clientX + t2.clientX) / 2, (t1.clientY + t2.clientY) / 2);
        pinchRef.current = {
          startDist: Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY),
          anchorX: a.x,
          anchorY: a.y,
          baseView: viewRef.current,
        };
      }
    }

    function onTouchMove(e: TouchEvent) {
      const pinch = pinchRef.current;
      if (!(e.touches.length === 2 && pinch)) return;
      e.preventDefault();
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
      const ratio = dist / pinch.startDist;
      anchorZoom(clampZoom(pinch.baseView.zoom * ratio), pinch.anchorX, pinch.anchorY, pinch.baseView);
    }

    function onTouchEnd(e: TouchEvent) {
      if (e.touches.length < 2) pinchRef.current = null;
    }

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("touchstart", onTouchStart, { passive: false });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", onTouchEnd);
    el.addEventListener("touchcancel", onTouchEnd);

    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [svg]);

  return {
    view,
    reset: () => setView({ zoom: 1, panX: 0, panY: 0 }),
    toScreen: (p) => ({
      x: p.cx * view.zoom + view.panX,
      y: p.cy * view.zoom + view.panY,
    }),
    bind: setSvg,
  };
}
