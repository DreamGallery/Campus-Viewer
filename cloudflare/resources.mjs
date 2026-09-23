const error = status => Object.assign(new Error('Resource unavailable'), {status});
const safe = value => {
  if (!value || value.split('/').some(p => !p || p === '.' || p === '..') || /[\\\x00-\x1f]/.test(value)) throw error(400);
  return value;
};
export function resources(env) {
  const prefix = safe(env.CAMPUS_R2_PREFIX || 'campus-v1');
  const bucket = env.RESOURCES;
  async function text(key) {
    const obj = await bucket.get(prefix + '/' + safe(key));
    if (!obj) throw error(404);
    return obj.text();
  }
  // Immutable per-release maps; bound memory and retain legacy direct-object reads.
  const maps = new Map();
  async function resolveFile(key) {
    safe(key);
    const match = /^releases\/([^/]+)\/(web\/.*|story\/.*|adv\/.*)$/.exec(key);
    if (!match) return key;
    const release = match[1];
    if (!maps.has(release)) {
      const obj = await bucket.get(prefix+'/releases/'+release+'/file-map.json');
      // Do not cache a miss: the updater may still be publishing this release.
      if (!obj) return key;
      const map = JSON.parse(await obj.text());
      if (map.schema_version !== 1 || !map.files) throw error(503);
      maps.set(release, map.files);
      while (maps.size > 2) maps.delete(maps.keys().next().value);
    }
    const target = maps.get(release)[match[2]];
    if (!target) throw error(404);
    if (!/^text\/[a-f0-9]{64}\/[^/]+$/.test(target) && !/^releases\/[^/]+\/(story|adv)\/.+/.test(target)) throw error(503);
    return safe(target);
  }
  async function current() {
    try { return JSON.parse(await text('current.json')); }
    catch(e) { if(e.status === 404) return null; throw e; }
  }
  async function sourceRoots() {
    const info = await current(); if (!info) throw error(503);
    const root = 'releases/' + safe(info.release);
    return {web:root+'/web',story:root+'/story',adv:root+'/adv'};
  }
  async function readFile(root, relative) {
    // Catalog base_path is a public versioned URL; map it back to this release.
    const catalog = /^catalog\/releases\/([^/]+)\/(.+)$/.exec(relative);
    if(catalog) {
      if(root !== 'releases/'+catalog[1]+'/web') throw error(400);
      relative = 'catalog/'+catalog[2];
    }
    return text(await resolveFile(safe(root)+'/'+safe(relative)));
  }
  async function stream(request, key, download=false, immutable=false) {
    const headers = new Headers({'X-Content-Type-Options':'nosniff','Cache-Control':immutable?'public, max-age=31536000, immutable':'no-store','Accept-Ranges':'bytes'});
    const fullKey = prefix+'/'+await resolveFile(safe(key));
    const head = await bucket.head(fullKey); if(!head) throw error(404);
    head.writeHttpMetadata(headers); headers.set('ETag',head.httpEtag);
    headers.set('Cache-Control',immutable?'public, max-age=31536000, immutable':'no-store');
    if(download) headers.set('Content-Disposition', 'attachment; filename="'+key.split('/').pop()+'"');
    if(request.headers.get('If-None-Match') === head.httpEtag) return new Response(null,{status:304,headers});
    let start=0,end=head.size-1,status=200;
    const raw=request.headers.get('Range');
    if(raw && (!request.headers.get('If-Range') || request.headers.get('If-Range')===head.httpEtag)) {
      const match=/^bytes=(\d*)-(\d*)$/.exec(raw);
      if(match) {start=match[1]?Number(match[1]):Math.max(0,head.size-Number(match[2]));end=match[1]&&match[2]?Math.min(Number(match[2]),end):end;}
      if(!match || (!match[1]&&!match[2]) || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start>end || start>=head.size) {
        headers.set('Content-Range',`bytes */${head.size}`);return new Response(null,{status:416,headers});
      }
      status=206;headers.set('Content-Range',`bytes ${start}-${end}/${head.size}`);
    }
    headers.set('Content-Length', String(head.size ? end-start+1 : 0));
    if(request.method==='HEAD') return new Response(null,{status,headers});
    const obj=await bucket.get(fullKey,status===206?{range:{offset:start,length:end-start+1}}:{});
    if(!obj) throw error(404);
    return new Response(obj.body,{status,headers});
  }
  async function route(request) {
    const path=decodeURIComponent(new URL(request.url).pathname);
    const handled=path.startsWith('/catalog/') || path.startsWith('/media/') || path.startsWith('/api/resources/download/') || path==='/api/resources/versions';
    if(!handled) return null;
    if(!['GET','HEAD'].includes(request.method)) return new Response(null,{status:405,headers:{Allow:'GET, HEAD'}});
    if(path==='/api/resources/versions') {
      const info=await current();
      return new Response(request.method==='HEAD'?null:JSON.stringify(info?.versions || {revision:null,versions:[]}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
    }
    if(path.startsWith('/api/resources/download/')) {
      const name=path.slice('/api/resources/download/'.length), info=await current();
      if(!/^campus-resources-r[0-9]+-[a-f0-9]{12}\.tar\.gz$/.test(name) || !info?.versions?.versions.some(v=>v.filename===name)) throw error(404);
      if(env.CAMPUS_R2_PUBLIC_BASE_URL) {
        const base=new URL(env.CAMPUS_R2_PUBLIC_BASE_URL);if(base.protocol!=='https:') throw error(503);
        return new Response(null,{status:302,headers:{Location:base.href.replace(/\/$/,'')+'/'+prefix+'/downloads/'+name,'Cache-Control':'no-store'}});
      }
      return stream(request,'downloads/'+name,true);
    }
    if(path.startsWith('/media/')) {
      if(!/^\/media\/[a-f0-9]{64}\/[^/]+$/.test(path)) throw error(404);
      return stream(request,path.slice(1),false,true);
    }
    if(path==='/catalog/manifest.json') {
      const info=await current();if(!info) throw error(503);
      return stream(request,'releases/'+safe(info.release)+'/web/catalog/manifest.json');
    }
    const match=/^\/catalog\/releases\/([^/]+)\/(.+)$/.exec(path);
    if(!match) throw error(404);
    return stream(request,'releases/'+safe(match[1])+'/web/catalog/'+safe(match[2]),false,true);
  }
  return {route,sourceRoots,readFile,status:async()=>{
    const info=await current();return info?{state:'ready',revision:info.versions?.revision,release:info.release,last_success:info.published_at}:{state:'initializing',phase:'等待 Docker 更新器发布资源'};
  }};
}
