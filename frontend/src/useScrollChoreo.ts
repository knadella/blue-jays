import { useEffect } from "react";

/** 1 when the block’s center sits near the viewport “focal” band, 0 when off-screen */
function choreoFromRect(rect: DOMRect, vh: number): number {
  if (rect.bottom < -80 || rect.top > vh + 80) {
    return 0;
  }
  const cy = rect.top + rect.height / 2;
  const focusY = vh * 0.4;
  const span = Math.max(vh * 0.62, 280);
  const raw = 1 - Math.abs(cy - focusY) / span;
  return Math.min(1, Math.max(0, raw * 1.22));
}

export function useScrollChoreo() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    let raf = 0;

    const tick = () => {
      raf = 0;
      const docEl = document.documentElement;
      const vh = window.innerHeight;
      const maxScroll = Math.max(1, docEl.scrollHeight - vh);
      const pagePlay = Math.min(1, Math.max(0, window.scrollY / maxScroll));
      docEl.style.setProperty("--page-play", pagePlay.toFixed(4));

      document.querySelectorAll<HTMLElement>("[data-scroll-choreo]").forEach((el) => {
        const rect = el.getBoundingClientRect();
        el.style.setProperty("--choreo", choreoFromRect(rect, vh).toFixed(3));
      });
    };

    const schedule = () => {
      if (raf) {
        return;
      }
      raf = requestAnimationFrame(tick);
    };

    tick();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });

    /* Charts mount after async fetch; without this, new `[data-scroll-choreo]` nodes never get `--choreo` updated. */
    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => schedule())
        : null;
    ro?.observe(document.documentElement);
    for (let i = 0; i < 5; i++) {
      requestAnimationFrame(() => schedule());
    }

    return () => {
      ro?.disconnect();
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      document.documentElement.style.removeProperty("--page-play");
    };
  }, []);
}
