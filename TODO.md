# TODO

## Band-Infos & Login (Plan vom 2026-10-14)

- [x] 0. Versionsnummer in der Web-Oberfläche (v1.1.0)
- [x] 1. Bandnamen aus Event-Titeln erkennen + Testbefehl `artists <location>` (MusicBrainz + Deezer, speichert nichts) (v1.2.0)
- [x] 2. Artist-Infos speichern: Cache-Tabelle, Refresh alle ~30 Tage, Genres → grobe Genre-Gruppen,
         Fans → Popularität 0–100 (Headliner); Genres wirken in include/exclude (v1.2.0)
  - [ ] Last.fm als zusätzliche Genre-Quelle (API-Key folgt später)
  - [x] Ohne MusicBrainz-Genres auf die Tags der Location (PETZI/Schüür) zurückfallen (v1.2.0)
  - [x] Manuelle Korrektur falscher Zuordnungen (`artists.overrides` / `artists.titles` in config.yaml) (v1.2.0)
- [x] 3. Oberfläche: Genre-Filter, Popularitäts-Badge, Sortierung nach Popularität;
         Genre/Popularität auch im iCal-Abo (`?genre=…&pop=…`) (v1.3.0)
- [x] 4. Login (auch von ausserhalb des Heimnetzes) – Gäste sehen den Kalender nur lesend, alle
         Benutzer-Funktionen hinter Login; persönliche iCal-Links funktionieren ohne (geheimer Token)
  - [x] 4a. Login: Benutzer per Befehl anlegen, Login-Seite, Logout, Sperre nach Fehlversuchen,
            `/api/run` nur mit Login; iCal-Abo über persönlichen Token-Link (v1.5.0)
  - [x] Gäste dürfen den Kalender ansehen (nur lesen), «Anmelden»-Knopf schaltet Funktionen frei;
        `auth.guests: false` = alles hinter Login (v1.6.0)
  - [x] 4b. Konzerte markieren pro Benutzer: «Interessiert» / «Gehe hin» (v1.7.0)
    - [x] Ticket-Status: «Ja, selbst gekauft» / «Ja, jemand anderes hat sie» / «Noch nicht» (v1.7.0)
    - [x] Teilen per Opt-in, gegenseitig (nur wer teilt, sieht andere); andere sehen Name + Status,
          nicht den Ticket-Status. Filter «Meine Konzerte»: Markiert / Gehe hin / Ohne Ticket / Andere gehen (v1.7.0)
  - [x] 4c. Dashboard «Meine» (Tab, Klick auf den Namen oder /#meine): Ticket fehlt noch, Gehe hin,
            Interessiert, Vergangen – unabhängig von den Filtern (v1.8.0)
  - [x] 4d. Persönlicher iCal-Link mit den markierten Konzerten (☆/✓ im Titel, TENTATIVE/CONFIRMED,
            Ticket + wer sonst hingeht in der Beschreibung), `?status=going`, `?all=1` = alle mit Filtern;
            Link im Tab «Meine» erneuerbar (v1.9.0)
  - Zugang von aussen: eigene Domain über Cloudflare → nginx-Reverse-Proxy (noch nicht aktiviert)
  - Gegenseitig sehen, wer hingeht: pro Benutzer ein-/ausschaltbar (Opt-in) (v1.7.0)

## Weitere Locations & Scraper

- [x] 6. Neue Scraper: Dynamo (Zürich), X-tra (Zürich), Nordportal (Baden),
         Old Capitol (Langenthal), Z7 (Pratteln) (v1.4.0)
  - Old Capitol: PETZI 268307 · Z7: `css` · X-tra/Dynamo/Nordportal: eigene Scraper
  - X-tra erlaubt Bots inzwischen (robots.txt «Allow: /»)
  - [x] Dynamo: alle Events über die Drupal-JSON:API (dynamo.nodehive.app) statt nur ~6 Wochen; nur die
        nötigen Felder abgefragt (`fields[...]`), Veranstalter-Kontaktdaten werden nicht geladen (v1.14.0)
- [x] 14. Mehr Locations im 2-h-Umkreis (v1.15.0)
  - Zürich: Volkshaus, Komplex 457 (Base44-API), The Hall (Dübendorf), Halle 622, Moods (JSON in der Seite),
    Plaza, Kaufleuten, Papiersaal (`css`); PETZI: Rote Fabrik, Mehrspur, Planet 5, Zentralwäscherei
  - Winterthur: Salzhaus, Albani (eigene Scraper); PETZI: Gaswerk, Kraftfeld
  - PETZI: Flösserplatz, Böröm pöm pöm, OXIL, Meck · Bern: Bierhübeli (eigener Scraper), Dachstock, Gaskessel,
    ISC, Bee-flat, Rössli, Café Kairo, KUFA Lyss · Basel: Sommercasino, Kuppel, Sudhaus, Gannet, Hirscheneck ·
    Luzern: Sedel, Neubad, Treibhaus, Kulturwerk 118 · Ostschweiz: Grabenhalle, Palace, Flon, Kammgarn, TapTab,
    KAFF, Eisenwerk, Horstklub · Fribourg/Biel: Fri-Son, Bad Bonn, Le Singe, AJZ
  - Mühle Hunziken (Rubigen, eigener Scraper), Schützi Olten (`css`, nur «Schützi Live»)
  - [ ] Noch offen (eigene Seiten, keine API gefunden): siehe 19.
        Rote Fabrik hat auf PETZI nur wenige Events (eigene Seite prüfen)
- [ ] 19. Fehlende Pop/Rock-Locations Deutschschweiz
  - Vorgehen: URLs vor dem Scrapen prüfen (nicht verifiziert); zuerst schauen, ob die Location auf PETZI verkauft
    → dann über den PETZI-Scraper, sonst eigener Scraper; Duplikate mit bestehenden Locations/Events vermeiden
  - (P?) = wahrscheinlich PETZI-Mitglied, bestätigen
  - [ ] Grosse Hallen: St. Jakobshalle (Basel, stjakobshalle.ch), PostFinance Arena (Bern, postfinance-arena.ch),
        KKL Luzern (kkl-luzern.ch – viel Klassik, nur Pop/Rock übernehmen), Maag Halle (Zürich, maag-halle.ch),
        Theater 11 (Zürich, theater11.ch – viele Musicals, nur Konzerte übernehmen)
    - Samsung Hall (Dübendorf) = heute «The Hall», schon drin (v1.15.0) – nicht doppelt anlegen
  - [ ] Zürich: Mascotte (mascotte.ch); Rote Fabrik eigene Seite (rotefabrik.ch), PETZI liefert nur wenige Events
  - [ ] Basel: Kaserne Basel (kaserne-basel.ch, P?), Atlantis (atlan-tis.ch), Volkshaus Basel (volkshaus-basel.ch)
  - [ ] Bern und Umgebung: Mahogany Hall (Bern, mahogany.ch, P?), Heitere Fahne (Wabern, dieheiterefahne.ch, P?),
        Café Bar Mokka (Thun, mokka.ch, P?); Café Kairo schon drin (PETZI)
  - [ ] Zentralschweiz: Südpol (Kriens, sudpol.ch, P?), Galvanik (Zug, galvanik-zug.ch, P?),
        Chollerhalle (Zug, chollerhalle.ch)
  - [ ] Ostschweiz: Kugl (St. Gallen, kugl.ch, P?), Gare de Lion (Wil, garedelion.ch, P?)
  - [ ] Aargau, Solothurn, Baselland: Merkker (Baden, merkker.ch, P?), Odeon (Brugg, odeon-brugg.ch),
        Coq d'Or (Olten, coqdor.ch, P?), Guggenheim (Liestal, guggenheimliestal.ch, P?)
- [ ] 13. statt nur locations auch Bandseiten direkt, um Touranouncement abzufangen und die Daten einzupflegen
- [ ] 18. Regionen als «Plugins» (Länder/Bundesländer/Städte), getrennt deploybar – z. B. Schweiz und Berlin
  - [ ] Venue-Sets pro Region in eigene Dateien auslagern (z. B. `regions/ch.yaml`, `regions/de-berlin.yaml`),
        `config.yaml` wählt nur aus, welche Regionen aktiv sind
  - [ ] Regionsspezifische Scraper in eigene Module (`sources/ch/…`, `sources/de/…`); nur aktive Regionen laden
  - [ ] Pro Region: Zeitzone, Währung (CHF/EUR, Preisformat), Sprache der Status-Wörter, Ticketplattformen
        (PETZI ↔ z. B. Eventim/Eventbrite für Berlin)
  - [ ] Separat deploybar: eigene Instanz pro Region (eigene DB/Port) oder eine Instanz mit Regionsfilter in der UI
  - [ ] Berlin-Set: Venues sammeln und Scraper bauen
- [ ] 24. Verschwundene Events als abgesagt markieren: heute gilt ein Event nur als abgesagt, wenn die Location
      es so beschriftet – verschwindet es einfach aus dem Programm, bleibt es im Kalender stehen
  - [ ] Pro Lauf vergleichen: kommende Events der Location, die nicht mehr in der Liste sind (`last_seen` älter als
        der aktuelle Lauf) -> abgesagt markieren und markierten Benutzern melden (wie heute bei «abgesagt»)
  - [ ] Nur nach erfolgreichem Lauf mit plausibler Anzahl Events (nicht bei 0 Events/Fehler/Seitenumbau), evtl.
        erst nach 2 Läufen ohne Treffer; X-tra lädt ohne «Alle anzeigen» nur 9 Events -> dort nicht anwenden
  - [ ] Taucht das Event wieder auf: Absage zurücknehmen
## Layout & Bedienung

- [x] 7. Optimierungen am UX (v1.10.0)
  - [x] Zusätzlicher Kalenderselector um individuelle Zeiträume (nicht nur Wochenende, 7, 30 Tage etc.) zu wählen (v1.10.0)
  - [x] Locations als zusammenklappbar per Stadt (Haken pro Stadt, ⚠ bei Fehlern) (v1.10.0)
    - [x] Einfügen von "colapse all" («alle aufklappen / zuklappen») (v1.14.0)
    - [x] Hinter jeder Location eine "nur" Button (auch pro Stadt) (v1.14.0)
  - [x] Persönliche Einstellungen am Ende der Sidebar (Teilen zusätzlich im Dashboard) (v1.10.0)
  - [x] Filter nach Event-Typ: Konzert / Party / Andere – aus Tags der Location, sonst eindeutigen Titelwörtern
        (`konzert_agent/kinds.py`); auch im iCal-Abo (`?kind=…`) (v1.10.0)
- [x] 8. Optimierungen am Layout (v1.10.0)
  - [x] Option zur Wahl der Akzentfarbe (6 Farben, je hell/dunkel abgestimmt) (v1.10.0)
  - [x] Option für Dark-/Lightmode (System / Hell / Dunkel) – pro Gerät gespeichert, auch für Gäste (v1.10.0)
  - [x] add a disclaimer and copyright notice at the bottom (`settings.copyright`) (v1.14.0)
- [ ] 22. Neuer Name für die App finden und im Code anpassen (Titel, Header, iCal-Kalendername, Telegram-Texte,
      README, Docker-Image/Container, Paketname `konzert_agent`)
- [ ] 23. Animiertes Logo im Header im Stil der Ghostty-Website (animierter ASCII-Geist) – passend zum neuen
      Namen (22); hell/dunkel und Akzentfarbe berücksichtigen, `prefers-reduced-motion` respektieren

## Userfunktionen

- [x] 9. Individuelle Telegram-Konfiguration pro Benutzer (Voraussetzung für 10) (v1.11.0)
  - [x] Selbst verbinden über eigenen Bot: Einmal-Link `t.me/<bot>?start=<code>`, Long-Polling (kein Webhook) (v1.11.0)
  - [x] Pro Benutzer: neue Konzerte Aus / Alle / Nur passende (gespeicherter Filter), Absagen markierter Konzerte (v1.11.0)
  - [x] Trennen im Web, mit /stop oder `user telegram-off`; blockierter Bot trennt automatisch (v1.11.0)
- [x] 10. Bands folgen → Telegram-Meldung bei neuer Show (v1.12.0)
  - [x] Folgen per ＋ beim Konzert oder per Name im Tab «Meine»; ★ in der Liste, «★ Gefolgte Bands» im Dashboard (v1.12.0)
  - [x] Treffer über erkannte Bands oder Name als ganze Wörter im Titel (auch Support-Bands) (v1.12.0)
  - [x] Telegram: «⭐ Neue Show …» immer (auch bei «Aus»), abschaltbar; nicht doppelt in der allgemeinen Liste (v1.12.0)
- [ ] 17. Persönliches Dashboard funktionaler + soziale Funktionen
  - [ ] Freunde wählen: Freunde sehen meine Konzertliste (interessiert / gehe hin)
  - [ ] Bei «Tickets kaufte jemand anders» auswählen, welcher Freund die Tickets gekauft hat
  - [ ] Persönlicher Kalender im Dashboard (eigene Konzerte als Monatsansicht)
  - [ ] Einstellungen (Telegram, Filter, Passwort …) in einen eigenen Tab «Einstellungen» verschieben
- [ ] 20. Mehr Optionen im neuen Benutzerbereich: einzelne Locations (oder ganze Städte) von der automatischen
      Telegram-Benachrichtigung abwählen
- [ ] 21. Filter-Presets speichern (benannt, pro Benutzer), schnell wieder aufrufen; evtl. als Basis für
      «Nur passende» bei Telegram und fürs iCal-Abo

## Später

- [x] 11. Support-Bands in der Liste anzeigen, unterhalb des Hauptacts (v1.13.0)
  - Line-up aus dem Titel (Locations liefern Support nicht separat): Hauptact, darunter «mit …» mit Stil/Fans, ＋ folgen
- [x] 12. Archiv: vergangene Events anschauen (Events werden nicht gelöscht, die DB füllt sich ab 2026-10-14) (v1.13.0)
  - Tab «Archiv» (neueste zuerst, Filter ohne Zeitraum, auch für Gäste); Monatsansicht blättert zurück
  - [ ] auch einen "Von-Bis"Filter im Archiv
- [x] 15. Verschobene/verlegte Events («Verschoben», «Verlegt», «Neues Datum») nicht als ABGESAGT führen, sondern
      als eigener Status VERSCHOBEN (v1.17.0)
  - Aussehen wie abgesagt (durchgestrichen), aber mit Hinweis, wohin bzw. auf wann (z.B. «→ verlegt ins Dynamo»,
    «→ neu am 13.04.2027»), soweit die Quelle das liefert
  - Heute als abgesagt markiert: Komplex 457 «Verlegt» (Ziel steht in `postponed_info`), The Hall «… in eine andere
    Location verlegt»; heute nur aus dem Titel entfernt: «VERSCHOBEN!», «Neues Datum» (`split_status`, z.B. Halle 622);
    Moods liefert `isPostponed`
  - Auch in iCal (nicht `STATUS:CANCELLED`) und Telegram (eigene Meldung statt «❌ Abgesagt»); die Absage-Meldung
    für markierte Konzerte sinngemäss auch für Verschiebungen
  - Umgesetzt: Spalten `moved`/`moved_note` (ältere Datenbanken werden beim Start nachgerüstet); iCal
    «(VERSCHOBEN)» + `STATUS:TENTATIVE`; Telegram «↪️ Verschoben» mit Hinweis; war ein Event schon als abgesagt
    gemeldet, gibt es keine zweite Meldung. «Neues Datum» / «auf dieses Datum verschoben» = nicht verschoben
  - [ ] Tourdaten-Branch (`feature/tour-announcements`): Ticketmaster-Status `postponed`/`rescheduled` beim
        Zusammenführen ebenfalls als verschoben übernehmen

- [x] 16. Ticketpreise anzeigen (v1.18.0)
  - Einheitlich «ab CHF 35» / «CHF 25–30» / «gratis» (`prices.py`), fett in der Liste, im iCal-Abo «Preis: …»
  - Neu mit Preis: Kaufleuten, Albani, Plaza, Komplex 457 (nur eigener Verkauf); vorher schon PETZI, Moods, Dynamo
  - Preise bestehender Events werden bei jedem Lauf aktualisiert (vorher nur beim Erstimport)
  - [ ] PETZI-Preise nachladen, wenn der Vorverkauf später startet (Detailseite wird nur für neue Events geladen)
  - [ ] Optional: nach Preis filtern/sortieren, Preis in Telegram-Meldungen

Reihenfolge (2026-10-14): zuerst 6 (erledigt), dann 4 (erledigt).
Reihenfolge (2026-10-15): 7 + 8 zusammen, dann 9 → 10, danach 11 und 12.
