# FluxCatch — Alternative Linux à Internet Download Manager

Gestionnaire de téléchargements local pour Linux (Chromium + Firefox) — capture les vidéos **non-DRM** et les télécharge avec reprise, fusion HLS/DASH, et support YouTube via yt-dlp. Interface : page web locale + extension navigateur.

> Langue UI : français. Code : anglais. Licence MIT.

## Fonctionnalités (jalons M1→M5)

- **Accélération & reprise** : téléchargement direct avec `Range`/`206` et reprise après coupure
- **HLS/DASH** : fusion via `ffmpeg` (`-c copy` → mp4, repli mkv) puis `yt-dlp`
- **YouTube / Vimeo / Dailymotion** : profil `ytdlp` (best `bv*+ba/b`)
- **Enregistrement de secours** : `MediaRecorder` sur vidéo MSE non-EME → `.webm`
- **Relais navigateur (anti-403)** : `browser_proxy` quand le serveur exige un fetch navigateur
- **Page de gestion** : `http://127.0.0.1:8765` — liste, progression WS, pause/reprendre/annuler/retry, ouvrir dossier
- **Extension MV3 unique** (Chromium ≥111, Firefox ≥121) : détection webRequest (observe) + DOM `<video>` + hooks `fetch/XHR` en monde MAIN + `performance` entries

## Architecture

```
Navigateur (extension MV3) ──HTTP/WS localhost (Origin + code)──▶ Daemon fluxcatch (aiohttp 127.0.0.1:8765)
  popup / menu contextuel ← background (service worker)                moteurs: direct | hls | ytdlp | upload (recorder/browser_proxy)
  détection: webRequest • DOM <video> • hooks fetch/XHR                SQLite + page web UI
  cookies via chrome.cookies → header Cookie                            capabilities: ffmpeg & yt-dlp via PATH
```

## Prérequis

- Ubuntu 24.04+ (ou Debian/Fedora), Python ≥ 3.11, `ffmpeg` recommandé
- Chromium ≥ 111 / Firefox ≥ 128 pour hook monde MAIN (sinon repli DOM + webRequest)
- `yt-dlp` recommandé pour YouTube

```bash
sudo apt install -y ffmpeg
pip install yt-dlp    # ou via pipx
```

## Installation

### 1. Daemon

```bash
./scripts/install.sh         # venv manager/.venv, pip install -e, icônes, systemd --user
# ou manuel:
python3 -m venv manager/.venv
manager/.venv/bin/pip install -e ./manager
manager/.venv/bin/fluxcatch serve   # avant-plan, http://127.0.0.1:8765
manager/.venv/bin/fluxcatch pair    # affiche le code de liaison
manager/.venv/bin/fluxcatch status  # état
```

Service user (après `install.sh`):
```bash
systemctl --user enable --now fluxcatch
journalctl --user -u fluxcatch -f
```

Config XDG:
- `~/.config/fluxcatch/config.json` (host/port/download_dir/filename_template/concurrency)
- `~/.local/share/fluxcatch/fluxcatch.db` (SQLite)
- `~/.local/state/fluxcatch/fluxcatch.log`
- `~/.config/fluxcatch/secret` (0600) + `allowed_origins.json`

### 2. Extension

- **Chromium**: `chrome://extensions` → Mode développeur → Charger l'extension non empaquetée → dossier `extension/`
- **Firefox**: `about:debugging#/runtime/this-firefox` → Charger un module temporaire → `extension/manifest.json` (pérenne : `web-ext` / .xpi signé à prévoir)

Puis dans le popup : saisir le **code de liaison** affiché par `fluxcatch serve` → bouton *Lier*.

## Utilisation

1. Aller sur une page avec une vidéo non-DRM
2. Icône FluxCatch → liste des candidats (Directe / Flux HLS / YouTube·VOD / Enregistrement)
3. Cliquer **Télécharger** (ou **Enregistrer** pour MSE) → fichier dans `~/Téléchargements` (ou `download_dir`)
4. Suivre la progression sur `http://127.0.0.1:8765` (pause/reprendre/annuler/ouvrir dossier)

Ajout manuel via la page web : champ URL → détection auto du `kind`.

## Sécurité

- Daemon écoute uniquement `127.0.0.1:8765` (pas TLS, localhost)
- Pairing : code 8 chars → enregistre l'`Origin` exacte `chrome-extension://<id>` / `moz-extension://<uuid>` → middleware refuse tout `Origin` inconnu (sauf `/api/hello` et `/api/pair` exposés avec `Access-Control-Allow-Origin:*`)
- Pages web malveillantes ne peuvent pas piloter l'API (CORS + whitelist). Processus local = même utilisateur = hors menace (assumé)

## API (extraits)

```
GET  /api/hello              {app, version, paired}
POST /api/pair {code}        → enregistre Origin
GET  /api/capabilities       {ffmpeg, yt_dlp}
GET/PUT /api/settings        {download_dir, filename_template}
GET  /api/tasks              liste
POST /api/tasks {kind, url, page_url, title, headers} → 201 {id}
GET  /api/tasks/{id}
POST /api/tasks/{id}/pause|resume|cancel|retry|open_folder
POST /api/tasks/{id}/chunks  (binaire, recorder/browser_proxy)
POST /api/tasks/{id}/finish
WS   /api/ws                 {type: task_state|task_progress|settings_changed|pairing_changed}
```

Erreurs typées : `err_forbidden`, `err_gone`, `err_expired`, `err_network`, `err_drm`, `err_merge`, `err_empty`…

## Fixtures & tests

```bash
./scripts/gen_media_fixtures.sh /tmp/fluxcatch-fixtures  # mp4 + hls via ffmpeg
python3 -m http.server 8000 --directory /tmp/fluxcatch-fixtures

# tests (sans navigateur)
manager/.venv/bin/pytest -v
# ou depuis racine:
pytest -v
```

Checklist sites manuels : `docs/checklist-sites.md`

## Limitations & hors périmètre

- **DRM** (Widevine/PlayReady/EME, Netflix/Prime/Disney+) → refus explicite `err_drm`, aucun contournement
- HLS live (sans `#EXT-X-ENDLIST`) → conseil enregistrement en v1
- Serveur sans `Range` → reprise = relance complète
- Segments `.ts/.m4s` seuls (sans manifeste) → ignorés (bruit)
- Pause uniquement si serveur `Range`

## Dépannage

- **Extension "Non lié"** → relancer `fluxcatch serve`, copier le code, bouton *Lier* (vérif `fluxcatch pair`)
- **403 err_forbidden** → l'extension propose le relais navigateur (fetch avec `credentials:include` → push `browser_proxy`)
- **ffmpeg non trouvé** → `sudo apt install ffmpeg` (sinon repli yt-dlp pour HLS)
- **yt-dlp absent** → `pip install yt-dlp` (sinon YouTube impossible)
- **Rien ne s'affiche** → `journalctl --user -u fluxcatch -f` ou `FLUXCATCH_LOG=debug fluxcatch serve`

## Jalons

M0 spike API → M1 manager minimal → M2 extension directes → M3 HLS/MSE/DRM → M4 ytdlp → M5 robustesse → M6 catalogue par sites
