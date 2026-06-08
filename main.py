#!/usr/bin/env python3
"""
Bot de réservation Anybuddy — Tennis Jardin du Luxembourg.

Usage :
  python main.py check                 # voir l'état + l'heure d'ouverture des résas
  python main.py slots [YYYY-MM-DD]    # lister les créneaux dispos d'une date
  python main.py snipe                 # attendre l'ouverture J-7 08:00 et sniper
  python main.py watch [YYYY-MM-DD]    # surveiller en continu (annulations)

Config : config.yaml (voir config.example.yaml).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from anybuddy.client import AnybuddyClient
from anybuddy.sniper import Sniper

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

CONFIG = Path(__file__).parent / "config.yaml"


def load_cfg() -> dict:
    if not CONFIG.exists():
        sys.exit("config.yaml manquant. Copie config.example.yaml → config.yaml.")
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def cmd_check(cfg: dict) -> None:
    c = AnybuddyClient(
        token=cfg.get("auth_token") or None,
        extra_headers=cfg.get("auth_headers") or None,
        auth_cookie_name=cfg.get("auth_cookie_name", "AuthToken"),
    )
    sniper = Sniper(cfg)
    date = sniper.target_date()
    raw = c.availabilities_raw(cfg["center_id"], date, activities=sniper.activities)
    import datetime as _dt
    wd = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"][
        _dt.date.fromisoformat(date).weekday()
    ]
    print(f"Centre : {cfg['center_id']}")
    print(f"Date cible : {wd}. {date}")
    print(f"bookingRules : {raw.get('bookingRules')}")
    open_at = c.opening_time(raw)
    print(f"Ouverture des résas : {open_at if open_at else 'déjà ouvertes / inconnu'}")
    print(f"Créneaux actuels : {len(raw.get('data', []))}")


def cmd_slots(cfg: dict, date: str | None) -> None:
    sniper = Sniper(cfg)
    date = date or sniper.target_date()
    all_slots = AnybuddyClient(
        token=cfg.get("auth_token") or None,
        extra_headers=cfg.get("auth_headers") or None,
        auth_cookie_name=cfg.get("auth_cookie_name", "AuthToken"),
    ).slots(cfg["center_id"], date, activities=sniper.activities)
    print(f"{date} : {len(all_slots)} créneau(x) dispo(s) au total.")
    for s in all_slots:
        mark = "★" if sniper.matches(s) else " "
        print(f" {mark} {s.label()}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    cfg = load_cfg()

    if cmd == "check":
        cmd_check(cfg)
    elif cmd == "slots":
        cmd_slots(cfg, arg)
    elif cmd == "snipe":
        Sniper(cfg).snipe()
    elif cmd == "watch":
        s = Sniper(cfg)
        s.watch(arg or s.target_date(), cfg.get("sniping", {}).get("watch_poll_seconds", 60))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
