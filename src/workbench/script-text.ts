import { csvText } from './text-format';
import type { CsvDataLine } from './upstream/csv';

export function mergeScriptText(raw: string, rows: CsvDataLine[]): string {
  const pending = rows.filter(r => r.text && !['info', '译者'].includes(r.id));
  const used = new Set<number>();
  const changes: { start: number; end: number; text: string }[] = [];
  const pattern = /\[(message|choice|title|narration)\b/g;
  for (const command of raw.matchAll(pattern)) {
    // Skip escaped literal brackets within a text value.
    let slashes = 0; for (let j = command.index! - 1; j >= 0 && raw[j] === '\\'; j--) slashes++;
    if (slashes % 2) continue;
    let pos = command.index! + command[0].length;
    const attrs: Record<string, { start: number; end: number; value: string }> = {};
    while (pos < raw.length && raw[pos] !== ']') {
      const field = /^[ \t]+([A-Za-z_][\w]*)=/.exec(raw.slice(pos));
      if (!field) throw new Error('原脚本属性格式无法识别');
      pos += field[0].length;
      const start = pos; let depth = 0;
      while (pos < raw.length) {
        if (raw[pos] === '\\' && pos + 1 < raw.length) {
          if (raw[pos + 1] === '{') depth++;
          if (raw[pos + 1] === '}') depth--;
          pos += 2; continue;
        }
        if (!depth && (raw[pos] === ']' || /^[ \t]+[A-Za-z_]\w*=/.test(raw.slice(pos)))) break;
        pos++;
      }
      attrs[field[1]] = { start, end: pos, value: raw.slice(start, pos) };
    }
    const text = attrs[command[1] === 'title' ? 'title' : 'text'];
    if (!text?.value.trim()) continue;
    const name = command[1] === 'title' ? '__title__' : command[1] === 'narration' ? '__narration__' : command[1] === 'choice' ? '' : (attrs.name?.value || '__narration__');
    const i = pending.findIndex((r, n) => !used.has(n) && r.text.trim() === text.value.trim() && (command[1] === 'choice' ? r.id === 'select' : r.id !== 'select' && (r.name === name || command[1] === 'message' && !attrs.name?.value && ['', '__narration__'].includes(r.name))));
    if (i < 0 && command[1] === 'title' && !pending.some(r => r.name === '__title__')) continue;
    if (i < 0) throw new Error(`原脚本与 CSV 不一致：${text.value.slice(0, 35)}`);
    used.add(i);
    if (pending[i].trans.trim()) {
      const value = csvText(pending[i].trans).replace(/\\.|[[\]=]/g, token => token.startsWith('\\') ? token : '\\' + token);
      changes.push({ start: text.start, end: text.end, text: value });
    }
  }
  if (used.size !== pending.length) throw new Error(`有 ${pending.length - used.size} 条 CSV 原文未匹配到脚本，已停止 TXT 导出`);
  return changes.reverse().reduce((text, c) => text.slice(0, c.start) + c.text + text.slice(c.end), raw);
}
