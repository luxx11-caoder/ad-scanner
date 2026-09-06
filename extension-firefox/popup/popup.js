async function getStorage(key){ return new Promise(res=> chrome.storage.local.get(key, res)); }
async function setStorage(obj){ return new Promise(res=> chrome.storage.local.set(obj, ()=>res())); }

function typeLabel(t){
  const m={direct:"Directe", hls:"Flux HLS", ytdlp:"YouTube·VOD", mse:"MSE", recorder:"Enregistrement"};
  return m[t]||t;
}
function formatDuration(s){
  if (!Number.isFinite(s) || s<=0) return "";
  if (s < 60) return Math.round(s)+"s";
  const m = Math.floor(s/60), sec = Math.round(s%60);
  return `${m}m${sec.toString().padStart(2,'0')}s`;
}

async function refresh(){
  try{
    const resp = await chrome.runtime.sendMessage({type:"fluxcatch-hello"});
    if (resp && resp.ok){
      document.getElementById("pair-section").style.display = resp.data.paired ? "none" : "block";
      document.getElementById("status").textContent = resp.data.paired ? "Lié au daemon v"+resp.data.version : "Non lié (code requis)";
      if (resp.data.paired) document.getElementById("candidates-section").style.display = "block";
    } else {
      document.getElementById("status").textContent = "Daemon hors ligne — lancez fluxcatch serve";
      document.getElementById("pair-section").style.display = "block";
    }
  }catch(e){
    document.getElementById("status").textContent = "Erreur: "+e.message;
  }
  try{
    const cands = await chrome.runtime.sendMessage({type:"fluxcatch-get-candidates-tab"});
    renderCandidates(cands||[]);
  }catch{
    renderCandidates([]);
  }
}

function renderCandidates(list){
  const cont = document.getElementById("candidates");
  const no = document.getElementById("no-candidates");
  cont.innerHTML="";
  if (!list.length){
    no.style.display="block";
    return;
  }
  no.style.display="none";
  // list déjà triée côté content-detect, mais on re-trie au cas où
  // principal (likelyAd false, score haut) d'abord
  for (let idx=0; idx<list.length; idx++){
    const c = list[idx];
    const isPrincipal = idx===0 && !c.likelyAd && (c.playerScore||0) > 10;
    const div = document.createElement("div");
    div.className="candidate";
    const isDrm = c.drm;
    const dur = c.duration ? formatDuration(c.duration) : "";
    const res = (c.vw && c.vh) ? `${c.vw}×${c.vh}` : "";
    const playing = c.isPlaying ? "▶" : "";
    const score = c.playerScore !== undefined ? `score:${c.playerScore}` : "";
    let badges = `<span class="badge ${c.type}">${typeLabel(c.type)}</span>`;
    if (isPrincipal) badges += ` <span class="badge" style="background:#1a3a2a;color:#7be0a3;border-color:#2a6b44;">★ Principal</span>`;
    if (c.likelyAd) badges += ` <span class="badge" style="background:#3a2f1a;color:#ffdd8c;">pub probable</span>`;
    if (dur) badges += ` <span class="badge">${dur}</span>`;
    if (res) badges += ` <span class="badge">${res}</span>`;
    if (playing) badges += ` <span class="badge" style="background:#1a2a4a;color:#8cb3ff;">${playing} en lecture</span>`;
    // debug score en hint
    const metaLine = `${c.mime||""} ${c.sizeHint? Math.round(c.sizeHint/1024)+" Ko":""} ${score}`.trim();
    div.innerHTML=`
      <div class="candidate-title" title="${c.url}">${(c.title||c.url).slice(0,80)}</div>
      <div class="candidate-meta">${badges}</div>
      <div class="candidate-meta" style="font-size:10px; opacity:0.7;">${metaLine}</div>
      <div class="candidate-meta" style="font-size:10px; word-break:break-all;">${c.url.slice(0,120)}</div>
      ${isDrm ? `<div class="badge recorder">non capturable (protégé DRM)</div>` : `<div class="candidate-actions"><button data-url="${encodeURIComponent(c.url)}" data-type="${c.type}" class="primary">Télécharger</button><button data-url="${encodeURIComponent(c.url)}" data-force="ytdlp" class="small" title="Forcer via yt-dlp (page web)">Forcer yt-dlp</button></div>`}
    `;
    cont.appendChild(div);
  }
  cont.querySelectorAll("button[data-url]").forEach(btn=>{
    const isForce = btn.dataset.force === "ytdlp";
    btn.addEventListener("click", async ()=>{
      btn.disabled=true;
      const url = decodeURIComponent(btn.dataset.url);
      const candidate = list.find(x=>x.url===url);
      if (!candidate) return;
      if (!isForce && candidate.type==="mse"){
        document.getElementById("record-msg").textContent="Flux MSE détecté — utilisez Enregistrement ci-dessous";
        btn.disabled=false;
        return;
      }
      let toSend = candidate;
      if (isForce) {
        toSend = {...candidate, type:"ytdlp", page: candidate.page || candidate.url, url: candidate.url};
      }
      btn.textContent="…";
      const res = await chrome.runtime.sendMessage({type:"fluxcatch-create-task", candidate: toSend});
      if (res && res.ok){
        btn.textContent="✓ Envoyé";
        document.getElementById("status").textContent="Tâche créée: "+res.id;
      } else {
        btn.textContent="Erreur";
        document.getElementById("status").textContent=res?.error||"Erreur";
        alert(res?.error||"Erreur");
        btn.disabled=false;
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", ()=>{
  refresh();
  // bouton analyser
  const btnAnalyze = document.getElementById("btn-analyze");
  const analyzeMsg = document.getElementById("analyze-msg");
  if (btnAnalyze) {
    btnAnalyze.addEventListener("click", async ()=>{
      btnAnalyze.disabled = true;
      const old = btnAnalyze.textContent;
      btnAnalyze.textContent = "⏳ Détection...";
      analyzeMsg.textContent = "Lancement de la vidéo principale pour révéler le flux (3s)...";
      try{
        const res = await chrome.runtime.sendMessage({type:"fluxcatch-analyze-player"});
        if (res && res.ok) {
          if (res.played) analyzeMsg.textContent = "Vidéo lancée, flux détecté ✓";
          else if (res.error) analyzeMsg.textContent = "Analyse: " + res.error;
          else analyzeMsg.textContent = "Analyse terminée";
          if (res.candidates) renderCandidates(res.candidates);
          else {
            const cands = await chrome.runtime.sendMessage({type:"fluxcatch-get-candidates-tab"});
            renderCandidates(cands||[]);
          }
        } else {
          analyzeMsg.textContent = res?.error || "Aucune vidéo à analyser";
        }
      }catch(e){
        analyzeMsg.textContent = "Erreur: " + e.message;
      }
      btnAnalyze.textContent = old;
      btnAnalyze.disabled = false;
      setTimeout(()=> analyzeMsg.textContent="", 4000);
    });
  }

  document.getElementById("btn-pair").addEventListener("click", async ()=>{
    const code = document.getElementById("pair-code").value.trim().toUpperCase();
    if (!code) return;
    document.getElementById("pair-msg").textContent="Liaison…";
    const res = await chrome.runtime.sendMessage({type:"fluxcatch-pair", code});
    if (res && res.ok){
      document.getElementById("pair-msg").textContent="Lié !";
      setTimeout(refresh,500);
    } else {
      document.getElementById("pair-msg").textContent=res?.error||"Échec";
    }
  });
  document.getElementById("btn-unpair").addEventListener("click", async ()=>{
    await chrome.runtime.sendMessage({type:"fluxcatch-unpair"});
    document.getElementById("pair-msg").textContent="Dissocié";
    refresh();
  });
  document.getElementById("open-manager").addEventListener("click", (e)=>{});
  document.getElementById("btn-record-start").addEventListener("click", async ()=>{
    const tabs = await new Promise(res=> chrome.tabs.query({active:true, currentWindow:true}, res));
    if (!tabs[0]) return;
    document.getElementById("record-msg").textContent="Démarrage…";
    chrome.tabs.sendMessage(tabs[0].id, {type:"fluxcatch-start-recording"}, (resp)=>{
      if (chrome.runtime.lastError){
        document.getElementById("record-msg").textContent=chrome.runtime.lastError.message;
        return;
      }
      if (resp && resp.ok){
        document.getElementById("record-msg").textContent="Enregistrement en cours… tâche "+resp.taskId;
        document.getElementById("btn-record-start").disabled=true;
        document.getElementById("btn-record-stop").disabled=false;
      } else {
        document.getElementById("record-msg").textContent=resp?.error||"Échec enregistrement";
      }
    });
  });
  document.getElementById("btn-record-stop").addEventListener("click", async ()=>{
    const tabs = await new Promise(res=> chrome.tabs.query({active:true, currentWindow:true}, res));
    if (!tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, {type:"fluxcatch-stop-recording"}, (resp)=>{
      if (chrome.runtime.lastError){
        document.getElementById("record-msg").textContent=chrome.runtime.lastError.message;
        return;
      }
      if (resp && resp.ok){
        document.getElementById("record-msg").textContent="Enregistrement terminé";
        document.getElementById("btn-record-start").disabled=false;
        document.getElementById("btn-record-stop").disabled=true;
      } else {
        document.getElementById("record-msg").textContent=resp?.error||"Échec";
      }
    });
  });
});
