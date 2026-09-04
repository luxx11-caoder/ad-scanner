# FluxCatch — Spec d'implémentation (alternative Linux à IDM)

> **Statut** : plan approuvé, prêt pour implémentation par l'utilisateur.
> **Version** : 1.0 — date de rédaction du plan.
> Usage : spec de référence. L'implémenteur peut librement adapter la structure interne, mais doit respecter les **contrats** (API, schéma BDD, protocole extension↔daemon, comportements) marqués comme tels, sinon le retour-utilisateur risque de ne pas correspondre.
> Langue des chaînes UI : **français**. Code : identifiants en anglais.

---

## 1. Objectif

Sur **Chromium ET Firefox** (Linux), l'utilisateur repère une vidéo non-DRM sur un site web, clique « Attraper » (pop-up d'extension ou menu contextuel), et le fichier arrive dans son dossier de téléchargements avec **progression visible**, **reprise possible** après interruption et **fusion correcte** des flux segmentés. Gestionnaire = daemon local Python exposant une **page web locale** façon « fenêtre IDM ».

### Critères d'acceptation globaux

1. Capture d'une vidéo MP4 directe OK sur Chromium et Firefox.
2. Capture d'un flux HLS `.m3u8` non-DRM, fusion correcte en un fichier.
3. Téléchargement YouTube (URL de page) OK via yt-dlp.
4. Enregistrement de secours d'une vidéo MSE non-EME (MediaRecorder) OK.
5. Reprise d'un téléchargement interrompu OK (Range/206).
6. Flux DRM → message explicite « non capturable (protégé DRM) », aucun contournement.
7. Page web locale : liste, progression, pause/annuler/relancer, ouvrir le dossier.

## 2. Décisions validées (verrouillées)

| Sujet | Décision |
|---|---|
| UI du gestionnaire | Page web locale servie par le daemon sur `http://127.0.0.1:8765` |
| Moteur | Python ≥ 3.11 ; **une seule dépendance runtime : `aiohttp`** (serveur REST+WS+statique ET client HTTP en un) |
| Navigateurs | Chromium (MV3) **et** Firefox, un seul code (feature-detection), pas de build |
| Périmètre | Large, déployé **par types de sites, progressivement** (voir §10) |
| DRM | **Hors périmètre** (Netflix/Prime/Disney+…) : impossible techniquement, exclu légalement. Refus explicite si détecté |
| Emplacement projet | Racine du dossier de travail (actuellement vide) |
| Nom | « FluxCatch », préfixe interne unique `fluxcatch` (renomable sans impact) |
| Menace | Protéger contre les **pages web malveillantes** qui pilotaient le daemon. Pas de défense contre un processus local (même utilisateur) — assumé |

## 3. Architecture d'ensemble

```
┌──────────────────── Navigateur (extension MV3) ────────────────────┐
│ popup + menu contextuel  ←  background (service worker)             │
│  détection : webRequest (observe) • DOM <video> • hooks fetch/XHR   │
│  (monde MAIN) • performance entries                                  │
│  cookies via chrome.cookies → en-tête Cookie                         │
│  secours : enregistrement MediaRecorder • relais octets (anti-bot)  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP/WS localhost
                           │ (Origin contrôlée + code de liaison)
┌──────────────────────────▼──────────────────────────────────────────┐
│ daemon « fluxcatch » (127.0.0.1:8765, aiohttp)                      │
│  moteurs : direct (Range/reprise) • hls/dash (ffmpeg → yt-dlp)      │
│            • yt-dlp (profils VOD) • upload webm (recorder/proxy)    │
│  persistance : SQLite • page web UI (statique, FR)                  │
│  capabilities : ffmpeg & yt-dlp détectés via PATH                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 4. Arborescence cible du projet

```
. (racine du dossier de travail)
├── README.md                       # FR : installation + usage
├── PLAN.md                         # ce document
├── extension/
│   ├── manifest.json               # MV3 unique (Chromium + Firefox)
│   ├── src/
│   │   ├── background.js           # service worker : orchestration
│   │   ├── content-detect.js       # monde isolé : DOM <video>
│   │   ├── content-hook.js         # monde MAIN : hook fetch/XHR
│   │   └── api-shim.js             # petit wrapper promesses chrome.*/browser.*
│   ├── popup/                      # popup.html + popup.js + popup.css
│   └── icons/                      # 16/32/48/128 PNG (générés, cf. §9.6)
├── manager/
│   ├── pyproject.toml              # fluxcatch, dépendance aiohttp
│   ├── fluxcatch/
│   │   ├── __init__.py             # __version__
│   │   ├── __main__.py             # python -m fluxcatch
│   │   ├── cli.py                  # « serve », « pair », « status »
│   │   ├── config.py               # chemins XDG + réglages JSON
│   │   ├── store.py                # SQLite + machine à états (CONTRAT)
│   │   ├── pairing.py              # secret/code/origines autorisées
│   │   ├── server.py               # app aiohttp : REST + WS + statique
│   │   ├── tasks.py                # ordonnanceur asyncio des téléchargements
│   │   └── engines/
│   │       ├── __init__.py         # registry kind → moteur
│   │       ├── base.py             # helpers nommage/en-têtes/extension MIME
│   │       ├── direct.py           # GET Range reprise
│   │       ├── hls.py              # m3u8/mpd → ffmpeg puis yt-dlp
│   │       ├── ytdlp.py            # profils page-VOD (YouTube…)
│   │       └── upload.py           # kind recorder & browser_proxy (octets poussés)
│   └── webui/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── scripts/
│   ├── install.sh                  # venv, pip, systemd --user, contrôle ffmpeg
│   ├── make_icons.py               # PNG stdlib (zlib) : flèche bas
│   └── gen_media_fixtures.sh       # génère mp4/hls de test via ffmpeg
├── systemd/
│   └── fluxcatch.service           # unité user
├── tests/
│   ├── conftest.py                 # fixtures serveur HTTP local + app
│   ├── test_store.py
│   ├── test_api.py                 # REST, pairing, CORS/origines
│   ├── test_direct.py              # reprise Range, Content-Disposition, 403
│   └── test_hls.py                 # skip si ffmpeg absent
└── docs/
    └── checklist-sites.md          # tests manuels site par site
```

---

## 5. Gestionnaire Python (`fluxcatch`)

### 5.1 Chemins et réglages

- Dossiers XDG :
  - config : `${XDG_CONFIG_HOME:-~/.config}/fluxcatch/config.json`
  - data (BDD) : `${XDG_DATA_HOME:-~/.local/share}/fluxcatch/fluxcatch.db`
  - logs : `${XDG_STATE_HOME:-~/.local/state}/fluxcatch/fluxcatch.log`
  - secret + origines autorisées : dossier config (`secret` mode 0600, `allowed_origins.json`)
- Réglages (`config.json`) :

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "download_dir": "<xdg-user-dir DOWNLOAD, sinon ~/Téléchargements, sinon ~/Downloads>",
  "filename_template": "{title}.{ext}",
  "concurrency": 3
}
```

### 5.2 Schéma SQLite (CONTRAT)

```sql
CREATE TABLE IF NOT EXISTS tasks (
  id           TEXT PRIMARY KEY,          -- uuid4 hex
  kind         TEXT NOT NULL,             -- direct|hls|ytdlp|recorder|browser_proxy
  source_url   TEXT NOT NULL,
  page_url     TEXT,
  title        TEXT,
  headers_json TEXT NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL DEFAULT 'pending',
               -- pending|active|merging|paused|done|canceled|error
  target_path  TEXT,
  mime         TEXT,
  size_total   INTEGER,                   -- octets connus (Content-Length) ou NULL
  size_done    INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  extra_json   TEXT NOT NULL DEFAULT '{}',-- options moteur (format_id, durée, note)
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
```

**Machine à états** (CONTRAT) :
`pending → active → (merging →) done` ; `active ↔ paused` (pause seulement si serveur Range) ; depuis `pending|active|paused|merging → canceled` ; n'importe quel état actif → `error` (message typé, cf. §5.6).

### 5.3 Pairing et sécurité (CONTRAT)

- Le daemon écoute **uniquement** `127.0.0.1`. Pas de TLS (localhost mono-utilisateur, documenté).
- Au premier lancement : génération d'un **code de liaison** (ex. 8 caractères) affiché dans la console et l'UI.
- L'extension envoie `POST /api/pair {code}` → si code correct, le daemon enregistre l'**origine exacte** de la requête (`chrome-extension://<id>` ou `moz-extension://<uuid>`) dans `allowed_origins.json`.
- Middleware daemon : toute requête dont l'en-tête `Origin` n'est **pas** dans la liste blanche ne reçoit que `/api/hello` et `/api/pair` (réponse lisible, `Access-Control-Allow-Origin: *` sur ces deux-là) ; tout le reste → **403**. Une page web malveillante ne peut donc ni lire ni piloter l'API (CORS + liste blanche). Un processus local a déjà les droits utilisateur : hors menace.
- Bouton « re-lier » côté extension → `DELETE /api/pair` (retire l'origine) puis nouveau code.

### 5.4 Contrat d'API REST + WS

Base : `http://127.0.0.1:8765`. JSON partout. Réponses : `200/201/204`, `400` (payload invalide), `403` (origine inconnue ou code faux), `404`, `409` (transition d'état impossible).

| Méthode | Route | Corps / rôle |
|---|---|---|
| GET | `/api/hello` | `{app:"fluxcatch", version, paired:bool}` |
| POST | `/api/pair` | `{code}` → 200 ; enregistre l'Origin requérante |
| DELETE | `/api/pair` | retire l'origine requérante |
| GET | `/api/capabilities` | `{ffmpeg:bool, yt_dlp:bool, yt_dlp_path?}` |
| GET | `/api/settings` | réglages actuels |
| PUT | `/api/settings` | `{download_dir?, filename_template?}` → réglages à jour |
| GET | `/api/tasks` | liste (tri `created_at` desc) |
| POST | `/api/tasks` | `{kind, url?, page_url?, title?, headers?, extra?}` → `201 {id}` |
| GET | `/api/tasks/{id}` | détail |
| POST | `/api/tasks/{id}/cancel` | |
| POST | `/api/tasks/{id}/retry` | re-tente (re-capture ou re-démarrage) |
| POST | `/api/tasks/{id}/pause` | uniquement si `active` et Range |
| POST | `/api/tasks/{id}/resume` | |
| POST | `/api/tasks/{id}/open_folder` | `xdg-open` du dossier cible |
| POST | `/api/tasks/{id}/chunks` | **corps binaire brut** (recorder / browser_proxy) |
| POST | `/api/tasks/{id}/finish` | clôt le flux d'upload (`{bytes}`) |
| WS | `/api/ws` | événements push (voir ci-dessous) |

**Événements WS** (CONTRAT, JSON) :
- `{type:"task_state", task_id, status, error?}`
- `{type:"task_progress", task_id, size_done, size_total, speed}` (toutes les ~500 ms max)
- `{type:"settings_changed", settings}`
- `{type:"pairing_changed"}`

### 5.5 Moteurs de téléchargement

Interface commune : `async run(task, report)` où `report(size_done, size_total, speed)` met à jour BDD + WS. Registry `kind → moteur`.

#### `direct` — vidéos/liens progressifs
- `GET` via client aiohttp, en-têtes repris de la capture (voir §5.6), `allow_redirects=True`.
- Écriture dans `<cible>.part`, chunks de 256 Ko, `fsync` puis `rename` à la fin.
- **Reprise** : si `.part` existe et `size>0` → `Range: bytes=<taille>-` ; réponse `206` → on continue ; réponse `200` → serveur sans Range → on repart de zéro.
- `size_total` = `Content-Length` (corrigé de l'offset en reprise).
- Résolution du **nom de fichier** : `Content-Disposition` → basename de l'URL finale (après redirects, décodé) → titre de page → `fluxcatch-<timestamp>`. Extension : nom déjà extensé sinon MIME → extension (table §5.7).
- Erreurs : `403/401 → error:err_forbidden` (re-capturable, cf. relais navigateur §9.4) ; `404 → error:err_gone` ; 5xx/réseau → 3 tentatives backoff 2 s/5 s avant `error:err_network`.

#### `hls` — manifestes `.m3u8` / `.mpd`
1. **Mode A (recommandé)** : sous-processus `ffmpeg` :
   `ffmpeg -y -headers $'Referer: …\r\nCookie: …\r\nUser-Agent: …\r\n' -i <url> -c copy <cible>.mp4`
   Les en-têtes `-headers` s'appliquent au manifeste ET aux segments (flux http/https).
2. En cas d'échec de muxage : retry `-c copy` vers `.mkv` (PTS/codecs incompatibles mp4).
3. **Mode B (repli)** si ffmpeg absent : yt-dlp CLI (cf. §5.5 `ytdlp`) avec mêmes en-têtes.
4. **DRM manifeste** : si `#EXT-X-SESSION-KEY` avec `METHOD=WIDEVINE|PLAYREADY|CENC` ou mpd avec `<ContentProtection>` → échec immédiat `error:err_drm` (message explicite).
5. **Live** (pas de `#EXT-X-ENDLIST`, ou mpd `type="dynamic"`) : v1 → on **conseille** l'enregistrement webm ; l'option « fenêtre live » reste en backlog.

#### `ytdlp` — profils page-VOD (YouTube, Vimeo, Dailymotion…)
- Entrée : `page_url` (et non un fichier direct). Commande :
  `yt-dlp --no-playlist -f "bv*+ba/b" --merge-output-format mp4 -o "<template>" --add-header "Cookie: …" --referer <page_url> <page_url>`
- Progression : lancer sans `-q`, parser les lignes `[download] xx.x%` (parser tolérant ; si indisponible → statut « en cours »).
- Si les cookies de session manquent ou expirent → `error:err_expired`, l'extension propose de re-capturer la même page.

#### `upload` — `recorder` et `browser_proxy` (octets poussés par l'extension)
- Même mécanique pour les deux kinds : l'extension pousse des morceaux binaires via `POST /api/tasks/{id}/chunks`, le daemon écrit dans `<cible>.part` et met à jour `size_done` ; `POST …/finish` → `rename` → `done`.
- `recorder` : cible `<titre>.webm` (sortie MediaRecorder), `size_total = NULL`.
- `browser_proxy` : cible nommée comme `direct` (l'extension connaît le Content-Type), `size_total` facultatif.
- 0 octet reçu à `finish` → `error:err_empty`.

### 5.6 En-têtes capturés (CONTRAT)

Depuis `headers_json` de la tâche, **seuls** ces en-têtes sont envoyés au serveur (anti-pollution) :
`Cookie`, `Referer`, `Origin`, `User-Agent`, `X-Requested-With`, `Sec-Fetch-Site`, `Sec-Fetch-Mode`, `Sec-Fetch-Dest`, `Accept`.
- `Cookie` : reconstruit par l'extension via `chrome.cookies` (expose aussi HttpOnly) — priorité sur un éventuel `Cookie` lu par webRequest.
- `Range`/`If-Range` : **jamais** copiés (reprise gérée par le moteur).
- Nommage des erreurs typées : `err_http`, `err_forbidden`, `err_gone`, `err_expired`, `err_network`, `err_drm`, `err_merge`, `err_empty`, `err_space`, `err_unknown` — chacun avec message FR affichable.

### 5.7 Table MIME → extension

`video/mp4→.mp4` • `video/webm→.webm` • `video/quicktime→.mov` • `video/x-matroska→.mkv` • `application/vnd.apple.mpegurl→.mp4 (sortie fusion)` • `application/dash+xml→.mp4 (sortie fusion)` • `video/x-flv→.flv` • `video/mp2t→.ts` • `audio/mpeg→.mp3` • `audio/mp4→.m4a` • `audio/ogg→.ogg` • défaut → `.bin`.

### 5.8 Ordonnanceur et serveur

- `tasks.py` : sur `POST /api/tasks` → `asyncio.create_task(moteur)`, sémaphore `concurrency` (défaut 3), événements broadcastés aux clients WS ; sauvegarde du chemin `.part` pour reprise au redémarrage du daemon (les tâches `active`/`paused` au crash repassent `paused` si Range possible, sinon `pending`).
- `server.py` : app aiohttp avec middleware d'origines (cf. §5.3), routes ci-dessus, fichiers statiques `webui/` sur `/`, log fichier + stderr (niveau via `FLUXCATCH_LOG`).

### 5.9 CLI

- `fluxcatch serve` (avant-plan, dev) ; `fluxcatch status` (résumé + code de liaison) ; `fluxcatch pair` (affiche/regénère le code).

---

## 6. Page web locale (`webui`, FR, vanilla JS)

Sections :
1. **Barre d'état** : version, code de liaison (ou « lié »), badges capabilities (ffmpeg, yt-dlp), réglages.
2. **Ajouter une URL** (manuel) : champ URL → détection auto du `kind` (`.m3u8`/`.mpd` → `hls` ; domaine YouTube/Vimeo/Dailymotion → `ytdlp` ; sinon `direct`).
3. **Liste des tâches** : cartes/tableau avec titre, type, statut FR (En attente / En cours / Fusion / En pause / Terminé / Annulé / Erreur), taille, barre de progression + vitesse, boutons annuler / pause / reprendre / relancer / ouvrir dossier ; infobulle d'erreur typée.
4. **Réglages** : dossier de téléchargement, modèle de nom de fichier.

Mise à jour : événements WS ; repli polling `GET /api/tasks` toutes les 2 s. Aucune étape de build.

---

## 7. Extension navigateur (Manifest V3, Chromium + Firefox)

### 7.1 Manifest (un seul fichier)

- `manifest_version: 3`, name « FluxCatch », version `0.1.0`, description FR courte.
- `permissions`: `storage`, `cookies`, `tabs`, `webRequest`, `contextMenus`.
- `host_permissions`: `["<all_urls>"]` (nécessaire : observer les requêtes média de tous les sites + fetch relais). À documenter dans le README.
- `background`: `{"service_worker": "src/background.js"}` (classique, sans module ; les helpers sont chargés via un mini-shim en tête de fichier — pas d'`import` statique).
- `content_scripts` :
  - `src/content-detect.js` — `run_at: document_idle`, `all_frames: true`, monde **isolé**.
  - `src/content-hook.js` — `run_at: document_start`, `all_frames: true`, `world: "MAIN"` (Chromium ≥ 111, Firefox ≥ 128).
- `action`: popup `popup/popup.html`, titre FR, icône badge.
- `minimum_chrome_version: "111"` ; `browser_specific_settings.gecko`: `{"id":"fluxcatch@local", "strict_min_version":"121.0"}`.
- Pas de `declarativeNetRequest` pour le MVP (rien à bloquer).

### 7.2 Détection — par type de site (registre de détecteurs)

Priorités et mécanismes (cumulatifs, l'implémenteur peut activer par jalons) :

1. **Vidéos directes** (`webRequest` observe, Chromium) : `onBeforeRequest` + `onBeforeSendHeaders` (option `extraHeaders`) + `onHeadersReceived` sur URLs média. Candidat retenu si : URL = `/\.(mp4|webm|m4v|mov|mkv|ts|flv|ogv|avi|m3u8|mpd)(\?|#|$)/i` **ou** `Content-Type` observé commence par `video/` (ou `application/vnd.apple.mpegurl`, `application/dash+xml`). Anti-bruit : ignorer les segments `.m4s`/`.ts` seuls (sauf si m3u8/mpd), dédup par `(url, page)`. Firefox : même code (mode observe toléré), possibilité d'enrichir plus tard avec le blocage autorisé côté FF.
2. **DOM `<video>`** (content-detect, isolé) : MutationObserver + scan périodique : `<video>`/`<source>` à `src` non-blob → candidat **direct** ; `src` blob: + MSE → marquer `mse:true` (aucune URL directe exploitable) ; `srcObject` (WebRTC) → **ignorer**.
3. **Hooks monde MAIN** (content-hook) : patch transparent de `window.fetch` et `XMLHttpRequest` (si `window.__fluxcatchHook` absent) : on **lit les en-têtes de réponse seulement** (jamais le corps) — `Content-Type`, `Content-Length` quand accessibles (`content-type` est un en-tête de réponse CORS-safelisted, donc lisible même cross-origin via `getResponseHeader`). Signale au monde isolé via `window.postMessage` les événements média (m3u8/mpd/video) : `{url, contentType, sizeHint}`. Marque aussi l'usage EME : si `navigator.requestMediaKeySystemAccess` est appelé → `window.__fluxcatchEme = true` (transmis → garde DRM).
4. **Résolution MSE** : pour un `<video>` blob/MSE, croiser les manifestes vus par le hook (3) et `performance.getEntriesByType('resource')` filtrés `.m3u8/.mpd` → proposer tâche `hls` ; sinon proposer **enregistrement**.
5. **Profils yt-dlp** : si la page est un lecteur « player-JS » connu (YouTube, Vimeo, Dailymotion) sans URL directe → action menu « Télécharger via yt-dlp » (envoie `page_url` + cookies).
6. **Garde DRM** : `video.mediaKeys` présent, EME vu (2), ou manifeste protégé → **refus explicite** « non capturable (protégé DRM) ». Aucun contournement.

### 7.3 Flux de capture

- **Cookies** : `chrome.cookies.getAll({url: <origine de la ressource>})` → chaîne `Cookie:` (jointure `; `). Prioritaire.
- **En-têtes conservés** : §5.6.
- **Création de tâche** : `POST /api/tasks` avec `{kind, url|page_url, title, headers}`. Si 403 → l'extension passe en état « non lié » (invite à saisir le code).
- **Enregistrement webm** : depuis content-detect, vérifier non-DRM, `video.captureStream()` (Chromium) / `video.mozCaptureStream()` (Firefox), `MediaRecorder` (`video/webm;codecs=vp8,opus`, repli `video/webm`) ; chaque `dataavailable` → `window.postMessage` → background → `POST chunks` au daemon ; arrêt propre au clic « stop » ou au déchargement de page (déclenché par le daemon de fin de vie de l'onglet si possible, sinon au prochain passage).
- **Relais navigateur (anti-bot/403)** : si la tâche `direct` échoue en `err_forbidden`, l'extension peut re-télécharger elle-même (fetch du background **avec** `host_permissions` + `credentials:"include"` → le navigateur fournit cookies/CORS) et pousser les octets en morceaux bornés (buffer 1 Mo, pas de mise en mémoire intégrale) via le moteur `browser_proxy`. Signalé « lent » dans l'UI.
- **Badge** : nombre de candidats sur l'onglet actif.
- **Menu contextuel** : « Attraper la vidéo » (contextes `video`/`audio`/`page`) ; sur `<video>` ciblé → demande au content-detect du tab concerné.

### 7.4 Popup (FR)

États : (a) **non lié** : champ code de liaison + bouton « Lier » (+ rappel de lancer `fluxcatch serve`) ; (b) **lié** : liste des candidats de l'onglet courant (titre, type FR : Directe / Flux HLS / YouTube·VOD / Enregistrement), bouton « Télécharger » ou « Enregistrer », lien « Ouvrir le gestionnaire » (`http://127.0.0.1:8765`), dernière erreur éventuelle, bouton « re-lier ».

### 7.5 Communication extension ↔ daemon

- L'extension garde `{baseUrl:"http://127.0.0.1:8765", paired:bool}` dans `chrome.storage.local`.
- Les requêtes partent du background (service worker) avec `host_permissions` : pas de contrainte CORS de ce côté ; les pages web tierces restent bloquées côté serveur (cf. §5.3).
- `api-shim.js` : mini-wrapper promesses pour `chrome.cookies`, `chrome.storage`, `chrome.tabs`, `chrome.runtime`, `chrome.webRequest` (callbacks) — compatible `browser.*` si présent.

---

## 8. Spike M0 — points d'API à vérifier avant/au début du codage

Décisions définitives de détection prises après vérification sur les vrais navigateurs :

1. Chromium MV3 observe : `onHeadersReceived` fournit-il `responseHeaders` **sans** `webRequestBlocking` ? Sinon → détection « directe » = DOM + hooks MAIN + URL heuristiques (le webRequest ne servant qu'aux `.m3u8/.mpd`/segments) + repli yt-dlp/recorder.
2. `onBeforeSendHeaders` + `extraHeaders` en observe : en-têtes de requête lisibles ?
3. Firefox : service worker MV3 (≥ 121) ; `content_scripts.world: "MAIN"` (≥ 128) ; `captureStream` (moz).
4. `MediaRecorder` sur vidéo MSE **non-EME** : fonctionnement effectif Chromium + Firefox.
5. Fetch relais du background vers `127.0.0.1` avec `host_permissions` : aucune contrainte CORS (attendu oui).
6. `chrome.cookies` depuis le service worker MV3 (attendu oui).

Si un point échoue, appliquer le repli documenté ci-dessus — **aucun changement de protocole** daemon.

---

## 9. Installation, lancement, utilitaires

### 9.1 `scripts/install.sh`
1. Crée le venv `manager/.venv`, installe `pip install -e ./manager` (dépendance aiohttp).
2. Contrôle `ffmpeg` et `yt-dlp` dans le PATH ; si ffmpeg absent → affiche `sudo apt install -y ffmpeg` **sans l'exécuter**.
3. Installe l'unité systemd **user** `~/.config/systemd/user/fluxcatch.service` (template fourni) et `systemctl --user enable --now fluxcatch`.
4. Génère les icônes d'extension (`make_icons.py`).

### 9.2 `systemd/fluxcatch.service` (user)
`ExecStart=<manager/.venv>/bin/fluxcatch serve`, `Restart=on-failure`, `Environment=FLUXCATCH_LOG=info`. Dev : `fluxcatch serve` en avant-plan.

### 9.3 Chargement de l'extension (à documenter dans le README)
- Chromium : `chrome://extensions` → mode développeur → « Charger l'extension non empaquetée » → dossier `extension/`.
- Firefox : `about:debugging#/runtime/this-firefox` → « Charger un module temporaire » → `extension/manifest.json` (pour une installation pérenne : `web-ext` ou .xpi signé à étudier plus tard).

### 9.4 Relais navigateur
Cf. §7.3 — mécanisme distinct du flux d'upload standard, kind `browser_proxy`.

### 9.5 Fixtures de test
`scripts/gen_media_fixtures.sh` (ffmpeg, machine cible) : petit `.mp4` ; petit flux HLS (segmenté) ; page HTML `<video>` servie en HTTP local pour tests manuels. `docs/checklist-sites.md` : grille site par site (statut, navigateur, type, notes).

### 9.6 Icônes
`make_icons.py` : génération PNG pure stdlib (zlib + struct), 16/32/48/128 — flèche de téléchargement dans un carré arrondi (simple, suffisant pour MVP).

---

## 10. Déploiement par types de sites — jalons M0→M6

L'utilisateur veut couvrir « la majorité des sites », **par types, au fil de l'eau**. Les types correspondent aux détecteurs/moteurs ; chaque jalon ajoute un type complet (détection + capture + vérification).

| Jalon | Contenu | Critère d'acceptation |
|---|---|---|
| **M0** | Spike navigateur (§8) ; figer les sources de détection par navigateur | Points vérifiés, replis documentés |
| **M1** | Manager minimal : serveur, pairing, API, moteur `direct` + reprise, SQLite, web UI liste/progression | pytest verts ; MP4 local reprise OK |
| **M2** | Extension v1 : détection **vidéos directes** (webRequest observe + DOM), popup, cookies/en-têtes, badge | MP4 direct capturé sur Chromium **et** Firefox |
| **M3** | **HLS/DASH + MSE** : hooks MAIN, capture manifestes, fusion ffmpeg/yt-dlp, enregistrement de secours, garde DRM | m3u8 non-DRM fusionné OK ; vidéo MSE enregistrée OK ; DRM → refus explicite |
| **M4** | **Profils yt-dlp** (YouTube, Vimeo, Dailymotion) : bridge page-URL, menu contextuel, « best » par défaut | YouTube public téléchargé OK |
| **M5** | Robustesse/finitions : pause UI, erreurs typées + re-capture, relais anti-403, notifications, liste d'ignore de domaines DRM connus, `install.sh` + systemd finalisés, README FR | Checklist complète (critères globaux §1) |
| **M6** | **Extension du catalogue** : nouveaux types de sites à la demande via le mécanisme de profils (ex. : vidéos à jeton signé, lecteurs custom), un site/type à la fois | Chaque ajout vérifié dans `docs/checklist-sites.md` |

### Ordre de priorité des types de sites (pour le catalogue M6)
1. Lecteurs « fichier direct » (actualité, cours, self-hosted) — couvert M2.
2. Plateformes VOD **HLS non-DRM** — couvert M3.
3. YouTube / Vimeo / Dailymotion — couvert M4.
4. Vidéos à jeton signé ou requêtes multi-en-têtes — moteur `direct` enrichi.
5. Live (fenêtre) — backlog après M6.

---

## 11. Cas limites et échecs traités

- 403/anti-bot → `err_forbidden` + proposition **relais navigateur** (§9.4).
- URLs signées expirées → `err_expired` + bouton « re-capturer la même URL » (l'extension re-sniffe).
- Serveur sans Range → reprise = relance complète (documenté dans l'UI).
- Collisions de noms → suffixe `-2`, `-3`… ; assainissement des caractères interdits `/\<>:"|?*` + contrôles → `_`, trim espaces/points, longueur max 200.
- Doublons de candidats → dédup par `(URL, page)`.
- HLS live → conseil enregistrement (v1).
- DRM (EME/`mediaKeys`/manifeste protégé) → refus explicite.
- Onglet fermé pendant l'enregistrement → finalisation propre (au plus tard au prochain passage du content script / au clic).
- En-têtes requis par le CDN (Referer, Origin, Sec-Fetch-*) conservés et renvoyés.
- Segments `.ts`/`.m4s` seuls (sans manifeste) → ignorés (bruit).
- Tâches `active` au redémarrage du daemon → `paused` (Range) ou `pending`.

---

## 12. Tests

### 12.1 pytest (côté manager, exécutables sans navigateur)
- `test_store.py` : transitions d'état valides/invalides (409), CRUD.
- `test_api.py` : hello/pairing (code faux → 403 ; origine inconnue → 403 partout sauf hello/pair), CORS, création/annulation de tâches.
- `test_direct.py` : fixture **serveur HTTP local** (aiohttp test client + serveur fichier) — reprise après coupure (`Range`/`206`), serveur sans Range (`200` → relance), `Content-Disposition`, 403 → `err_forbidden`, 404 → `err_gone`, nommage/sanitisation.
- `test_hls.py` : fusion sur manifeste+segments générés par les fixtures ffmpeg — **skip** si ffmpeg absent.
- `test_upload.py` : chunks + finish (recorder), 0 octet → `err_empty`.

### 12.2 Manuels (sur la machine de l'utilisateur, Chromium + Firefox)
Fixtures locales servies en HTTP : page `<video src=mp4>`, page HLS, page MSE+blob, page EME simulée (refus attendu). Puis sites réels, consignés dans `docs/checklist-sites.md` au fil des jalons.

---

## 13. Prérequis et hypothèses

- Machine cible : Ubuntu 24.04 (ou similaire), Python ≥ 3.11, **ffmpeg à installer** (commande proposée par `install.sh`), yt-dlp recommandé (présent par défaut sur Ubuntu) — replis documentés sans lui.
- Chromium ≥ 111 / Firefox ≥ 128 pour le hook monde MAIN (sinon repli : DOM + webRequest + yt-dlp + enregistrement).
- Usage personnel, contenu **non-DRM**, respect des conditions d'utilisation des sites. Aucune fonctionnalité de contournement DRM (y compris en backlog).
- Aucun build nécessaire pour l'extension (JS vanilla) ; Node requis seulement si l'on ajoute des tests JS (optionnel).

## 14. Contrat de retour utilisateur

Après implémentation partielle ou complète, retour attendu (structurer librement, tout est utile) :
1. **Points de blocage** (API navigateur du spike M0, comportements inattendus) — avec version des navigateurs testés.
2. **Écarts au contrat** que tu as dû faire (et pourquoi).
3. **Sites réels testés** (ajouter à `docs/checklist-sites.md`) : domaine, type, résultat.
4. **Souhaits de priorité** pour M6 (types de sites suivants).
