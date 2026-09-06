// background.js — service worker MV3 (Chromium) / background (Firefox)
// Load shim: include api-shim inline? Since we use importless, inline helper here.

// Shim minimal promisses
const fcBrowser = (() => {
  const b = typeof browser !== "undefined" ? browser : null;
  const c = typeof chrome !== "undefined" ? chrome : null;
  const hasBrowser = !!b && !!b.runtime && !!b.storage;
  function promisify(fn, ctx) {
    return (...args) => new Promise((resolve, reject) => {
      try {
        if (hasBrowser && fn && fn.then) return fn(...args).then(resolve, reject);
        // For chrome, try to check if function returns promise (Manifest V3 chrome.* may return promise if no callback)
        const maybe = fn.call(ctx, ...args, (res) => {
          if (c && c.runtime && c.runtime.lastError) reject(c.runtime.lastError);
          else resolve(res);
        });
        if (maybe && typeof maybe.then === "function") {
          maybe.then(resolve, reject);
        }
      } catch (e) { reject(e); }
    });
  }
  return {
    storageGet: (keys) => {
      if (hasBrowser && b.storage) return b.storage.local.get(keys);
      // Chrome storage may return promise directly
      try {
        const res = c.storage.local.get(keys);
        if (res && typeof res.then === "function") return res;
      } catch {}
      return promisify(c.storage.local.get, c.storage.local)(keys);
    },
    storageSet: (obj) => {
      if (hasBrowser && b.storage) return b.storage.local.set(obj);
      try {
        const res = c.storage.local.set(obj);
        if (res && typeof res.then === "function") return res;
      } catch {}
      return promisify(c.storage.local.set, c.storage.local)(obj);
    },
    cookiesGetAll: (details) => {
      if (hasBrowser && b.cookies) return b.cookies.getAll(details);
      try {
        const maybe = c.cookies.getAll(details);
        if (maybe && typeof maybe.then === "function") return maybe;
      } catch {}
      return promisify(c.cookies.getAll, c.cookies)(details);
    },
    tabsQuery: (q) => {
      if (hasBrowser && b.tabs) return b.tabs.query(q);
      try { const m = c.tabs.query(q); if (m && m.then) return m; } catch {}
      return promisify(c.tabs.query, c.tabs)(q);
    },
    tabsSendMessage: (tabId, msg) => {
      if (hasBrowser && b.tabs) return b.tabs.sendMessage(tabId, msg);
      try { const m = c.tabs.sendMessage(tabId, msg); if (m && m.then) return m; } catch {}
      return promisify(c.tabs.sendMessage, c.tabs)(tabId, msg);
    },
  };
})();

// Config default
const DEFAULT_BASE = "http://127.0.0.1:8765";
let candidatesPerTab = new Map(); // tabId -> count
let mediaHeadersMap = new Map(); // url -> {requestHeaders, responseHeaders, mime} from webRequest

// Helpers
async function getBaseUrl() {
  const data = await fcBrowser.storageGet(["baseUrl"]);
  return data.baseUrl || DEFAULT_BASE;
}
async function getPaired() {
  const d = await fcBrowser.storageGet(["paired"]);
  return !!d.paired;
}

// Badge
function updateBadge(tabId, count){
  candidatesPerTab.set(tabId, count);
  try{
    chrome.action.setBadgeText({tabId, text: count ? String(count) : ""});
    chrome.action.setBadgeBackgroundColor({tabId, color: "#4f8cff"});
  }catch{}
}

// webRequest observers (observe without blocking)
try {
  chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
      const url = details.url;
      if (/\.(mp4|webm|m4v|mov|mkv|ts|flv|ogv|avi|m3u8|mpd)(\?|#|$)/i.test(url) || url.includes(".m3u8") || url.includes(".mpd")) {
        // candidate seen, but content-type unknown yet; store placeholder
        if (!mediaHeadersMap.has(url)) mediaHeadersMap.set(url, {});
        mediaHeadersMap.get(url).url = url;
      }
    },
    {urls: ["<all_urls>"]}
  );
} catch(e){ console.warn("onBeforeRequest", e); }

try {
  chrome.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
      const entry = mediaHeadersMap.get(details.url) || {};
      entry.requestHeaders = details.requestHeaders || [];
      entry.url = details.url;
      mediaHeadersMap.set(details.url, entry);
    },
    {urls: ["<all_urls>"]},
    ["requestHeaders", "extraHeaders"].filter(Boolean)
  );
} catch(e){
  try{
    chrome.webRequest.onBeforeSendHeaders.addListener(
      (details)=>{
        const entry = mediaHeadersMap.get(details.url) || {};
        entry.requestHeaders = details.requestHeaders || [];
        entry.url = details.url;
        mediaHeadersMap.set(details.url, entry);
      },
      {urls: ["<all_urls>"]},
      ["requestHeaders"]
    );
  }catch{}
}

try {
  chrome.webRequest.onHeadersReceived.addListener(
    (details) => {
      const ct = (details.responseHeaders || []).find(h=> h.name.toLowerCase()==="content-type");
      const mime = ct ? ct.value : "";
      if (mime && (mime.startsWith("video/") || mime.startsWith("audio/") || mime.includes("mpegurl") || mime.includes("dash+xml"))) {
        const entry = mediaHeadersMap.get(details.url) || {};
        entry.responseHeaders = details.responseHeaders;
        entry.mime = mime;
        entry.url = details.url;
        mediaHeadersMap.set(details.url, entry);
      } else if (/\.(mp4|webm|m4v|mov|m3u8|mpd)/i.test(details.url)) {
        const entry = mediaHeadersMap.get(details.url) || {};
        entry.responseHeaders = details.responseHeaders;
        entry.url = details.url;
        if (mime) entry.mime = mime;
        mediaHeadersMap.set(details.url, entry);
      }
    },
    {urls: ["<all_urls>"]},
    ["responseHeaders", "extraHeaders"].filter(Boolean)
  );
} catch(e){
  try{
    chrome.webRequest.onHeadersReceived.addListener(
      (details)=>{
        const ct = (details.responseHeaders || []).find(h=> h.name.toLowerCase()==="content-type");
        const mime = ct ? ct.value : "";
        if (mime && mime.startsWith("video/")) {
          const entry = mediaHeadersMap.get(details.url) || {};
          entry.responseHeaders = details.responseHeaders;
          entry.mime = mime;
          entry.url = details.url;
          mediaHeadersMap.set(details.url, entry);
        }
      },
      {urls: ["<all_urls>"]},
      ["responseHeaders"]
    );
  }catch{}
}

// Cookies helper
async function buildCookieHeader(resourceUrl){
  try{
    const all = await fcBrowser.cookiesGetAll({url: resourceUrl});
    if (!all || !all.length) return null;
    return all.map(c=> `${c.name}=${c.value}`).join("; ");
  }catch{ return null; }
}

// Build headers map for daemon (only allowed ones)
function headersFromWebRequest(url, pageUrl){
  const entry = mediaHeadersMap.get(url) || {};
  const reqHeaders = entry.requestHeaders || [];
  const allowed = new Set(["cookie","referer","origin","user-agent","x-requested-with","sec-fetch-site","sec-fetch-mode","sec-fetch-dest","accept"]);
  const out = {};
  for (const h of reqHeaders){
    const low = h.name.toLowerCase();
    if (allowed.has(low) && low!=="range" && low!=="if-range"){
      out[h.name] = h.value;
    }
  }
  // Ensure Referer and Origin
  if (!out.Referer && !out.referer && pageUrl) out["Referer"] = pageUrl;
  if (!out.Origin && pageUrl) {
    try{ out["Origin"] = new URL(pageUrl).origin; }catch{}
  }
  return out;
}

// Context menus
try{
  chrome.runtime.onInstalled.addListener(()=>{
    try{
      chrome.contextMenus.create({id:"fluxcatch-video", title:"Attraper la vidéo", contexts:["video","audio","page"]});
    }catch{}
  });
  chrome.contextMenus.onClicked.addListener(async (info, tab)=>{
    if (info.menuItemId==="fluxcatch-video"){
      // Try to get candidates from that tab
      let candidates = [];
      try{
        candidates = await fcBrowser.tabsSendMessage(tab.id, {type:"fluxcatch-get-candidates"});
      }catch{}
      // If video element srcUrl available, prioritize
      const src = info.srcUrl || info.pageUrl;
      let target = null;
      if (info.srcUrl) target = candidates.find(c=>c.url===info.srcUrl) || {url: info.srcUrl, type:"direct", title: tab.title, page: tab.url};
      else target = candidates[0];
      if (!target) target = {url: info.pageUrl, type:"ytdlp", title: tab.title, page: tab.url};
      await createTaskFromCandidate(target, tab);
    }
  });
}catch{}

// Messaging
chrome.runtime.onMessage.addListener((msg, sender, sendResponse)=>{
  (async ()=>{
    if (msg.type==="fluxcatch-candidates"){
      if (sender.tab) updateBadge(sender.tab.id, msg.count);
      sendResponse({ok:true});
    } else if (msg.type==="fluxcatch-create-task"){
      // from popup
      const res = await createTaskFromCandidate(msg.candidate, null);
      sendResponse(res);
    } else if (msg.type==="fluxcatch-create-recorder"){
      const res = await createRecorderTask(msg.title, msg.pageUrl, msg.mime);
      sendResponse(res);
    } else if (msg.type==="fluxcatch-recorder-chunk"){
      const res = await pushChunk(msg.taskId, msg.chunk);
      sendResponse(res);
    } else if (msg.type==="fluxcatch-recorder-finish"){
      const res = await finishUpload(msg.taskId);
      sendResponse(res);
    } else if (msg.type==="fluxcatch-get-candidates-tab"){
      // popup asks background to fetch from active tab
      const tabs = await fcBrowser.tabsQuery({active:true, currentWindow:true});
      if (!tabs[0]) return sendResponse([]);
      try{
        const cand = await fcBrowser.tabsSendMessage(tabs[0].id, {type:"fluxcatch-get-candidates"});
        sendResponse(cand);
      }catch(e){
        sendResponse([]);
      }
    } else if (msg.type==="fluxcatch-pair"){
      const r = await pairWithDaemon(msg.code);
      sendResponse(r);
    } else if (msg.type==="fluxcatch-unpair"){
      const r = await unpairDaemon();
      sendResponse(r);
    } else if (msg.type==="fluxcatch-hello"){
      const r = await helloDaemon();
      sendResponse(r);
    } else if (msg.type==="fluxcatch-browser-proxy"){
      // anti-403 relais: fetch via browser and push via browser_proxy
      const r = await browserProxyRelay(msg.taskId, msg.url, msg.headers);
      sendResponse(r);
    }
  })();
  return true;
});

async function helloDaemon(){
  const base = await getBaseUrl();
  try{
    const r = await fetch(base + "/api/hello");
    const j = await r.json();
    return {ok:true, data:j, base};
  }catch(e){
    return {ok:false, error:String(e)};
  }
}

async function pairWithDaemon(code){
  const base = await getBaseUrl();
  try{
    const r = await fetch(base + "/api/pair", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({code})});
    const j = await r.json().catch(()=>({}));
    if (!r.ok) return {ok:false, error: j.error || r.statusText};
    await fcBrowser.storageSet({paired:true});
    return {ok:true};
  }catch(e){ return {ok:false, error:String(e)}; }
}
async function unpairDaemon(){
  const base = await getBaseUrl();
  try{
    const r = await fetch(base + "/api/pair", {method:"DELETE"});
    await fcBrowser.storageSet({paired:false});
    return {ok:true};
  }catch(e){ return {ok:false, error:String(e)}; }
}

async function createTaskFromCandidate(cand, tab){
  const base = await getBaseUrl();
  if (!cand || !cand.url) return {ok:false, error:"URL manquante"};

  // DRM guard before creating task
  if (cand.drm) return {ok:false, error:"non capturable (protégé DRM)"};

  let kind = cand.type;
  // Map popup type to daemon kind
  if (kind==="ytdlp") kind="ytdlp";
  else if (kind==="hls") kind="hls";
  else if (kind==="direct") kind="direct";
  else if (kind==="mse") {
    // mse blob without URL -> propose recorder fallback? For now return error suggesting recording
    return {ok:false, error:"Flux MSE détecté — utilisez Enregistrement"};
  }
  else kind="direct";

  // Garde-fou #1 : si direct mais URL ressemble à une page (pas d'extension média, .php, viewkey), forcer ytdlp
  if (kind === "direct") {
    const urlLower = (cand.url || "").toLowerCase();
    const hasMediaExt = /\.(mp4|webm|m4v|mov|mkv|ts|flv|ogv|avi|m3u8|mpd)(\?|#|$)/i.test(urlLower);
    const looksLikePage = urlLower.includes("view_video.php") || urlLower.includes("viewkey=") || /\/video\/show\//i.test(urlLower) || (!hasMediaExt && !cand.mime?.toLowerCase().startsWith("video/") && !cand.mime?.toLowerCase().startsWith("audio/"));
    const isPhpHtml = /\.(php|html|htm|aspx|jsp)(\?|#|$)/i.test(urlLower) && !hasMediaExt;
    if (looksLikePage || isPhpHtml) {
      kind = "ytdlp";
      if (!cand.page) cand.page = cand.url;
    }
  }

  // Build headers with cookies
  let urlForCookies = cand.url;
  if (kind==="ytdlp") urlForCookies = cand.page || cand.url;
  const cookie = await buildCookieHeader(urlForCookies);
  let headers = {};
  if (kind !== "ytdlp"){
    headers = headersFromWebRequest(cand.url, cand.page);
  } else {
    // for ytdlp, just referer
    if (cand.page) headers["Referer"] = cand.page;
  }
  if (cookie) headers["Cookie"] = cookie;
  // Ensure allowed headers only (daemon will filter but we filter too)
  const allowed = new Set(["cookie","referer","origin","user-agent","x-requested-with","sec-fetch-site","sec-fetch-mode","sec-fetch-dest","accept"]);
  const filtered = {};
  for (const [k,v] of Object.entries(headers)){
    if (allowed.has(k.toLowerCase())) filtered[k]=v;
  }
  // If we have origin from headersFrom, keep it; else set from page
  if (!filtered.Origin && !filtered.origin && cand.page){
    try{ filtered["Origin"] = new URL(cand.page).origin; }catch{}
  }

  const body = {
    kind,
    url: kind==="ytdlp" ? undefined : cand.url,
    page_url: cand.page,
    title: cand.title || "video",
    headers: filtered,
  };
  try{
    const r = await fetch(base + "/api/tasks", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(()=>({}));
    if (r.status===403){
      await fcBrowser.storageSet({paired:false});
      return {ok:false, error:"Non lié — saisissez le code de liaison dans le popup"};
    }
    if (!r.ok) return {ok:false, error: j.error || r.statusText};
    return {ok:true, id: j.id};
  }catch(e){
    return {ok:false, error:String(e)};
  }
}

async function createRecorderTask(title, pageUrl, mime){
  const base = await getBaseUrl();
  const cookie = await buildCookieHeader(pageUrl);
  const headers = {};
  if (cookie) headers["Cookie"] = cookie;
  if (pageUrl) headers["Referer"] = pageUrl;
  try{ headers["Origin"] = new URL(pageUrl).origin; }catch{}
  const body = {kind:"recorder", page_url: pageUrl, title, headers, extra:{mime}};
  try{
    const r = await fetch(base + "/api/tasks", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(()=>({}));
    if (r.status===403){
      await fcBrowser.storageSet({paired:false});
      return {ok:false, error:"Non lié"};
    }
    if (!r.ok) return {ok:false, error: j.error || r.statusText};
    return {ok:true, id:j.id};
  }catch(e){ return {ok:false, error:String(e)}; }
}

async function pushChunk(taskId, arrayBuffer){
  const base = await getBaseUrl();
  try{
    // arrayBuffer may be serialized as object? In message passing, ArrayBuffer is transferable but we used chunk: buf
    let buf = arrayBuffer;
    if (buf instanceof ArrayBuffer) buf = new Uint8Array(buf);
    else if (Array.isArray(buf)) buf = new Uint8Array(buf);
    // Need Blob
    const r = await fetch(base + `/api/tasks/${taskId}/chunks`, {method:"POST", body: buf, headers:{"Content-Type":"application/octet-stream"}});
    if (!r.ok){
      const j = await r.json().catch(()=>({}));
      return {ok:false, error: j.error || r.statusText};
    }
    return {ok:true};
  }catch(e){ return {ok:false, error:String(e)}; }
}
async function finishUpload(taskId){
  const base = await getBaseUrl();
  try{
    const r = await fetch(base + `/api/tasks/${taskId}/finish`, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({})});
    if (!r.ok){
      const j = await r.json().catch(()=>({}));
      return {ok:false, error: j.error || r.statusText};
    }
    return {ok:true};
  }catch(e){ return {ok:false, error:String(e)}; }
}

// Browser proxy relay (anti-403) - fetch with browser's credentials and push as browser_proxy task
async function browserProxyRelay(taskId, url, headers){
  const base = await getBaseUrl();
  try{
    // First create browser_proxy task if taskId not given? Actually spec says if direct fails 403, extension can re-download and push via browser_proxy kind.
    // Here we assume caller already has a failed direct task and wants to retry via relay; we will create a new browser_proxy task and relay.
    // For simplicity, if taskId exists, we reuse it? But chunks expects recorder/browser_proxy kind. If original task was direct and 403, we create new.
    let proxyId = taskId;
    if (!proxyId){
      // create new task
      const cookie = await buildCookieHeader(url);
      const hdrs = {...(headers||{})};
      if (cookie) hdrs["Cookie"] = cookie;
      const body = {kind:"browser_proxy", url, page_url: headers?.Referer, title: url.split("/").pop()||"video", headers: hdrs};
      const cr = await fetch(base+"/api/tasks", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
      const cj = await cr.json();
      if (!cr.ok) return {ok:false, error: cj.error};
      proxyId = cj.id;
    }
    // Fetch with credentials include
    const resp = await fetch(url, {credentials:"include", headers: headers||{}});
    if (!resp.ok) return {ok:false, error:`fetch ${resp.status}`};
    const reader = resp.body.getReader();
    while(true){
      const {done, value} = await reader.read();
      if (done) break;
      if (value && value.length){
        // buffer 1M chunks: value is already Uint8Array
        // push
        const r = await fetch(base + `/api/tasks/${proxyId}/chunks`, {method:"POST", body: value});
        if (!r.ok) return {ok:false, error:"chunks failed"};
      }
    }
    const fin = await fetch(base+`/api/tasks/${proxyId}/finish`, {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    if (!fin.ok) return {ok:false, error:"finish failed"};
    return {ok:true, id: proxyId};
  }catch(e){ return {ok:false, error:String(e)}; }
}

// Cleanup old headers map periodically
setInterval(()=>{ if (mediaHeadersMap.size>500) mediaHeadersMap.clear(); }, 60000);
