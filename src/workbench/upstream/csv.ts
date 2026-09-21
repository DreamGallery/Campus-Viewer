import { csvText } from '../text-format';
import Papa from 'papaparse';
export interface CsvDataLine { id: string; name: string; text: string; trans: string; [key: string]: string }
export interface CsvTextInfo { data: CsvDataLine[]; translator: string; jsonUrl: string; records: CsvDataLine[]; fields: string[] }
export function extractInfoFromCsvText(text: string): CsvTextInfo {
  const parsed = Papa.parse<CsvDataLine>(text.replace(/^\uFEFF/, ''), { header: true, skipEmptyLines: 'greedy' });
  if (parsed.errors.length || !['id', 'name', 'text', 'trans'].every(k => parsed.meta.fields?.includes(k))) throw new Error('CSV 格式不正确，需要 id / name / text / trans 列');
  const records = parsed.data.map(r => ({ ...r, trans: r.trans || '' }));
  const info = records.find(r => r.id === 'info');
  if (!info) throw new Error('CSV 缺少 info 元数据');
  return { data: records.filter(r => r.id !== 'info' && r.id !== '译者' && r.text), translator: records.find(r => r.id === '译者')?.name || '', jsonUrl: info.name, records, fields: parsed.meta.fields! };
}
export function toCsvText(info: CsvTextInfo): string {
  let index = 0;
  const rows: CsvDataLine[] = info.records.map(row => row.id === '译者' ? { ...row, name: info.translator } : row.id !== 'info' && row.text ? { ...row, trans: csvText(info.data[index++].trans) } : { ...row });
  if (!rows.some(r => r.id === '译者')) rows.push({ id: '译者', name: info.translator, text: '', trans: '' });
  return Papa.unparse({ fields: info.fields, data: rows.map(row => info.fields.map(k => row[k] || '')) }, { newline: '\r\n' });
}
export function setCsvTranslator(text: string, name: string): string { return toCsvText({ ...extractInfoFromCsvText(text), translator: name }); }
export function mergeTranslation(source: CsvTextInfo, text: string): CsvTextInfo {
  const translated = extractInfoFromCsvText(text);
  if (translated.jsonUrl !== source.jsonUrl || translated.data.length !== source.data.length || source.data.some((r, i) => ['id', 'name', 'text'].some(k => r[k] !== translated.data[i][k]))) throw new Error('译文与当前原文不一致，未导入。请检查章节、行顺序或原文版本');
  return { ...source, translator: translated.translator, data: source.data.map((r, i) => ({ ...r, trans: translated.data[i].trans })) };
}
