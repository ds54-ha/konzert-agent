# TODO

## Band-Infos & Login (Plan vom 2026-10-14)

- [x] 0. Versionsnummer in der Web-Oberfläche (v1.1.0)
- [x] 1. Bandnamen aus Event-Titeln erkennen + Testbefehl `artists <location>` (MusicBrainz + Deezer, speichert nichts)
- [x] 2. Artist-Infos speichern: Cache-Tabelle, Refresh alle ~30 Tage, Genres → grobe Genre-Gruppen,
         Fans → Popularität 0–100 (Headliner); Genres wirken in include/exclude (v1.2.0)
  - [ ] Last.fm als zusätzliche Genre-Quelle (API-Key folgt später)
  - [x] Ohne MusicBrainz-Genres auf die Tags der Location (PETZI/Schüür) zurückfallen
  - [x] Manuelle Korrektur falscher Zuordnungen (`artists.overrides` / `artists.titles` in config.yaml)
- [ ] 3. Oberfläche: Genre-Filter, Popularitäts-Badge, Sortierung nach Popularität
- [ ] 4. Login (auch von ausserhalb des Heimnetzes): Benutzer per Befehl anlegen, Favoriten-Stern,
         «Meine Favoriten», persönlicher iCal-Link mit geheimem Token, Login-Sperre nach Fehlversuchen,
         `/api/run` nur mit Login
- [ ] 5. Optional: Bands folgen → Telegram-Meldung bei neuer Show
