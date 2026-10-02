import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lyricIndex, clockTime } from './lyrics';
test('lyrics support prelude, exact boundaries, instrumental gaps and backwards seeking', () => {
  const lines = [{start: 3, end: 5, text: 'a'}, {start: 7, end: 9, text: 'b'}];
  assert.equal(lyricIndex([], 4), -1);
  assert.equal(lyricIndex(lines, 2), -1);
  assert.equal(lyricIndex(lines, 3), 0);
  assert.equal(lyricIndex(lines, 6), 0);
  assert.equal(lyricIndex(lines, 7), 1);
  assert.equal(lyricIndex(lines, 100), 1);
  assert.equal(lyricIndex(lines, 4), 0);
});
test('duration handles absent metadata and displays minutes', () => {
  assert.equal(clockTime(NaN), '0:00');
  assert.equal(clockTime(Infinity), '0:00');
  assert.equal(clockTime(-1), '0:00');
  assert.equal(clockTime(125.9), '2:05');
});
