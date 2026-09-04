#!/usr/bin/env bash
set -e
OUT="${1:-/tmp/fluxcatch-fixtures}"
mkdir -p "$OUT"
echo "→ Génération fixtures dans $OUT"

# petit mp4 5s (testsrc)
if command -v ffmpeg >/dev/null 2>&1; then
  echo "→ mp4 5s"
  ffmpeg -y -f lavfi -i testsrc=size=320x240:rate=30 -f lavfi -i anullsrc -t 5 -pix_fmt yuv420p -c:v libx264 -c:a aac "$OUT/sample.mp4" >/dev/null 2>&1 || echo "ffmpeg mp4 failed"
  echo "→ HLS"
  mkdir -p "$OUT/hls"
  ffmpeg -y -f lavfi -i testsrc=size=320x240:rate=30 -t 5 -c:v libx264 -pix_fmt yuv420p -hls_time 1 -hls_list_size 0 -hls_segment_filename "$OUT/hls/seg%03d.ts" "$OUT/hls/index.m3u8" >/dev/null 2>&1 || echo "ffmpeg hls failed"
else
  echo "ffmpeg absent, impossible de générer fixtures"
  exit 1
fi

# page html
cat > "$OUT/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Fixtures FluxCatch</title>
<h1>Fixtures locales</h1>
<h2>MP4 direct</h2><video src="sample.mp4" controls></video>
<h2>HLS</h2><video src="hls/index.m3u8" controls></video>
<h2>MSE blob</h2><video id="v" controls></video>
<script>
  // MSE simple: fetch mp4 et append
  (async()=>{
    const v=document.getElementById('v');
    if(!window.MediaSource) return;
    const ms=new MediaSource();
    v.src=URL.createObjectURL(ms);
    ms.addEventListener('sourceopen', async()=>{
      const buf=await fetch('sample.mp4').then(r=>r.arrayBuffer());
      const sb=ms.addSourceBuffer('video/mp4; codecs="avc1.42E01E"');
      sb.appendBuffer(buf);
      sb.addEventListener('updateend',()=>{ ms.endOfStream(); v.play().catch(()=>{}); });
    });
  })();
</script>
<h2>EME simulée</h2><video id="eme" controls></video>
<script>
  // Simuler EME: appeler requestMediaKeySystemAccess
  try{ navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{initDataTypes:['cenc']}]).catch(()=>{});}catch{}
</script>
HTML

echo "→ Fixtures prêts: $OUT/sample.mp4, $OUT/hls/index.m3u8, $OUT/index.html"
echo "  Servir: python3 -m http.server 8000 --directory $OUT"
