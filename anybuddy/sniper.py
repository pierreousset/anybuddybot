"""
Orchestration du sniping.

Stratégie pour Jardin du Luxembourg : les réservations ouvrent J-7 à 08:00 pile.
L'API nous donne l'instant exact via `bookingRules`. Le bot :
  1. cible une date (par défaut aujourd'hui + `open_days_ahead`),
  2. lit l'heure d'ouverture renvoyée par l'API,
  3. dort jusqu'à T-`prefire_seconds`,
  4. martèle /availabilities à haute fréquence,
  5. réserve le meilleur créneau correspondant aux préférences (ou notifie seulement),
  6. notifie le résultat.
"""

from __future__ import annotations

import datetime as dt
import time

from .client import AnybuddyClient, Slot
from .notifier import Notifier


class Sniper:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.center_id = cfg["center_id"]
        self.client = AnybuddyClient(
            token=cfg.get("auth_token") or None,
            extra_headers=cfg.get("auth_headers") or None,
            auth_cookie_name=cfg.get("auth_cookie_name", "AuthToken"),
        )
        self.notifier = Notifier(cfg.get("notifications"))
        t = cfg.get("targets", {})
        self.activities = t.get("activity", "tennis")
        self.weekdays = set(t.get("weekdays", []))        # 0=lun … 6=dim
        self.time_from = t.get("time_from", "00:00")
        self.time_to = t.get("time_to", "23:59")
        self.duration = t.get("duration")                  # minutes
        self.party_size = t.get("party_size")
        self.court_prefs = [c.lower() for c in t.get("court_keywords", [])]
        self.max_price = t.get("max_price_eur")            # euros
        s = cfg.get("sniping", {})
        # Jour cible : prochaine occurrence de ce jour (5=samedi). Prioritaire
        # sur open_days_ahead s'il est défini.
        self.target_weekday = s.get("target_weekday", None)
        self.open_days_ahead = s.get("open_days_ahead", 7)
        self.prefire_seconds = s.get("prefire_seconds", 3)
        self.burst_hz = s.get("burst_hz", 4)
        self.burst_duration = s.get("burst_duration_seconds", 60)
        self.auto_book = cfg.get("auto_book", False)
        self.dry_run = cfg.get("dry_run", True)
        # "notify" = alerte seulement | "browser" = réservation+paiement via Playwright
        self.booking_method = cfg.get("booking_method", "notify")
        # Verrou : passe à True dès qu'une résa réelle aboutit → stoppe tout.
        self.booked = False

    # --------------------------------------------------------------- matching
    def matches(self, slot: Slot) -> bool:
        d = slot.start_dt
        if self.weekdays and d.weekday() not in self.weekdays:
            return False
        hhmm = f"{d:%H:%M}"
        if not (self.time_from <= hhmm <= self.time_to):
            return False
        if self.duration and slot.duration != self.duration:
            return False
        if self.max_price and slot.price_eur > self.max_price:
            return False
        if self.court_prefs and not any(
            k in slot.court_name.lower() for k in self.court_prefs
        ):
            return False
        return True

    def rank(self, slot: Slot) -> tuple:
        """Plus petit = meilleur. Priorise l'ordre des mots-clés de court,
        puis l'heure de début, puis le prix."""
        court_rank = len(self.court_prefs)
        for i, k in enumerate(self.court_prefs):
            if k in slot.court_name.lower():
                court_rank = i
                break
        return (court_rank, slot.start, slot.price)

    # ------------------------------------------------------------------ dates
    def target_date(self) -> str:
        t = self.cfg.get("targets", {})
        if t.get("date"):
            return t["date"]
        today = dt.date.today()
        if self.target_weekday is None:
            return (today + dt.timedelta(days=self.open_days_ahead)).isoformat()

        # Auto : parmi les prochains samedis, viser celui dont l'OUVERTURE est
        # la plus proche dans le futur (= la prochaine qu'on peut sniper).
        # Robuste quel que soit le moment du lancement (vendredi soir, samedi…).
        now = dt.datetime.now()
        first = (self.target_weekday - today.weekday()) % 7 or 7
        candidates = [today + dt.timedelta(days=first + 7 * k) for k in range(6)]
        best = best_open = fallback = None
        for d in candidates:
            try:
                raw = self.client.availabilities_raw(
                    self.center_id, d.isoformat(), activities=self.activities
                )
            except Exception:  # noqa: BLE001
                continue
            op = self.client.opening_time(raw)
            if op and op > now:
                if best_open is None or op < best_open:
                    best_open, best = op, d
            elif fallback is None and raw.get("data"):
                fallback = d  # déjà ouvert et encore des créneaux (annulations)
        chosen = best or fallback or candidates[0]
        return chosen.isoformat()

    # ------------------------------------------------------------------- once
    def scan_once(self, date: str) -> list[Slot]:
        slots = self.client.slots(
            self.center_id,
            date,
            activities=self.activities,
            duration=self.duration,
            party_size=self.party_size,
        )
        return sorted((s for s in slots if self.matches(s)), key=self.rank)

    # ------------------------------------------------------- réserver + notif
    def grab(self, slot: Slot) -> bool:
        """Tente la réservation. Renvoie True s'il faut S'ARRÊTER
        (réservation réelle aboutie → ne pas réserver d'autres créneaux)."""
        # Garde-fou : si déjà réservé, ne retente jamais.
        if self.booked:
            return True

        # Mode notification seule (ou auto_book off, ou dry_run sans navigateur).
        if not self.auto_book or self.booking_method == "notify":
            self.notifier.send(
                "🎾 Créneau dispo",
                f"{slot.label()}\n→ Réserve vite dans l'app : "
                f"{self._booking_link(slot)}",
            )
            return False

        if self.booking_method == "browser":
            from .booker_browser import BrowserBooker

            booker = BrowserBooker(
                self.center_id,
                locale=self.cfg.get("locale", "fr"),
                headless=self.cfg.get("headless", False),
                channel=self.cfg.get("browser_channel") or None,
            )
            res = booker.book(slot, dry_run=self.dry_run)
            status = res.get("status", "?")
            # États qui signifient « la résa est partie » → on bloque tout.
            stop = status in ("confirmed", "pending", "unknown_after_pay")
            if stop and not self.dry_run:
                self.booked = True
            ok = status == "confirmed"
            self.notifier.send(
                "✅ Réservation confirmée — bot stoppé" if ok
                else f"ℹ️ Réservation ({status})",
                f"{slot.label()}\nStatut: {status}\n"
                f"{res.get('note') or res.get('error') or ''}\n"
                f"{self._booking_link(slot)}",
            )
            # En dry_run on NE bloque pas (on teste). Sinon, stop dès que partie.
            return self.booked

        return False

    def _booking_link(self, slot: Slot) -> str:
        d = slot.start_dt
        return (
            f"https://www.anybuddyapp.com/fr/club/{self.center_id}"
            f"?date={d:%Y-%m-%d}&serviceId={slot.service_id}"
            f"&time={d:%H:%M}&duration={slot.duration}"
        )

    # ------------------------------------------------------------------- snipe
    def snipe(self) -> None:
        date = self.cfg.get("targets", {}).get("date") or self.target_date()
        raw = self.client.availabilities_raw(
            self.center_id, date, activities=self.activities
        )
        open_at = self.client.opening_time(raw)
        now = dt.datetime.now()

        if open_at and open_at > now:
            fire_at = open_at - dt.timedelta(seconds=self.prefire_seconds)
            wait = (fire_at - now).total_seconds()
            print(
                f"[snipe] {date} : ouverture {open_at:%d/%m %H:%M}. "
                f"Attente {wait/3600:.2f} h jusqu'à T-{self.prefire_seconds}s…"
            )
            if wait > 0:
                time.sleep(wait)
        else:
            print(f"[snipe] {date} : réservations déjà ouvertes, scan immédiat.")

        # Burst
        deadline = time.monotonic() + self.burst_duration
        interval = 1.0 / self.burst_hz
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                matched = self.scan_once(date)
            except Exception as e:  # noqa: BLE001
                print(f"[snipe] tentative {attempt} erreur: {e}")
                time.sleep(interval)
                continue
            if matched:
                print(f"[snipe] {len(matched)} créneau(x) trouvé(s) "
                      f"à la tentative {attempt}.")
                for s in matched:
                    print("   →", s.label())
                if self.grab(matched[0]):
                    print("[snipe] Réservé → arrêt (aucun autre créneau pris).")
                    return
                # Notify / browser : une seule tentative, on s'arrête.
                if not self.auto_book or self.booking_method == "browser":
                    return
            time.sleep(interval)
        print("[snipe] Aucun créneau correspondant pendant la fenêtre de burst.")
        self.notifier.send(
            "ℹ️ Sniping terminé",
            f"{date} : aucun créneau correspondant trouvé après "
            f"{attempt} tentatives.",
        )

    # ------------------------------------------------------------- watch (alt)
    def watch(self, date: str, poll_seconds: int = 60) -> None:
        """Surveillance continue (annulations) sur une date déjà ouverte."""
        seen: set[str] = set()
        print(f"[watch] surveillance {date} toutes les {poll_seconds}s…")
        while not self.booked:
            try:
                for s in self.scan_once(date):
                    key = f"{s.start}|{s.service_id}"
                    if key not in seen:
                        seen.add(key)
                        print("   →", s.label())
                        if self.grab(s):
                            print("[watch] Réservé → arrêt.")
                            return
            except Exception as e:  # noqa: BLE001
                print(f"[watch] erreur: {e}")
            time.sleep(poll_seconds)
