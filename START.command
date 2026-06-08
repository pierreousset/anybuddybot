#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  AnyBuddy Sniper — DÉMARRAGE TOUT-EN-UN
#  Double-clique ce fichier. C'est tout.
#  (Installe ce qu'il faut tout seul, te connecte, puis réserve à 8h le samedi.)
# ═══════════════════════════════════════════════════════════════════════════

cd "$(dirname "$0")" || exit 1
TITLE="AnyBuddy Sniper"

popup()  { osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"$TITLE\"" >/dev/null 2>&1; }
notify() { osascript -e "display notification \"$1\" with title \"$TITLE\"" >/dev/null 2>&1; }

# ── 1. Installation automatique (première fois seulement) ──────────────────
if [ ! -d .venv ]; then
  notify "Installation en cours… patiente ~2 minutes."
  echo "Installation (première utilisation, ~2 min)…"
  python3 -m venv .venv || { popup "Python 3 est requis. Installe-le depuis python.org puis relance."; exit 1; }
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  .venv/bin/python -m playwright install chromium
fi

# ── 2. Config par défaut (Jardin du Luxembourg, samedi 9h–12h) ─────────────
[ -f config.yaml ] || cp config.example.yaml config.yaml

# ── 3. Connexion (première fois seulement) ─────────────────────────────────
if [ ! -d .pw-profile ]; then
  popup "Première utilisation : une fenêtre va s'ouvrir. Connecte-toi à ton compte AnyBuddy (et vérifie qu'une carte est bien enregistrée). La fenêtre se ferme toute seule une fois connecté."
  .venv/bin/python -m anybuddy.booker_browser login
fi

# ── 4. Une seule question : test ou pour de vrai ? ─────────────────────────
CHOIX=$(osascript -e "button returned of (display dialog \"Le bot va guetter un créneau le samedi matin (9h–12h) au Jardin du Luxembourg et le réserver dès 8h.\n\nQue veux-tu ?\" buttons {\"Test (sans payer)\",\"Réserver pour de vrai\"} default button 1 with title \"$TITLE\")")

if [ "$CHOIX" = "Réserver pour de vrai" ]; then
  osascript -e "display dialog \"⚠️ Le bot RÉSERVERA et PAIERA avec ta carte enregistrée dès qu'un créneau 9h–12h se libère samedi.\n\n(Créneau annulable/remboursable jusqu'à ~24-48h avant.)\n\nConfirmer ?\" buttons {\"Annuler\",\"Oui, réserver\"} default button 2 with title \"$TITLE\"" >/dev/null 2>&1 || exit 0
  DRY="false"
else
  DRY="true"
fi

# Applique le mode dans la config (navigateur, auto-book, test ou réel).
.venv/bin/python - "$DRY" <<'PY'
import sys, yaml
dry = sys.argv[1] == "true"
c = yaml.safe_load(open("config.yaml"))
c["booking_method"] = "browser"
c["auto_book"] = True
c["dry_run"] = dry
c["headless"] = False
yaml.safe_dump(c, open("config.yaml", "w"), allow_unicode=True)
PY

# ── 5. Lancement (garde le Mac éveillé, attend 8h, réserve, s'arrête) ──────
popup "C'est parti ! Laisse le Mac branché et l'écran ouvert.\n\nLe bot attend l'ouverture (samedi 8h), réserve le 1er créneau 9h–12h, puis s'arrête tout seul. Tu peux laisser cette fenêtre ouverte."
notify "Bot lancé. Il attend l'ouverture des créneaux."

LOG="snipe-$(date +%Y%m%d-%H%M).log"
caffeinate -dis .venv/bin/python main.py snipe 2>&1 | tee "$LOG"

notify "Bot terminé. Vérifie tes réservations sur AnyBuddy."
popup "Terminé. Regarde le résultat ci-dessus (et tes réservations sur AnyBuddy).\n\nAppuie sur OK pour fermer."
