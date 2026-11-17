# StatsByDate – dynamisk schemaläggning v4

## Installation
Detta är en uppdatering ovanpå redan installerad v3. Kopiera de sex filerna i arkivet till motsvarande sökvägar. Behåll v3-Worker som reserv; workflow och publiceringsskript är oförändrade.

1. Kör `python3 -m unittest discover -s statsByDate/scripts -p test_dynamic_scheduler.py` och `node test_worker.mjs` från reporoten.
2. Granska diff, stage endast de sex filerna, commit, pull --rebase --autostash och push. Kör workflow StatsByDate manuellt med daily. Kontrollera att updateSchedule.json har schemaVersion 2, windows och rimliga UTC-tider.
3. Först efter verifiering: kopiera v4-Worker till Cloudflare. Behåll GITHUB_TOKEN. Använd SCHEDULER_MODE=shadow, ENABLE_DISPATCH=true för fortsatt fast drift när den nya Workern ersätter den gamla. Byt de gamla cron-triggers till exakt `*/5 * * * *`. Undvik två aktiva dispatchers och planera bytet så att ingen körning missas. ENABLE_DISPATCH=false är endast dry-run och stoppar även fasta starter.
4. Jämför shadow-loggar och JSON minst en matchnatt, inklusive 04:50. Aktivera dynamic först efter godkänd kontroll. Rollback: SCHEDULER_MODE=fixed med samma femminuterscron.

## Policy
- NHL och AHL: var 10:e minut från planerad start till, men inte inklusive, start +210 minuter, eller tidigare upptäckt FINAL. CANCELLED/POSTPONED undantas. SCHEDULED/UNKNOWN efter start hanteras som ej avslutade.
- NHL FINAL: första observerade FINAL sparas per match. Saknade målvideo-länkar utlöser 30-minutersuppdateringar innan FINAL +130 minuter. Alla mål måste finnas i Goals_<datum>.csv, räknat mot slutsumman (minus ett vid GWS), och ha en HTTP(S)-videolänk. Giltig tom målfil och 0 mål räknas som komplett; saknad fil räknas inte som komplett. Ingen kontroll av videons faktiska spelbarhet.
- AHL har i befintlig getGamePlayerStats.py ingen hämtning av målvideo; därför ingen highlight-trigger för AHL i denna version. En sådan källa krävs innan funktionen kan aktiveras för AHL.
- Varje match har ett separat tidsfönster i schemaVersion 2. Worker avrundar upp till UTC-femminutersslot och respekterar slutgränsen även om JSON inte uppdaterats. Överlappande fönster kan ge en gemensam regular-körning. En regular-körning hämtar fortfarande statistik för gårdagen/dagen och befintliga NHL-backfills; ingen separat highlight-only hämtning har införts. Därför kan andra uppdateringar fortfarande hämta en match som inte själv begär uppdateringar.
- FINAL som upptäcks vid bootstrap kan ge extra highlightförsök; faktisk sluttid saknas. Om matchen inte hinner bli observerad som FINAL före 210 min kan nästa ordinarie/dagliga uppdatering vara den första som upptäcker FINAL. 04:50 svensk tid kör daily oavsett fönster.
- Saknad/ogiltig/äldre än 26 timmar state ger fast fallback, vilket kan göra körningar utanför matchfönstren. Pågående workflow kontrolleras före dynamic regular; inga exakt-once-garantier. Intervallen är planerade starter, inte garanti vid kö/fel/cache.
- v4-Worker kräver schemaVersion 2; v3-state ger fallback. Vid fel i befintligt workflow publiceras schemaVersion 0, vilket kan förlora tidigare FINAL-observationer (oförändrat från v3).

## Tester och begränsningar
8 Python-testmetoder och 18 JS-assertions. Syntetisk data; inga externa API-anrop eller driftsättning. CSV-kolumner kontrollerade mot tidigare uppladdat getGamePlayerStats.py. Full integration behöver verifieras med riktiga CSV-filer och workflow i repot. Worker antar publikt läsbar råfil på GitHub main.
