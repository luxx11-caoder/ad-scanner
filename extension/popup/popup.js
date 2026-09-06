async function getStorage(key){ return new Promise(res=> chrome.storage.local.get(key, res)); }
async function setStorage(obj){ return new Promise(res=> chrome.storage.local.set(obj, ()=>res())); }

function typeLabel(t){
  const m={direct:"Directe", hls:"Flux HLS", ytdlp:"YouTube·VOD", mse:"MSE", recorder:"Enregistrement"};
  return m[t]||t;
}

async function refresh(){
  // check hello
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

  // get candidates
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
  for (const c of list){
    const div = document.createElement("div");
    div.className="candidate";
    const isDrm = c.drm;
    const isPageLike = c.url.toLowerCase().includes("view_video.php") || c.url.toLowerCase().includes("viewkey=");
    div.innerHTML=`
      <div class="candidate-title" title="${c.url}">${(c.title||c.url).slice(0,80)}</div>
      <div class="candidate-meta"><span class="badge ${c.type}">${typeLabel(c.type)}</span> ${c.mime||""} ${c.sizeHint? Math.round(c.sizeHint/1024)+" Ko":""} ${isPageLike? '<span class="badge" title="URL de page détectée">page</span>':''}</div>
      <div class="candidate-meta" style="font-size:10px;">${c.url.slice(0,120)}</div>
      ${isDrm ? `<div class="badge recorder">non capturable (protégé DRM)</div>` : `<div class="candidate-actions"><button data-url="${encodeURIComponent(c.url)}" data-type="${c.type}" class="primary">Télécharger</button><button data-url="${encodeURIComponent(c.url)}" data-force="ytdlp" class="small" title="Forcer le téléchargement via yt-dlp (page web)">Forcer yt-dlp</button></div>`}
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
        // Force en ytdlp : on envoie la page comme source
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
  document.getElementById("open-manager").addEventListener("click", (e)=>{
    // keep default
  });
  // recording
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
