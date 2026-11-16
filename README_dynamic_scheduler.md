# StatsByDate – dynamisk schemaläggning, pilot v3

## Installation (shadow först)
1. Kopiera `.github/workflows/StatsByDate.yml` och de fyra scheduler-/publiceringsfilerna under `statsByDate/scripts/` till samma sökvägar i repot. Övriga tre match-/recapscripts är oförändrade och behöver inte kopieras.
2. Kör från reporoten `python3 -m unittest discover -s statsByDate/scripts -p test_dynamic_scheduler.py` och `node test_worker.mjs` (om testfilerna kopierats).
3. Commit/push till main. Starta workflow manuellt med daily för att skapa `statsByDate/data/updateSchedule.json` inklusive dagens data och framtida schema.
4. Behåll befintlig Worker som backup. Kopiera innehållet i `LocalSport_Cloudflare_Scheduler_v3.js` till Worker. Sätt `SCHEDULER_MODE=shadow` och behåll `GITHUB_TOKEN`. Sätt `ENABLE_DISPATCH=false` under första kontrollen. Ersätt de gamla tre cron-triggers med exakt `*/5 * * * *` (UTC). Undvik överlappande aktiva Workers. Aktivera `ENABLE_DISPATCH=true` efter kontroll; shadow kör gamla tidsschemat och loggar dynamiska beslut.
5. Jämför loggar och JSON minst en full matchnatt, inklusive 04:50. Byt sedan `SCHEDULER_MODE=dynamic` om allt stämmer. Rollback: `SCHEDULER_MODE=fixed` (behåll nya cron-triggern). För full rollback återställ gamla filer, Worker och tre triggers tillsammans.

## Policy
- 10 min för LIVE, SCHEDULED eller UNKNOWN efter start, även efter 210 min. CANCELLED/POSTPONED undantas. En tidigare FINAL aktiverar eftermatchfasen om ingen annan match är aktiv.
- Efter sista observerade FINAL: 0–<60 min: 15; 60–<180: 30; 180–<400: 120; därefter ingen. Nästa kommande match kan tidigarelägga körningen. Intervallen beräknas vid varje lyckad körning. Första observation av FINAL sparas per liga/spel-ID; vid bootstrap kan historiska FINAL ge några extra körningar.
- Daglig 04:50 svensk tid kör nu även regular, så kolliderande dynamisk uppdatering täcks. Det genererar både dagens och framtidens data i samma workflow.
- 5-minuters cron behövs för 15-minutersintervall. Starttider avrundas upp till nästa 5-minutersslot. Uppdateringsintervall avser planerade starter, inte absolut garanti vid kö, fel, lång körning, cache eller fördröjning. Pågående workflow kontrolleras före dynamisk regular-dispatch; GitHub concurrency är kvar. Inte exakt-once.
- Saknad/ogiltig/för gammal state ger fast fallback. Det gamla schemat garanterar inte 10 min hela dygnet under fallback. Förfallotid 26 timmar för att tillåta matchfria dagar. Fel vid schemagenerering publicerar invalid state men blockerar inte statistikpublicering.
- SCHEDULED/UNKNOWN som aldrig blir terminal kan orsaka extra trafik så länge matchen finns i gårdagens/dagens datumfönster. Saknad StartUTC ger fallback. Ingen faktisk sluttid finns i källfilen.

## Testbegränsningar
Python enhetstester använder syntetiska CSV-rader; JS testar rena beslut, inte externa API-anrop. Inga liveanrop eller driftsättning utförda. Originalarkivet saknar riktiga CSV-filer och beroende getGamePlayerStats.py, så full integration måste verifieras i repot. Worker antar att råfilen är publikt läsbar på GitHub main.
