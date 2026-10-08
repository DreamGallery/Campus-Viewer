import { api, decode, Github } from './github';
import { extractInfoFromCsvText, type CsvDataLine } from './upstream/csv';
import { type DocTask, buildChineseTxt, fetchNameDict, WORK_BRANCH, WORK_OWNER, WORK_REPO } from './upstream/workflow';

// Manual, batch and proofread exports use the same command-aware merger.
export function translatedScript(raw: string, rows: CsvDataLine[], nameDict: Record<string, string> = {}): string {
  return buildChineseTxt(raw, rows, nameDict);
}
export async function exportTxt(id: string, csv: string): Promise<string> {
  const [{ txt }, nameDict] = await Promise.all([
    api<{ txt: string }>('script/' + encodeURIComponent(id)), fetchNameDict(),
  ]);
  return translatedScript(txt, extractInfoFromCsvText(csv).data, nameDict);
}
export function downloadFile(content: BlobPart, name: string, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
export type ExportStage = 'best' | 'translated' | 'proofread' | 'ai';
export async function taskCsv(w: Github, task: DocTask, stage: ExportStage): Promise<string> {
  const candidates = stage === 'best' ? [task.proofreadPath, task.translatedPath] : [stage === 'ai' ? task.aiPath : stage === 'proofread' ? task.proofreadPath : task.translatedPath];
  for (const path of [...new Set(candidates)].filter(Boolean)) {
    try { return decode((await w.getContent(WORK_OWNER, WORK_REPO, WORK_BRANCH, path)).content); }
    catch (e) { if ((e as { response?: { status: number } }).response?.status !== 404) throw e; }
  }
  throw new Error('所选阶段没有稿件');
}
