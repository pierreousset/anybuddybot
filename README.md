# 🎾 AnyBuddy Sniper

Bot de réservation pour [Anybuddy](https://www.anybuddyapp.com) — détecte les
créneaux dès leur ouverture (ou dès qu'une annulation se libère) et réserve le
premier créneau correspondant à tes critères, puis s'arrête.

Pensé pour les clubs très demandés (ex. **Tennis du Jardin du Luxembourg**) où
les créneaux partent en quelques secondes et sont impossibles à attraper à la
main.

> ⚠️ **Usage strictement personnel.** L'automatisation viole probablement les
> CGU d'Anybuddy. Cet outil sert à réserver **tes propres** créneaux, avec une
> cadence de requêtes raisonnable. Ne l'utilise pas pour réserver en masse ou
> revendre — ça nuit aux autres joueurs et peut faire suspendre ton compte.

---

## 🟢 Mode ultra-simple (aucune connaissance requise)

Double-clique le lanceur correspondant à ton ordinateur :

- **Mac** → `START.command`
- **Windows** → `START.bat`

C'est tout. Au premier lancement il :
1. installe tout seul ce qu'il faut (~2 min) ;
2. ouvre une fenêtre pour que tu te **connectes à ton compte AnyBuddy** (vérifie qu'une carte est enregistrée) ;
3. te demande dans une fenêtre : **réserver pour de vrai**, ou **test sans payer** ;
4. attend l'ouverture du samedi à 8h, réserve le 1er créneau **9h–12h**, puis s'arrête.

👉 Lance-le **le vendredi soir**, laisse l'ordinateur **branché et l'écran ouvert**, et oublie-le. Il garde le PC éveillé tout seul.

**Prérequis unique : Python 3** doit être installé.
- Mac : généralement déjà présent (sinon [python.org](https://www.python.org/downloads/)).
- Windows : [python.org](https://www.python.org/downloads/) → coche **« Add Python to PATH »** à l'installation.

> macOS : si le fichier est bloqué (« développeur non identifié »), clic droit sur
> `START.command` → **Ouvrir** → **Ouvrir** (une seule fois).
> Windows : si SmartScreen s'affiche, **Informations complémentaires** → **Exécuter quand même**.

Le reste de ce README est pour un usage avancé / personnalisé.

---

## Comment ça marche

Le bot est en deux étages :

| Étage | Rôle | Auth |
|---|---|---|
| **Détection** | Interroge l'API du site (`/api/v1/availabilities`) en continu pour repérer les créneaux, y compris ceux qui n'apparaissent que quelques secondes. | Aucune |
| **Réservation** | Pilote un vrai navigateur connecté (Playwright) : sélection du créneau → CGV → carte enregistrée → paiement. | Session navigateur |

Pourquoi un navigateur pour réserver ? Le paiement passe par **Stripe Elements**
(iframe sécurisée, possible 3-D Secure) et la session Anybuddy expire ~1 h. Un
navigateur connecté rejoue le vrai parcours et garde la session vivante toute la
nuit — c'est la seule voie fiable pour une réservation 100 % automatique.

**Règle d'ouverture observée (Jardin du Luxembourg)** : les réservations d'un
jour ouvrent **7 jours avant, à 08:00 pile**. Le bot lit l'heure exacte dans la
réponse de l'API et attend à la seconde près.

---

## Installation

Prérequis : Python 3.10+.

```bash
git clone <repo>
cd anybuddy-sniper

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Navigateur pour la réservation automatique (optionnel si mode notif seul)
.venv/bin/playwright install chromium

cp config.example.yaml config.yaml   # puis édite config.yaml
```

---

## Configuration (`config.yaml`)

```yaml
center_id: tennis-jardin-du-luxembourg   # slug du club (cf. URL /fr/club/<slug>)

targets:
  activity: tennis
  weekdays: [5]            # 0=lun … 6=dim ; [] = tous. Ici samedi.
  time_from: "09:00"       # heure de début souhaitée (min)
  time_to:   "12:00"       # heure de début souhaitée (max)
  duration: null           # null = toute durée (créneaux par 30 min)
  court_keywords: []        # ex ["court 1"] ; ordre = préférence
  max_price_eur: null

sniping:
  target_weekday: 5        # vise le PROCHAIN samedi (auto, peu importe le jour de lancement)
  prefire_seconds: 3       # commence à marteler N s avant l'ouverture
  burst_hz: 4              # requêtes/seconde pendant le burst
  burst_duration_seconds: 120
  watch_poll_seconds: 60

# Réservation
booking_method: notify     # "notify" (alerte seule) | "browser" (résa + paiement)
dry_run: true              # browser + dry_run : ouvre le paiement mais NE paie PAS
headless: false
locale: fr

notifications:
  telegram: { bot_token: "", chat_id: "" }
  email:    { smtp_host: "", smtp_port: 587, username: "", password: "", from: "", to: "" }
```

---

## Utilisation

### 1. Vérifier l'état

```bash
.venv/bin/python main.py check
```
Affiche le samedi visé, l'heure d'ouverture des réservations et le nombre de
créneaux actuels.

### 2. Lister les créneaux d'une date (★ = correspond à tes critères)

```bash
.venv/bin/python main.py slots 2026-06-20
```

### 3. Sniper l'ouverture

```bash
.venv/bin/python main.py snipe
```
Attend l'heure d'ouverture (ex. samedi 08:00), martèle l'API, réserve le premier
créneau correspondant, puis **s'arrête** (jamais de second terrain).

### 4. Surveiller les annulations (sur une date déjà ouverte)

```bash
.venv/bin/python main.py watch 2026-06-20
```

---

## Réservation automatique (mode `browser`)

Par défaut le bot **notifie** seulement. Pour qu'il réserve et paie :

```bash
# 1. Connexion (une seule fois — session sauvegardée dans .pw-profile/)
.venv/bin/python -m anybuddy.booker_browser login

# 2. Dans config.yaml :
#    booking_method: browser
#    auto_book: true
#    dry_run: true     # garde true d'abord : va jusqu'au paiement SANS payer
```

Le bot ouvre l'URL préremplie du créneau → coche « J'accepte les CGV + conditions
du club » → sélectionne ta carte enregistrée → (si `dry_run: false`) clique
« Payer ». Un éventuel 3-D Secure est géré par le navigateur.

Les créneaux étant **annulables/remboursables ~24–48 h avant**, une erreur reste
sans risque financier (tu annules).

---

## Structure

```
START.command            Launcher double-clic — macOS
START.bat                Launcher double-clic — Windows
main.py                  CLI : check / slots / snipe / watch
config.example.yaml      Modèle de configuration
anybuddy/
  launcher.py            Flux tout-en-un cross-platform (fenêtres, garde-éveillé)
  client.py              Client API + parsing des disponibilités
  sniper.py              Stratégie : attente d'ouverture → burst → réservation → stop
  booker_browser.py      Réservation + paiement via Playwright (session connectée)
  notifier.py            Notifications Telegram / e-mail
```

---

## Notifications (optionnel)

- **Telegram** : crée un bot via [@BotFather](https://t.me/BotFather), récupère
  ton `chat_id` via [@userinfobot](https://t.me/userinfobot), renseigne-les dans
  `config.yaml`.
- **E-mail** : SMTP classique (ex. Gmail avec un mot de passe d'application).

Sans configuration, les alertes s'affichent dans la console.

---

## Licence

[MIT](LICENSE). Fourni tel quel, sans garantie. Respecte les CGU d'Anybuddy et
les conditions des clubs.
