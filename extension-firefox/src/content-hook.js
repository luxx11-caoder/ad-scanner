// content-hook.js — monde MAIN (isolé non, page). Hook fetch/XHR + EME + performance entries + player tracking
(function(){
  if (window.__fluxcatchHook) return;
  window.__fluxcatchHook = true;
  window.__fluxcatchEme = false;

  const seen = new Set();
  function notify(url, contentType, sizeHint){
    try{
      const payload = {type:"fluxcatch-media", url, contentType: contentType||"", sizeHint: sizeHint||null};
      window.postMessage(payload, "*");
    }catch{}
  }
  function notifyPlayer(url, kind){
    try{
      const vids = document.querySelectorAll("video");
      let idx = -1;
      let best = null;
      // trouve la vidéo qui a déclenché (la plus proche du viewport ou en lecture)
      for (let i=0;i<vids.length;i++){
        const r = vids[i].getBoundingClientRect();
        const area = r.width * r.height;
        if (!best || area > best.area) best = {i, area, el: vids[i]};
        // si l'URL correspond à currentSrc, c'est elle
        try{
          const src = vids[i].currentSrc || vids[i].src || "";
          if (src && url && src === url) { idx = i; break; }
        }catch{}
      }
      if (idx === -1 && best) idx = best.i;
      const el = idx >=0 ? vids[idx] : null;
      const w = el ? el.videoWidth || el.clientWidth : 0;
      const h = el ? el.videoHeight || el.clientHeight : 0;
      const rect = el ? el.getBoundingClientRect() : {width:0,height:0};
      window.postMessage({type:"fluxcatch-player-src", url, kind: kind||"src", videoIndex: idx, w, h, vw: rect.width, vh: rect.height}, "*");
    }catch{}
  }

  // Detect EME
  try{
    const orig = navigator.requestMediaKeySystemAccess;
    if (orig){
      navigator.requestMediaKeySystemAccess = function(...args){
        window.__fluxcatchEme = true;
        try{ window.postMessage({type:"fluxcatch-eme", eme:true}, "*"); }catch{}
        return orig.apply(this, args);
      };
    }
  }catch{}

  // Hook player src / play pour lier flux ↔ élément
  try{
    const proto = HTMLMediaElement.prototype;
    const descSrc = Object.getOwnPropertyDescriptor(proto, "src");
    if (descSrc && descSrc.set){
      Object.defineProperty(proto, "src", {
        get: descSrc.get,
        set: function(v){
          try{ if (v) notifyPlayer(v, "src-set"); }catch{}
          return descSrc.set.call(this, v);
        },
        configurable: true
      });
    }
    const origPlay = proto.play;
    if (origPlay){
      proto.play = function(...args){
        try{
          const src = this.currentSrc || this.src || "";
          if (src) notifyPlayer(src, "play");
          else {
            const s = this.querySelector("source");
            if (s && s.src) notifyPlayer(s.src, "play-source");
          }
          // notifie aussi le manifest en cours si blob/MSE
          if (this.src && this.src.startsWith("blob:")) {
            notifyPlayer(this.src, "play-blob");
          }
        }catch{}
        return origPlay.apply(this, args);
      };
    }
    // intercepte load() aussi
    const origLoad = proto.load;
    if (origLoad){
      proto.load = function(...a){
        try{
          const src = this.currentSrc || this.src || "";
          if (src) notifyPlayer(src, "load");
        }catch{}
        return origLoad.apply(this, a);
      };
    }
  }catch{}

  // Helper to check media types
  function isMediaUrl(url){
    if(!url) return false;
    const l = url.split("?")[0].split("#")[0].toLowerCase();
    return /\.(mp4|webm|m4v|mov|mkv|ts|flv|ogv|avi|m3u8|mpd)(\/|$)/i.test(url) || /\.(mp4|webm|m4v|mov|mkv|ts|flv|ogv|avi|m3u8|mpd)(\?|#|$)/i.test(url);
  }
  function isMediaContentType(ct){
    if(!ct) return false;
    ct = ct.toLowerCase();
    return ct.startsWith("video/") || ct.startsWith("audio/") || ct.includes("mpegurl") || ct.includes("dash+xml") || ct.includes("mp2t");
  }

  // Patch fetch
  try{
    const origFetch = window.fetch;
    if (origFetch){
      window.fetch = async function(input, init){
        const resp = await origFetch.apply(this, arguments);
        try{
          const url = typeof input === "string" ? input : input?.url;
          if (url && (isMediaUrl(url))){
            const ct = resp.headers.get("content-type") || "";
            const cl = resp.headers.get("content-length");
            if (isMediaUrl(url) || isMediaContentType(ct)){
              notify(url, ct, cl ? parseInt(cl,10) : null);
            }
          } else {
            const ct = resp.headers.get("content-type") || "";
            if (isMediaContentType(ct)){
              const url2 = typeof input === "string" ? input : input?.url;
              notify(url2, ct, resp.headers.get("content-length") ? parseInt(resp.headers.get("content-length"),10):null);
            }
          }
        }catch{}
        return resp;
      };
    }
  }catch{}

  // Patch XHR
  try{
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest){
      this.__fluxcatchUrl = url;
      return origOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(...args){
      this.addEventListener("readystatechange", function(){
        if (this.readyState === 2){
          try{
            const ct = this.getResponseHeader("content-type") || "";
            const url = this.__fluxcatchUrl || this.responseURL;
            if (url && (isMediaUrl(url) || isMediaContentType(ct))){
              const cl = this.getResponseHeader("content-length");
              notify(url, ct, cl ? parseInt(cl,10):null);
            }
          }catch{}
        }
      });
      return origSend.apply(this, args);
    };
  }catch{}

  // Also watch performance entries for .m3u8/.mpd after load
  try{
    const checkPerf = () => {
      try{
        const entries = performance.getEntriesByType("resource");
        for (const e of entries){
          const url = e.name;
          if (!url || seen.has(url)) continue;
          if (isMediaUrl(url)){
            seen.add(url);
            notify(url, "", null);
          }
        }
      }catch{}
    };
    setInterval(checkPerf, 3000);
    window.addEventListener("load", checkPerf);
  }catch{}
})();
