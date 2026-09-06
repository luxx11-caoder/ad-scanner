// content-detect.js — monde isolé, DOM <video> + relais hook + MediaRecorder + scoring anti-pub
(function(){
  const candidates = new Map(); // url -> {url, type, title, page, mime, sizeHint, from, playerScore...}
  let emeDetected = false;
  const pageUrl = location.href;
  const pageTitle = document.title || "";
  const playerMap = new Map(); // url -> {videoIndex, w, h}
  const prevTime = new Map(); // video element -> last currentTime
  const prevCheck = new Map(); // video element -> last check timestamp

  function sanitizeKey(url, page){ return url + "::" + page; }

  function getDuration(el){
    let d = el.duration;
    if (Number.isFinite(d) && d > 0) return d;
    try{
      if (el.seekable && el.seekable.length) {
        const e = el.seekable.end(el.seekable.length-1);
        if (Number.isFinite(e) && e>0) return e;
      }
    }catch{}
    try{
      if (el.buffered && el.buffered.length) {
        const e = el.buffered.end(el.buffered.length-1);
        if (Number.isFinite(e) && e>0) return e;
      }
    }catch{}
    return NaN;
  }

  function scoreVideo(el){
    if (!el) return 0;
    let score = 0;
    try{
      const rect = el.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight;
      const area = Math.max(0, rect.width) * Math.max(0, rect.height);
      const viewportArea = vw * vh;
      const pct = viewportArea ? (area / viewportArea) * 100 : 0;
      // Surface visible +40 si grande, +20 si moyenne, 0 si petite, -30 si cachée
      if (rect.width < 2 || rect.height < 2) score -= 30;
      else if (area < 50*50) score -= 10;
      else if (pct >= 10) score += 40;
      else if (pct >= 3) score += 20;
      else if (area >= 320*180) score += 10;

      // Visible / pas display:none, opacity, etc.
      const style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) score -= 30;
      if (rect.top > vh || rect.bottom < 0 || rect.left > vw || rect.right < 0) score -= 30;
      if (rect.width === 0 || rect.height === 0) score -= 20;

      // En lecture +25 si en cours
      const isPlayingNow = !el.paused && !el.ended && el.readyState > 2;
      // Vérifie que currentTime avance (entre 2 scans)
      let advancing = false;
      const last = prevTime.get(el);
      const curT = el.currentTime;
      if (last !== undefined && Number.isFinite(curT) && Number.isFinite(last) && curT > last + 0.05) advancing = true;
      prevTime.set(el, curT);
      if (isPlayingNow && advancing) score += 25;
      else if (isPlayingNow) score += 10;
      else if (el.paused && el.currentTime > 0) score += 5;

      // Durée
      const dur = getDuration(el);
      if (Number.isFinite(dur)) {
        if (dur > 60) score += 15;
        else if (dur < 15) score -= 20;
        else if (dur < 30) score -= 5;
      }

      // Son non muté +10 (faible poids, pubs souvent mutées au début)
      if (!el.muted && el.volume > 0) score += 10;

      // Premier plan (z-index) +5 si grande surface déjà
      if (pct >= 5) score += 5;

    }catch{}
    return Math.max(-50, Math.min(100, score));
  }

  function isLikelyAd(el, score, duration){
    try{
      const rect = el.getBoundingClientRect();
      const small = rect.width < 320 || rect.height < 180 || (rect.width*rect.height) < 50000;
      const shortDur = Number.isFinite(duration) && duration < 15;
      // petite + courte = pub très probable
      if (small && shortDur) return true;
      // cachée/hors écran + courte
      if (score < -10 && shortDur) return true;
      // très petit et pas en lecture
      if (small && el.paused && !el.autoplay) {
        // peut être pub en attente, mais on ne marque que si aussi courte ou score bas
        if (score < 0) return true;
      }
    }catch{}
    return false;
  }

  function addCandidate(url, meta){
    if (!url || url.startsWith("blob:")) {
      if (url && url.startsWith("blob:")){
        const key = sanitizeKey(url, pageUrl);
        if (!candidates.has(key)){
          // essaie de scorer la vidéo blob
          let bestScore = 0, bestEl = null;
          document.querySelectorAll("video").forEach(v=>{
            if ((v.currentSrc && v.currentSrc === url) || v.src === url) {
              const s = scoreVideo(v);
              if (s > bestScore) { bestScore = s; bestEl = v; }
            }
          });
          const dur = bestEl ? getDuration(bestEl) : NaN;
          candidates.set(key, {url, type:"mse", title: pageTitle, page: pageUrl, mse:true, from:"dom", eme: emeDetected, playerScore: bestScore, duration: dur, likelyAd: bestEl ? isLikelyAd(bestEl, bestScore, dur) : false, vw: bestEl? bestEl.clientWidth:0, vh: bestEl? bestEl.clientHeight:0, isPlaying: bestEl? !bestEl.paused:false});
          updateBadge();
        }
      }
      return;
    }
    const key = sanitizeKey(url, pageUrl);
    if (candidates.has(key)) {
      // mettre à jour score si on a de nouvelles infos player
      const existing = candidates.get(key);
      if (meta && meta.videoIndex !== undefined) {
        const vids = document.querySelectorAll("video");
        const el = vids[meta.videoIndex];
        if (el) {
          const s = scoreVideo(el);
          const dur = getDuration(el);
          existing.playerScore = Math.max(existing.playerScore||0, s);
          existing.duration = dur;
          existing.likelyAd = isLikelyAd(el, s, dur);
          existing.vw = el.clientWidth;
          existing.vh = el.clientHeight;
          existing.isPlaying = !el.paused && !el.ended;
        }
      }
      return;
    }
    const low = url.split("?")[0].split("#")[0].toLowerCase();
    if ( (low.endsWith(".ts") || low.endsWith(".m4s")) && !low.includes(".m3u8") && !low.includes(".mpd")){
      return;
    }
    let type = "direct";
    if (low.endsWith(".m3u8") || low.endsWith(".mpd")) type = "hls";
    else if (meta && meta.contentType && (meta.contentType.includes("mpegurl") || meta.contentType.includes("dash+xml"))) type = "hls";
    else if (/youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|dai\.ly/i.test(pageUrl) || /youtube\.com|youtu\.be|vimeo\.com/i.test(url)) type = "ytdlp";
    else type = "direct";

    let isDrm = false;
    try{
      const vids = document.querySelectorAll("video");
      for (const v of vids){
        if (v.mediaKeys) isDrm = true;
      }
    }catch{}
    if (emeDetected) isDrm = true;

    // scoring : trouve la vidéo la plus liée à cette URL
    let bestScore = -100, bestEl = null, bestDur = NaN;
    const vids = document.querySelectorAll("video");
    const playerInfo = playerMap.get(url);
    if (playerInfo && playerInfo.videoIndex !== undefined && vids[playerInfo.videoIndex]) {
      bestEl = vids[playerInfo.videoIndex];
      bestScore = scoreVideo(bestEl);
      bestDur = getDuration(bestEl);
    } else {
      // cherche par src match ou par score max si manifest
      for (const v of vids) {
        const src = v.currentSrc || v.src || "";
        const s = scoreVideo(v);
        // si src correspond, boost
        if (src && url && (src === url || src.includes(url) || url.includes(src))) {
          bestScore = Math.max(bestScore, s + 10);
          bestEl = v; bestDur = getDuration(v);
          break;
        }
        // pour HLS, le manifest n'est pas le src de la vidéo (blob), on prend la meilleure vidéo en lecture
        if (type === "hls" && !v.paused && s > bestScore) {
          bestScore = s;
          bestEl = v; bestDur = getDuration(v);
        }
      }
      // si toujours pas trouvé, prend la meilleure vidéo globale pour donner un score
      if (!bestEl) {
        for (const v of vids) {
          const s = scoreVideo(v);
          if (s > bestScore) { bestScore = s; bestEl = v; bestDur = getDuration(v); }
        }
      }
    }
    if (bestScore === -100) { bestScore = 0; }

    const likelyAd = bestEl ? isLikelyAd(bestEl, bestScore, bestDur) : false;

    candidates.set(key, {
      url, type, title: meta?.title || pageTitle, page: pageUrl,
      mime: meta?.contentType || "", sizeHint: meta?.sizeHint || null,
      from: meta?.from || "unknown",
      drm: isDrm,
      eme: emeDetected,
      playerScore: bestScore,
      duration: bestDur,
      likelyAd,
      vw: bestEl ? bestEl.clientWidth : (meta?.vw||0),
      vh: bestEl ? bestEl.clientHeight : (meta?.vh||0),
      isPlaying: bestEl ? (!bestEl.paused && !bestEl.ended) : false
    });
    updateBadge();
  }

  function scanVideos(){
    const videos = document.querySelectorAll("video, audio, source");
    videos.forEach(el=>{
      let src = el.currentSrc || el.src || el.getAttribute("src");
      if (src){
        try{ src = new URL(src, location.href).href; }catch{}
        addCandidate(src, {from:"dom"});
      }
      if (el.tagName.toLowerCase()==="video"){
        const sources = el.querySelectorAll("source");
        sources.forEach(s=>{
          let ssrc = s.src || s.getAttribute("src");
          if (ssrc){
            try{ ssrc = new URL(ssrc, location.href).href; }catch{}
            addCandidate(ssrc, {from:"dom"});
          }
        });
        if (el.srcObject) {}
        if (el.src && el.src.startsWith("blob:")){
          addCandidate(el.src, {from:"dom"});
        }
      }
    });
    try{
      const entries = performance.getEntriesByType("resource");
      entries.forEach(e=>{
        if (e.name && (e.name.includes(".m3u8") || e.name.includes(".mpd"))){
          addCandidate(e.name, {from:"perf"});
        }
      });
    }catch{}
    // rescore toutes les candidates périodiquement (pour mettre à jour isPlaying/duration)
    try{
      candidates.forEach((cand, key)=>{
        // retrouve la vidéo liée si possible
        const vids = document.querySelectorAll("video");
        let bestEl = null, bestScore = cand.playerScore || 0;
        // si on a déjà un playerMap pour cette URL, rescore
        const pm = playerMap.get(cand.url);
        if (pm && vids[pm.videoIndex]) bestEl = vids[pm.videoIndex];
        if (bestEl) {
          const s = scoreVideo(bestEl);
          if (s !== cand.playerScore) {
            cand.playerScore = s;
            cand.isPlaying = !bestEl.paused;
            cand.duration = getDuration(bestEl);
            cand.likelyAd = isLikelyAd(bestEl, s, cand.duration);
          }
        }
      });
    }catch{}
  }

  window.addEventListener("message", (ev)=>{
    if (!ev.data || typeof ev.data !== "object") return;
    if (ev.data.type==="fluxcatch-media"){
      const {url, contentType, sizeHint} = ev.data;
      if (!url) return;
      addCandidate(url, {contentType, sizeHint, from:"hook"});
    } else if (ev.data.type==="fluxcatch-eme"){
      emeDetected = true;
    } else if (ev.data.type==="fluxcatch-player-src"){
      const {url, videoIndex, w, h} = ev.data;
      if (url) playerMap.set(url, {videoIndex, w, h});
      // aussi ajouter comme candidate si c'est une URL média
      if (url && (url.includes(".m3u8") || url.includes(".mpd") || url.startsWith("blob:") || url.includes(".mp4"))) {
        addCandidate(url, {from:"hook-player", videoIndex, vw: w, vh: h});
      }
    }
  });

  const mo = new MutationObserver(()=> scanVideos());
  try{ mo.observe(document.documentElement, {childList:true, subtree:true, attributes:true, attributeFilter:["src"]}); }catch{}
  setInterval(scanVideos, 3000);
  // interval plus rapide pour détecter currentTime qui avance (scoring isPlaying)
  setInterval(()=>{
    document.querySelectorAll("video").forEach(v=>{
      // juste pour mettre à jour prevTime
      scoreVideo(v);
    });
  }, 1000);
  scanVideos();

  function updateBadge(){
    try{
      // compte sans les pubs ? on compte tout mais on pourrait compter non-pub
      chrome.runtime.sendMessage({type:"fluxcatch-candidates", count: candidates.size, page: pageUrl});
    }catch{}
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse)=>{
    (async ()=>{
      if (msg.type==="fluxcatch-get-candidates"){
        // trier par score décroissant : principal d'abord, pubs en bas
        const arr = Array.from(candidates.values()).map(c=>({
          url: c.url, type: c.type, title: c.title, page: c.page, mime: c.mime, sizeHint: c.sizeHint, drm: !!c.drm,
          playerScore: c.playerScore||0, duration: c.duration, likelyAd: !!c.likelyAd, vw: c.vw, vh: c.vh, isPlaying: !!c.isPlaying
        }));
        arr.sort((a,b)=>{
          // DRM à la fin ? non, on garde DRM visible mais on pourrait les mettre en bas
          if (a.likelyAd && !b.likelyAd) return 1;
          if (!a.likelyAd && b.likelyAd) return -1;
          return (b.playerScore||0) - (a.playerScore||0);
        });
        if (/youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|dai\.ly/i.test(pageUrl)){
          const hasYt = arr.some(x=>x.type==="ytdlp");
          if (!hasYt){
            arr.push({url: pageUrl, type:"ytdlp", title: pageTitle, page: pageUrl, mime:"", sizeHint:null, drm:false, playerScore: 0, likelyAd:false});
          }
        }
        sendResponse(arr);
        return;
      } else if (msg.type==="fluxcatch-analyze-player"){
        // Lancer le meilleur candidat et rescanner
        const vids = Array.from(document.querySelectorAll("video"));
        // trouve le meilleur score
        let best = null, bestScore = -100;
        vids.forEach(v=>{
          const s = scoreVideo(v);
          if (s > bestScore) { bestScore = s; best = v; }
        });
        if (!best) {
          // pas de vidéo, essaie de jouer la première
          best = vids[0];
        }
        let played = false;
        let error = null;
        if (best) {
          try{
            // essaie de jouer (muted si besoin)
            const p = best.play();
            if (p && p.then) await p.catch(async e=>{
              // NotAllowedError -> essayer muted
              if (e && e.name === "NotAllowedError") {
                const wasMuted = best.muted;
                best.muted = true;
                try{ await best.play(); played = true; }catch(e2){ error = String(e2); }
                // on laisse muted, l'utilisateur pourra démuter
              } else error = String(e);
            });
            if (!error) played = true;
          }catch(e){ error = String(e); }
          // attend 3s que le player charge le manifest
          await new Promise(r=>setTimeout(r, 3000));
          scanVideos();
          // rescore après play
          // attend un peu plus si besoin
          await new Promise(r=>setTimeout(r, 500));
        }
        const arr = Array.from(candidates.values()).map(c=>({
          url: c.url, type: c.type, title: c.title, page: c.page, mime: c.mime, sizeHint: c.sizeHint, drm: !!c.drm,
          playerScore: c.playerScore||0, duration: c.duration, likelyAd: !!c.likelyAd, vw: c.vw, vh: c.vh, isPlaying: !!c.isPlaying
        }));
        arr.sort((a,b)=>{
          if (a.likelyAd && !b.likelyAd) return 1;
          if (!a.likelyAd && b.likelyAd) return -1;
          return (b.playerScore||0) - (a.playerScore||0);
        });
        sendResponse({ok:true, played, error, candidates: arr});
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

  let recorder = null;
  let recordChunks = [];
  let recordTaskId = null;
  let recordVideo = null;

  async function startRecording(selector){
    try{
      let video = null;
      if (selector){
        video = document.querySelector(selector);
      } else {
        // prend la meilleure vidéo au lieu de la première
        const vids = Array.from(document.querySelectorAll("video"));
        let best = null, bestScore=-100;
        vids.forEach(v=>{
          const s = scoreVideo(v);
          if (s > bestScore) { bestScore=s; best=v; }
        });
        video = best || document.querySelector("video");
      }
      if (!video) return {ok:false, error:"Aucune vidéo trouvée"};
      if (video.mediaKeys || emeDetected || window.__fluxcatchEme){
        return {ok:false, error:"non capturable (protégé DRM)"};
      }
      const stream = video.captureStream ? video.captureStream() : (video.mozCaptureStream ? video.mozCaptureStream() : null);
      if (!stream) return {ok:false, error:"captureStream non supporté"};
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
      const resp = await new Promise(res=>{
        chrome.runtime.sendMessage({type:"fluxcatch-create-recorder", title: document.title, pageUrl: location.href, mime: chosen}, (r)=> res(r));
      });
      if (!resp || !resp.ok) return {ok:false, error: resp?.error || "échec création tâche"};
      recordTaskId = resp.id;
      recorder.ondataavailable = (e)=>{
        if (e.data && e.data.size>0){
          e.data.arrayBuffer().then(buf=>{
            chrome.runtime.sendMessage({type:"fluxcatch-recorder-chunk", taskId: recordTaskId, chunk: buf}, ()=>{});
          });
        }
      };
      recorder.onstop = async ()=>{
        chrome.runtime.sendMessage({type:"fluxcatch-recorder-finish", taskId: recordTaskId}, ()=>{});
        recordTaskId = null;
      };
      recorder.start(1000);
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

  window.addEventListener("beforeunload", ()=>{
    if (recorder && recorder.state==="recording"){
      try{ recorder.stop(); }catch{}
    }
  });
})();
