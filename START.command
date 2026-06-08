#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  AnyBuddy Sniper — DÉMARRAGE (macOS)
#  Double-clique ce fichier. C'est tout.
# ═══════════════════════════════════════════════════════════════════════════
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  osascript -e 'display notification "Installation en cours… ~2 min." with title "AnyBuddy Sniper"' 2>/dev/null
  echo "Installation (première utilisation, ~2 min)…"
  python3 -m venv .venv || { osascript -e 'display dialog "Python 3 requis. Installe-le depuis python.org puis relance." buttons {"OK"}' 2>/dev/null; exit 1; }
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  .venv/bin/python -m playwright install chromium
fi

.venv/bin/python -m anybuddy.launcher
echo
echo "Fenêtre fermable. (Appuie sur une touche.)"
read -r -n 1
