from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

from . import config as cfg
from . import pairing as pairing_mod
from .__init__ import __version__
from .server import create_app
from .store import Store


def setup_logging():
    level_name = os.environ.get("FLUXCATCH_LOG", "info").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # also file log
    try:
        cfg.ensure_dirs()
        log_path = cfg.log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path))
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass


def cmd_serve(args):
    setup_logging()
    cfg.ensure_dirs()
    store = Store()
    app = create_app(store)
    cfg_data = cfg.load_config()
    host = cfg_data.get("host", "127.0.0.1")
    port = int(cfg_data.get("port", 8765))
    if args.host:
        host = args.host
    if args.port:
        port = int(args.port)

    if port != cfg_data.get("port"):
        print(f"Port override: {port} (config {cfg_data.get('port')})")

    code = pairing_mod.get_or_create_secret()
    paired = pairing_mod.is_paired()
    print(f"FluxCatch v{__version__} — http://{host}:{port}")
    print(f"Dossier téléchargements: {cfg_data.get('download_dir')}")
    print(f"BDD: {cfg.db_path()}")
    print(f"Code de liaison: {code} {'(déjà lié)' if paired else '(en attente de liaison)'}")
    if not paired:
        print("→ Dans l'extension, saisissez ce code pour lier le navigateur.")
    try:
        import shutil
        print(f"ffmpeg: {'trouvé' if shutil.which('ffmpeg') else 'NON TROUVÉ (sudo apt install ffmpeg)'}")
        yt = shutil.which("yt-dlp") or shutil.which("yt_dlp")
        print(f"yt-dlp: {'trouvé @ '+yt if yt else 'NON TROUVÉ (pip install yt-dlp)'}")
    except Exception:
        pass

    # Run
    web.run_app(app, host=host, port=port, print=None)


def cmd_pair(args):
    cfg.ensure_dirs()
    if args.regenerate:
        code = pairing_mod.regenerate_secret()
        print(f"Nouveau code de liaison: {code}")
    else:
        code = pairing_mod.get_or_create_secret()
        print(f"Code de liaison: {code}")
    origins = pairing_mod.load_allowed_origins()
    if origins:
        print("Origines liées:")
        for o in sorted(origins):
            print(f"  - {o}")
    else:
        print("Aucune origine liée (extension non liée).")
    if args.clear:
        pairing_mod.save_allowed_origins(set())
        print("Origines effacées.")


def cmd_status(args):
    cfg.ensure_dirs()
    cfg_data = cfg.load_config()
    print(f"FluxCatch v{__version__}")
    print(f"Config: {cfg.config_path()} -> {cfg_data}")
    print(f"BDD: {cfg.db_path()} exists={cfg.db_path().exists()}")
    code = pairing_mod.get_or_create_secret()
    print(f"Code: {code}")
    print(f"Paired: {pairing_mod.is_paired()} origins={pairing_mod.load_allowed_origins()}")
    print(f"ffmpeg: {__import__('shutil').which('ffmpeg')}")
    yt = __import__('shutil').which("yt-dlp") or __import__('shutil').which("yt_dlp")
    print(f"yt-dlp: {yt}")
    # try to check if daemon running via http
    import urllib.request, json
    host = cfg_data.get("host", "127.0.0.1")
    port = cfg_data.get("port", 8765)
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/hello", timeout=2) as r:
            data = json.loads(r.read().decode())
            print(f"Daemon: RUNNING @ http://{host}:{port} -> {data}")
    except Exception as e:
        print(f"Daemon: NOT RUNNING ({e})")


def main():
    parser = argparse.ArgumentParser(prog="fluxcatch", description="FluxCatch - gestionnaire de téléchargements")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="lancer le daemon (avant-plan)")
    p_serve.add_argument("--host", help="hôte d'écoute (défaut config)")
    p_serve.add_argument("--port", type=int, help="port d'écoute")
    p_serve.set_defaults(func=cmd_serve)

    p_pair = sub.add_parser("pair", help="afficher/générer le code de liaison")
    p_pair.add_argument("--regenerate", action="store_true", help="générer un nouveau code")
    p_pair.add_argument("--clear", action="store_true", help="effacer les origines liées")
    p_pair.set_defaults(func=cmd_pair)

    p_status = sub.add_parser("status", help="état du daemon et config")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
