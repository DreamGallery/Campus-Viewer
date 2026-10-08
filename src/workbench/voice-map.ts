import type { ChapterVoices } from '../catalog';
import type { CsvTextInfo } from './upstream/csv';

export type VoiceLine = ChapterVoices['lines'][number];
export function chapterVoiceMap(source: CsvTextInfo | null, sourceHash: string, voices?: ChapterVoices) {
  const result = new Map<number, VoiceLine>();
  if (!source || !sourceHash || voices?.source_sha256 !== sourceHash) return result;
  const indexes = new Map(source.data.map((row, index) => [row, index]));
  for (const line of voices.lines) {
    const record = source.records[line.record_index - 1];
    const index = indexes.get(record);
    if (index !== undefined && record.text === line.text && record.name === line.speaker) result.set(index, line);
  }
  return result;
}
