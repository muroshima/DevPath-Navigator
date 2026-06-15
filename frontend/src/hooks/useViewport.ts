"use client";

import { useEffect, useState } from "react";

export const MOBILE_BREAKPOINT = 768;

export function useViewport() {
  const [width, setWidth] = useState<number>(() => {
    if (typeof window === "undefined") return 1440;
    return window.innerWidth;
  });

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return { width, isMobile: width < MOBILE_BREAKPOINT };
}
