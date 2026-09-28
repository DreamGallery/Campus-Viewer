import { useRef, useState } from 'react';
import { Play, Pause } from 'lucide-react';
export default function ProfileVoice({ voices }: { voices: string[] }) {
  const audio = useRef<HTMLAudioElement>(null);
  const request = useRef(0);
  const [active, setActive] = useState<number | null>(null);
  const [error, setError] = useState('');
  async function play(index: number) {
    const player = audio.current;
    if (!player) return;
    const currentRequest = ++request.current;
    if (active === index && !player.paused) { player.pause(); setActive(null); return; }
    player.pause(); setError('');
    player.src = voices[index]; setActive(index);
    try { await player.play(); }
    catch { if (currentRequest === request.current) { setActive(null); setError('语音暂时无法播放，请稍后重试。'); } }
  }
  return <div className="profile-voices" role="group" aria-label="自我介绍语音">
    {voices.map((url, index) => <button key={url} aria-pressed={active === index} onClick={() => play(index)}>
      {active === index ? <Pause size={14} /> : <Play size={14} />} 自我介绍 {index + 1}
    </button>)}
    <audio ref={audio} preload="none" onEnded={() => setActive(null)} onError={() => { setActive(null); setError('语音暂时无法播放，请稍后重试。'); }} />
    {error && <span role="status">{error}</span>}
  </div>;
}
