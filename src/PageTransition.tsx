import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { PageLoadingContext } from "./page-loading";
import "./page-transition.css";

const sectionPaths = new Set([
  "/idols", "/stories/character", "/stories/main", "/stories/support_card",
  "/stories/event", "/stories/other", "/updates", "/workbench",
]);
const MINIMUM_HOLD_MS = 600;
const FADE_MS = 400;
const MAXIMUM_WAIT_MS = 15000;

function waitForImage(image: HTMLImageElement, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  const decoded = () => image.decode().catch(() => {});
  if (image.complete) return decoded();
  return new Promise<void>(resolve => {
    const done = () => {
      image.removeEventListener("load", done);
      image.removeEventListener("error", done);
      signal.removeEventListener("abort", done);
      if (signal.aborted) resolve();
      else void decoded().then(resolve);
    };
    image.addEventListener("load", done);
    image.addEventListener("error", done);
    signal.addEventListener("abort", done, { once: true });
  });
}

function waitForPageImages(content: HTMLElement | null, signal: AbortSignal) {
  const visible = (element: Element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.top < innerHeight && rect.bottom > 0
      && rect.left < innerWidth && rect.right > 0;
  };
  const images = [...content?.querySelectorAll("img") || []].filter(image =>
    !image.closest("dialog:not([open])") && (visible(image)
      || image.matches(".character-hero img, .roster img, .card-preview img")));
  // Include artwork on the current page below the fold. Lazy images would otherwise
  // start loading only after the curtain has gone and the reader scrolls to them.
  for (const image of images) {
    if (image.loading === "lazy") image.loading = "eager";
  }
  // The character introduction uses a CSS classroom background rather than an <img>.
  for (const element of content?.querySelectorAll(".character-hero") || []) {
    const url = /url\(["']?(.*?)["']?\)/.exec(getComputedStyle(element).backgroundImage)?.[1];
    if (url) { const image = new Image(); image.src = url; images.push(image); }
  }
  return Promise.all(images.map(image => waitForImage(image, signal)));
}

function LoadingCurtain({ pending }: { pending: number }) {
  const { pathname } = useLocation();
  const path = pathname === "/" ? "/idols" : pathname;
  const curtain = useRef<HTMLDivElement>(null);
  const opening = useRef(true);
  const pendingRef = useRef(pending);
  const recheck = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    pendingRef.current = pending;
    recheck.current?.();
  }, [pending]);

  useLayoutEffect(() => {
    const layer = curtain.current;
    const detailPath = /^\/(?:idol-commu|character-card|chapter)\/[^/]+\/?$/.test(path);
    if (!layer || (!opening.current && !sectionPaths.has(path) && !detailPath)) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reducedMotion.matches) { opening.current = false; return; }

    const content = document.getElementById("content");
    const wasInert = content?.inert ?? false;
    const wasBusy = content?.getAttribute("aria-busy");
    let stopped = false, expired = false, minimumElapsed = false, frame = 0;
    let images: AbortController | null = null;
    let fade: Animation | undefined;
    layer.dataset.active = "true";
    if (content) { content.inert = true; content.setAttribute("aria-busy", "true"); }

    const cancelPending = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      images?.abort(); images = null;
      fade?.cancel(); fade = undefined;
    };
    const stop = () => {
      stopped = true;
      cancelPending();
      clearTimeout(minimum); clearTimeout(deadline);
      layer.dataset.active = "false";
      if (content) {
        content.inert = wasInert;
        if (wasBusy == null) content.removeAttribute("aria-busy");
        else content.setAttribute("aria-busy", wasBusy);
      }
    };
    const reveal = () => {
      if (stopped || fade) return;
      fade = layer.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FADE_MS, easing: "ease", fill: "forwards" });
      fade.onfinish = () => { opening.current = false; stop(); };
    };
    const check = () => {
      if (stopped || expired) return;
      if (pendingRef.current) { cancelPending(); return; }
      if (!minimumElapsed || images || frame || fade) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const controller = new AbortController();
        images = controller;
        void waitForPageImages(content, controller.signal).then(() => {
          if (!controller.signal.aborted && !pendingRef.current) reveal();
        });
      });
    };
    const minimum = window.setTimeout(() => { minimumElapsed = true; check(); }, MINIMUM_HOLD_MS);
    // A stalled request must not permanently hide the page's loading/error UI.
    const deadline = window.setTimeout(() => { expired = true; reveal(); }, MAXIMUM_WAIT_MS);
    const motionChanged = () => {
      if (reducedMotion.matches) { opening.current = false; stop(); }
    };
    recheck.current = check;
    reducedMotion.addEventListener("change", motionChanged);
    return () => { stop(); recheck.current = null; reducedMotion.removeEventListener("change", motionChanged); };
  }, [path]);

  return <div className="page-transition" ref={curtain} data-active="false" aria-hidden="true">
    <div className="page-transition-pattern" />
    <div className="page-transition-emblem">
      <svg className="page-transition-crest" viewBox="0 0 100 100">
        <defs><filter id="transition-crest-ink" colorInterpolationFilters="sRGB">
          <feComponentTransfer result="ink"><feFuncA type="linear" slope="9.8077" /></feComponentTransfer>
          <feFlood floodColor="#ffe7bf" /><feComposite in2="ink" operator="in" />
        </filter></defs>
        <image href="/images/official/crest.png" width="100" height="100" filter="url(#transition-crest-ink)" />
      </svg>
      <span className="page-transition-text">Loading</span>
    </div>
  </div>;
}

export default function PageTransition({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState(0);
  const register = useCallback(() => {
    setPending(count => count + 1);
    return () => setPending(count => count - 1);
  }, []);
  return <PageLoadingContext.Provider value={register}>
    {children}
    <LoadingCurtain pending={pending} />
  </PageLoadingContext.Provider>;
}
