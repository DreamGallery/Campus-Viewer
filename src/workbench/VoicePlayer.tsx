import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Volume1, Pause } from 'lucide-react';
import Select from '../Select';
export function VoicePlayer({ clips, row, speaker, onPlay }: { clips: { url: string; label: string }[]; row: number; speaker: ReactNode; onPlay: (audio: HTMLAudioElement) => void }) {
  const [selected, setSelected] = useState(0), [failed, setFailed] = useState(false), [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0), [duration, setDuration] = useState(0);
  const player = useRef<HTMLAudioElement>(null);
  const clip = clips[selected] || clips[0];
  useEffect(() => { const audio = player.current; return () => { audio?.pause(); }; }, [clip.url]);
  async function toggle() {
    const audio = player.current; if (!audio) return;
    if (!audio.paused) { audio.pause(); return; }
    setFailed(false);
    try { await audio.play(); } catch (error) { if (!(error instanceof DOMException && error.name === 'AbortError')) setFailed(true); }
  }
  return <div className="work-voice">
    <div className="work-voice-header">
      <div className="work-voice-speaker">
        {speaker}
        <button className="work-voice-toggle" type="button" title={playing ? '暂停语音' : '播放语音'} aria-label={`${playing ? '暂停' : '播放'}第 ${row} 条语音`} onClick={toggle}>{playing ? <Pause size={18} strokeWidth={1.75} aria-hidden="true" /> : <Volume1 size={18} strokeWidth={1.75} aria-hidden="true" />}</button>
      </div>
      {clips.length > 1 && <Select aria-label={`第 ${row} 条台词语音版本`} value={selected} onChange={e => { player.current?.pause(); setSelected(Number(e.target.value)); setFailed(false); setTime(0); setDuration(0); }}>{clips.map((c, i) => <option key={c.url} value={i}>语音 {i + 1}</option>)}</Select>}
    </div>
    <audio ref={player} key={clip.url} preload="none" src={clip.url} onPlay={e => { setPlaying(true); onPlay(e.currentTarget); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onTimeUpdate={e => setTime(e.currentTarget.currentTime)} onLoadedMetadata={e => setDuration(e.currentTarget.duration)} onError={() => { setFailed(true); setPlaying(false); }} />
    {duration > 0 && <div className="work-voice-progress"><input type="range" aria-label={`第 ${row} 条语音进度`} min={0} max={duration} step={0.05} value={time} onChange={e => { if (player.current) player.current.currentTime = Number(e.target.value); }} /><span className="work-voice-time">{time.toFixed(1)} / {duration.toFixed(1)} 秒</span></div>}
    {failed && <small role="status">语音未能加载，请检查音频资源是否已挂载。</small>}
  </div>;
}
