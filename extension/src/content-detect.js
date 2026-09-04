// content-detect.js — monde isolé, DOM <video> + relais hook + MediaRecorder
(function(){
  const candidates = new Map(); // url -> {url, type, title, page, mime, sizeHint, from}
  let emeDetected = false;
  const pageUrl = location.href;
  const pageTitle = document.title || "";

  function sanitizeKey(url, page){ return url + "::" + page; }

  function addCandidate(url, meta){
    if (!url || url.startsWith("blob:")) {
      // For blob, mark mse
      if (url && url.startsWith("blob:")){
        // keep as mse candidate (needs recorder or manifest correlation)
        const key = sanitizeKey(url, pageUrl);
        if (!candidates.has(key)){
          candidates.set(key, {url, type:"mse", title: pageTitle, page: pageUrl, mse:true, from:"dom", eme: emeDetected});
          updateBadge();
        }
      }
      return;
    }
    // dedup by (url, page)
    const key = sanitizeKey(url, pageUrl);
    if (candidates.has(key)) return;
    // ignore segments alone .ts/.m4s without manifest? spec says ignore .ts/.m4s alone
    const low = url.split("?")[0].split("#")[0].toLowerCase();
    if ( (low.endsWith(".ts") || low.endsWith(".m4s")) && !low.includes(".m3u8") && !low.includes(".mpd")){
      // check if we have manifest known? if not, ignore as noise
      // But we still allow direct .ts video file if explicit <video src=.ts>? For MVP ignore as spec
      return;
    }
    // Determine type
    let type = "direct";
    if (low.endsWith(".m3u8") || low.endsWith(".mpd")) type = "hls";
    else if (meta && meta.contentType && (meta.contentType.includes("mpegurl") || meta.contentType.includes("dash+xml"))) type = "hls";
    else if (/youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|dai\.ly/i.test(pageUrl) || /youtube\.com|youtu\.be|vimeo\.com/i.test(url)) type = "ytdlp";
    else type = "direct";

    // DRM guard: if video has mediaKeys or emeDetected, mark drm
    let isDrm = false;
    try{
      const vids = document.querySelectorAll("video");
      for (const v of vids){
        if (v.mediaKeys) isDrm = true;
      }
    }catch{}
    if (emeDetected) isDrm = true;

    candidates.set(key, {
      url, type, title: meta?.title || pageTitle, page: pageUrl,
      mime: meta?.contentType || "", sizeHint: meta?.sizeHint || null,
      from: meta?.from || "unknown",
      drm: isDrm,
      eme: emeDetected
    });
    updateBadge();
  }

  function scanVideos(){
    const videos = document.querySelectorAll("video, audio, source");
    videos.forEach(el=>{
      let src = el.currentSrc || el.src || el.getAttribute("src");
      if (src){
        // resolve relative
        try{ src = new URL(src, location.href).href; }catch{}
        addCandidate(src, {from:"dom"});
      }
      // <video><source>
      if (el.tagName.toLowerCase()==="video"){
        const sources = el.querySelectorAll("source");
        sources.forEach(s=>{
          let ssrc = s.src || s.getAttribute("src");
          if (ssrc){
            try{ ssrc = new URL(ssrc, location.href).href; }catch{}
            addCandidate(ssrc, {from:"dom"});
          }
        });
        // srcObject (WebRTC) -> ignore
        if (el.srcObject) {
          // ignore
        }
        // check mse/blob
        if (el.src && el.src.startsWith("blob:")){
          addCandidate(el.src, {from:"dom"});
        }
      }
    });
    // also watch performance entries for manifest correlation for mse
    try{
      const entries = performance.getEntriesByType("resource");
      entries.forEach(e=>{
        if (e.name && (e.name.includes(".m3u8") || e.name.includes(".mpd"))){
          addCandidate(e.name, {from:"perf"});
        }
      });
    }catch{}
  }

  // Listen to hook messages
  window.addEventListener("message", (ev)=>{
    if (!ev.data || typeof ev.data !== "object") return;
    if (ev.data.type==="fluxcatch-media"){
      const {url, contentType, sizeHint} = ev.data;
      if (!url) return;
      addCandidate(url, {contentType, sizeHint, from:"hook"});
    } else if (ev.data.type==="fluxcatch-eme"){
      emeDetected = true;
    }
  });

  // MutationObserver
  const mo = new MutationObserver(()=> scanVideos());
  try{ mo.observe(document.documentElement, {childList:true, subtree:true, attributes:true, attributeFilter:["src"]}); }catch{}
  setInterval(scanVideos, 3000);
  scanVideos();

  function updateBadge(){
    try{
      chrome.runtime.sendMessage({type:"fluxcatch-candidates", count: candidates.size, page: pageUrl});
    }catch{}
  }

  // Handle messages from background
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse)=>{
    (async ()=>{
      if (msg.type==="fluxcatch-get-candidates"){
        // Return array
        const arr = Array.from(candidates.values()).map(c=>({
          url: c.url, type: c.type, title: c.title, page: c.page, mime: c.mime, sizeHint: c.sizeHint, drm: !!c.drm
        }));
        // Also add ytdlp profile if page is known VOD without direct URL
        if (/youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|dai\.ly/i.test(pageUrl)){
          const hasYt = arr.some(x=>x.type==="ytdlp");
          if (!hasYt){
            arr.push({url: pageUrl, type:"ytdlp", title: pageTitle, page: pageUrl, mime:"", sizeHint:null, drm:false});
          }
        }
        sendResponse(arr);
        // For recorder detection: add synthetic recorder candidate if video MSE detected and not DRM
        const mseVideos = Array.from(document.querySelectorAll("video")).filter(v=> v.src && v.src.startsWith("blob:") || v.srcObject===null && v.currentSrc.startsWith("blob:"));
        // But we already have mse type; add recorder type alternative
        // We'll annotate already; popup can offer recording
        return;
      } else if (msg.type==="fluxcatch-start-recording"){
        const res = await startRecording(msg.videoSelector);
        sendResponse(res);
        return;
      } else if (msg.type==="fluxcatch-stop-recording"){
        const res = await stopRecording();
        sendResponse(res);
        return;
      }
    })();
    return true;
  });

  // MediaRecorder logic
  let recorder = null;
  let recordChunks = [];
  let recordTaskId = null;
  let recordVideo = null;

  async function startRecording(selector){
    try{
      // Find video
      let video = null;
      if (selector){
        video = document.querySelector(selector);
      } else {
        video = document.querySelector("video");
      }
      if (!video) return {ok:false, error:"Aucune vidéo trouvée"};
      // DRM guard
      if (video.mediaKeys || emeDetected || window.__fluxcatchEme){
        return {ok:false, error:"non capturable (protégé DRM)"};
      }
      const stream = video.captureStream ? video.captureStream() : (video.mozCaptureStream ? video.mozCaptureStream() : null);
      if (!stream) return {ok:false, error:"captureStream non supporté"};
      // Check DRM again via EME
      if (video.mediaKeys) return {ok:false, error:"non capturable (protégé DRM)"};
      recordVideo = video;
      recordChunks = [];
      const mimeOpts = [
        'video/webm;codecs=vp8,opus',
        'video/webm;codecs=vp9,opus',
        'video/webm'
      ];
      let chosen = "";
      for (const m of mimeOpts){
        if (MediaRecorder.isTypeSupported(m)){ chosen = m; break; }
      }
      if (!chosen) return {ok:false, error:"MediaRecorder non supporté"};
      recorder = new MediaRecorder(stream, {mimeType: chosen});
      // First, ask background to create task
      // We need to communicate via runtime
      const resp = await new Promise(res=>{
        chrome.runtime.sendMessage({type:"fluxcatch-create-recorder", title: document.title, pageUrl: location.href, mime: chosen}, (r)=> res(r));
      });
      if (!resp || !resp.ok) return {ok:false, error: resp?.error || "échec création tâche"};
      recordTaskId = resp.id;
      recorder.ondataavailable = (e)=>{
        if (e.data && e.data.size>0){
          // Send chunk to background
          e.data.arrayBuffer().then(buf=>{
            chrome.runtime.sendMessage({type:"fluxcatch-recorder-chunk", taskId: recordTaskId, chunk: buf}, ()=>{});
          });
        }
      };
      recorder.onstop = async ()=>{
        // finalize
        chrome.runtime.sendMessage({type:"fluxcatch-recorder-finish", taskId: recordTaskId}, ()=>{});
        recordTaskId = null;
      };
      recorder.start(1000); // 1s chunks
      return {ok:true, taskId: recordTaskId};
    }catch(e){
      return {ok:false, error: String(e)};
    }
  }
  async function stopRecording(){
    try{
      if (recorder && recorder.state !== "inactive"){
        recorder.stop();
        recorder = null;
        return {ok:true};
      }
      return {ok:false, error:"Pas d'enregistrement en cours"};
    }catch(e){ return {ok:false, error:String(e)}; }
  }

  // Also detect page unload to finalize recording?
  window.addEventListener("beforeunload", ()=>{
    if (recorder && recorder.state==="recording"){
      try{ recorder.stop(); }catch{}
    }
  });
})();
