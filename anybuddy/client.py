"""
Client HTTP pour l'API Anybuddy.

Découvert par reconnaissance + capture DevTools (juin 2026) :
  - Dispos (site web)  : GET https://www.anybuddyapp.com/api/v1/availabilities
                         PUBLIQUE (aucun cookie ni token), schéma riche (slotId).
  - Dispos (mobile)    : GET https://api.anybuddyapp.com/v2/centers/{id}/availabilities
  - slotId             : déterministe = base64("{startDateTime}_{duration}")
                         ex base64("2026-06-22T16:00_60")
  - Réservation finale : le site passe par des Next.js Server Actions
                         (en-tête next-action, lié au x-deployment-id → fragile).
                         La voie propre reste l'API mobile POST /v2/reservations
                         avec le bearer token de l'utilisateur — à confirmer par
                         la capture d'une réservation réelle.

Réponse de /api/v1/availabilities :
  {"bookingRules": "...|null",
   "data": [{"startDateTime": "2026-06-22T16:00",
             "services": [{"id":"qee","duration":60,"slotId":"...",
                           "price":2300,"discountPrice":2300, ...}]}]}
"""

from __future__ import annotations

import base64
import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

import requests

WEB_BASE = "https://www.anybuddyapp.com"      # endpoint dispos public, schéma riche
BASE_URL = "https://api.anybuddyapp.com"      # API mobile (réservation)


def make_slot_id(start_datetime: str, duration: int) -> str:
    """Reconstruit le slotId Anybuddy : base64('{start}_{duration}')."""
    return base64.b64encode(f"{start_datetime}_{duration}".encode()).decode()

# Headers qui imitent l'app web. Indispensables : sans Origin/Referer/UA réalistes
# l'API renvoie 403.
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://www.anybuddyapp.com",
    "Referer": "https://www.anybuddyapp.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

# Heure d'ouverture entre parenthèses, EN ou FR :
#   "(Jun 14, 2026 at 08:00)"   ou   "(14 juin 2026 à 08:00)"
_OPEN_RE = re.compile(r"\(([^)]*\d{4}[^)]*\d{1,2}:\d{2})\)")

_FR_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "decembre": 12,
}


def _parse_opening(text: str) -> "dt.datetime | None":
    text = text.strip()
    # FR : "14 juin 2026 à 08:00"
    m = re.match(
        r"(\d{1,2})\s+([A-Za-zéûôàèç]+)\s+(\d{4}).*?(\d{1,2}):(\d{2})", text
    )
    if m and m.group(2).lower() in _FR_MONTHS:
        day, mon, year, hh, mm = (
            int(m.group(1)), _FR_MONTHS[m.group(2).lower()],
            int(m.group(3)), int(m.group(4)), int(m.group(5)),
        )
        return dt.datetime(year, mon, day, hh, mm)
    # EN : "Jun 14, 2026 at 08:00"
    try:
        return dt.datetime.strptime(text, "%b %d, %Y at %H:%M")
    except ValueError:
        return None


@dataclass
class Slot:
    """Un créneau réservable renvoyé par /api/v1/availabilities."""

    service_id: str
    start: str           # ISO local, ex "2026-06-22T16:00"
    duration: int        # minutes
    price: int           # centimes (ex 2300 = 23,00 €)
    slot_id: str
    discount_price: int
    activity_id: str = "tennis"
    court_name: str = ""
    raw: dict[str, Any] | None = None

    @property
    def price_eur(self) -> float:
        return (self.discount_price or self.price) / 100.0

    @property
    def start_dt(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.start)

    @property
    def end(self) -> str:
        return (self.start_dt + dt.timedelta(minutes=self.duration)).isoformat()

    def label(self) -> str:
        d = self.start_dt
        court = f" | {self.court_name}" if self.court_name else ""
        return f"{d:%a %d/%m %H:%M}+{self.duration}min{court} | {self.price_eur:.2f}€"


class AnybuddyClient:
    def __init__(
        self,
        token: str | None = None,
        timeout: float = 10.0,
        extra_headers: dict[str, str] | None = None,
        auth_cookie_name: str | None = "AuthToken",
    ):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.token = token
        if token:
            # Auth Anybuddy = cookie « AuthToken=<token> » (confirmé).
            if auth_cookie_name:
                self.session.cookies.set(
                    auth_cookie_name, token, domain=".anybuddyapp.com"
                )
            else:
                self.session.headers["Authorization"] = f"Bearer {token}"
        # En-têtes libres additionnels si besoin.
        if extra_headers:
            self.session.headers.update(extra_headers)

    # ----------------------------------------------------------------- centers
    def center(self, center_id: str) -> dict[str, Any]:
        r = self.session.get(
            f"{BASE_URL}/v1/centers/{center_id}", timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------ disponibilités
    def availabilities_raw(
        self,
        center_id: str,
        date: str,                       # "YYYY-MM-DD"
        activities: str = "tennis",
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Endpoint web public : schéma riche (slotId, discountPrice)."""
        params = {
            "clubSlug": center_id,
            "dateFrom": date,
            "dateTo": f"{date}T23:59",
            "activity": activities,
        }
        r = self.session.get(
            f"{WEB_BASE}/api/v1/availabilities", params=params, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    def slots(self, center_id: str, date: str, **kw) -> list[Slot]:
        data = self.availabilities_raw(center_id, date, **kw)
        out: list[Slot] = []
        for group in data.get("data", []):
            start = group.get("startDateTime", "")
            for svc in group.get("services", []):
                duration = svc.get("duration") or 0
                out.append(
                    Slot(
                        service_id=svc.get("id", ""),
                        start=start,
                        duration=duration,
                        price=svc.get("price") or 0,
                        discount_price=svc.get("discountPrice") or 0,
                        slot_id=svc.get("slotId")
                        or make_slot_id(start, duration),
                        court_name=svc.get("name", ""),
                        raw=svc,
                    )
                )
        return out

    @staticmethod
    def opening_time(raw: dict[str, Any]) -> dt.datetime | None:
        """Parse bookingRules pour extraire l'heure d'ouverture des résas.

        Renvoie None si les réservations sont déjà ouvertes ou si la règle
        est inconnue.
        """
        rules = raw.get("bookingRules") or ""
        m = _OPEN_RE.search(rules)
        if not m:
            return None
        return _parse_opening(m.group(1))

    # ------------------------------------------------------------- réservation
    def reserve(
        self,
        center_id: str,
        slot: Slot,
        first_name: str,
        last_name: str,
        email: str,
        party_size: int | None = None,
    ) -> dict[str, Any]:
        """Crée une réservation. NÉCESSITE un token utilisateur valide.

        ⚠️ NON CONFIRMÉ : les requêtes réelles n'ont pas encore été capturées.

        Flux observé côté UI (à transposer en appels HTTP une fois capturés) :
          1. cocher « J'accepte les CGV + conditions du club » (flag type
             acceptedTerms=true) puis confirmer le créneau (slotId/serviceId)
             → crée la réservation / le panier.
          2. « Use this card » : la carte est DÉJÀ enregistrée sur le compte,
             donc le paiement réutilise un moyen de paiement stocké
             (probablement un paymentMethodId Stripe) — pas de ressaisie CB.
          3. « Payer » → confirmation du paiement.

        Ce payload suit la doc partenaire Apiary + le slotId observé ; il sera
        réécrit (incl. acceptedTerms + paymentMethodId + étape paiement) dès que
        les requêtes des étapes 1-3 auront été capturées (voir README).
        """
        if not self.token:
            raise RuntimeError(
                "Aucun token : la réservation nécessite Authorization Bearer. "
                "Capture-le depuis les DevTools (voir README)."
            )
        payload: dict[str, Any] = {
            "centerId": center_id,
            "serviceId": slot.service_id,
            "slotId": slot.slot_id,
            "startDateTime": slot.start,
            "endDateTime": slot.end,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "price": slot.price,
        }
        if party_size:
            payload["partySize"] = party_size
        r = self.session.post(
            f"{BASE_URL}/v2/reservations", json=payload, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()
