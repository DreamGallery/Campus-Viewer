import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { ArrowDown, ChevronUp, Disc3, ListMusic, Loader2, Music2, Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume2, VolumeX } from 'lucide-react';
import { clockTime, lyricIndex, type LyricLine } from './lyrics';
import './music.css';
interface Track {
  id: string; title: string; artist: string; audio: string; cover: string; version: string;
  lyrics: LyricLine[]; credits: { lyrics: string; composer: string; arranger: string };
}
function savedVolume() {
  try { const n = Number(localStorage.getItem('campus-music-volume') ?? .65); return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : .65; }
  catch { return .65; }
}
export default function MusicPlayer() {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selected, setSelected] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState<'lyrics' | 'queue'>('lyrics');
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(savedVolume);
  const [shuffle, setShuffle] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const [search, setSearch] = useState('');
  const [follow, setFollow] = useState(true);
  const audio = useRef<HTMLAudioElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const lyrics = useRef<HTMLDivElement>(null);
  const currentLine = useRef<HTMLButtonElement>(null);
  const startOnLoad = useRef(false);
  const request = useRef(0);
  const lastVolume = useRef(.65);
  const track = tracks[selected];
  const index = lyricIndex(track?.lyrics || [], time);
  const active = index >= 0 && time < track.lyrics[index].end;
  useEffect(() => {
    const controller = new AbortController();
    fetch('/music/library.json', { signal: controller.signal }).then(r => {
      if (!r.ok) throw new Error('Missing library'); return r.json();
    }).then(data => {
      if (!Array.isArray(data.tracks)) return;
      setTracks(data.tracks);
      try { const i = data.tracks.findIndex((t: Track) => t.id === localStorage.getItem('campus-music-track')); if (i >= 0) setSelected(i); } catch { /* Storage optional. */ }
    }).catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!tracks.length) return;
    document.body.classList.add('has-music-player');
    return () => document.body.classList.remove('has-music-player');
  }, [tracks.length]);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [expanded]);
  useEffect(() => {
    if (audio.current) audio.current.volume = volume;
    try { localStorage.setItem('campus-music-volume', String(volume)); } catch { /* Storage optional. */ }
  }, [volume, track?.id]);
  async function play() {
    const player = audio.current; if (!player) return;
    const id = ++request.current;
    setError(''); setLoading(true);
    try { await player.play(); }
    catch { if (id === request.current) { setLoading(false); setError('歌曲未能播放，请重试。'); } }
  }
  useEffect(() => {
    if (!track || !audio.current) return;
    request.current++; setTime(0); setDuration(0); setPlaying(false); setError(''); setFollow(true);
    audio.current.load();
    try { localStorage.setItem('campus-music-track', track.id); } catch { /* Storage optional. */ }
    if (startOnLoad.current) { startOnLoad.current = false; void play(); }
    else setLoading(false);
    // Source changes are the only trigger; volume and controls must not restart audio.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track?.id]);
  useEffect(() => {
    if (!expanded || view !== 'lyrics' || !follow || !lyrics.current || !currentLine.current) return;
    const box = lyrics.current, line = currentLine.current;
    box.scrollTo({ top: line.offsetTop - box.clientHeight / 2 + line.clientHeight / 2,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }, [index, expanded, view, follow]);
  // Reading a story voice or profile introduction pauses the music, and vice versa.
  useEffect(() => {
    const onPlay = (event: Event) => {
      if (event.target !== audio.current && event.target instanceof HTMLMediaElement) audio.current?.pause();
      if (event.target === audio.current) document.querySelectorAll('audio,video').forEach(node => {
        if (node !== audio.current) (node as HTMLMediaElement).pause();
      });
    };
    document.addEventListener('play', onPlay, true);
    return () => document.removeEventListener('play', onPlay, true);
  }, []);
  function toggle() { if (audio.current?.paused) void play(); else { request.current++; audio.current?.pause(); setLoading(false); } }
  function choose(i: number) {
    if (i === selected) { void play(); return; }
    startOnLoad.current = true; setSelected(i);
  }
  function step(direction: number) {
    if (!tracks.length) return;
    if (direction < 0 && (audio.current?.currentTime || 0) > 3) { seek(0); return; }
    const next = shuffle && tracks.length > 1
      ? (selected + 1 + Math.floor(Math.random() * (tracks.length - 1))) % tracks.length
      : (selected + direction + tracks.length) % tracks.length;
    choose(next);
  }
  function seek(value: number) {
    const player = audio.current;
    if (!player || !Number.isFinite(player.duration)) return;
    player.currentTime = Math.min(player.duration, Math.max(0, value)); setTime(player.currentTime);
  }
  function open(nextView: 'lyrics' | 'queue' = 'lyrics') { setView(nextView); setFollow(true); dialog.current?.showModal(); setExpanded(true); }
  function mute() { if (volume > 0) { lastVolume.current = volume; setVolume(0); } else setVolume(lastVolume.current); }
  useEffect(() => {
    if (!track || !('mediaSession' in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({ title: track.title, artist: track.artist, album: '学園アイドルマスター', artwork: [{ src: new URL(track.cover, location.href).href }] });
    navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
    const actions: Partial<Record<MediaSessionAction, MediaSessionActionHandler>> = {
      play: () => { void play(); }, pause: () => audio.current?.pause(),
      previoustrack: () => step(-1), nexttrack: () => step(1), seekto: event => seek(event.seekTime || 0),
    };
    for (const [key, handler] of Object.entries(actions)) { try { navigator.mediaSession.setActionHandler(key as MediaSessionAction, handler!); } catch { /* Unsupported platform action. */ } }
    return () => { for (const key of Object.keys(actions)) { try { navigator.mediaSession.setActionHandler(key as MediaSessionAction, null); } catch { /* Unsupported platform action. */ } } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track, playing, shuffle]);
  if (!track) return null;
  const progress = duration > 0 ? time / duration * 100 : 0;
  const transport = (large = false) => <div className={'music-transport' + (large ? ' music-transport-large' : '')}>
    {large && <button aria-label="随机播放" aria-pressed={shuffle} onClick={() => setShuffle(!shuffle)}><Shuffle size={18} /></button>}
    <button aria-label="上一首" onClick={() => step(-1)}><SkipBack size={large ? 24 : 19} fill="currentColor" /></button>
    <button className="music-play" aria-label={playing ? '暂停音乐' : '播放音乐'} onClick={toggle}>{loading ? <Loader2 className="music-spin" size={large ? 28 : 22} /> : playing ? <Pause size={large ? 28 : 22} fill="currentColor" /> : <Play size={large ? 28 : 22} fill="currentColor" />}</button>
    <button aria-label="下一首" onClick={() => step(1)}><SkipForward size={large ? 24 : 19} fill="currentColor" /></button>
    {large && <button aria-label="单曲循环" aria-pressed={repeat} onClick={() => setRepeat(!repeat)}>{repeat ? <Repeat1 size={18} /> : <Repeat size={18} />}</button>}
  </div>;
  const volumeControl = <div className="music-volume"><button onClick={mute} aria-label={volume ? '静音' : '取消静音'}>{volume ? <Volume2 size={18} /> : <VolumeX size={18} />}</button><input type="range" aria-label="音乐音量" min="0" max="1" step="0.01" value={volume} onChange={e => setVolume(Number(e.target.value))} /></div>;
  return <>
    <audio ref={audio} src={track.audio} preload="metadata" onPlay={() => { setPlaying(true); setLoading(false); }} onPause={() => { setPlaying(false); setLoading(false); }} onWaiting={() => setLoading(true)} onPlaying={() => setLoading(false)} onCanPlay={() => setLoading(false)} onTimeUpdate={e => setTime(e.currentTarget.currentTime)} onLoadedMetadata={e => setDuration(e.currentTarget.duration)} onEnded={() => { if (repeat) { seek(0); void play(); } else step(1); }} onError={() => { setError('歌曲未能加载，请检查本地音乐资源。'); setLoading(false); setPlaying(false); }} />
    <aside className="music-dock" aria-label="音乐播放器" hidden={expanded}>
      <button className="music-dock-track" aria-label={`展开播放器：${track.title}`} onClick={() => open()}><img src={track.cover} alt="" /><span><strong>{track.title}</strong><small>{track.artist}</small></span>{playing && <span className="music-equalizer" aria-hidden="true"><i/><i/><i/></span>}</button>
      {transport()}
      <div className="music-dock-actions">{volumeControl}<button aria-label="打开歌单" onClick={() => open('queue')}><ListMusic size={20}/></button><button aria-label="展开歌词" onClick={() => open()}><ChevronUp size={22}/></button></div>
      <input className="music-mini-progress" aria-label="迷你播放器进度" type="range" min="0" max={duration || 1} step="0.1" value={Math.min(time, duration || 1)} style={{'--progress': `${progress}%`} as CSSProperties} onChange={e => seek(Number(e.target.value))} />
      {error && <span className="music-dock-error" role="status">{error}</span>}
    </aside>
    <dialog ref={dialog} className="music-expanded" aria-label="音乐播放面板" onClose={() => setExpanded(false)} onClick={e => { if (e.target === e.currentTarget) dialog.current?.close(); }}>
      <div className="music-scene" style={{'--cover': `url("${track.cover}")`} as CSSProperties}>
        <div className="music-topbar"><span className="music-wordmark"><Disc3 size={18}/> 音乐</span><div className="music-tabs" role="group" aria-label="播放器视图"><button aria-pressed={view === 'lyrics'} onClick={() => setView('lyrics')}>歌词</button><button aria-pressed={view === 'queue'} onClick={() => setView('queue')}>歌单 <small>{tracks.length}</small></button></div><button className="music-collapse" autoFocus aria-label="缩小播放器" onClick={() => dialog.current?.close()}><ArrowDown size={20}/></button></div>
        <div className="music-stage">
          <section className="music-now" aria-label="正在播放">
            <div className={'music-artwork' + (playing ? ' is-playing' : '')}><img src={track.cover} alt={`${track.title} 歌曲封面`}/><span className="music-artwork-line"/></div>
            <div className="music-track-heading"><div><span className="music-version">{track.version.replace(/\s*·\s*FLAC$/i, '')}</span><h2>{track.title}</h2><p>{track.artist}</p></div><Music2 size={22} aria-hidden="true"/></div>
            <div className="music-seek"><input aria-label="音乐播放进度" type="range" min="0" max={duration || 1} step="0.1" value={Math.min(time, duration || 1)} style={{'--progress': `${progress}%`} as CSSProperties} onChange={e => seek(Number(e.target.value))}/><div><span>{clockTime(time)}</span><span>{clockTime(duration)}</span></div></div>
            {transport(true)}
            <div className="music-player-foot">{volumeControl}<span>{selected + 1} <em>/</em> {String(tracks.length).padStart(2, '0')}</span></div>
            {error && <p className="music-error" role="status">{error}</p>}
          </section>
          <section className="music-content" aria-label={view === 'lyrics' ? '同步歌词' : '歌曲列表'}>
            {view === 'lyrics' ? <><div className="music-lyric-meta"><span>作词 {track.credits.lyrics}</span><span>作曲 {track.credits.composer}</span></div>
              <div ref={lyrics} className="music-lyrics" tabIndex={0} aria-label="歌词，点击歌词可跳转播放" onWheel={() => setFollow(false)} onTouchMove={() => setFollow(false)} onKeyDown={e => { if (['ArrowDown','ArrowUp','PageDown','PageUp'].includes(e.key)) setFollow(false); }}>
                {track.lyrics.length ? <><div className="music-lyric-space"/>{track.lyrics.map((line, i) => <button key={`${line.start}-${i}`} ref={i === index ? currentLine : undefined} className={(i === index && active ? 'is-current ' : '') + (i < index ? 'is-past' : '')} aria-current={i === index && active ? 'true' : undefined} aria-label={`${clockTime(line.start)} ${line.text}`} onClick={() => { seek(line.start); setFollow(true); void play(); }}>{line.text}</button>)}<div className="music-lyric-end"><Disc3 size={22}/><span>{track.title}</span></div><div className="music-lyric-space"/></> : <div className="music-no-lyrics"><Music2 size={32}/><p>暂无同步歌词</p></div>}
              </div>
              {!follow && <button className="music-follow" onClick={() => setFollow(true)}>回到当前歌词</button>}
            </> : <><div className="music-queue-heading"><h3>歌曲列表</h3><span>{tracks.length} 首 · 游戏版本</span></div><input className="music-search" placeholder="搜索歌曲或角色" aria-label="搜索歌曲或角色" value={search} onChange={e => setSearch(e.target.value)}/><div className="music-queue">{tracks.map((item, i) => ({item, i})).filter(({item}) => (item.title + item.artist).toLowerCase().includes(search.toLowerCase())).map(({item, i}) => <button key={item.id} aria-label={`播放 ${item.title}`} aria-pressed={i === selected} onClick={() => choose(i)}><span className="music-track-number">{i === selected ? <Music2 size={16}/> : String(i + 1).padStart(2,'0')}</span><img src={item.cover} alt="" loading="lazy"/><span><strong>{item.title}</strong><small>{item.artist}</small></span><Play size={16}/></button>)}{!tracks.some(t => (t.title+t.artist).toLowerCase().includes(search.toLowerCase())) && <p className="music-empty">没有匹配的歌曲</p>}</div></>}
          </section>
        </div>
        <div className="music-bottom-note"><span>学園アイドルマスター</span><span>{playing ? '正在播放' : '已暂停'}<i className={playing ? 'playing' : ''}/></span></div>
      </div>
    </dialog>
  </>;
}
