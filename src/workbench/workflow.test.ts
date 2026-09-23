import { completionStats } from './completion-stats';
import { docFromIssue, setAssigneeUsers } from './upstream/workflow';
import { csvText, editorText, lineLengths, longLines, insertFormat } from './text-format';
import test from 'node:test';
import assert from 'node:assert/strict';
import { extractInfoFromCsvText, toCsvText, mergeTranslation, setCsvTranslator } from './upstream/csv';
import { completionPath, myStatusOf, validateRowsHtmlTags, saveDraft, completeStage, StaleRevisionError } from './upstream/workflow';
const csv='id,name,text,trans,extra\r\n000,A,"one,\ntwo",,keep\r\n000,A,second,,keep2\r\ninfo,test.txt,,,metadata\r\n译者,old,,,';
test('CSV round trip preserves duplicate IDs, multiline cells and metadata without mutation',()=>{const d=extractInfoFromCsvText(csv);d.data[0].trans='中,文\n"引号"';const copy=JSON.stringify(d);const out=extractInfoFromCsvText(toCsvText(d));assert.equal(out.data.length,2);assert.equal(out.data[0].trans,'中,文\\n"引号"');assert.equal(out.records[2].extra,'metadata');assert.equal(JSON.stringify(d),copy);});
test('translation import rejects reordered duplicate IDs',()=>{const d=extractInfoFromCsvText(csv);const swapped={...d,data:[d.data[1],d.data[0]]}; const wrong=toCsvText(d).replace('second','changed');assert.throws(()=>mergeTranslation(d,wrong),/不一致/);assert.equal(swapped.data[0].id,swapped.data[1].id);});
test('translator with commas and newline is escaped correctly',()=>{assert.equal(extractInfoFromCsvText(setCsvTranslator(csv,'a,\nb')).translator,'a,\nb');});
test('stage path and proofread prerequisite retained',()=>{assert.equal(completionPath('', 'adv_dear_hski_001','tr'),'translated_csv/adv/dear/hski/001.csv');assert.equal(myStatusOf({user:'other',state:'进行中'},{user:'me',state:'进行中'},'me','pr').blocked,true);});
test('unbalanced translation markup rejected',()=>assert.ok(validateRowsHtmlTags([{id:'0',text:'a',trans:'<b>a'}]).length));
const b64=(s:string)=>Buffer.from(s).toString('base64');
function fake(record: object) { let written: {path:string;content:string|null}[]=[];return {get written(){return written;},async getContent(_a:string,_b:string,_c:string,path:string){if(path.startsWith('records/'))return {content:b64(JSON.stringify(record))};throw {response:{status:404}};},async commitFiles(_a:string,_b:string,_c:string,_m:string,files: typeof written){written=files;return 'commit';}}; }
test('draft writes CSV and record in a single commit without completing track',async()=>{const w=fake({translation:{revision:3,state:'进行中'},artifacts:{}});await saveDraft(w,{fileId:'test',role:'tr',sourcePath:'',contentB64:b64(csv),operatorGithub:'me'});assert.equal(w.written.length,2);const record=JSON.parse(Buffer.from(w.written[1].content!,'base64').toString());assert.equal(record.translation.state,'进行中');assert.equal(record.translation.revision,3);assert.equal(record.artifacts.translation_draft.based_on_revision,3);});
test('completion rejects stale revision before any commit',async()=>{const w=fake({translation:{revision:4},artifacts:{}});await assert.rejects(()=>completeStage(w,{fileId:'test',role:'tr',sourcePath:'',contentB64:b64(csv),operatorGithub:'me',baseRevision:3}),StaleRevisionError);assert.equal(w.written.length,0);});

test('completion commits formal CSV and incremented record together',async()=>{const w=fake({translation:{revision:1,state:'进行中'},proofread:{revision:0},artifacts:{}});const result=await completeStage(w,{fileId:'test',role:'tr',sourcePath:'',contentB64:b64(csv),operatorGithub:'me',baseRevision:1});assert.equal(result.commitSha,'commit');assert.ok(w.written.some(f=>f.path==='translated_csv/test.csv'));const record=JSON.parse(Buffer.from(w.written.find(f=>f.path==='records/test.json')!.content!,'base64').toString());assert.equal(record.translation.revision,2);assert.equal(record.translation.state,'完成');});

test('editor line breaks serialize as literal backslash-n without changing source',()=>{assert.equal(csvText('甲\n乙\r\n丙'), '甲\\n乙\\n丙');assert.equal(editorText('甲\\n乙'), '甲\n乙');const d=extractInfoFromCsvText(csv);d.data[0].trans='甲\n乙';const out=extractInfoFromCsvText(toCsvText(d));assert.equal(out.data[0].trans,'甲\\n乙');assert.equal(out.data[0].text,d.data[0].text);});
test('length limit excludes formatting and ruby annotations, counts punctuation and Unicode',()=>{assert.deepEqual(lineLengths('<em\\=>文字</em>『<r\\=Prima Stella>启明星</r>』\\n你好！'),[7,3]);assert.equal(longLines([{trans:'字'.repeat(21)}]).length,0);assert.deepEqual(longLines([{trans:'字'.repeat(22)+'\\n短句'}]),[{row:1,line:1,length:22}]);assert.deepEqual(lineLengths('😀'),[1]);});
test('format wraps selected text and returns editable selection',()=>{const em=insertFormat('前文字后',1,3,'em');assert.equal(em.text,'前<em\\=>文字</em>后');assert.equal(em.text.slice(em.start,em.end),'文字');assert.equal(insertFormat('启明星',0,3,'ruby','Prima Stella').text,'<r\\=Prima Stella>启明星</r>');assert.equal(insertFormat('',0,0,'em').text,'<em\\=>文字</em>');assert.throws(()=>insertFormat('',0,0,'ruby','a>b'));});

test('completion stats merge aliases, ignore unfinished tracks and deduplicate chapters',()=>{setAssigneeUsers({alice:{github:'AliceGH',qq:'123'}});const make=(number:number,title:string,tr:string,pr:string)=>docFromIssue({number,title,updated_at:'2026-01-01',body:`<!-- tr:${tr} -->\n<!-- pr:${pr} -->`});const a=make(1,'story1','qq-123:完成','AliceGH:完成');const stats=completionStats([a,a,make(2,'story2','alice:完成','bob:进行中'),make(3,'story3',':完成','bob:完成')]);assert.deepEqual(stats.find(s=>s.id==='alicegh'),{id:'alicegh',name:'alice',translation:2,proofread:1,total:3,chapters:2});assert.equal(stats.find(s=>s.id==='bob')?.total,1);assert.equal(stats.length,2);setAssigneeUsers({});});

// Personal display IDs must not replace the authentication identity written to tasks.
import { displayWorkUser, findWorkUser, sameWorkUser, canonicalOperator } from './upstream/workflow';
test('user directory resolves personal ID, GitHub case and QQ aliases',()=>{
 setAssigneeUsers({'病毒':{github:'kitsurato',qq:'12345'},'QQ成员':{github:'',qq:'67890'}});
 for(const value of ['病毒','kitsurato','KITSURATO','qq-12345','12345'])assert.equal(displayWorkUser(value),'病毒');
 assert.equal(displayWorkUser('qq-67890'),'QQ成员');assert.equal(displayWorkUser(''), '');assert.equal(findWorkUser(''),undefined);
 assert.equal(displayWorkUser('unknown'),'unknown');assert.ok(sameWorkUser('qq-12345','kitsurato'));assert.equal(canonicalOperator('病毒'),'kitsurato');
 const task=docFromIssue({number:1,title:'test',body:'<!-- tr:qq-12345:完成 -->\n<!-- pr:kitsurato:完成 -->'});assert.equal(completionStats([task])[0].total,2);assert.equal(completionStats([task])[0].name,'病毒');
 setAssigneeUsers({a:{github:'duplicate'},b:{github:'DUPLICATE'}});assert.equal(findWorkUser('duplicate'),undefined);setAssigneeUsers({});
});

import { buildChineseTxt } from './upstream/workflow';
test('proofread TXT uses occurrence matching and preserves name dictionary behavior',()=>{
 const raw='[message text=同文 name=A]\n[message text=同文 name=A]';
 const rows=[{id:'0000000000000',name:'A',text:'同文',trans:'第一句'},{id:'0000000000000',name:'A',text:'同文',trans:'第二句'}];
 assert.equal(buildChineseTxt(raw,rows,{A:'甲'}),'[message text=第一句 name=甲]\n[message text=第二句 name=甲]');
 assert.throws(()=>buildChineseTxt(raw,rows.slice(0,1),{}),/不一致/);
});

import { applyTrack } from './upstream/workflow';
test('batch claim rechecks the latest track and never reopens a completed or owned task',async()=>{
 for(const state of ['进行中','完成']) {
  let writes=0;
  const w={getIssue:async()=>({body:`<!-- tr:other:${state} -->\n<!-- pr::待认领 -->`}),updateIssue:async()=>{writes++;}};
  await assert.rejects(()=>applyTrack(w,1,'tr',{user:'me',state:'进行中'},true),/不再待认领/);
  assert.equal(writes,0);
 }
});
test('batch claim preserves the other workflow track',async()=>{
 let update:any;
 const w={getIssue:async()=>({body:'<!-- tr::待认领 -->\n<!-- pr:reviewer:进行中 -->'}),updateIssue:async(_o:string,_r:string,_n:number,p:any)=>{update=p;}};
 await applyTrack(w,1,'tr',{user:'me',state:'进行中'},true);
 assert.match(update.body,/tr:me:进行中/);assert.match(update.body,/pr:reviewer:进行中/);assert.equal(update.state,'open');
});

import { completionTranslator } from './upstream/workflow';
test('translation completion signs with the users.json display ID',async()=>{
 const w=fake({translation:{revision:0}}), read=w.getContent;
 w.getContent=async(a,b,c,path)=>path==='users.json'?{content:b64(JSON.stringify({'个人名字':{github:'Me'}}))}:read(a,b,c,path);
 await completeStage(w,{fileId:'test',role:'tr',sourcePath:'',contentB64:b64(csv),operatorGithub:'me',baseRevision:0});
 const file=w.written.find(f=>f.path==='translated_csv/test.csv')!;
 assert.equal(extractInfoFromCsvText(Buffer.from(file.content!,'base64').toString()).translator,'翻译：个人名字');
});
test('proofreading preserves formal translator over imported attribution and records',async()=>{
 const w={getContent:async()=>({content:b64(setCsvTranslator(csv,'原译者'))})};
 assert.equal(await completionTranslator(w,{role:'pr',sourcePath:'',fileId:'test',contentB64:b64(csv)},{translation:{display_id:'其他署名'}},'校对者'),'原译者');
});
test('legacy proofreading falls back to original translator record or CSV, never reviewer',async()=>{
 const opts={role:'pr' as const,sourcePath:'',fileId:'test',contentB64:b64(csv)};
 assert.equal(await completionTranslator(fake({}),opts,{translation:{display_id:'记录译者'}},'校对者'),'记录译者');
 assert.equal(await completionTranslator(fake({}),opts,{},'校对者'),'old');
 assert.equal(await completionTranslator(fake({}),opts,{direct_machine_proofread:true},'校对者'),'校对者');
 await assert.rejects(()=>completionTranslator({getContent:async()=>{throw {response:{status:500}};}},opts,{},'校对者'));
});

import { originalTranslator, completionCredit } from './upstream/workflow';
test('single-row credits preserve legacy names and replace reviewer without duplication',()=>{
 assert.equal(originalTranslator('原译者'),'原译者');
 assert.equal(originalTranslator('翻译：原译者；校对：旧校对'),'原译者');
 assert.equal(completionCredit(originalTranslator('翻译：原译者；校对：旧校对'),'新校对'),'翻译：原译者；校对：新校对');
 const signed=setCsvTranslator(csv,'翻译：原译者；校对：新校对');
 const out=extractInfoFromCsvText(toCsvText(mergeTranslation(extractInfoFromCsvText(csv),signed)));
 assert.equal(out.translator,'翻译：原译者；校对：新校对');
 assert.equal(out.records.filter(r=>r.id==='译者').length,1);assert.equal(out.records.some(r=>r.id==='校对'),false);assert.equal(out.data.length,2);
});
test('proofread completion credits translator and reviewer in the existing row',async(t)=>{
 t.mock.method(globalThis,'fetch',async()=>{throw new Error('No external TXT fetch in this test');});
 const w=fake({translation:{revision:1,state:'完成',display_id:'原译者'},proofread:{revision:0}}),read=w.getContent;
 w.getContent=async(a,b,c,path)=>path==='users.json'?{content:b64(JSON.stringify({'校对名字':{github:'reviewer'}}))}:path==='translated_csv/test.csv'?{content:b64(setCsvTranslator(csv,'翻译：原译者'))}:read(a,b,c,path);
 await completeStage(w,{fileId:'test',role:'pr',sourcePath:'',contentB64:b64(csv),operatorGithub:'reviewer',baseRevision:0});
 const output=extractInfoFromCsvText(Buffer.from(w.written.find(f=>f.path==='proofread_csv/test.csv')!.content!,'base64').toString());
 assert.equal(output.translator,'翻译：原译者；校对：校对名字');assert.equal(output.records.some(r=>r.id==='校对'),false);
 const record=JSON.parse(Buffer.from(w.written.find(f=>f.path==='records/test.json')!.content!,'base64').toString());
 assert.equal(record.translation.display_id,'原译者');assert.equal(record.proofread.display_id,'校对名字');
});
