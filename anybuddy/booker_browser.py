"""
Réservation + paiement via navigateur réel (Playwright).

Pourquoi un navigateur et pas du HTTP pur ?
  - Le paiement Anybuddy passe par Stripe Elements (iframe, clé pk_live_…),
    conçu pour empêcher l'automatisation HTTP directe (conformité PCI), avec
    possible 3-D Secure.
  - La réservation passe par des Next.js Server Actions liées au déploiement
    (fragiles à rejouer).
Un navigateur connecté contourne tout ça : il rejoue le vrai parcours.

Découverte clé (capture DevTools) : le formulaire de paiement s'ouvre
directement via les paramètres d'URL :
  /fr/club/{centerId}?date=YYYY-MM-DD&serviceId=...&time=HH:MM&duration=NN

Pré-requis :
  pip install playwright && playwright install chromium

Connexion : la 1re fois, lance `login()` pour te connecter à la main ; la
session est sauvegardée dans un profil persistant (PROFILE_DIR) et réutilisée.
"""

from __future__ import annotations

import time
from pathlib import Path

from .client import Slot

PROFILE_DIR = Path(__file__).parent.parent / ".pw-profile"
LOGIN_MARKER = PROFILE_DIR / ".logged_in"   # écrit seulement après connexion réussie
WEB = "https://www.anybuddyapp.com"


def is_logged_in() -> bool:
    """Vrai seulement si une connexion a réellement abouti (cookie capté)."""
    return LOGIN_MARKER.exists()

# Navigateurs supportés pour login + réservation.
#   ""/"chromium" = Chromium intégré | "chrome" = Google Chrome
#   "msedge" = Microsoft Edge | "firefox" = Firefox
def _launch_context(p, channel: str | None, headless: bool):
    """Ouvre un contexte persistant avec le navigateur choisi.

    Masque les signaux d'automatisation pour éviter le blocage Google
    (« This browser or app may not be secure »).
    """
    PROFILE_DIR.mkdir(exist_ok=True)
    ch = (channel or "").lower().strip()
    if ch == "firefox":
        return p.firefox.launch_persistent_context(str(PROFILE_DIR), headless=headless)
    kwargs = {
        "headless": headless,
        # Anti-détection : retire le bandeau « automation » et navigator.webdriver.
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
        ],
    }
    if ch in ("chrome", "msedge", "chrome-beta", "msedge-beta", "chrome-dev"):
        kwargs["channel"] = ch  # vrai Chrome / Edge installé sur la machine
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), **kwargs)
    # Cache navigator.webdriver côté page (signal n°1 que Google regarde).
    try:
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
    except Exception:  # noqa: BLE001
        pass
    return ctx

# Labels FR/EN observés dans la page (cf. capture).
TERMS_LABELS = ["J'accepte les", "Conditions Générales de Vente", "I accept"]
PAY_LABELS = ["Payer", "Pay"]


def _booking_url(center_id: str, slot: Slot, locale: str = "fr") -> str:
    d = slot.start_dt
    return (
        f"{WEB}/{locale}/club/{center_id}"
        f"?date={d:%Y-%m-%d}&serviceId={slot.service_id}"
        f"&time={d:%H:%M}&duration={slot.duration}"
    )


def login(headless: bool = False, timeout_s: int = 300,
          channel: str | None = None) -> None:
    """Ouvre un navigateur pour te connecter une fois. Session persistée.

    Détecte automatiquement la connexion (cookie AuthToken) — pas besoin
    d'appuyer sur une touche. Se ferme tout seul une fois connecté.
    `channel` : "" (Chromium intégré), "chrome", "msedge" ou "firefox".
    """
    import time

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _launch_context(p, channel, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{WEB}/fr/compte")
        print("→ Connecte-toi dans la fenêtre qui s'est ouverte "
              "(Google, Apple ou email).")
        print("  Dès que tu es connecté, la session est sauvegardée "
              "automatiquement.")
        deadline = time.monotonic() + timeout_s
        ok = False
        while time.monotonic() < deadline:
            cookies = {c["name"] for c in ctx.cookies()}
            if "AuthToken" in cookies:
                ok = True
                break
            time.sleep(2)
        ctx.close()
        if ok:
            LOGIN_MARKER.write_text(channel or "", encoding="utf-8")
            print(f"✅ Connecté. Session sauvegardée dans {PROFILE_DIR}")
        else:
            print("⏱️  Délai dépassé sans connexion détectée. Relance et "
                  "connecte-toi plus vite, ou augmente timeout_s.")


def login_with_token(token: str, channel: str | None = None) -> bool:
    """Connexion SANS fenêtre Google : injecte le cookie AuthToken.

    Utile quand Google bloque la connexion dans le navigateur automatisé
    (« This browser or app may not be secure »). Colle la valeur du cookie
    AuthToken de ton navigateur normal. Renvoie True si la session est posée.
    """
    from playwright.sync_api import sync_playwright

    token = token.strip()
    with sync_playwright() as p:
        ctx = _launch_context(p, channel, headless=True)
        ctx.add_cookies([{
            "name": "AuthToken", "value": token,
            "domain": ".anybuddyapp.com", "path": "/",
        }])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(f"{WEB}/fr/compte", wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001
            pass
        ok = "AuthToken" in {c["name"] for c in ctx.cookies()}
        ctx.close()
    if ok:
        LOGIN_MARKER.write_text(channel or "", encoding="utf-8")
        print("✅ Session enregistrée via token.")
    else:
        print("❌ Token non accepté (peut-être expiré).")
    return ok


class BrowserBooker:
    def __init__(self, center_id: str, locale: str = "fr", headless: bool = False,
                 channel: str | None = None):
        self.center_id = center_id
        self.locale = locale
        self.headless = headless
        self.channel = channel

    def book(self, slot: Slot, dry_run: bool = True) -> dict:
        """Réserve + paie un créneau via le navigateur connecté.

        dry_run=True : va jusqu'au formulaire de paiement mais NE clique PAS
        sur « Payer » (sécurité). Mets dry_run=False pour payer réellement.
        """
        from playwright.sync_api import sync_playwright

        if not PROFILE_DIR.exists():
            raise RuntimeError(
                "Aucune session. Lance d'abord : python -m anybuddy.booker_browser login"
            )

        url = _booking_url(self.center_id, slot, self.locale)
        result: dict = {"slot": slot.label(), "url": url, "status": "init"}

        with sync_playwright() as p:
            ctx = _launch_context(p, self.channel, self.headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded")

                # Cocher les CGV (case « J'accepte les … »).
                self._check_terms(page)

                # S'assurer que la carte enregistrée est sélectionnée (Stripe
                # affiche en général la carte sauvegardée présélectionnée).
                self._select_saved_card(page)

                if dry_run:
                    result["status"] = "dry_run_ready"
                    result["note"] = "Formulaire de paiement prêt — non payé (dry_run)."
                    page.wait_for_timeout(1500)
                    return result

                # Cliquer « Payer ».
                paid = self._click_pay(page)
                if not paid:
                    result["status"] = "pay_button_not_found"
                    return result

                # Attendre confirmation (toast/redirect). 3-DS éventuel géré ici
                # par le navigateur (challenge interactif si déclenché).
                ok = self._wait_confirmation(page, timeout_s=90)
                result["status"] = "confirmed" if ok else "unknown_after_pay"
                return result
            except Exception as e:  # noqa: BLE001
                result["status"] = "error"
                result["error"] = str(e)
                return result
            finally:
                if not self.headless:
                    page.wait_for_timeout(2000)
                ctx.close()

    # ------------------------------------------------------------- internals
    @staticmethod
    def _check_terms(page) -> None:
        # Essayer plusieurs stratégies pour la case CGV.
        for sel in [
            "input[type=checkbox]",
            "[role=checkbox]",
        ]:
            try:
                boxes = page.locator(sel)
                n = boxes.count()
                for i in range(n):
                    box = boxes.nth(i)
                    if box.is_visible() and not (box.is_checked() if sel.startswith("input") else False):
                        box.check(timeout=2000)
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _select_saved_card(page) -> None:
        # La carte enregistrée est généralement déjà sélectionnée. On tente un
        # clic doux sur un éventuel libellé « carte enregistrée / use this card ».
        for label in ["carte enregistrée", "use this card", "Utiliser cette carte"]:
            try:
                el = page.get_by_text(label, exact=False)
                if el.count() and el.first.is_visible():
                    el.first.click(timeout=1500)
                    break
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _click_pay(page) -> bool:
        for label in PAY_LABELS:
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if btn.count() and btn.first.is_enabled():
                    btn.first.click(timeout=3000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    @staticmethod
    def _wait_confirmation(page, timeout_s: int = 90) -> bool:
        markers = [
            "Réservation confirmée", "Paiement confirmé", "Le terrain est à toi",
            "Booking confirmed", "réservation",
        ]
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for m in markers:
                try:
                    if page.get_by_text(m, exact=False).count():
                        return True
                except Exception:  # noqa: BLE001
                    pass
            if "/confirmation" in page.url or "/success" in page.url:
                return True
            page.wait_for_timeout(1000)
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "login":
        login()
    else:
        print("Usage : python -m anybuddy.booker_browser login")
