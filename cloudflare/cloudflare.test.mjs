import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {getPlatformProxy, createTestHarness} from 'wrangler';
import {sessionStore} from './session.mjs';
import {resources} from './resources.mjs';

async function fixture(fn) {
  const proxy=await getPlatformProxy({configPath:'wrangler.jsonc',persist:false});
  try {await fn(proxy.env.RESOURCES,proxy.env.DB);} finally {await proxy.dispose();}
}
test('D1 encrypted sessions survive new store instances; OAuth consumption is atomic',()=>fixture(async (_bucket,db)=>{
  await db.exec((await readFile(new URL('./migrations/0001_sessions.sql',import.meta.url),'utf8')).replace(/\n/g,' '));
  const secret='test-secret-'.repeat(4);
  const a=sessionStore(db,secret,'session'), b=sessionStore(db,secret,'session');
  await a.set('cookie-id',{token:'private-github-token',expires:Date.now()+60000});
  const raw=await db.prepare('SELECT * FROM auth_state').first();
  assert.notEqual(raw.id,'cookie-id');assert.ok(!raw.value.includes('private-github-token'));
  assert.equal((await b.get('cookie-id')).token,'private-github-token');
  const rotated=sessionStore(db,'new-secret-'.repeat(4),'session');
  assert.equal(await rotated.get('cookie-id'),undefined);
  await assert.rejects(()=>sessionStore(db,'short','session').get('cookie-id'),/SESSION_SECRET/);
  await db.prepare('UPDATE auth_state SET value=? WHERE namespace=?').bind('invalid-base64!', 'session').run();
  assert.equal(await a.get('cookie-id'),undefined);
  await b.delete('cookie-id');assert.equal(await a.get('cookie-id'),undefined);
  await a.set('expired',{expires:1});assert.equal(await b.get('expired'),undefined);
  const oauth=sessionStore(db,secret,'oauth');await oauth.set('state',{expires:Date.now()+60000});
  const taken=await Promise.all([oauth.take('state'),oauth.take('state')]);assert.equal(taken.filter(Boolean).length,1);
}));
test('R2 routes cold start, immutable catalog, source reads, range and download allowlist',()=>fixture(async bucket=>{
  const data=resources({RESOURCES:bucket,CAMPUS_R2_PREFIX:'test'});
  assert.equal((await data.status()).state,'initializing');
  await assert.rejects(()=>data.sourceRoots(),{status:503});
  const name='campus-resources-r63-abcdef123456.tar.gz';
  await bucket.put('test/current.json',JSON.stringify({release:'r1',versions:{revision:63,versions:[{filename:name}]}}));
  await bucket.put('test/releases/r1/web/catalog/manifest.json',JSON.stringify({base_path:'/catalog/releases/r1/builds/x'}));
  await bucket.put('test/releases/r1/web/catalog/builds/x/chapters/adv_a.json','{"csv_path":"CSV/a.csv"}');
  await bucket.put('test/releases/r1/story/CSV/a.csv','name,text');
  await bucket.put('test/downloads/'+name,'0123456789');
  const req=(path,opts)=>new Request('https://site.test'+path,opts);
  assert.equal((await data.status()).revision,63);
  const roots=await data.sourceRoots();assert.equal(await data.readFile(roots.story,'CSV/a.csv'),'name,text');
  assert.ok(await data.readFile(roots.web,'catalog/releases/r1/builds/x/chapters/adv_a.json'));
  await assert.rejects(()=>data.readFile(roots.story,'../secret'),{status:400});
  await assert.rejects(()=>data.readFile(roots.web,'catalog/releases/r2/manifest.json'),{status:400});
  assert.equal((await data.route(req('/catalog/manifest.json'))).status,200);
  const response=await data.route(req('/api/resources/download/'+name,{headers:{Range:'bytes=2-5'}}));
  assert.equal(response.status,206);assert.equal(await response.text(),'2345');
  assert.equal((await data.route(req('/api/resources/download/'+name,{headers:{Range:'bytes=30-'}}))).status,416);
  assert.equal((await data.route(req('/api/resources/download/'+name,{method:'HEAD'}))).headers.get('Content-Length'),'10');
  await assert.rejects(()=>data.route(req('/api/resources/download/campus-resources-r1-111111111111.tar.gz')),{status:404});
  const direct=resources({RESOURCES:bucket,CAMPUS_R2_PREFIX:'test',CAMPUS_R2_PUBLIC_BASE_URL:'https://assets.test'});
  assert.equal((await direct.route(req('/api/resources/download/'+name))).headers.get('Location'),'https://assets.test/test/downloads/'+name);
}));

test('actual Workers runtime serves SPA, Node API, R2 text, OAuth state and logout',async()=>{
  const secret='integration-secret-'.repeat(4);
  const harness=createTestHarness({workers:[{configPath:'wrangler.jsonc',secrets:{SESSION_SECRET:secret,GITHUB_CLIENT_ID:'test-id',GITHUB_CLIENT_SECRET:'test-secret'}}]});
  try {
    await harness.listen();
    const worker=harness.getWorker();const env=await worker.getEnv();
    await env.DB.exec((await readFile(new URL('./migrations/0001_sessions.sql',import.meta.url),'utf8')).replace(/\n/g,' '));
    const get=(path,init)=>harness.fetch('http://127.0.0.1:8788'+path,init);
    assert.equal((await (await get('/api/health')).json()).ok,true);
    assert.equal((await get('/workbench')).headers.get('Content-Type').includes('text/html'),true);
    assert.equal((await get('/api/source/adv_demo')).status,503);
    await env.RESOURCES.put('campus-v1/current.json',JSON.stringify({release:'r1',versions:{revision:62,versions:[]}}));
    await env.RESOURCES.put('campus-v1/releases/r1/web/catalog/manifest.json',JSON.stringify({base_path:'/catalog/releases/r1/builds/x'}));
    await env.RESOURCES.put('campus-v1/releases/r1/web/catalog/builds/x/chapters/adv_demo.json',JSON.stringify({csv_path:'CSV/demo.csv'}));
    await env.RESOURCES.put('campus-v1/releases/r1/story/CSV/demo.csv','name,text\n咲季,你好');
    await env.RESOURCES.put('campus-v1/releases/r1/adv/adv_demo.txt','original script');
    assert.equal((await (await get('/api/source/adv_demo')).json()).csv,'name,text\n咲季,你好');
    assert.equal((await (await get('/api/script/adv_demo')).json()).txt,'original script');
    const login=await get('/api/auth/login?returnTo=/workbench',{redirect:'manual'});
    assert.equal(login.status,302);const location=new URL(login.headers.get('Location'));const state=location.searchParams.get('state');
    const flow=await sessionStore(env.DB,secret,'oauth').get(state);assert.equal(flow.returnTo,'/workbench');
    const callback='/api/auth/callback?state='+state;
    assert.equal((await get(callback,{headers:{Cookie:'campus_oauth='+state}})).status,400);
    assert.equal(await sessionStore(env.DB,secret,'oauth').get(state),undefined);
    const sessions=sessionStore(env.DB,secret,'session');await sessions.set('test-cookie',{token:'fake',csrf:'csrf-test',expires:Date.now()+60000});
    const logout=await get('/api/auth/logout',{method:'POST',headers:{Origin:'http://127.0.0.1:8788',Cookie:'campus_session=test-cookie','X-CSRF-Token':'csrf-test'},body:'{}'});
    assert.equal(logout.status,200);assert.equal(await sessions.get('test-cookie'),undefined);
  } finally {await harness.close();}
});


test('content-addressed release maps serve CSV, TXT and catalog; older releases still work',()=>fixture(async bucket=>{
  const data=resources({RESOURCES:bucket,CAMPUS_R2_PREFIX:'mapped'});
  const csv='text/'+'a'.repeat(64)+'/demo.csv', txt='text/'+'b'.repeat(64)+'/demo.txt', catalog='text/'+'c'.repeat(64)+'/manifest.json';
  await bucket.put('mapped/'+csv,'name,text\n咲季,你好');
  await bucket.put('mapped/'+txt,'original script');
  await bucket.put('mapped/'+catalog,'{"base_path":"/catalog/releases/new/builds/x"}');
  await bucket.put('mapped/releases/new/file-map.json',JSON.stringify({schema_version:1,files:{'story/CSV/demo.csv':csv,'adv/demo.txt':txt,'web/catalog/manifest.json':catalog,'story/CSV/legacy.csv':'releases/old/story/CSV/demo.csv','story/CSV/bad.csv':'../secret'}}));
  await bucket.put('mapped/current.json',JSON.stringify({release:'new',versions:{revision:62,versions:[]}}));
  const roots=await data.sourceRoots();
  assert.equal(await data.readFile(roots.story,'CSV/demo.csv'),'name,text\n咲季,你好');
  assert.equal(await data.readFile(roots.adv,'demo.txt'),'original script');
  const res=await data.route(new Request('https://site.test/catalog/manifest.json'));
  assert.equal(res.status,200);assert.equal((await res.json()).base_path,'/catalog/releases/new/builds/x');
  await assert.rejects(()=>data.readFile(roots.story,'CSV/absent.csv'),{status:404});
  await assert.rejects(()=>data.readFile(roots.story,'CSV/bad.csv'),{status:503});
  await bucket.put('mapped/releases/old/story/CSV/demo.csv','legacy');
  assert.equal(await data.readFile('releases/old/story','CSV/demo.csv'),'legacy');
  assert.equal(await data.readFile(roots.story,'CSV/legacy.csv'),'legacy');
}));
