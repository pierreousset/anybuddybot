"""
Lanceur tout-en-un cross-platform (macOS + Windows).

Appelé par START.command (Mac) ou START.bat (Windows) après l'installation.
Gère : config par défaut, connexion (1re fois), choix test/réel via fenêtres,
maintien du PC éveillé, lancement du sniping.

Aucune connaissance technique requise côté utilisateur.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
from pathlib import Path

import yaml

# Console Windows (cp1252) : éviter les plantages sur les emojis/accents.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
EXAMPLE = ROOT / "config.example.yaml"
PROFILE = ROOT / ".pw-profile"
TITLE = "AnyBuddy Sniper"
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


# ─────────────────────────────── fenêtres (avec repli console) ──────────────
def _tk():
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return tk, messagebox, root


def info(msg: str) -> None:
    try:
        tk, mb, root = _tk()
        mb.showinfo(TITLE, msg)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(f"\n=== {TITLE} ===\n{msg}\n")


def ask_yes_no(msg: str) -> bool:
    try:
        tk, mb, root = _tk()
        r = mb.askyesno(TITLE, msg)
        root.destroy()
        return bool(r)
    except Exception:  # noqa: BLE001
        return input(f"{msg} [o/N] ").strip().lower().startswith("o")


def ask_token() -> str:
    """Demande de coller le token AuthToken (repli console)."""
    msg = ("Google bloque la connexion automatisée.\n\n"
           "Colle ici ton cookie « AuthToken » (depuis ton navigateur :\n"
           "DevTools → Application → Cookies → anybuddyapp.com → AuthToken) :")
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        val = simpledialog.askstring(TITLE, msg, parent=root)
        root.destroy()
        return (val or "").strip()
    except Exception:  # noqa: BLE001
        return input(msg + "\n> ").strip()


def ask_browser() -> str:
    """Choix du navigateur. Renvoie le channel Playwright ('' = intégré)."""
    options = [
        ("Chromium intégré (recommandé)", ""),
        ("Google Chrome", "chrome"),
        ("Microsoft Edge", "msedge"),
        ("Firefox", "firefox"),
    ]
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title(TITLE)
        root.attributes("-topmost", True)
        choice = {"v": ""}
        tk.Label(root, text="Avec quel navigateur veux-tu te connecter ?",
                 padx=20, pady=10).pack()

        def pick(val):
            choice["v"] = val
            root.destroy()

        for label, val in options:
            tk.Button(root, text=label, width=32,
                      command=lambda v=val: pick(v)).pack(padx=20, pady=4)
        tk.Label(root, text="", pady=6).pack()
        root.mainloop()
        return choice["v"]
    except Exception:  # noqa: BLE001
        print("Navigateur : 1) Intégré  2) Chrome  3) Edge  4) Firefox")
        m = {"2": "chrome", "3": "msedge", "4": "firefox"}
        return m.get(input("Choix [1] : ").strip(), "")


# ─────────────────────────────── garder le PC éveillé ───────────────────────
class KeepAwake:
    """Empêche la mise en veille pendant l'attente (Mac: caffeinate, Win: API)."""

    def __enter__(self):
        self._proc = None
        if IS_MAC:
            try:
                self._proc = subprocess.Popen(
                    ["caffeinate", "-dimsu", "-w", str(os.getpid())]
                )
            except Exception:  # noqa: BLE001
                pass
        elif IS_WIN:
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    0x80000000 | 0x00000001 | 0x00000002
                )
            except Exception:  # noqa: BLE001
                pass
        return self

    def __exit__(self, *exc):
        if IS_WIN:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:  # noqa: BLE001
                pass
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass


# ─────────────────────────────────────── flux ──────────────────────────────
def main() -> None:
    if not CONFIG.exists():
        CONFIG.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    from . import booker_browser

    # Connexion (tant qu'aucune connexion réelle n'a abouti) avec le navigateur choisi.
    if not booker_browser.is_logged_in():
        channel = ask_browser()
        cfg["browser_channel"] = channel
        CONFIG.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        # Firefox nécessite un téléchargement Playwright ; Chrome/Edge utilisent
        # le navigateur déjà installé sur la machine.
        if channel == "firefox":
            info("Téléchargement de Firefox… (~1 min)")
            subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"])
        info(
            "Une fenêtre va s'ouvrir dans le navigateur choisi.\n\n"
            "Connecte-toi à ton compte AnyBuddy (et vérifie qu'une carte est "
            "bien enregistrée). La fenêtre se ferme toute seule une fois "
            "connecté."
        )
        booker_browser.login(channel=channel or None)

        # Google bloque parfois la connexion automatisée → repli par token.
        if not booker_browser.is_logged_in():
            if ask_yes_no(
                "La connexion par fenêtre n'a pas abouti (Google bloque "
                "souvent les navigateurs automatisés).\n\n"
                "Veux-tu te connecter en collant ton token AuthToken à la "
                "place ? (voir README : « Connexion bloquée par Google »)"
            ):
                tok = ask_token()
                if tok:
                    booker_browser.login_with_token(tok, channel or None)

        if not booker_browser.is_logged_in():
            info("Connexion non aboutie. Réessaie, ou vois le README "
                 "(section « Connexion bloquée par Google »).")
            return

    # Test ou réel ?
    reel = ask_yes_no(
        "Le bot va guetter un créneau le samedi matin (9h–12h) et le réserver "
        "dès l'ouverture (8h).\n\n"
        "RÉSERVER POUR DE VRAI (payer avec ta carte enregistrée) ?\n\n"
        "• Oui  = réserve et paie\n"
        "• Non  = test (va jusqu'au paiement SANS payer)"
    )
    if reel:
        if not ask_yes_no(
            "⚠️ Confirmation\n\nLe bot RÉSERVERA et PAIERA avec ta carte dès "
            "qu'un créneau 9h–12h se libère.\n"
            "(Créneau annulable/remboursable ~24-48h avant.)\n\nContinuer ?"
        ):
            return

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cfg["booking_method"] = "browser"
    cfg["auto_book"] = True
    cfg["dry_run"] = not reel
    cfg["headless"] = False
    CONFIG.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    info(
        "C'est parti ! Laisse l'ordinateur branché et l'écran ouvert.\n\n"
        "Le bot attend l'ouverture (samedi 8h), réserve le 1er créneau 9h–12h, "
        "puis s'arrête tout seul.\n\nTu peux laisser cette fenêtre ouverte."
    )

    # Import tardif pour que les fenêtres s'affichent avant tout chargement réseau.
    from .sniper import Sniper

    with KeepAwake():
        Sniper(cfg).snipe()

    info("Terminé. Vérifie tes réservations sur AnyBuddy 🎾")


if __name__ == "__main__":
    main()
