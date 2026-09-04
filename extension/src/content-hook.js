// content-hook.js — monde MAIN (isolé non, page). Hook fetch/XHR + EME + performance entries
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
            // try to read content-type without consuming body
            const ct = resp.headers.get("content-type") || "";
            const cl = resp.headers.get("content-length");
            if (isMediaUrl(url) || isMediaContentType(ct)){
              notify(url, ct, cl ? parseInt(cl,10) : null);
            }
          } else {
            // also check content-type even if URL not media (could be blob)
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
    const origGetHeader = XMLHttpRequest.prototype.getResponseHeader;
    XMLHttpRequest.prototype.open = function(method, url, ...rest){
      this.__fluxcatchUrl = url;
      return origOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(...args){
      this.addEventListener("readystatechange", function(){
        if (this.readyState === 2){ // HEADERS_RECEIVED
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
    // also observe?
    window.addEventListener("load", checkPerf);
  }catch{}
})();
