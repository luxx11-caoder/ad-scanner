# Checklist sites — FluxCatch

| Domaine | Type | Navigateur | Résultat | Notes |
|---|---|---|---|---|
| `localhost:8000/sample.mp4` | direct | Chromium 120 + Firefox 121 | OK / TODO | Fixture locale mp4 direct |
| `localhost:8000/hls/index.m3u8` | hls | Chromium 120 + Firefox 121 | OK / TODO | Fixture HLS non-DRM |
| `localhost:8000` MSE blob | recorder | Chromium 120 + Firefox 121 | OK / TODO | Enregistrement MediaRecorder |
| YouTube (youtube.com/watch?v=…) | ytdlp | Chromium 120 + Firefox 121 | TODO | Nécessite yt-dlp |
| Vimeo (vimeo.com/…) | ytdlp | Chromium 120 | TODO | |
| Dailymotion | ytdlp | Chromium 120 | TODO | |
| Page avec `video` directe (ex: w3schools) | direct | Chromium + Firefox | TODO | |
| Site avec flux protégé DRM (Netflix) | drm | - | Refus explicite | Vérifier message err_drm |

> Ajouter à chaque test réel : domaine, type (direct/hls/ytdlp/recorder), navigateur/version, résultat.

## Procédure manuelle
1. `scripts/gen_media_fixtures.sh /tmp/fluxcatch-fixtures && python3 -m http.server 8000 --directory /tmp/fluxcatch-fixtures`
2. Ouvrir `http://127.0.0.1:8765` (daemon) + extension liée
3. Tester capture popup → téléchargement → vérif taille/progression/reprise
