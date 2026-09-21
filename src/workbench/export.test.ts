import test from 'node:test';
import assert from 'node:assert/strict';
import { translatedScript, taskCsv } from './export';
import { type CsvDataLine } from './upstream/csv';
import { type Github } from './github';
import { docFromIssue } from './upstream/workflow';
const row = (text: string, trans: string, name = 'A', id = '0000000000000'): CsvDataLine => ({ id, name, text, trans });
test('duplicate dialogue is replaced independently without changing commands or line endings', () => {
 const raw='[message text=はい name=A clip=timing]\r\n[voice voice=x]\r\n[message text=はい name=A]\r\n';
 assert.equal(translatedScript(raw,[row('はい','好'),row('はい','是的')]),'[message text=好 name=A clip=timing]\r\n[voice voice=x]\r\n[message text=是的 name=A]\r\n');
});
test('choices, titles, narration, markup and newlines preserve script escaping', () => {
 const raw='[title title=原題]\n[choicegroup choices=[choice text=選択 id=1][choice text=取消 id=2]]\n[narration text=原文]';
 assert.equal(translatedScript(raw,[row('原題','标题','__title__'),row('選択','选择','','select'),row('取消','','','select'),row('原文','<r\\=Prima Stella>启明星</r>\n[注]=好','__narration__')]),'[title title=标题]\n[choicegroup choices=[choice text=选择 id=1][choice text=取消 id=2]]\n[narration text=<r\\=Prima Stella>启明星</r>\\n\\[注\\]\\=好]');
});
test('mismatch, missing rows, and malformed markup refuse TXT output',()=>{
 assert.throws(()=>translatedScript('[message text=one name=A]',[row('two','中')]),/不一致/);
 assert.throws(()=>translatedScript('',[row('one','中')]),/未匹配/);
 assert.throws(()=>translatedScript('[message text=one name=A]',[row('one','<em\\=>中')]),/标签/);
});
test('translation never cascades into following source occurrences',()=>assert.equal(translatedScript('[message text=a name=A]\n[message text=b name=A]',[row('a','b'),row('b','$&')]),'[message text=b name=A]\n[message text=$& name=A]'));
test('best stage falls back only on missing file; never masks authorization failures',async()=>{
 const task=docFromIssue({number:1,title:'adv_test',body:'',updated_at:''});const paths:string[]=[];
 const w={async getContent(_a:string,_b:string,_c:string,path:string){paths.push(path);if(path===task.proofreadPath)throw {response:{status:404}};return {content:Buffer.from('csv').toString('base64')};}} as unknown as Github;
 assert.equal(await taskCsv(w,task,'best'),'csv');assert.deepEqual(paths,[task.proofreadPath,task.translatedPath]);
 const denied={async getContent(){throw {response:{status:403}};}} as unknown as Github;await assert.rejects(()=>taskCsv(denied,task,'best'));
});

test('unlisted titles stay unchanged and unnamed message narration is supported',()=>{const raw='[title title=1話]\n[message text=旁白 hide=true]\n[message text=心声 isInner=true]';assert.equal(translatedScript(raw,[row('旁白','叙述','__narration__'),row('心声','内心','')]),'[title title=1話]\n[message text=叙述 hide=true]\n[message text=内心 isInner=true]');});
