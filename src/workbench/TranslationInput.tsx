import { useRef, useState } from 'react';
import { csvText, editorText, insertFormat, lineLengths } from './text-format';
export function TranslationInput({ value, index, disabled, onChange }: { value: string; index: number; disabled: boolean; onChange: (value: string) => void }) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [error, setError] = useState('');
  const [ruby, setRuby] = useState<{ start: number; end: number } | null>(null);
  const [annotation, setAnnotation] = useState('');
  const text = editorText(value);
  const lengths = lineLengths(text);
  const over = lengths.flatMap((n, i) => n > 21 ? [`第 ${i + 1} 行 ${n} 字`] : []);
  function format(kind: 'em' | 'ruby', apply = false) {
    const area = textarea.current;
    if (!area) return;
    if (kind === 'ruby' && !apply) { setRuby({ start: area.selectionStart, end: area.selectionEnd }); setAnnotation(''); return; }
    try {
      const next = insertFormat(text, ruby?.start ?? area.selectionStart, ruby?.end ?? area.selectionEnd, kind, annotation);
      setError(''); setRuby(null); onChange(csvText(next.text));
      requestAnimationFrame(() => { area.focus(); area.setSelectionRange(next.start, next.end); });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <div className="translation-input">
    <div className="translation-tools" role="group" aria-label={`第 ${index + 1} 行格式工具`}>
      <button type="button" disabled={disabled || !!ruby} title="给选中文字添加强调点" onMouseDown={e => e.preventDefault()} onClick={() => format('em')}>强调点</button>
      <button type="button" disabled={disabled || !!ruby} title="给选中文字添加上方注音" onMouseDown={e => e.preventDefault()} onClick={() => format('ruby')}>注音</button>
      <span className={over.length ? 'translation-length-warning' : ''}>{lengths.join(' / ')} 字</span>
    </div>
    {ruby && <div className="translation-ruby" role="group" aria-label={`第 ${index + 1} 行注音设置`}>
      <input autoFocus aria-label="上方注音" placeholder="例如 Prima Stella" value={annotation} disabled={disabled} onChange={e => setAnnotation(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); format('ruby', true); } if (e.key === 'Escape') setRuby(null); }} />
      <button type="button" disabled={disabled || !annotation.trim()} onClick={() => format('ruby', true)}>插入注音</button>
      <button type="button" onClick={() => { setRuby(null); textarea.current?.focus(); }}>取消</button>
    </div>}
    <textarea ref={textarea} aria-label={`第 ${index + 1} 行译文`} aria-describedby={over.length ? `line-warning-${index}` : undefined} placeholder="填写译文，回车换行" rows={3} value={text} disabled={disabled || !!ruby} onChange={e => onChange(csvText(e.target.value))} />
    {over.length > 0 && <small id={`line-warning-${index}`} className="translation-length-warning">{over.join('，')}，建议每行不超过 21 字</small>}
    {error && <small role="alert">{error}</small>}
  </div>;
}
