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

## Login

Ohne Anmeldung kann man den Kalender **nur ansehen** (inkl. allgemeinem iCal-Abo). Mit dem Knopf
**Anmelden** kommen die Funktionen für Benutzer dazu – z.B. «Jetzt prüfen» (alle Locations neu einlesen)
und der persönliche Kalender-Link. Soll die Seite ganz hinter dem Login sein: `auth.guests: false`.

Angemeldet kann man Konzerte markieren: **☆ Interessiert** oder **✓ Gehe hin**, bei «Gehe hin» mit
Ticket-Status (noch nicht / selbst gekauft / hat jemand anderes). Nochmals klicken entfernt die Markierung.
Unter «Meine Konzerte» lässt sich danach filtern. Der Tab **Meine** (oder Klick auf den
eigenen Namen, Direktlink `/#meine`) zeigt alle markierten Konzerte auf einen Blick: zuerst die ohne Ticket,
dann «Gehe hin», «Interessiert» und (zum Aufklappen) die vergangenen. Mit **Markierungen teilen** sehen andere, wohin man geht –
gegenseitig: nur wer selbst teilt, sieht die anderen (Name und Status, nicht den Ticket-Status).

Benutzer werden nur per Befehl angelegt (keine Registrierung):

```bash
docker compose exec konzert-agent python -m konzert_agent user add anna     # fragt nach dem Passwort
docker compose exec konzert-agent python -m konzert_agent user list
```

Weitere: `user passwd <name>` (beendet auch alle Sitzungen), `user disable|enable <name>`,
`user delete <name>`, `user logout <name>` (alle Sitzungen beenden), `user new-ical <name>`
(neuer Kalender-Link, der alte wird ungültig). Passwörter: mindestens 10 Zeichen.

Nach 5 Fehlversuchen in 15 Minuten sind der Benutzername und die IP 15 Minuten gesperrt (`auth:` in
`config.yaml`). Der **iCal-Abo**-Link ist persönlich und funktioniert ohne Passwort (Kalender-Apps können
sich nicht anmelden) – also nicht weitergeben; bei Bedarf mit `user new-ical` erneuern.

**Hinter nginx / Cloudflare** braucht der Login diese Header, sonst lehnt die Origin-Prüfung das
Anmelden ab bzw. das Cookie ist nicht als `Secure` markiert:

```nginx
location / {
    proxy_pass http://<homelab>:9099;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;   # bei Cloudflare «Flexible»: https fest eintragen
    proxy_set_header X-Real-IP $remote_addr;
}
```

Dazu in `config.yaml`: `settings.base_url` auf die öffentliche Adresse setzen (z.B.
`https://konzerte.example.ch`) und hinter Cloudflare `auth.client_ip_header: CF-Connecting-IP`,
damit die Sperre die echte IP sieht. Den Port 9099 im Heimnetz nicht ins Internet freigeben – nur den
Proxy. Ohne Login (nur Heimnetz): `auth.enabled: false`.

## Befehle

| Befehl | Zweck |
|---|---|
| `python -m konzert_agent test kiff` | eine Location live testen (speichert nichts, zeigt Filter-Treffer) |
| `python -m konzert_agent test kiff --details` | dito, inkl. Genre-Tags und Uhrzeit |
| `python -m konzert_agent run` | sofort alle prüfen und benachrichtigen |
| `python -m konzert_agent run kiff royal --no-notify` | nur bestimmte Locations, ohne Nachricht |
| `python -m konzert_agent types` | verfügbare Quellentypen |
| `python -m konzert_agent artists kiff` | erkannte Bands mit Genre, Stil und Popularität anzeigen |
| `python -m konzert_agent artists --save` | Band-Infos aller Events neu berechnen und speichern (z.B. nach Korrekturen) |
| `python -m konzert_agent artists kiff --no-lookup` | nur zeigen, welche Bandnamen aus den Titeln gelesen werden |
| `python -m konzert_agent --version` | installierte Version (steht auch in der Web-Oberfläche oben) |

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

## Band-Infos (Genre, Stil, Popularität)

Der Agent liest die Bandnamen aus den Event-Titeln und schlägt sie bei MusicBrainz (Genres/Stile) und
Deezer (Anzahl Fans) nach – für neue Events sofort, für bestehende schrittweise (`backfill_per_run`).
Ergebnisse werden 30 Tage gespeichert. Daraus entstehen pro Event:

- **Genres** – grobe Gruppen wie «Metal», «Indie & Alternative»; kennt keine Datenbank die Band, kommen
  sie aus den Tags der Location (PETZI, Schüür). Die `include`/`exclude`-Filter wirken auch auf Genres
  und Stile, z.B. `include: ["Metal", "Punk"]`.
- **Stile** – die feineren Tags («doom metal», «stoner rock»).
- **Popularität** 0–100 vom Headliner (logarithmisch aus den Deezer-Fans) und eine Stufe:
  lokal (< 1000 Fans) · Szene (< 20 000) · bekannt (< 300 000) · Star.

Im Web-Kalender lässt sich nach Genre und Popularität filtern und die Liste nach Popularität sortieren;
der «iCal-Abo»-Link übernimmt diese Filter (z.B. ein Abo nur mit Metal-Konzerten).

Gezählt werden nur sichere Treffer. Antwortet eine Datenbank nicht, wird das Event in späteren Läufen
erneut nachgeschlagen. Kurze oder häufige Namen («Elin», «Sports») werden oft der falschen
Band zugeordnet – mit `artists <location>` prüfen und in `config.yaml` unter `artists:` korrigieren
(`overrides` pro Bandname, `titles` für Titel ohne echte Bandnamen), danach `artists --save`.

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
die Programmseite von kiff.ch) – darum laufen KiFF & Co. über PETZI. Diese Seiten werden
mit `respect_robots: true` übersprungen und im Kalender als Fehler markiert.

Ausnahme: Die Band-Infos kommen über die offiziellen APIs von MusicBrainz und Deezer. MusicBrainz sperrt
`/ws` per robots.txt für Crawler, erlaubt Programmen den API-Zugriff aber ausdrücklich (max. 1 Anfrage/s,
erkennbarer User-Agent). Diese Anfragen laufen darum ohne robots-Prüfung, aber mit derselben Pause.

## Hinweise

- Die Scraper für **Exil**, **Hallenstadion**, **X-tra**, **Dynamo**, **Z7** und **Schüür** lesen die
  HTML-Struktur der Seiten; ändert sich das Layout, meldet der Kalender bei der Location «⚠ Fehler»
  bzw. 0 Events → mit `test <id>` prüfen.
- Hallenstadion zeigt auf der Übersicht nur 12 Events; der Scraper lädt die weiteren Seiten über den
  «mehr laden»-Endpunkt (`admin-ajax.php`, ≈ 8 Seiten → 8 Anfragen à 2 s pro Lauf).
- **X-tra** zeigt 9 Events; der Rest kommt wie im Browser über «Alle anzeigen» (POST mit dem
  CSRF-Token der Seite). Klappt das nicht mehr, bleiben die ersten 9 und im Log steht eine Warnung.
- **Dynamo** zeigt nur ~6 Wochen im Voraus – spätere Konzerte erscheinen, sobald sie nachrücken. Die
  Uhrzeiten in der Liste sind UTC und werden umgerechnet.
- **Nordportal** lädt sein Programm per JavaScript aus einer WordPress-API (`npwp.kailua.ch`); der
  Scraper fragt dieselbe API ab. Standard: nur Liveshows (`kinds` in config.yaml).
- Wenn `./data` nicht beschreibbar ist (Container läuft als UID 1000): `sudo chown 1000 data`.

## Tests

```bash
python -m unittest discover tests
```
