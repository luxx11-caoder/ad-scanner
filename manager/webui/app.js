const API = ""; // same origin
const $ = (s) => document.querySelector(s);

let tasksCache = [];

function formatSize(n) {
  if (n == null) return "?";
  if (n < 1024) return n + " o";
  if (n < 1024*1024) return (n/1024).toFixed(1) + " Ko";
  if (n < 1024*1024*1024) return (n/1024/1024).toFixed(1) + " Mo";
  return (n/1024/1024/1024).toFixed(2) + " Go";
}
function formatSpeed(bps) {
  if (!bps || bps<=0) return "";
  if (bps < 1024) return bps.toFixed(0)+" o/s";
  if (bps < 1024*1024) return (bps/1024).toFixed(1)+" Ko/s";
  return (bps/1024/1024).toFixed(2)+" Mo/s";
}
function statusFR(s) {
  const map = {pending:"En attente", active:"En cours", merging:"Fusion", paused:"En pause", done:"Terminé", canceled:"Annulé", error:"Erreur"};
  return map[s] || s;
}
function typeFR(k) {
  const m = {direct:"Directe", hls:"Flux HLS", ytdlp:"YouTube·VOD", recorder:"Enregistrement", browser_proxy:"Relais navigateur"};
  return m[k] || k;
}
function errorFR(e){
  if(!e) return "";
  if(e.includes("err_not_media")) return "Page web détectée (pas un fichier vidéo) — utilisez yt-dlp ou HLS";
  if(e.includes("err_forbidden")) return "Accès refusé (403) — essayez Forcer yt-dlp";
  if(e.includes("err_gone")) return "Fichier introuvable (404)";
  if(e.includes("err_drm")) return "Protégé DRM — non capturable";
  if(e.includes("err_empty")) return "Fichier vide";
  if(e.includes("err_space")) return "Espace disque insuffisant";
  if(e.includes("err_network")) return "Erreur réseau";
  return e;
}

async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(path, {method:"POST", headers: body instanceof Blob || body instanceof ArrayBuffer ? {} : {"Content-Type":"application/json"}, body: body ? (typeof body==="string"? body : JSON.stringify(body)) : undefined});
  if (!r.ok) throw new Error(await r.text());
  return r.json().catch(()=>({}));
}
async function fetchHello() {
  try {
    const h = await apiGet("/api/hello");
    $("#version").textContent = "v" + h.version;
    $("#pair-status").textContent = h.paired ? "Lié" : "Non lié";
    $("#pair-status").className = "badge " + (h.paired ? "ok" : "err");
    if (!h.paired) {
      // try to get code? Not exposed without pairing; keep empty
    }
  } catch(e){
    $("#pair-status").textContent = "Daemon hors ligne";
    $("#pair-status").className = "badge err";
  }
}
async function fetchCapabilities() {
  try{
    const c = await apiGet("/api/capabilities");
    const f = $("#caps-ffmpeg"); f.textContent = "ffmpeg: " + (c.ffmpeg ? "oui" : "non"); f.className = "badge " + (c.ffmpeg ? "ok":"err");
    const y = $("#caps-ytdlp"); y.textContent = "yt-dlp: " + (c.yt_dlp ? "oui" : "non"); y.className = "badge " + (c.yt_dlp ? "ok":"err");
  }catch{}
}
async function fetchSettings(){
  try{
    const s = await apiGet("/api/settings");
    $("#input-download-dir").value = s.download_dir || "";
    $("#input-template").value = s.filename_template || "";
    return s;
  }catch{}
}
async function fetchTasks(){
  try{
    const list = await apiGet("/api/tasks");
    tasksCache = list;
    renderTasks();
  }catch(e){ console.error(e); }
}
function renderTasks(){
  const cont = $("#tasks");
  $("#task-count").textContent = `(${tasksCache.length})`;
  if (!tasksCache.length){
    cont.innerHTML = `<p class="hint">Aucune tâche. Ajoutez une URL ou capturez depuis l'extension.</p>`;
    return;
  }
  cont.innerHTML = "";
  for (const t of tasksCache){
    const pct = (t.size_total && t.size_done!=null) ? Math.min(100, Math.round(t.size_done / t.size_total * 100)) : (t.status==="done"?100:0);
    const hasTotal = t.size_total != null;
    const barCls = t.status==="done" ? "task-bar done" : (t.status==="error" ? "task-bar error" : "task-bar");
    const speed = t._speed ? formatSpeed(t._speed) : "";
    const errLabel = t.error ? errorFR(t.error) : "";
    const err = t.error ? `<span title="${t.error}" class="badge err">${errLabel}</span>` : "";
    const div = document.createElement("div");
    div.className = "task";
    div.innerHTML = `
      <div class="task-head">
        <div class="task-title" title="${(t.title||t.source_url||'') }">${(t.title||t.source_url||'Sans titre').slice(0,120)}</div>
        <span class="status ${t.status}">${statusFR(t.status)}</span>
      </div>
      <div class="task-meta">
        <span>${typeFR(t.kind)}</span>
        <span>• ${formatSize(t.size_done)}${hasTotal ? " / "+formatSize(t.size_total) : ""}</span>
        ${speed ? `<span>• ${speed}</span>`: ""}
        ${hasTotal ? `<span>• ${pct}%</span>`:""}
        ${err}
      </div>
      <div class="${barCls}"><i style="width:${pct}%"></i></div>
      <div class="task-meta" style="font-size:11px; word-break:break-all;">
        <span>${t.source_url||""}</span>
        ${t.target_path ? `<span>→ ${t.target_path}</span>`:""}
      </div>
      <div class="task-actions">
        ${t.status==="active" ? `<button data-act="pause" data-id="${t.id}">Pause</button>`:""}
        ${t.status==="paused" ? `<button data-act="resume" data-id="${t.id}">Reprendre</button>`:""}
        ${["pending","active","paused","merging"].includes(t.status) ? `<button data-act="cancel" data-id="${t.id}">Annuler</button>`:""}
        ${["error","canceled"].includes(t.status) ? `<button data-act="retry" data-id="${t.id}">Relancer</button>`:""}
        ${t.target_path ? `<button data-act="open" data-id="${t.id}">Ouvrir dossier</button>`:""}
      </div>
    `;
    cont.appendChild(div);
  }
  cont.querySelectorAll("button[data-act]").forEach(btn=>{
    btn.addEventListener("click", async ()=>{
      const id = btn.dataset.id, act = btn.dataset.act;
      btn.disabled = true;
      try{
        if (act==="pause") await apiPost(`/api/tasks/${id}/pause`);
        else if (act==="resume") await apiPost(`/api/tasks/${id}/resume`);
        else if (act==="cancel") await apiPost(`/api/tasks/${id}/cancel`);
        else if (act==="retry") await apiPost(`/api/tasks/${id}/retry`);
        else if (act==="open") await apiPost(`/api/tasks/${id}/open_folder`);
        await fetchTasks();
      }catch(e){ alert(e.message); }
      btn.disabled = false;
    });
  });
}

function detectKind(url){
  const sel = $("#select-kind").value;
  if (sel !== "auto") return sel;
  const low = url.toLowerCase();
  if (low.includes(".m3u8") || low.includes(".mpd")) return "hls";
  if (/(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|dai\.ly)/i.test(url)) return "ytdlp";
  // Page web avec vidéo embarquée (pas un fichier direct) → ytdlp générique
  if (low.includes("view_video.php") || low.includes("viewkey=") || low.includes("/video/") || /\.(php|html|htm|aspx|jsp)(\?|#|$)/i.test(low)) return "ytdlp";
  return "direct";
}

async function addTask(){
  const url = $("#input-url").value.trim();
  if (!url) return alert("Entrez une URL");
  const kind = detectKind(url);
  const title = url.split("/").pop()?.split("?")[0] || url;
  const isYt = kind==="ytdlp";
  const body = {
    kind,
    url: isYt ? undefined : url,
    page_url: isYt ? url : window.location.href,
    title: title.slice(0,80),
    headers: {},
  };
  try{
    $("#btn-add").disabled = true;
    const res = await apiPost("/api/tasks", body);
    $("#input-url").value = "";
    await fetchTasks();
  }catch(e){ alert("Erreur création tâche: "+e.message); }
  finally{ $("#btn-add").disabled = false; }
}

function connectWS(){
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = proto + "//" + location.host + "/api/ws";
  let ws;
  try{
    ws = new WebSocket(wsUrl);
  }catch(e){ return; }
  ws.onmessage = (ev)=>{
    try{
      const msg = JSON.parse(ev.data);
      if (msg.type==="task_state"){
        const t = tasksCache.find(x=>x.id===msg.task_id);
        if (t) { t.status = msg.status; if (msg.error) t.error = msg.error; }
        else fetchTasks();
        renderTasks();
      } else if (msg.type==="task_progress"){
        const t = tasksCache.find(x=>x.id===msg.task_id);
        if (t){ t.size_done = msg.size_done; t.size_total = msg.size_total; t._speed = msg.speed; renderTasks(); }
        else fetchTasks();
      } else if (msg.type==="pairing_changed"){
        fetchHello();
      } else if (msg.type==="settings_changed"){
        fetchSettings();
      }
    }catch{}
  };
  ws.onclose = ()=> setTimeout(connectWS, 3000);
  ws.onerror = ()=> ws.close();
}

document.addEventListener("DOMContentLoaded", ()=>{
  fetchHello(); fetchCapabilities(); fetchSettings(); fetchTasks();
  connectWS();
  setInterval(fetchTasks, 2000); // fallback polling
  $("#btn-add").addEventListener("click", addTask);
  $("#input-url").addEventListener("keydown", e=>{ if(e.key==="Enter") addTask(); });
  $("#btn-refresh").addEventListener("click", ()=>{ fetchHello(); fetchTasks(); fetchCapabilities(); });
  $("#btn-save-settings").addEventListener("click", async ()=>{
    const body = {
      download_dir: $("#input-download-dir").value.trim(),
      filename_template: $("#input-template").value.trim(),
    };
    try{
      await fetch("/api/settings", {method:"PUT", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
      $("#settings-msg").textContent = "Réglages enregistrés";
      setTimeout(()=> $("#settings-msg").textContent="", 2000);
    }catch(e){ $("#settings-msg").textContent = "Erreur: "+e.message; }
  });
});
