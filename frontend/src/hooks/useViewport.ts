"use client";

import { useEffect, useState } from "react";

export const MOBILE_BREAKPOINT = 768;

// SSR / pre-mount default. The first client render uses this value, then a
// post-mount effect swaps it for the real `window.innerWidth`. We pick
// "desktop" as the deterministic fallback because that's the layout most
// likely to be intended on a server-rendered fresh load — when JS hydrates
// on a mobile browser we'll re-render into the drawer layout within a tick.
const SSR_FALLBACK_WIDTH = 1440;

export function useViewport() {
  const [width, setWidth] = useState<number>(SSR_FALLBACK_WIDTH);

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return { width, isMobile: width < MOBILE_BREAKPOINT };
}
