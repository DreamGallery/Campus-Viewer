// CSV uses literal backslash-n; textarea uses real line breaks.
export const editorText = (text: string) => text.replace(/\\n/g, '\n').replace(/\r\n?/g, '\n');
export const csvText = (text: string) => text.replace(/\r\n?|\n/g, '\\n');
export const textBody = (text: string) => editorText(text).replace(/(?:\n[^\S\n]*)+$/, '');
export const hasTranslation = (text: string) => editorText(text).trim().length > 0;
export const cleanTranslation = (text: string) => hasTranslation(text) ? csvText(textBody(text)) : '';
export function lineLengths(text: string): number[] {
  // Count visible base text only, not markup or ruby annotations.
  return textBody(text.replace(/<\/?(?:em|r)(?:\\?=[^>]*|\s[^>]*)?>/g, '')).split('\n').map(line => Array.from(line).length);
}
export function lineBreakMismatch(source: string, translation: string) {
  if (!hasTranslation(translation)) return null;
  const expected = textBody(source).split('\n').length - 1;
  const actual = textBody(translation).split('\n').length - 1;
  return expected === actual ? null : { expected, actual };
}
export function validateLineBreaks(rows: { text: string; trans: string }[]) {
  const errors = rows.flatMap((row, i) => {
    const mismatch = lineBreakMismatch(row.text, row.trans);
    return mismatch ? [`第 ${i + 1} 条台词的正文换行数量不一致（原文 ${mismatch.expected} 处，译文 ${mismatch.actual} 处）`] : [];
  });
  if (errors.length) throw new Error(errors.join('；'));
}
export function longLines(rows: { trans: string }[]) {
  return rows.flatMap((row, i) => lineLengths(row.trans).flatMap((length, line) => length > 21 ? [{ row: i + 1, line: line + 1, length }] : []));
}
export function insertFormat(text: string, start: number, end: number, kind: 'em' | 'ruby', annotation = '') {
  const selected = text.slice(start, end) || '文字';
  if (kind === 'ruby' && /[<>\r\n\\]/.test(annotation)) throw new Error('注音不能包含尖括号、反斜杠或换行');
  const open = kind === 'em' ? '<em\\=>' : `<r\\=${annotation}>`;
  const close = kind === 'em' ? '</em>' : '</r>';
  return { text: text.slice(0, start) + open + selected + close + text.slice(end), start: start + open.length, end: start + open.length + selected.length };
}
