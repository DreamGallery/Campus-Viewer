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
    const statusIp='192.0.2.9';
    for(let i=0;i<301;i++) await env.RESOURCE_MISS_LIMITER.limit({key:'campus:resource:'+statusIp});
    const deniedStatus=await get('/api/resources/status',{headers:{'CF-Connecting-IP':statusIp}});
    assert.equal(deniedStatus.status,429);assert.equal(deniedStatus.headers.get('Retry-After'),'60');
    await env.RESOURCES.put('campus-v1/current.json',JSON.stringify({release:'r1',versions:{revision:62,versions:[]}}));
    await env.RESOURCES.put('campus-v1/releases/r1/web/catalog/manifest.json',JSON.stringify({base_path:'/catalog/releases/r1/builds/x'}));
    await env.RESOURCES.put('campus-v1/releases/r1/web/catalog/builds/x/chapters/adv_demo.json',JSON.stringify({csv_path:'CSV/demo.csv'}));
    await env.RESOURCES.put('campus-v1/releases/r1/story/CSV/demo.csv','name,text\n咲季,你好');
    await env.RESOURCES.put('campus-v1/releases/r1/adv/adv_demo.txt','original script');
    assert.equal((await (await get('/api/source/adv_demo')).json()).csv,'name,text\n咲季,你好');
    assert.equal((await (await get('/api/script/adv_demo')).json()).txt,'original script');
    const cachedStatus=await get('/api/resources/status',{headers:{'CF-Connecting-IP':statusIp}});
    assert.equal(cachedStatus.status,200);assert.equal(cachedStatus.headers.get('Cache-Control'),'no-store');
    assert.equal((await cachedStatus.json()).revision,62);
    const login=await get('/api/auth/login?returnTo=/workbench',{redirect:'manual'});
    assert.equal(login.status,302);const location=new URL(login.headers.get('Location'));const state=location.searchParams.get('state');
    const flow=await sessionStore(env.DB,secret,'oauth').get(state);assert.equal(flow.returnTo,'/workbench');
    const callback='/api/auth/callback?state='+state;
    assert.equal((await get(callback,{headers:{Cookie:'campus_oauth='+state}})).status,400);
    assert.equal(await sessionStore(env.DB,secret,'oauth').get(state),undefined);
    const sessions=sessionStore(env.DB,secret,'session');await sessions.set('test-cookie',{token:'fake',csrf:'csrf-test',expires:Date.now()+60000});
    const logout=await get('/api/auth/logout',{method:'POST',headers:{Origin:'http://127.0.0.1:8788',Cookie:'campus_session=test-cookie','X-CSRF-Token':'csrf-test','Content-Type':'application/json'},body:'{}'});
    assert.equal(logout.status,200);assert.equal(await sessions.get('test-cookie'),undefined);
    const countStates=async()=>Number((await env.DB.prepare("SELECT COUNT(*) AS total FROM auth_state WHERE namespace='oauth'").first()).total);
    const before=await countStates();let allowed=0,denied=0;
    for(let i=0;i<12;i++) {
      const attempt=await get('/api/auth/login',{redirect:'manual'});
      if(attempt.status===302) allowed++;
      else {assert.equal(attempt.status,429);assert.equal(attempt.headers.get('Retry-After'),'60');denied++;}
    }
    assert.ok(denied>0);assert.equal(await countStates()-before,allowed);
    const media='media/'+'e'.repeat(64)+'/cached.flac';
    await env.RESOURCES.put('campus-v1/'+media,'0123456789',{httpMetadata:{contentType:'audio/flac'}});
    assert.equal(await(await get('/'+media)).text(),'0123456789');
    // Removing the simulated origin object distinguishes a real cache hit from another R2 read.
    await env.RESOURCES.delete('campus-v1/'+media);
    assert.equal(await(await get('/'+media+'?fresh=1')).text(),'0123456789');
    const range=await get('/'+media,{headers:{Range:'bytes=2-5'}});
    assert.equal(range.status,206);assert.equal(await range.text(),'2345');
    const fullRangeMedia='media/'+'d'.repeat(64)+'/browser.flac';
    await env.RESOURCES.put('campus-v1/'+fullRangeMedia,'0123456789',{httpMetadata:{contentType:'audio/flac'}});
    const initialRange=await get('/'+fullRangeMedia,{headers:{Range:'bytes=0-'}});
    assert.equal(initialRange.status,206);assert.equal(await initialRange.text(),'0123456789');
    await env.RESOURCES.delete('campus-v1/'+fullRangeMedia);
    assert.equal(await(await get('/'+fullRangeMedia,{headers:{Range:'bytes=4-6'}})).text(),'456');
    const blockedIp='192.0.2.7';
    for(let i=0;i<301;i++) await env.RESOURCE_MISS_LIMITER.limit({key:'campus:resource:'+blockedIp});
    for(const path of ['/api/source/adv_uncached','/api/script/adv_uncached']) {
      const denied=await get(path,{headers:{'CF-Connecting-IP':blockedIp}});
      assert.equal(denied.status,429);assert.equal(denied.headers.get('Retry-After'),'60');
    }
    assert.equal((await get('/api/source/adv_demo',{headers:{'CF-Connecting-IP':blockedIp}})).status,200);
    const anonymous=await get('/api/auth/status');
    assert.equal(anonymous.headers.get('Cache-Control'),'no-store');assert.equal((await anonymous.json()).user,null);
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
  await bucket.put('mapped/releases/old/resource-snapshot.json','{"revision":"61"}');
  assert.equal(await data.readFile('releases/old/story','CSV/demo.csv'),'legacy');
  assert.equal(await data.readFile(roots.story,'CSV/legacy.csv'),'legacy');
}));

test('music index is independent, dynamic, and FLAC supports byte ranges',()=>fixture(async bucket=>{
  const data=resources({RESOURCES:bucket,CAMPUS_R2_PREFIX:'music-test'});
  const request=(path,options)=>new Request('https://site.test'+path,options);
  assert.deepEqual((await (await data.route(request('/music/library.json'))).json()).tracks,[]);
  const key='text/'+'a'.repeat(64)+'/music-library.json';
  await bucket.put('music-test/'+key,JSON.stringify({schema_version:1,tracks:[{id:'song',format:'flac'}]}),{httpMetadata:{contentType:'application/json'}});
  await bucket.put('music-test/music/current.json',JSON.stringify({schema_version:1,library:key}));
  const response=await data.route(request('/music/library.json'));
  assert.equal(response.headers.get('Cache-Control'),'no-store');
  assert.equal((await response.json()).tracks[0].format,'flac');
  const audio='media/'+'b'.repeat(64)+'/song.flac';
  await bucket.put('music-test/'+audio,'0123456789',{httpMetadata:{contentType:'audio/flac'}});
  const range=await data.route(request('/'+audio,{headers:{Range:'bytes=2-5'}}));
  assert.equal(range.status,206);assert.equal(range.headers.get('Content-Type'),'audio/flac');
  assert.equal(await range.text(),'2345');
  await assert.rejects(()=>data.route(request('/music/secret')),{status:404});
  await bucket.put('music-test/music/current.json',JSON.stringify({schema_version:1,library:'../secret'}));
  await assert.rejects(()=>data.route(request('/music/library.json')),{status:503});
}));

// Controllable Cache API clock; real R2 bindings still exercise object metadata and ranges.
function timedCache() {
  let now=0;
  const entries=new Map();
  return {
    advance:seconds=>{now+=seconds;},
    async put(request,response) {
      assert.equal(request.method,'GET');assert.notEqual(response.status,206);
      assert.equal(response.headers.has('Set-Cookie'),false);
      const ttl=Number(/max-age=(\d+)/.exec(response.headers.get('Cache-Control'))?.[1]);
      assert.ok(ttl>0);
      entries.set(request.url,{body:await response.arrayBuffer(),headers:new Headers(response.headers),status:response.status,expires:now+ttl});
    },
    async match(request) {
      const row=entries.get(request.url);if(!row || row.expires<=now)return undefined;
      const range=/^bytes=(\d+)-(\d+)$/.exec(request.headers.get('Range')||'');
      if(range && row.status===200) {
        const start=Number(range[1]),end=Number(range[2]),headers=new Headers(row.headers);
        headers.set('Content-Length',String(end-start+1));headers.set('Content-Range',`bytes ${start}-${end}/${row.body.byteLength}`);
        return new Response(row.body.slice(start,end+1),{status:206,headers});
      }
      return new Response([204,304].includes(row.status)?null:row.body.slice(0),{status:row.status,headers:row.headers});
    },
  };
}
function countedBucket(bucket) {
  const calls={get:0,head:0};
  return {calls,bucket:{get:(...args)=>{calls.get++;return bucket.get(...args);},head:(...args)=>{calls.head++;return bucket.head(...args);}}};
}
test('immutable cache shares query variants and supports HEAD, ETag and ranges without R2 reads',()=>fixture(async bucket=>{
  const key='media/'+'c'.repeat(64)+'/voice.flac';
  await bucket.put('cache/'+key,'0123456789',{httpMetadata:{contentType:'audio/flac'}});
  const counted=countedBucket(bucket),cache=timedCache();
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'cache',CAMPUS_PUBLIC_ORIGIN:'https://site.test'},{cache});
  const req=(query='',options)=>new Request('https://site.test/'+key+query,options);
  const first=await data.route(req());const etag=first.headers.get('ETag');
  assert.equal(await first.text(),'0123456789');assert.deepEqual(counted.calls,{get:1,head:0});
  for(let i=0;i<5;i++) assert.equal(await(await data.route(req('?random='+i,{headers:{Cookie:'campus_session=anything'}}))).text(),'0123456789');
  assert.equal((await data.route(req('',{method:'HEAD'}))).headers.get('Content-Length'),'10');
  assert.equal((await data.route(req('',{headers:{'If-None-Match':'"other", W/'+etag}}))).status,304);
  const range=await data.route(req('',{headers:{Range:'bytes=2-5','If-Range':etag}}));
  assert.equal(range.status,206);assert.equal(await range.text(),'2345');
  assert.equal(range.headers.get('Content-Range'),'bytes 2-5/10');
  const stale=await data.route(req('',{headers:{Range:'bytes=2-5','If-Range':'"stale"'}}));
  assert.equal(stale.status,200);assert.equal(await stale.text(),'0123456789');
  for(const value of ['bytes=-0','bytes=10-','bytes=0-1,4-5','bytes=9007199254740993-']) assert.equal((await data.route(req('',{headers:{Range:value}}))).status,416);
  assert.deepEqual(counted.calls,{get:1,head:0});
}));
test('a cold Range response is not cached as the whole audio file',()=>fixture(async bucket=>{
  const key='media/'+'d'.repeat(64)+'/voice.flac';
  await bucket.put('partial/'+key,'0123456789');
  const counted=countedBucket(bucket),cache=timedCache();
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'partial'},{cache});
  const req=headers=>new Request('https://site.test/'+key,{headers});
  assert.equal(await(await data.route(req({Range:'bytes=-3'}))).text(),'789');
  assert.deepEqual(counted.calls,{get:1,head:1});
  assert.equal(await(await data.route(req())).text(),'0123456789');
  assert.deepEqual(counted.calls,{get:2,head:1});
  assert.equal(await(await data.route(req({Range:'bytes=1-2'}))).text(),'12');
  assert.deepEqual(counted.calls,{get:2,head:1});
}));
test('pointer and negative caches expire while published old versions stay readable',()=>fixture(async bucket=>{
  const counted=countedBucket(bucket),cache=timedCache();
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'versions'},{cache});
  const req=path=>new Request('https://site.test'+path);
  async function seed(release,digit) {
    const key='text/'+digit.repeat(64)+'/manifest.json';
    await bucket.put('versions/'+key,JSON.stringify({base_path:'/catalog/releases/'+release+'/builds/build'}));
    await bucket.put('versions/releases/'+release+'/file-map.json',JSON.stringify({schema_version:1,files:{'web/catalog/manifest.json':key}}));
    await bucket.put('versions/current.json',JSON.stringify({release,versions:{revision:Number(digit),versions:[]}}));
  }
  await seed('r1','1');
  assert.match((await(await data.route(req('/catalog/manifest.json'))).json()).base_path,/r1/);
  const before=counted.calls.get;
  await seed('r2','2');
  assert.match((await(await data.route(req('/catalog/manifest.json?reload=1'))).json()).base_path,/r1/);
  assert.equal(counted.calls.get,before);
  cache.advance(31);
  assert.match((await(await data.route(req('/catalog/manifest.json'))).json()).base_path,/r2/);
  assert.match((await(await data.route(req('/catalog/releases/r1/manifest.json'))).json()).base_path,/r1/);
  const missing='/media/'+'f'.repeat(64)+'/new.flac';
  await assert.rejects(()=>data.route(req(missing)),{status:404});
  const missCalls=counted.calls.get;
  await bucket.put('versions'+missing,'new-audio');
  await assert.rejects(()=>data.route(req(missing+'?bypass=1')),{status:404});
  assert.equal(counted.calls.get,missCalls);
  cache.advance(16);
  assert.equal(await(await data.route(req(missing))).text(),'new-audio');
  const unknown=req('/catalog/releases/unknown/manifest.json');
  await assert.rejects(()=>data.route(unknown),{status:404});
  const unknownCalls={...counted.calls};
  await assert.rejects(()=>data.route(unknown),{status:404});
  assert.deepEqual(counted.calls,unknownCalls);
}));
test('malformed resources and throttled misses never reach R2, but cache hits remain available',()=>fixture(async bucket=>{
  let allowed=false,checks=0;
  const counted=countedBucket(bucket),cache=timedCache();
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'limits'},{cache,allowMiss:async()=>{checks++;return allowed;}});
  const req=path=>new Request('https://site.test'+path);
  for(const path of ['/catalog/releases/no/version.txt','/api/resources/download/invalid','/media/not-a-hash/file.flac']) await assert.rejects(()=>data.route(req(path)),{status:404});
  assert.equal(checks,0);assert.deepEqual(counted.calls,{get:0,head:0});
  const key='media/'+'a'.repeat(64)+'/voice.flac';
  await bucket.put('limits/'+key,'audio');
  await assert.rejects(()=>data.route(req('/'+key)),{status:429});
  assert.deepEqual(counted.calls,{get:0,head:0});
  allowed=true;assert.equal(await(await data.route(req('/'+key))).text(),'audio');
  const previousChecks=checks;
  allowed=false;assert.equal(await(await data.route(req('/'+key+'?random=2'))).text(),'audio');
  assert.equal(checks,previousChecks);assert.deepEqual(counted.calls,{get:1,head:0});
}));

test('a temporarily missing release map is retried after publication',()=>fixture(async bucket=>{
  const cache=timedCache(),release='publishing',target='text/'+'a'.repeat(64)+'/manifest.json';
  const mapKey='publication/releases/'+release+'/file-map.json';
  let published=false;
  const racingBucket={head:(...args)=>bucket.head(...args),get:async(key,...args)=>{
    const object=await bucket.get(key,...args);
    if(key===mapKey && !published) {
      published=true;
      // Publication completes while a reader is still handling an earlier map miss.
      await bucket.put('publication/'+target,'{"base_path":"/catalog/releases/publishing/builds/new"}');
      await bucket.put(mapKey,JSON.stringify({schema_version:1,files:{'web/catalog/manifest.json':target}}));
      await bucket.put('publication/current.json',JSON.stringify({release,versions:{versions:[]}}));
    }
    return object;
  }};
  const data=resources({RESOURCES:racingBucket,CAMPUS_R2_PREFIX:'publication'},{cache});
  const request=new Request('https://site.test/catalog/releases/'+release+'/manifest.json');
  await assert.rejects(()=>data.route(request),{status:404});
  cache.advance(16);
  assert.equal((await(await data.route(request)).json()).base_path,'/catalog/releases/publishing/builds/new');
}));

test('a full-file Range request warms the complete cache without caching a 206',()=>fixture(async bucket=>{
  const key='media/'+'f'.repeat(64)+'/voice.flac';
  await bucket.put('range-full/'+key,'0123456789');
  const counted=countedBucket(bucket),cache=timedCache();
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'range-full'},{cache});
  const req=range=>new Request('https://site.test/'+key,{headers:{Range:range}});
  const first=await data.route(req('bytes=0-'));
  assert.equal(first.status,206);assert.equal(await first.text(),'0123456789');
  assert.deepEqual(counted.calls,{get:1,head:1});
  assert.equal(await(await data.route(req('bytes=2-5'))).text(),'2345');
  assert.deepEqual(counted.calls,{get:1,head:1});
}));

test('cache read or write failures never hide an available resource',()=>fixture(async bucket=>{
  const key='media/'+'b'.repeat(64)+'/voice.flac';
  await bucket.put('unavailable-cache/'+key,'audio');
  for(const sync of [true,false]) {
    const cache={match:async()=>{throw new Error('cache offline');},put:()=>{
      if(sync)throw new Error('cache offline');
      return Promise.reject(new Error('cache offline'));
    }};
    const data=resources({RESOURCES:bucket,CAMPUS_R2_PREFIX:'unavailable-cache'},{cache});
    assert.equal(await(await data.route(new Request('https://site.test/'+key))).text(),'audio');
  }
}));

test('original-text API services share miss limits and retain access to cached files',()=>fixture(async bucket=>{
  await bucket.put('original/current.json',JSON.stringify({release:'r1',versions:{versions:[]}}));
  const target='text/'+'c'.repeat(64)+'/story.txt';
  await bucket.put('original/'+target,'script');
  await bucket.put('original/releases/r1/file-map.json',JSON.stringify({schema_version:1,files:{'adv/story.txt':target}}));
  const counted=countedBucket(bucket),cache=timedCache();let allowed=false,checks=0;
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'original'},{cache,allowMiss:async()=>{checks++;return allowed;}});
  const req=()=>new Request('https://site.test/api/script/story');
  await assert.rejects(()=>data.sourceRoots(req()),{status:429});
  await assert.rejects(()=>data.readFile('releases/r1/adv','story.txt',req()),{status:429});
  assert.deepEqual(counted.calls,{get:0,head:0});
  allowed=true;const oneRequest=req(),before=checks;
  const roots=await data.sourceRoots(oneRequest);
  assert.equal(await data.readFile(roots.adv,'story.txt',oneRequest),'script');
  assert.equal(checks-before,1);
  allowed=false;const after=checks;
  assert.equal(await data.readFile(roots.adv,'story.txt',req()),'script');assert.equal(checks,after);
}));

test('resource status checks the miss limit on cold and expired caches without charging hits',()=>fixture(async bucket=>{
  const counted=countedBucket(bucket),cache=timedCache();let allowed=false,checks=0;
  const req=()=>new Request('https://site.test/api/resources/status');
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'status'},{cache,allowMiss:async request=>{
    assert.equal(new URL(request.url).pathname,'/api/resources/status');checks++;return allowed;
  }});
  await bucket.put('status/current.json',JSON.stringify({release:'r1',published_at:1,versions:{revision:1}}));
  await assert.rejects(()=>data.status(req()),{status:429});
  assert.equal(checks,1);assert.deepEqual(counted.calls,{get:0,head:0});
  allowed=true;
  assert.deepEqual(await data.status(req()),{state:'ready',revision:1,release:'r1',last_success:1});
  assert.equal(checks,2);assert.deepEqual(counted.calls,{get:1,head:0});
  allowed=false;
  await bucket.put('status/current.json',JSON.stringify({release:'r2',published_at:2,versions:{revision:2}}));
  assert.equal((await data.status(req())).revision,1);
  assert.equal(checks,2);assert.deepEqual(counted.calls,{get:1,head:0});
  cache.advance(31);
  await assert.rejects(()=>data.status(req()),{status:429});
  assert.equal(checks,3);assert.deepEqual(counted.calls,{get:1,head:0});
  allowed=true;
  assert.equal((await data.status(req())).revision,2);
  assert.equal(checks,4);assert.deepEqual(counted.calls,{get:2,head:0});
}));

test('initialization status caches a missing pointer briefly, then checks the limit again',()=>fixture(async bucket=>{
  const counted=countedBucket(bucket),cache=timedCache();let allowed=true,checks=0;
  const req=()=>new Request('https://site.test/api/resources/status');
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'initializing-status'},{cache,allowMiss:async()=>{checks++;return allowed;}});
  assert.equal((await data.status(req())).state,'initializing');
  allowed=false;
  assert.equal((await data.status(req())).state,'initializing');
  assert.equal(checks,1);assert.deepEqual(counted.calls,{get:1,head:0});
  cache.advance(16);
  await assert.rejects(()=>data.status(req()),{status:429});
  assert.equal(checks,2);assert.deepEqual(counted.calls,{get:1,head:0});
}));

test('legacy release checks use cached metadata without reading the large snapshot',()=>fixture(async bucket=>{
  await bucket.put('legacy/current.json',JSON.stringify({release:'new',versions:{versions:[]}}));
  await bucket.put('legacy/releases/old/resource-snapshot.json','unused snapshot');
  await bucket.put('legacy/releases/old/web/catalog/manifest.json','{"legacy":true}');
  const counted=countedBucket(bucket),cache=timedCache(),get=counted.bucket.get;
  counted.bucket.get=(key,...args)=>{assert.ok(!key.endsWith('/resource-snapshot.json'));return get(key,...args);};
  const data=resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:'legacy'},{cache});
  const req=()=>new Request('https://site.test/catalog/releases/old/manifest.json');
  assert.equal((await(await data.route(req())).json()).legacy,true);assert.equal(counted.calls.head,1);
  const before={...counted.calls};
  assert.equal((await(await data.route(req())).json()).legacy,true);assert.deepEqual(counted.calls,before);
}));

test('large media stay streamed and do not populate the in-Worker cache',()=>fixture(async bucket=>{
  const size=8*1024*1024+1,key='media/'+'a'.repeat(64)+'/song.flac';
  await bucket.put('large/'+key,new Uint8Array(size));
  let puts=0;
  const data=resources({RESOURCES:bucket,CAMPUS_R2_PREFIX:'large'},{cache:{match:async()=>undefined,put:async()=>{puts++;}}});
  const response=await data.route(new Request('https://site.test/'+key,{headers:{Range:'bytes=0-'}}));
  assert.equal(response.status,206);assert.equal(response.headers.get('Content-Length'),String(size));
  assert.equal((await response.arrayBuffer()).byteLength,size);assert.equal(puts,0);
}));

test('cold HEAD cannot cache an empty file, and prefixes and hashes stay isolated',()=>fixture(async bucket=>{
  const key='media/'+'1'.repeat(64)+'/same.flac',next='media/'+'2'.repeat(64)+'/same.flac';
  await bucket.put('one/'+key,'first');await bucket.put('two/'+key,'second');await bucket.put('one/'+next,'next');
  const counted=countedBucket(bucket),cache=timedCache();
  const make=prefix=>resources({RESOURCES:counted.bucket,CAMPUS_R2_PREFIX:prefix,CAMPUS_PUBLIC_ORIGIN:'https://site.test'},{cache});
  const one=make('one'),two=make('two'),req=(key,method='GET')=>new Request('https://site.test/'+key,{method});
  const head=await one.route(req(key,'HEAD'));assert.equal(head.headers.get('Content-Length'),'5');
  assert.equal(await head.text(),'');assert.deepEqual(counted.calls,{get:0,head:1});
  assert.equal(await(await one.route(req(key))).text(),'first');
  assert.equal(await(await two.route(req(key))).text(),'second');
  assert.equal(await(await one.route(req(next))).text(),'next');
  const before={...counted.calls};
  assert.equal(await(await one.route(req(key))).text(),'first');assert.deepEqual(counted.calls,before);
}));
