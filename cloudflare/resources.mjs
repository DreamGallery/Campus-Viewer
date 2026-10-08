const error = status => Object.assign(new Error(status === 429 ? '请求过于频繁，请稍后重试' : 'Resource unavailable'), {status});
const IMMUTABLE_TTL = 31536000, POINTER_TTL = 30, MISSING_TTL = 15;
const MAX_CACHE_BYTES = 8 * 1024 * 1024;
const safe = value => {
  if (!value || value.length > 1024 || value.split('/').some(p => !p || p === '.' || p === '..') || /[\\\x00-\x1f]/.test(value)) throw error(400);
  return value;
};
const matchesEtag = (value, etag) => value?.split(',').some(tag => tag.trim() === '*' || tag.trim().replace(/^W\//, '') === etag);
function byteRange(raw, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(raw);
  if (!match || (!match[1] && !match[2])) return null;
  const first = match[1] ? Number(match[1]) : null, last = match[2] ? Number(match[2]) : null;
  if ((first !== null && !Number.isSafeInteger(first)) || (last !== null && !Number.isSafeInteger(last))) return null;
  const start = first === null ? Math.max(0, size - last) : first;
  const end = first !== null && last !== null ? Math.min(last, size - 1) : size - 1;
  return start < 0 || start > end || start >= size ? null : {start, end};
}
export function resources(env, options = {}) {
  const prefix = safe(env.CAMPUS_R2_PREFIX || 'campus-v1');
  const bucket = env.RESOURCES;
  const cacheOrigin = new URL(env.CAMPUS_PUBLIC_ORIGIN || 'https://campus-cache.invalid').origin;
  const cache = () => options.cache === undefined ? globalThis.caches?.default : options.cache;
  const scopes = new WeakMap();
  function scopeFor(request, ctx) {
    if (!request) return undefined;
    if (!scopes.has(request)) scopes.set(request, {request, ctx, checked:false});
    return scopes.get(request);
  }
  // Do not await a cancelled tee branch: its sibling may still be streaming to the client/cache.
  const discard = response => { void response?.body?.cancel().catch(() => {}); };
  // Object keys, not incoming query strings/cookies, identify these public resources.
  const cacheKey = key => new Request(cacheOrigin + '/__resource_cache/v1/' + (prefix + '/' + safe(key)).split('/').map(encodeURIComponent).join('/'));
  async function matchCache(key, headers) {
    try { return await cache()?.match(new Request(cacheKey(key), {headers})); }
    catch { return undefined; } // Cache availability must not decide resource availability.
  }
  async function storeCache(key, response, ttl, scope) {
    if (!ttl || ![200,204,404].includes(response.status) || response.headers.has('Set-Cookie')) return;
    const size = Number(response.headers.get('Content-Length'));
    if (!Number.isSafeInteger(size) || size < 0 || size > MAX_CACHE_BYTES || (response.body && !response.headers.has('Content-Length'))) return;
    let copy;
    try {
      const target = cache(); if (!target) return;
      const headers = new Headers(response.headers);
      headers.set('Cache-Control', `public, max-age=${ttl}`);
      copy = new Response(response.clone().body, {status: response.status, headers});
      const put = Promise.resolve(target.put(cacheKey(key), copy)).catch(() => discard(copy));
      if (scope?.ctx) scope.ctx.waitUntil(put); else await put;
    } catch { discard(copy); } // Includes synchronous Cache API errors; still serve the R2 response.
  }
  async function beforeRead(scope) {
    if (scope && !scope.checked) {
      if (options.allowMiss && !await options.allowMiss(scope.request)) throw error(429);
      scope.checked = true;
    }
  }
  async function missing(key, ttl, scope) {
    if (ttl) await storeCache(key, new Response(null, {status:404}), MISSING_TTL, scope);
    throw error(404);
  }
  function objectResponse(obj) {
    const headers = new Headers({'X-Content-Type-Options':'nosniff', 'Accept-Ranges':'bytes'});
    obj.writeHttpMetadata(headers);
    headers.set('ETag', obj.httpEtag);
    headers.set('Content-Length', String(obj.size));
    if (obj.uploaded) headers.set('Last-Modified', obj.uploaded.toUTCString());
    return new Response(obj.body ?? null, {headers});
  }
  async function fullObject(key, ttl, scope) {
    const cached = ttl && await matchCache(key);
    if (cached) { if (cached.status === 404) throw error(404); return cached; }
    await beforeRead(scope);
    const obj = await bucket.get(prefix + '/' + safe(key));
    if (!obj) return missing(key, ttl, scope);
    const response = objectResponse(obj);
    await storeCache(key, response, ttl, scope);
    return response;
  }
  async function text(key, ttl = IMMUTABLE_TTL, scope) {
    return (await fullObject(key, ttl, scope)).text();
  }
  async function requireLegacyRelease(release, scope) {
    // A separate cache marker records existence, never the potentially large resource manifest.
    const marker = '__legacy-release/' + release;
    const cached = await matchCache(marker);
    if (cached) { discard(cached); if (cached.status === 404) throw error(404); return; }
    await beforeRead(scope);
    if (!await bucket.head(prefix + '/releases/' + release + '/resource-snapshot.json')) return missing(marker, IMMUTABLE_TTL, scope);
    await storeCache(marker, new Response(null, {status:204}), IMMUTABLE_TTL, scope);
  }
  const maps = new Map();
  async function resolveFile(key, scope) {
    safe(key);
    const match = /^releases\/([\w-]{1,80})\/(web\/.*|story\/.*|adv\/.*)$/.exec(key);
    if (!match) return key;
    const release = match[1];
    if (!maps.has(release)) {
      let map;
      try {
        map = JSON.parse(await text('releases/' + release + '/file-map.json', IMMUTABLE_TTL, scope));
        if (!map || map.schema_version !== 1 || !map.files || typeof map.files !== 'object' || Array.isArray(map.files)) throw error(503);
      }
      catch (e) { if (e.status !== 404) throw e; }
      if (!map) {
        // Legacy releases have no map. Require a published pointer/snapshot before
        // falling back to direct objects; random versions must not probe arbitrary paths.
        if ((await current(scope))?.release !== release) await requireLegacyRelease(release, scope);
        // A cached 404 may predate publication. Only remember successfully parsed maps.
        return key;
      }
      maps.set(release, map.files);
      while (maps.size > 2) maps.delete(maps.keys().next().value);
    }
    const files = maps.get(release);
    const target = Object.hasOwn(files, match[2]) ? files[match[2]] : null;
    if (!target) throw error(404);
    if (!/^text\/[a-f0-9]{64}\/[^/]+$/.test(target) && !/^releases\/[\w-]{1,80}\/(story|adv)\/.+/.test(target)) throw error(503);
    return safe(target);
  }
  async function current(scope) {
    try { return JSON.parse(await text('current.json', POINTER_TTL, scope)); }
    catch(e) { if(e.status === 404) return null; throw e; }
  }
  async function sourceRoots(request) {
    const info = await current(scopeFor(request)); if (!info) throw error(503);
    const root = 'releases/' + safe(info.release);
    return {web:root+'/web',story:root+'/story',adv:root+'/adv'};
  }
  async function readFile(root, relative, request) {
    const catalog = /^catalog\/releases\/([^/]+)\/(.+)$/.exec(relative);
    if(catalog) {
      if(root !== 'releases/'+catalog[1]+'/web') throw error(400);
      relative = 'catalog/'+catalog[2];
    }
    const scope = scopeFor(request);
    return text(await resolveFile(safe(root)+'/'+safe(relative), scope), IMMUTABLE_TTL, scope);
  }
  async function stream(request, key, download=false, immutable=false, scope) {
    key = await resolveFile(safe(key), scope);
    const ttl = download ? 0 : IMMUTABLE_TTL;
    let full = ttl && await matchCache(key);
    if (full?.status === 404) throw error(404);
    let metadata;
    if (full) metadata = full.headers;
    else if (request.method === 'HEAD' || request.headers.has('Range')) {
      await beforeRead(scope);
      const head = await bucket.head(prefix + '/' + key);
      if (!head) return missing(key, ttl, scope);
      metadata = objectResponse(head).headers;
    } else {
      // A normal GET needs no preceding HEAD; R2 returns metadata with the body.
      full = await fullObject(key, ttl, scope);
      metadata = full.headers;
    }
    const headers = new Headers(metadata);
    headers.set('Cache-Control', immutable ? 'public, max-age=31536000, immutable' : 'no-store');
    if(download) headers.set('Content-Disposition', 'attachment; filename="'+key.split('/').pop()+'"');
    if(matchesEtag(request.headers.get('If-None-Match'), headers.get('ETag'))) {
      discard(full); headers.delete('Content-Length');
      return new Response(null, {status:304, headers});
    }
    const size = Number(headers.get('Content-Length')), raw = request.headers.get('Range');
    if (raw && (!request.headers.get('If-Range') || request.headers.get('If-Range') === headers.get('ETag'))) {
      const range = byteRange(raw, size);
      if (!range) {
        discard(full); headers.set('Content-Range', `bytes */${size}`); headers.set('Content-Length', '0');
        return new Response(null, {status:416, headers});
      }
      const {start, end} = range;
      headers.set('Content-Range', `bytes ${start}-${end}/${size}`);
      headers.set('Content-Length', String(end-start+1));
      if (request.method === 'HEAD') { discard(full); return new Response(null, {status:206, headers}); }
      if (start === 0 && end === size - 1) {
        // Browsers often start audio with bytes=0-. Cache the complete 200 internally,
        // then return the requested 206; subsequent seeks can reuse the whole file.
        full ||= await fullObject(key, ttl, scope);
        return new Response(full.body, {status:206, headers});
      }
      discard(full);
      const hit = ttl && await matchCache(key, {Range:`bytes=${start}-${end}`});
      if (hit?.status === 206) return new Response(hit.body, {status:206, headers});
      discard(hit);
      await beforeRead(scope);
      const obj = await bucket.get(prefix+'/'+key, {range:{offset:start,length:end-start+1}});
      if (!obj) return missing(key, ttl, scope);
      // Partial responses are never stored as if they were a complete file.
      return new Response(obj.body, {status:206, headers});
    }
    if (request.method === 'HEAD') { discard(full); return new Response(null, {headers}); }
    full ||= await fullObject(key, ttl, scope);
    return new Response(full.body, {headers});
  }
  async function route(request, ctx) {
    let path;
    try { path = decodeURIComponent(new URL(request.url).pathname); } catch { throw error(400); }
    const handled=path.startsWith('/music/') || path.startsWith('/catalog/') || path.startsWith('/media/') || path.startsWith('/api/resources/download/') || path==='/api/resources/versions';
    if(!handled) return null;
    if(!['GET','HEAD'].includes(request.method)) return new Response(null,{status:405,headers:{Allow:'GET, HEAD'}});
    const scope = scopeFor(request, ctx);
    if(path==='/api/resources/versions') {
      const info=await current(scope);
      return new Response(request.method==='HEAD'?null:JSON.stringify(info?.versions || {revision:null,versions:[]}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
    }
    if(path.startsWith('/api/resources/download/')) {
      const name=path.slice('/api/resources/download/'.length);
      if(!/^campus-resources-r[0-9]+-[a-f0-9]{12}\.tar\.gz$/.test(name)) throw error(404);
      const info=await current(scope);
      if(!info?.versions?.versions.some(v=>v.filename===name)) throw error(404);
      if(env.CAMPUS_R2_PUBLIC_BASE_URL) {
        const base=new URL(env.CAMPUS_R2_PUBLIC_BASE_URL);if(base.protocol!=='https:') throw error(503);
        return new Response(null,{status:302,headers:{Location:base.href.replace(/\/$/,'')+'/'+prefix+'/downloads/'+name,'Cache-Control':'no-store'}});
      }
      return stream(request,'downloads/'+name,true,false,scope);
    }
    if(path.startsWith('/media/')) {
      if(!/^\/media\/[a-f0-9]{64}\/[^/]{1,240}$/.test(path)) throw error(404);
      return stream(request,path.slice(1),false,true,scope);
    }
    if(path.startsWith('/music/')) {
      if(path!=='/music/library.json') throw error(404);
      let info;
      try { info=JSON.parse(await text('music/current.json', POINTER_TTL, scope)); }
      catch(e) { if(e.status!==404) throw e; return new Response(request.method==='HEAD'?null:JSON.stringify({schema_version:1,tracks:[]}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}); }
      if(info.schema_version!==1 || !/^text\/[a-f0-9]{64}\/music-library\.json$/.test(info.library)) throw error(503);
      return stream(request,info.library,false,false,scope);
    }
    if(path==='/catalog/manifest.json') {
      const info=await current(scope);if(!info) throw error(503);
      return stream(request,'releases/'+safe(info.release)+'/web/catalog/manifest.json',false,false,scope);
    }
    const match=/^\/catalog\/releases\/([\w-]{1,80})\/(manifest\.json|builds\/[\w-]{1,80}\/(?:updates\.json|lists\/[\w-]{1,80}\.json|chapters\/[\w-]{1,200}\.json))$/.exec(path);
    if(!match) throw error(404);
    return stream(request,'releases/'+match[1]+'/web/catalog/'+match[2],false,true,scope);
  }
  return {route,sourceRoots,readFile,status:async request=>{
    const info=await current(scopeFor(request));return info?{state:'ready',revision:info.versions?.revision,release:info.release,last_success:info.published_at}:{state:'initializing',phase:'等待 Docker 更新器发布资源'};
  }};
}
