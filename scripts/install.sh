#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANAGER="$ROOT/manager"
VENV="$MANAGER/.venv"

echo "[FluxCatch] Installation..."

# venv
if [ ! -d "$VENV" ]; then
  echo "→ Création venv $VENV"
  python3 -m venv "$VENV"
fi
echo "→ pip install -e manager"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "$MANAGER"

# ffmpeg check
if command -v ffmpeg >/dev/null 2>&1; then
  echo "✓ ffmpeg trouvé: $(ffmpeg -version | head -n1)"
else
  echo "✗ ffmpeg NON TROUVÉ — installez avec:"
  echo "  sudo apt install -y ffmpeg"
fi
# yt-dlp check
if command -v yt-dlp >/dev/null 2>&1; then
  echo "✓ yt-dlp trouvé: $(yt-dlp --version 2>/dev/null)"
elif "$VENV/bin/yt-dlp" >/dev/null 2>&1; then
  echo "✓ yt-dlp dans venv"
else
  echo "ℹ yt-dlp non trouvé (optionnel) — pip install yt-dlp"
fi

# icons
echo "→ Génération icônes"
python3 "$ROOT/scripts/make_icons.py"

# systemd user
SERVICE_SRC="$ROOT/systemd/fluxcatch.service"
SERVICE_DST="$HOME/.config/systemd/user/fluxcatch.service"
mkdir -p "$HOME/.config/systemd/user"
if [ -f "$SERVICE_SRC" ]; then
  # replace placeholder venv path
  sed "s|__VENV__|$VENV|g; s|__ROOT__|$ROOT|g" "$SERVICE_SRC" > "$SERVICE_DST"
  echo "→ Service systemd installé: $SERVICE_DST"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
    systemctl --user enable --now fluxcatch || echo "ℹ systemctl --user enable --now fluxcatch à lancer manuellement"
    echo "✓ Service activé. Logs: journalctl --user -u fluxcatch -f"
  fi
else
  echo "⚠ Service template manquant"
fi

echo ""
echo "✅ Install terminé"
echo "  Lancer en dev: $VENV/bin/fluxcatch serve"
echo "  Code liaison: $VENV/bin/fluxcatch pair"
echo "  Extension: charger dossier $ROOT/extension dans chrome://extensions ou about:debugging"
