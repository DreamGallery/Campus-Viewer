export interface LyricLine { start: number; end: number; text: string }
export function lyricIndex(lines: LyricLine[], time: number) {
  let left = 0, right = lines.length - 1, index = -1;
  while (left <= right) {
    const middle = (left + right) >> 1;
    if (lines[middle].start <= time) { index = middle; left = middle + 1; }
    else right = middle - 1;
  }
  return index;
}
export function clockTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return '0:00';
  return Math.floor(value / 60) + ':' + String(Math.floor(value % 60)).padStart(2, '0');
}
