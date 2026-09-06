#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/extension"
DST="$ROOT/extension-firefox"

echo "[FluxCatch] Génération extension-firefox (Firefox event page)..."

rm -rf "$DST"
mkdir -p "$DST"
# cp tout sauf le manifest (on le regenère)
rsync -a --exclude="manifest.json" "$SRC"/ "$DST"/

# Regenère manifest Firefox : service_worker -> scripts, supprime minimum_chrome_version
python3 << 'PY'
import json, pathlib
root = pathlib.Path(__file__).parent.parent if '__file__' in globals() else pathlib.Path(".")
# Quand lancé via bash, __file__ non défini, on prend ROOT via env
import os
root = pathlib.Path(os.environ.get("ROOT", pathlib.Path.cwd()))
src = pathlib.Path(root) / "extension" / "manifest.json"
dst = pathlib.Path(root) / "extension-firefox" / "manifest.json"
data = json.loads(src.read_text())
# Firefox MV3 event page
if "background" in data and "service_worker" in data["background"]:
    sw = data["background"].pop("service_worker")
    data["background"]["scripts"] = [sw]
# Supprime la contrainte Chrome-only
data.pop("minimum_chrome_version", None)
# S'assure que gecko est présent (déjà)
dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(f"  manifest Firefox écrit: {dst}")
# diff rapide
import difflib, json as j
orig = json.loads(src.read_text())
new = json.loads(dst.read_text())
if orig != new:
    print("  diff background:", orig.get("background"), "->", new.get("background"))
    if "minimum_chrome_version" in orig:
        print("  minimum_chrome_version supprimé")
PY

# Vérif JSON
python3 -m json.tool "$DST/manifest.json" > /dev/null && echo "  JSON manifest OK"
# node --check si dispo
for f in "$DST/src/background.js" "$DST/src/content-detect.js" "$DST/src/content-hook.js" "$DST/popup/popup.js"; do
  if command -v node >/dev/null 2>&1; then node --check "$f" && echo "  $(basename $f) OK" || echo "  $(basename $f) FAIL"; fi
done

echo "  → Charge dans Firefox: about:debugging#/runtime/this-firefox → Charger un module temporaire → $DST/manifest.json"
echo "  (temporaire, à Recharger après chaque modif et à recharger au reboot Firefox)"
