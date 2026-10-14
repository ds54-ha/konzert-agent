# Konzert-Agent

Prüft regelmässig die Programme deiner Konzertlocations, meldet neu angekündigte Konzerte per
Telegram und zeigt alles in einem filterbaren Web-Kalender (Liste + Monatsansicht, iCal-Abo).
Läuft als ein kleiner Docker-Container (≈ 60 MB RAM) – gedacht für den N100 im Homelab.

## Start

```bash
cp .env.example .env          # Telegram-Token + Chat-ID eintragen
docker compose up -d --build
```

Web-Kalender: `http://<homelab>:8080`. Der erste Lauf startet ein paar Sekunden nach dem Start und
importiert alle Events still (kein Telegram-Spam). Ab dem zweiten Lauf (Standard alle 6 h) kommen nur
noch neu angekündigte Konzerte und Absagen.

**Telegram einrichten:** Bei [@BotFather](https://t.me/BotFather) `/newbot` → Token. Dem Bot eine
Nachricht schicken, dann `https://api.telegram.org/bot<TOKEN>/getUpdates` öffnen → `chat.id`.
Testen mit:

```bash
docker compose exec konzert-agent python -m konzert_agent test-notify
```

## Befehle

| Befehl | Zweck |
|---|---|
| `python -m konzert_agent test kiff` | eine Location live testen (speichert nichts, zeigt Filter-Treffer) |
| `python -m konzert_agent test kiff --details` | dito, inkl. Genre-Tags und Uhrzeit |
| `python -m konzert_agent run` | sofort alle prüfen und benachrichtigen |
| `python -m konzert_agent run kiff royal --no-notify` | nur bestimmte Locations, ohne Nachricht |
| `python -m konzert_agent types` | verfügbare Quellentypen |

Im Container jeweils mit `docker compose exec konzert-agent …` voranstellen.

## Locations hinzufügen (meist ohne Code)

Alles passiert in `config.yaml` (wird gemountet, Container danach neu starten).

**1. PETZI-Clubs** – der einfachste Weg. Über 100 Schweizer Clubs verkaufen über petzi.ch
(KiFF, Royal, Bogen F, Helsinki, Moods, Mehrspur, Gaswerk, Kraftfeld, Schüür, Dachstock …).
Auf einer beliebigen Event-Seite des Clubs den Link «Organisiert von» öffnen –
`petzi.ch/de/organiser/225/` → ID `225`.

```yaml
- id: moods
  name: Moods
  city: Zürich
  type: petzi
  options: {organiser: <ID aus dem Link>}
```

**2. Seiten mit schema.org-Daten** (`type: jsonld`) – viele CMS (WordPress-Event-Plugins, Eventbrite,
Ticketcorner-Seiten) liefern das automatisch. Einfach URL eintragen und mit `test` prüfen.

**3. iCal-Feed** (`type: ical`) – falls die Location einen `.ics`-Link anbietet.

**4. CSS-Selektoren** (`type: css`) – für jede andere HTML-Liste. Im Browser per Rechtsklick →
«Untersuchen» die Elemente bestimmen; Beispiel siehe `config.yaml`.

**5. Eigene Python-Quelle** – für knifflige Seiten. Vorlage: `plugins/beispiel_quelle.py`,
dann in `config.yaml` unter `plugins:` eintragen. Eine Quelle ist eine Klasse mit `parse(html)`,
optional `fetch()` (Paginierung/APIs) und `enrich(event)` (Details nur für neue Events).

**Filter pro Location:** `include:` / `exclude:` sind Regex-Listen, geprüft auf Titel + Genre-Tags.
Beispiel: `exclude: ["Comedy", "Party"]` oder `include: ["Metal", "Punk"]`.

## Weitere Benachrichtigungen

`webhook` sendet JSON (`new`, `cancelled`, `summary`) an eine URL – z.B. eine Home-Assistant-
Automation mit Webhook-Trigger, die dann eine Push-Nachricht oder TTS auslöst. Eigene Kanäle:
Klasse mit `send(new, cancelled)` in `konzert_agent/notifiers/` und `@register("name")`.

## Kalender-Abo

Der Button «iCal-Abo» kopiert einen Link mit den aktuell gewählten Filtern. Apple- und
Outlook-Kalender abonnieren ihn direkt aus dem Heimnetz; **Google Calendar** holt Abos von seinen
Servern und braucht daher eine öffentlich erreichbare URL (z.B. via Cloudflare Tunnel oder Tailscale Funnel).

## Fair scrapen

Der Agent beachtet `robots.txt`, wartet 2 s zwischen Anfragen an denselben Server und lädt
Detailseiten nur für neue Events. Einige Locations sperren Bots per robots.txt (z.B. merkker.ch,
x-tra.ch, die Programmseite von kiff.ch) – darum laufen KiFF & Co. über PETZI. Diese Seiten werden
mit `respect_robots: true` übersprungen und im Kalender als Fehler markiert.

## Hinweise

- Die Scraper für **Exil** und **Hallenstadion** lesen die HTML-Struktur der Seiten; ändert sich das
  Layout, meldet der Kalender bei der Location «⚠ Fehler» bzw. 0 Events → mit `test <id>` prüfen.
- Hallenstadion zeigt auf der Übersicht nur die nächsten ~12 Events; spätere Ankündigungen erscheinen,
  sobald sie nachrücken.
- Wenn `./data` nicht beschreibbar ist (Container läuft als UID 1000): `sudo chown 1000 data`.

## Tests

```bash
python -m unittest discover tests
```
