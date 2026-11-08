import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Pause, Play } from "lucide-react";
import type { Character } from "./catalog";

const INTERVAL_MS = 10_000;

async function prepareImages(element: HTMLElement) {
  const images = [...element.querySelectorAll<HTMLImageElement>("img")];
  const urls = [...element.querySelectorAll<SVGImageElement>("svg image")]
    .map(image => image.href.baseVal);
  const hero = element.querySelector(".character-hero");
  const background = hero && /url\(["']?(.*?)["']?\)/.exec(getComputedStyle(hero).backgroundImage)?.[1];
  if (background) urls.push(background);
  for (const url of new Set(urls.filter(Boolean))) {
    const image = new Image();
    image.src = url;
    images.push(image);
  }
  // A failed decode must leave the current character on screen.
  await Promise.all(images.map(image => image.decode()));
}

export default function CharacterCarousel({ characters, current, onChange, onTransitionTargetChange, children }: {
  characters: Character[];
  current: Character;
  onChange: (id: string) => void;
  onTransitionTargetChange?: (id: string | null) => void;
  children: (character: Character) => ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(() => !matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [visible, setVisible] = useState(false);
  const [foreground, setForeground] = useState(!document.hidden);
  const [touching, setTouching] = useState(false);
  const [focused, setFocused] = useState(false);
  const [voicePlaying, setVoicePlaying] = useState(false);
  const next = characters[(characters.findIndex(character => character.id === current.id) + 1) % characters.length];
  const active = playing && visible && foreground && !touching && !focused && !voicePlaying;

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => {
      setVisible(entry.isIntersecting && entry.intersectionRatio >= 0.35);
    }, { threshold: [0, 0.35] });
    const visibilityChanged = () => setForeground(!document.hidden);
    const releasePointer = () => setTouching(false);
    const focusChanged = (event: FocusEvent) => {
      const target = event.type === "focusout" ? event.relatedTarget : event.target;
      setFocused(target instanceof Element && Boolean(element.closest("main")?.contains(target))
        && !target.closest(".character-carousel-toggle"));
    };
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const motionChanged = () => { if (motion.matches) setPlaying(false); };
    observer.observe(element);
    document.addEventListener("visibilitychange", visibilityChanged);
    document.addEventListener("focusin", focusChanged);
    document.addEventListener("focusout", focusChanged);
    window.addEventListener("pointerup", releasePointer);
    window.addEventListener("pointercancel", releasePointer);
    motion.addEventListener("change", motionChanged);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", visibilityChanged);
      document.removeEventListener("focusin", focusChanged);
      document.removeEventListener("focusout", focusChanged);
      window.removeEventListener("pointerup", releasePointer);
      window.removeEventListener("pointercancel", releasePointer);
      motion.removeEventListener("change", motionChanged);
    };
  }, []);

  useLayoutEffect(() => {
    const element = track.current;
    if (!element || !active || !next || next.id === current.id) return;
    let cancelled = false;
    let timer = 0;
    let animation: Animation | undefined;
    const wait = (duration: number) => new Promise<void>(resolve => { timer = window.setTimeout(resolve, duration); });
    // Load only the current and next profile; never preload every character's cards or audio.
    void (async () => {
      const [currentSlide, nextSlide] = [...element.children] as HTMLElement[];
      const nextReady = prepareImages(nextSlide).then(() => true, () => false);
      await prepareImages(currentSlide);
      // The initial page curtain must finish before the visible 10-second interval starts.
      while (!cancelled && element.closest("[inert]")) await wait(100);
      if (cancelled) return;
      const [, ready] = await Promise.all([wait(INTERVAL_MS), nextReady]);
      if (cancelled || !ready) return;
      animation = element.animate([{ transform: "translateX(0)" }, { transform: "translateX(-100%)" }], {
        duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 650,
        easing: "cubic-bezier(.22,.61,.36,1)",
        fill: "forwards",
      });
      onTransitionTargetChange?.(next.id);
      await animation.finished;
      if (!cancelled) onChange(next.id);
    })().catch(() => { /* Keep the current profile when resources fail or rotation is cancelled. */ });
    return () => {
      cancelled = true;
      clearTimeout(timer);
      animation?.cancel();
      if (animation) onTransitionTargetChange?.(null);
    };
  }, [active, current.id, next, onChange, onTransitionTargetChange]);

  return <div className="character-carousel" ref={container} role="region" aria-roledescription="轮播" aria-label="角色档案">
    <div className="character-carousel-track" ref={track}
      onPointerDown={() => setTouching(true)} onPointerUp={() => setTouching(false)} onPointerCancel={() => setTouching(false)}
      onPlayCapture={() => setVoicePlaying(true)} onPauseCapture={() => setVoicePlaying(false)} onEndedCapture={() => setVoicePlaying(false)}
      onErrorCapture={event => { if (event.target instanceof HTMLAudioElement) setVoicePlaying(false); }}>
      {[current, ...(next && next.id !== current.id ? [next] : [])].map((character, index) => <div
        className="character-carousel-slide" key={character.id} aria-hidden={index !== 0 ? true : undefined}
        ref={element => { if (element) element.inert = index !== 0; }}
        style={{ "--accent": character.color } as CSSProperties}>
        {children(character)}
      </div>)}
    </div>
    {characters.length > 1 && <button type="button" className="character-carousel-toggle"
      aria-label={playing ? "暂停角色轮播" : "开始角色轮播"} title={playing ? "暂停角色轮播" : "开始角色轮播"}
      onClick={() => setPlaying(value => !value)}>
      {playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
    </button>}
  </div>;
}
