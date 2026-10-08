import test from 'node:test';
import assert from 'node:assert/strict';
import { translatedScript, taskCsv, exportTxt } from './export';
import { type CsvDataLine } from './upstream/csv';
import { type Github } from './github';
import { docFromIssue, fetchNameDict, buildChineseTxt } from './upstream/workflow';
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

test('speaker dictionary changes only whole message names without cascading or touching dialogue', () => {
 const raw = '[message name=咲季 text=咲季]\r\n[message text=同文 name=咲季たち]\r\n[message text=name\\=咲季 name=花海 咲季]\r\n[chara name=咲季]\r\n[message text=未訳 name=未登録]';
 const rows = [row('咲季', '咲季', '咲季'), row('同文', '', '咲季たち'), row('name\\=咲季', '', '花海 咲季'), row('未訳', '', '未登録')];
 const dict = {'咲季':'咲季訳', '咲季訳':'不应再次替换', '花海 咲季':'花海 咲季 [晨]=好'};
 const expected = '[message name=咲季訳 text=咲季]\r\n[message text=同文 name=咲季たち]\r\n[message text=name\\=咲季 name=花海 咲季 \\[晨\\]\\=好]\r\n[chara name=咲季]\r\n[message text=未訳 name=未登録]';
 assert.equal(translatedScript(raw, rows, dict), expected);
 assert.equal(buildChineseTxt(raw, rows, dict), expected);
});

test('dictionary handles markup and empty dialogue, keeps unknown and empty translations', () => {
 const ruby = '<r\\=プリマステラ>一番星</r>';
 const translated = '<r\\=Prima Stella>启明星</r>';
 assert.equal(translatedScript(`[message name=${ruby} text=原文][message name=咲季 text=][message name=constructor text=]`, [row('原文', '译文', ruby)], {[ruby]: translated, '咲季':''}), `[message name=${translated} text=译文][message name=咲季 text=][message name=constructor text=]`);
});

test('TXT exports share the upstream dictionary download, retry failures and refresh cached names', async t => {
 let requests = 0, now = 1000, mode: 'error' | 'invalid' | 'ok' = 'error';
 t.mock.method(Date, 'now', () => now);
 t.mock.method(globalThis, 'fetch', async (url: string) => {
   if (url.startsWith('/api/script/')) return Response.json({txt:'[message name=ことね text=原文]'});
   assert.equal(url, 'https://raw.githubusercontent.com/chihya72/Gakumas-Auto-Translate/master/name_dictionary.json');
   requests++;
   if (mode === 'error') return new Response('', {status:503});
   return Response.json(mode === 'invalid' ? {ことね:5} : {ことね:'琴音'});
 });
 await assert.rejects(fetchNameDict, /人名字典加载失败/);
 mode = 'invalid'; await assert.rejects(fetchNameDict, /人名字典加载失败/);
 mode = 'ok';
 const csv = 'id,name,text,trans\ninfo,adv_test.txt,,\n0000000000000,ことね,原文,译文\n';
 const results = await Promise.all([exportTxt('adv_a',csv),exportTxt('adv_b',csv)]);
 assert.deepEqual(results,['[message name=琴音 text=译文]','[message name=琴音 text=译文]']);
 await fetchNameDict(); assert.equal(requests,3);
 now += 5 * 60 * 1000; await fetchNameDict(); assert.equal(requests,4);
});
