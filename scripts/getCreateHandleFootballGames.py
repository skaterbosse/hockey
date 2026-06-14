#!/usr/bin/env python3
"""
getCreateHandleFootballGames.py

Hämtar gbgfotboll-matcher, mappar matcher till fotbollskluster och uppdaterar
football_games.csv utan mellanlagringsfiler.

Normal drift:
  python3 scripts/getCreateHandleFootballGames.py \
    -dbg \
    -dl "2026-05-19-2026-05-30" \
    -ail "1,7,8,21,28" \
    -ik data/FootballFieldsCluster.txt \
    -ef Error_File_createFotballGames.txt \
    -io data/football_games.csv

Test/troubleshooting:
  python3 scripts/getCreateHandleFootballGames.py \
    -dbg \
    -dl "2026-05-22" \
    -ail "1,7,8,21,28" \
    -ik data/FootballFieldsCluster.txt \
    -ef Error_File_createFotballGames.txt \
    -i data/football_games.csv \
    -o /tmp/football_games_test.csv

Regel:
  För varje datum i -dl tas alla befintliga matcher för datumet bort från input-CSV
  och ersätts helt av nyhämtade matcher för samma datum.

Krav:
  Scriptet återanvänder senaste syskonscript när de finns:
    scripts/getGbgFootball.py       för API-hämtning
    scripts/createFootballGames.py  för klustermappning/deduplicering
    scripts/createFootballGamesCsv.py för CSV-format/association-namn
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

BASE_URL = "https://www.gbgfotboll.se/api/matches-today/games/"
SLEEP_SECONDS = 0.5
DEFAULT_ERROR_FILE = "Error_File_createFotballGames.txt"

ASSOCIATION_NAMES = {
    "7": "Göteborg",
    "8": "Halland",
    "21": "Västergötland",
    "28": "Bohuslän-Dalsland",
}

CSV_HEADER = [
    "Serie_Match_AssId", "Datum", "Klockslag", "SerieId", "SerieNamn",
    "SerieKönId", "ÅldersKatId", "MatchId", "MatchStatus", "MatchUrl",
    "HemmalagNamn", "HemmalagLogoUrl", "HemmalagAssId",
    "BortalagNamn", "BortalagLogoUrl", "BortalagAssId",
    "MatchResultat", "ArenaNamn", "ArenaKluster",
    "ArenaKlusterAdress", "SäkerMapping",
    "LS_Lat", "LS_Long", "LS_admin", "LS_sport",
]


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"DEBUG: {message}", file=sys.stderr)


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Ogiltigt datum: {value}. Förväntat YYYY-MM-DD.") from exc


def parse_relative_day_offset(value: str) -> int:
    value = value.strip()
    if value.startswith("+"):
        value = value[1:]

    try:
        return int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Ogiltig relativ dag-offset: {value}. Exempel: 0, -3, +8."
        ) from exc


def expand_relative_date_range(value: str) -> Optional[List[str]]:
    """
    Stödjer:
      0        -> idag
      -3:+8   -> idag-3 till idag+8
      -1:2    -> idag-1 till idag+2
      +1:+3   -> imorgon till idag+3

    Returnerar None om value inte är ett relativt format.
    """
    item = value.strip()

    if re.fullmatch(r"[+-]?\d+", item):
        offset = parse_relative_day_offset(item)
        return [(date.today() + timedelta(days=offset)).isoformat()]

    match = re.fullmatch(r"([+-]?\d+):([+-]?\d+)", item)
    if not match:
        return None

    start_offset = parse_relative_day_offset(match.group(1))
    end_offset = parse_relative_day_offset(match.group(2))

    if end_offset < start_offset:
        raise argparse.ArgumentTypeError(
            f"Ogiltigt relativt datumintervall: {value}. Slutoffset är före startoffset."
        )

    start_date = date.today() + timedelta(days=start_offset)
    end_date = date.today() + timedelta(days=end_offset)

    dates: List[str] = []
    current = start_date
    while current <= end_date:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    return dates


def parse_date_list(value: str) -> List[str]:
    if not value or not value.strip():
        raise argparse.ArgumentTypeError("-dl får inte vara tom")

    dates: List[date] = []
    seen: Set[date] = set()

    # Ex:
    #   2026-04-14
    #   2026-04-20-2026-04-25
    #   2026-04-14,2026-04-20-2026-04-25,2026-05-02
    #   0
    #   -3:+8
    #   -1:+2,2026-05-30
    absolute_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d{4}-\d{2}-\d{2}))?$")

    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue

        relative_dates = expand_relative_date_range(part)
        if relative_dates is not None:
            for date_text in relative_dates:
                d = parse_date(date_text)
                if d not in seen:
                    dates.append(d)
                    seen.add(d)
            continue

        match = absolute_pattern.fullmatch(part)
        if not match:
            raise argparse.ArgumentTypeError(
                f"Ogiltigt datum/datumintervall i -dl: {part}. "
                "Ex: 2026-05-19, 2026-05-19-2026-05-30, 0 eller -3:+8"
            )

        start = parse_date(match.group(1))
        end = parse_date(match.group(2)) if match.group(2) else start

        if end < start:
            raise argparse.ArgumentTypeError(f"Ogiltigt datumintervall: {part}. Slutdatum före startdatum.")

        current = start
        while current <= end:
            if current not in seen:
                dates.append(current)
                seen.add(current)
            current += timedelta(days=1)

    if not dates:
        raise argparse.ArgumentTypeError("-dl måste innehålla minst ett datum")

    if len(dates) > 250:
        raise argparse.ArgumentTypeError(f"-dl expanderade till {len(dates)} datum. Max är 250.")

    return [d.isoformat() for d in sorted(dates)]

def parse_association_ids(value: str) -> List[str]:
    if not value or not value.strip():
        raise argparse.ArgumentTypeError("-ail får inte vara tom")

    result: List[str] = []
    seen: Set[str] = set()

    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if not item.isdigit() or int(item) < 1:
            raise argparse.ArgumentTypeError(f"Ogiltigt associationId i -ail: {item}")
        if item not in seen:
            result.append(item)
            seen.add(item)

    if not result:
        raise argparse.ArgumentTypeError("-ail måste innehålla minst ett associationId")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="getCreateHandleFootballGames.py",
        description="Samlat script för LocalSport fotboll: hämta, mappa, skapa CSV, uppdatera CSV, förbättra kluster och analysera mappning.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='ANVÄNDNINGSFALL\n\n1) Normal drift / GitHub Action: uppdatera data/football_games.csv\n   Hämtar matcher online, mappar till fotbollskluster och ersätter alla matcher\n   för datumen i -dl i befintlig CSV.\n\n   Exempel:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode update-csv \\\n       -dbg \\\n       -dl "2026-05-19-2026-05-30" \\\n       -ail "1,7,8,21,28" \\\n       -ik data/FootballFieldsCluster.txt \\\n       -ef temp/Error_File_createFotballGames.txt \\\n       -io data/football_games.csv\n\n   Input:\n     data/football_games.csv\n     data/FootballFieldsCluster.txt\n\n   Output:\n     data/football_games.csv\n     temp/Error_File_createFotballGames.txt\n\n   Princip:\n     För varje datum i -dl tas gamla matcher för datumet bort och ersätts helt\n     av nya matcher.\n\n\n2) Endast hämta rå matcher: ersätter gamla getGbgFootball.py\n   Hämtar rå JSON från gbgfotboll.se och skriver:\n     datum;associationId;json-response\n\n   Exempel:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode fetch-raw \\\n       -dbg \\\n       -dl "2026-05-21-2026-05-22" \\\n       -ail "1,7,8,21,28" \\\n       -of temp/gbgfotboll_matches_2026-05-21_2026-05-22.txt\n\n   Outputformat:\n     2026-05-21;7;{"associationId":7,"date":"2026-05-21T00:00:00","competitions":[...]}\n     2026-05-21;8;{"associationId":8,"date":"2026-05-21T00:00:00","competitions":[...]}\n\n   Notera:\n     JSON-raderna kan vara mycket långa.\n\n\n3) Endast mappa rå matcher till intern matchfil: ersätter gamla createFootballGames.py\n   Läser råfilen från fetch-raw, mappar location till fotbollskluster och skriver\n   intern semikolonfil med 22 kolumner.\n\n   Exempel:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode map-games \\\n       -ig temp/gbgfotboll_matches_2026-05-21_2026-05-22.txt \\\n       -ik data/FootballFieldsCluster.txt \\\n       -og temp/footballGames.txt \\\n       -ef temp/Error_File_createFotballGames.txt \\\n       -dbg\n\n   Input:\n     temp/gbgfotboll_matches_2026-05-21_2026-05-22.txt\n     data/FootballFieldsCluster.txt\n\n   Output:\n     temp/footballGames.txt\n     temp/Error_File_createFotballGames.txt\n\n   Exempelrad i temp/footballGames.txt:\n     7;2026-05-21;19:00;133152;Division 6A Herr;2;4;6532596;4;/go-to/?fmid=6532596;Lekstorps IF;...;LP - Idrottspark A - plan;LP - Idrottspark;57.841028, 12.289142;LP Idrottspark, Sportvägen 7, 443 40 Gråbo;Y\n\n\n4) Endast skapa frontend-CSV: ersätter gamla createFootballGamesCsv.py\n   Konverterar intern matchfil till data/football_games.csv-formatet som frontend\n   läser.\n\n   Exempel:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode make-csv \\\n       -i temp/footballGames.txt \\\n       -o data/football_games.csv\n\n   Outputheader:\n     Serie_Match_AssId;Datum;Klockslag;SerieId;SerieNamn;SerieKönId;ÅldersKatId;MatchId;MatchStatus;MatchUrl;HemmalagNamn;HemmalagLogoUrl;HemmalagAssId;BortalagNamn;BortalagLogoUrl;BortalagAssId;MatchResultat;ArenaNamn;ArenaKluster;ArenaKlusterAdress;SäkerMapping;LS_Lat;LS_Long;LS_admin;LS_sport\n\n   Exempelrad:\n     7;2026-05-21;19:00;133152;Division 6A Herr;2;4;6532596;4;/go-to/?fmid=6532596;Lekstorps IF;https://staticcdn.svenskfotboll.se/img/teamssm/10760.png;7;Bellevue City FK;https://staticcdn.svenskfotboll.se/img/teamssm/13632.png;7;1-1;LP - Idrottspark A - plan;LP - Idrottspark;LP Idrottspark, Sportvägen 7, 443 40 Gråbo;Y;57.841028;12.289142;Göteborg;football\n\n\n5) Förbättra kluster med hemmalag/AssID: ersätter enhanceFotballArenaClusterWithHomeTeams_v8.py\n   Läser klusterfil och en eller flera hemmalagsfiler. Lägger till/uppdaterar\n   AssID och hemmalag i klusterfilen.\n\n   Exempel:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode enhance-clusters \\\n       -cf data/FootballFieldsCluster.txt \\\n       -hf data/HomeTeams_old.txt,data/HomeTeams_addition.txt \\\n       -of data/FootballFieldsCluster_enhanced.txt \\\n       -ot data/HomeTeams_merged.txt\n\n   För att skriva tillbaka resultatet till -cf:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode enhance-clusters \\\n       -cf data/FootballFieldsCluster.txt \\\n       -hf data/HomeTeams_merged.txt \\\n       -of data/FootballFieldsCluster_enhanced.txt \\\n       -ucf\n\n   Klusterfil, exempel:\n     7;Kviberg;57.737550, 12.038540;Luftvärnsvägen, 415 06 Göteborg;Kviberg|Kviberg 1 konstgräs|Kviberg 3:1 gräs 7M7;1,Utbynäs SK Gul|1,Qviding FIF\n     7,21;Gamla Ullevi;57.706411, 11.980905;Ullevigatan 5, 411 39 Göteborg;Gamla Ullevi;2,IFK Göteborg|2,GAIS\n\n   Hemmalagsfil, exempel:\n     1;7;Kviberg 3 Gräs;Utbynäs SK Gul\n     2;7;Gamla Ullevi;GAIS\n\n   Output:\n     uppdaterad klusterfil\n     optional mergad hemmalagsfil med -ot\n\n\n6) Analysera mappning / förslag för manuell klusterförbättring\n   Tänkt QA-läge för att hitta:\n     - nya hemmalag som bör läggas till på kluster\n     - nya planalias som bör läggas till på kluster\n     - matcher som inte kan placeras\n     - förslag till nya kluster\n\n   Exempel:\n     python3 scripts/getCreateHandleFootballGames.py \\\n       --mode analyze-mapping \\\n       -ef temp/Error_File_createFotballGames.txt \\\n       -ik data/FootballFieldsCluster.txt \\\n       -puf temp/ProposedFootballFieldsClusterUpdates.txt \\\n       -npc temp/NewProposedFootballArenaClusters.txt \\\n       -uht temp/UnmatchedHomeTeams.txt\n\n   Föreslagen output:\n     temp/ProposedFootballFieldsClusterUpdates.txt\n     temp/NewProposedFootballArenaClusters.txt\n     temp/UnmatchedHomeTeams.txt\n\n   Exempel ProposedFootballFieldsClusterUpdates.txt:\n     UPDATE_HOME_TEAM;Kviberg;ADD_HOME_TEAM;1,Utbynäs SK Gul\n     UPDATE_PLAN;Kviberg;ADD_PLAN;Kviberg 3 Gräs\n\n   Exempel NewProposedFootballArenaClusters.txt:\n     0;NYTT_KLUSTER_BEHÖVS;0,0;;Strandvallen 1, Unnaryd;1,Unnaryds GoIF\n\n\n7) State-fil för automatisk körning\n   När GitHub Action introduceras bör scriptet använda:\n     data/getCreateHandleFootballGames.state.json\n\n   Tanken:\n     Första körningen per dygn:\n       FULL_WINDOW_REFRESH, t.ex. dag -3 till dag +8\n     Senare körningar samma dygn:\n       TODAY_ONLY_REFRESH\n\n   Exempel state:\n     {"last_full_refresh_date":"2026-05-22","last_run_timestamp":"2026-05-22T14:33:11","runs_today":3}\n\n\nPARAMETRAR\n\nGemensamma:\n  --mode MODE\n      update-csv | fetch-raw | map-games | make-csv | enhance-clusters | analyze-mapping | generate-series-ranking\n\n  -dbg\n      Skriv debug-information till stderr.\n\nDatum och associationer:\n  -dl DATE_LIST\n      Datum eller datumintervall.\n      Ex: "2026-05-21"\n      Ex: "2026-05-19-2026-05-30"\n      Ex: "2026-05-19,2026-05-21-2026-05-23"\n\n  -ail ASSOCIATION_ID_LIST\n      Ex: "1,7,8,21,28"\n\nMatch/kluster:\n  -ik FILE\n      Klusterfil för matchmappning.\n      Ex: data/FootballFieldsCluster.txt\n\n  -ef FILE\n      Error/diagnostikfil.\n      Ex: temp/Error_File_createFotballGames.txt\n\nCSV update:\n  -io FILE\n      Input/output samma fil. Ex: data/football_games.csv\n\n  -i FILE\n      Inputfil vid test/felsökning eller make-csv.\n\n  -o FILE\n      Outputfil vid test/felsökning eller make-csv.\n\nRå-/internfiler:\n  -of FILE\n      Outputfil för fetch-raw eller enhance-clusters.\n\n  -ig FILE\n      Input games, råfil från fetch-raw.\n\n  -og FILE\n      Output games, intern 22-kolumners matchfil.\n\nEnhance clusters:\n  -cf FILE\n      Cluster file.\n\n  -hf FILE[,FILE...]\n      En eller flera hemmalagsfiler.\n\n  -ot FILE\n      Optional output team file med mergade hemmalagsrader.\n\n  -ucf\n      Skriv tillbaka uppdaterad klusterfil till -cf.\n\nAnalyze mapping:\n  -puf FILE\n      ProposedFootballFieldsClusterUpdates.txt\n\n  -npc FILE\n      NewProposedFootballArenaClusters.txt\n\n  -uht FILE\n      UnmatchedHomeTeams.txt\n',
    )

    parser.add_argument(
        "--mode",
        choices=["update-csv", "fetch-raw", "map-games", "make-csv", "enhance-clusters", "analyze-mapping", "generate-series-ranking"],
        default="update-csv",
        help="Körläge. Default: update-csv.",
    )

    parser.add_argument("-dbg", action="store_true", help="Skriv debug-information till stderr.")
    parser.add_argument("-dl", type=parse_date_list, help='Datumlista/intervall, ex "2026-05-19-2026-05-30"')
    parser.add_argument("-ail", type=parse_association_ids, help='AssociationId-lista, ex "1,7,8,21,28"')

    parser.add_argument("-ik", help="Input klusterfil för matchmappning, ex data/FootballFieldsCluster.txt")
    parser.add_argument("-ef", default=DEFAULT_ERROR_FILE, help=f"Error file. Default: {DEFAULT_ERROR_FILE}")
    parser.add_argument("-umf", help="Optional fil med endast osäkra/gissade mappningar.")
    parser.add_argument("-ecsv", help="Optional outputfil för genererad FootballClustersEnhanced.csv. Default: samma katalog som -ik.")
    parser.add_argument("-state", help="Optional statefil för automatisk dagslogik.")
    parser.add_argument("-old", help="Optional old games CSV. Kräver -state.")

    parser.add_argument("-io", help="Input/output CSV-fil som uppdateras in-place, ex data/football_games.csv")
    parser.add_argument("-i", help="Inputfil vid test/felsökning eller make-csv.")
    parser.add_argument("-o", help="Outputfil vid test/felsökning eller make-csv.")

    parser.add_argument("-of", help="Outputfil för fetch-raw eller enhance-clusters.")
    parser.add_argument("-ig", "--input-games", dest="input_games", help="Input games, råfil från fetch-raw.")
    parser.add_argument("-og", "--output-games", dest="output_games", help="Output games, intern 22-kolumners matchfil.")

    parser.add_argument("-cf", "--cluster-file", dest="cluster_file", help="Cluster file för enhance-clusters.")
    parser.add_argument("-hf", "--home-team-file", dest="home_team_file", help="En eller flera hemmalagsfiler, kommaseparerade.")
    parser.add_argument("-ot", "--output-team-file", dest="output_team_file", help="Output team file med mergade hemmalagsrader.")
    parser.add_argument("-ucf", "--update-cluster-file", dest="update_cluster_file", action="store_true", help="Skriv tillbaka enhance-resultat till -cf.")

    parser.add_argument("-puf", help="ProposedFootballFieldsClusterUpdates.txt")
    parser.add_argument("-npc", help="NewProposedFootballArenaClusters.txt")
    parser.add_argument("-uht", help="UnmatchedHomeTeams.txt")

    args = parser.parse_args()

    def require(*names: str) -> None:
        missing = [name for name in names if not getattr(args, name)]
        if missing:
            parser.error(f"--mode {args.mode} kräver: " + ", ".join("-" + name.replace("_", "-") for name in missing))

    if args.mode == "update-csv":
        require("ail", "ik")
        if not args.dl and not args.state:
            parser.error("--mode update-csv kräver -dl, eller -state för automatisk dagslogik")
        if args.state and not args.old:
            parser.error("--mode update-csv med -state kräver även -old")
        if args.old and not args.state:
            parser.error("--mode update-csv med -old kräver även -state")
        if not args.io and not (args.i and args.o):
            parser.error("--mode update-csv kräver antingen -io eller både -i och -o")
        if args.io and (args.i or args.o):
            parser.error("--mode update-csv: använd antingen -io eller -i/-o, inte båda")

    elif args.mode == "fetch-raw":
        require("dl", "ail", "of")

    elif args.mode == "map-games":
        require("input_games", "ik", "output_games")

    elif args.mode == "make-csv":
        require("i", "o")

    elif args.mode == "enhance-clusters":
        require("cluster_file", "home_team_file", "of")

    elif args.mode == "analyze-mapping":
        require("ef", "umf", "ik", "puf", "npc", "uht")

    elif args.mode == "generate-series-ranking":
        require("i", "old", "o")

    return args

def load_python_module(module_name: str, candidates: Sequence[Path]):
    for path in candidates:
        if not path.exists():
            continue

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module, path

    return None, None


def load_create_football_games_module():
    script_dir = Path(__file__).resolve().parent

    # Prioritera den nya stavningen och scripts/-katalogen.
    # Acceptera inte äldre createFotballGames.py-varianter som saknar nya hjälpfunktioner.
    candidates = [
        Path.cwd() / "scripts" / "createFootballGames.py",
        script_dir / "createFootballGames.py",
        Path.cwd() / "scripts" / "createFotballGames.py",
        script_dir / "createFotballGames.py",
        script_dir / "createFotballGames_v5.py",
    ]

    required_attrs = [
        "read_clusters",
        "iter_json_objects",
        "iter_competitions",
        "should_skip_game",
        "map_game_to_cluster",
        "game_to_output_row",
        "write_error",
    ]

    rejected = []

    for path in candidates:
        module, loaded_path = load_python_module("local_create_football_games", [path])
        if module is None or loaded_path is None:
            continue

        missing = [attr for attr in required_attrs if not hasattr(module, attr)]
        if missing:
            rejected.append(f"{loaded_path} saknar: {', '.join(missing)}")
            continue

        return module, loaded_path

    tried = "\n".join(f"  {path}" for path in candidates)
    rejected_text = "\n".join(f"  {item}" for item in rejected)
    raise FileNotFoundError(
        "Kunde inte hitta en kompatibel createFootballGames.py/createFotballGames.py.\n"
        "Testade:\n" + tried +
        ("\nAvvisade filer:\n" + rejected_text if rejected_text else "")
    )

def load_get_gbg_football_module():
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "getGbgFootball.py",
        script_dir / "getGbgFotboll.py",
        Path.cwd() / "scripts" / "getGbgFootball.py",
        Path.cwd() / "scripts" / "getGbgFotboll.py",
    ]

    return load_python_module("local_get_gbg_football", candidates)


def load_create_football_games_csv_module():
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "createFootballGamesCsv.py",
        script_dir / "createFootballGamesCsv_v3.py",
        Path.cwd() / "scripts" / "createFootballGamesCsv.py",
        Path.cwd() / "scripts" / "createFootballGamesCsv_v3.py",
    ]

    return load_python_module("local_create_football_games_csv", candidates)


def load_enhance_clusters_module():
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "enhanceFotballArenaClusterWithHomeTeams.py",
        script_dir / "enhanceFotballArenaClusterWithHomeTeams_v8.py",
        Path.cwd() / "scripts" / "enhanceFotballArenaClusterWithHomeTeams.py",
        Path.cwd() / "scripts" / "enhanceFotballArenaClusterWithHomeTeams_v8.py",
    ]

    return load_python_module("local_enhance_football_clusters", candidates)


def fetch_games_json(date_text: str, association_id: str, get_module=None, debug: bool = False) -> str:
    if get_module is not None and hasattr(get_module, "fetch_data"):
        try:
            return get_module.fetch_data(int(association_id), date_text, debug=debug)
        except Exception as exc:  # noqa: BLE001 - fallback till urllib om syskonscriptet fallerar.
            debug_print(debug, f"getGbgFootball.fetch_data fallerade, använder urllib fallback: {exc}")

    url = f"{BASE_URL}?associationId={association_id}&date={date_text}"
    debug_print(debug, f"Hämtar {url}")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LocalSport/getCreateHandleFootballGames.py",
            "Accept": "application/json,text/plain,*/*",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            data = response.read()
            return data.decode("utf-8", errors="replace").replace("\n", " ").strip()
    except urllib.error.HTTPError as exc:
        return f"ERROR: http_status={exc.code} url={url}"
    except urllib.error.URLError as exc:
        return f"ERROR: url_error={exc.reason} url={url}"
    except TimeoutError:
        return f"ERROR: timeout url={url}"
    except Exception as exc:  # noqa: BLE001 - script ska fortsätta och logga felet.
        return f"ERROR: {exc} url={url}"


def iter_raw_fetch_lines(dates: Sequence[str], association_ids: Sequence[str], get_module=None, debug: bool = False) -> Iterable[Tuple[int, str, str, str]]:
    line_number = 0

    for date_text in dates:
        for association_id in association_ids:
            line_number += 1
            json_text = fetch_games_json(date_text, association_id, get_module=get_module, debug=debug)
            yield line_number, date_text, association_id, json_text
            time.sleep(SLEEP_SECONDS)


def output_row_to_csv_row(row: List[str], csv_module=None) -> List[str]:
    # createFootballGames.py outputformat 22 kolumner:
    # 0 AssId, 1 Datum, 2 Tid, 3 SerieId, ..., 19 Koordinater, 20 Adress, 21 SäkerMapping
    row = list(row) + [""] * (22 - len(row))

    if csv_module is not None and hasattr(csv_module, "split_coords"):
        lat, lon = csv_module.split_coords(row[19])
    else:
        lat, lon = split_coordinates(row[19])

    association_names = ASSOCIATION_NAMES
    if csv_module is not None and hasattr(csv_module, "ASSOCIATION_NAMES"):
        association_names = csv_module.ASSOCIATION_NAMES

    return [
        row[0], row[1], row[2], row[3], row[4],
        row[5], row[6], row[7], row[8], row[9],
        row[10], row[11], row[12],
        row[13], row[14], row[15],
        row[16], row[17], row[18],
        row[20], row[21],
        lat, lon,
        association_names.get(row[0], row[0]),
        "football",
    ]


def split_coordinates(value: str) -> Tuple[str, str]:
    value = str(value or "").strip()
    if "," not in value:
        return "", ""
    lat, lon = value.split(",", 1)
    return lat.strip(), lon.strip()


def row_match_id(row: List[str]) -> str:
    return row[7] if len(row) > 7 else ""


def duplicate_preference_rank(row: List[str]) -> int:
    # Lägre värde = bättre rad att behålla.
    # Om samma MatchId finns med flera Serie_Match_AssId behåller vi AssId 1.
    return 0 if row and row[0] == "1" else 1



def write_unsafe_mapping(unsafe_handle, row: List[str], reason: str) -> None:
    if unsafe_handle is None:
        return

    # Intern 22-kolumners rad:
    # 1 Datum index 1, 7 MatchId index 7, 10 Hemmalag index 10,
    # 12 HemmalagAssId index 12, 17 ArenaNamn/location index 17,
    # 18 ArenaKluster index 18, 19 koordinater index 19, 20 adress index 20.
    padded = list(row) + [""] * (22 - len(row))
    fields = [
        padded[1],
        padded[7],
        padded[10],
        padded[12],
        padded[17],
        padded[18],
        padded[19],
        padded[20],
        str(reason or "").replace(";", ","),
    ]
    unsafe_handle.write(";".join(fields) + "\n")


def generate_new_csv_rows(
    cfg,
    dates: Sequence[str],
    association_ids: Sequence[str],
    cluster_file: Path,
    error_file: Path,
    unsafe_mapping_file: Optional[Path] = None,
    get_module=None,
    csv_module=None,
    debug: bool = False,
) -> Tuple[List[List[str]], Dict[str, int]]:
    clusters, alias_to_indexes, home_team_to_indexes = cfg.read_clusters(cluster_file, debug=debug)

    error_file.parent.mkdir(parents=True, exist_ok=True)

    total_games = 0
    mapped_safe = 0
    mapped_unsafe = 0
    errors = 0
    duplicate_games = 0
    fetched_calls = 0

    output_rows_by_match_id: Dict[str, List[str]] = {}

    unsafe_handle = None

    if unsafe_mapping_file:
        unsafe_mapping_file.parent.mkdir(parents=True, exist_ok=True)
        unsafe_handle = unsafe_mapping_file.open("w", encoding="utf-8")
        unsafe_handle.write("Datum;MatchId;Hemmalag;HemmalagAssId;Location;ArenaKluster;ArenaKlusterKoordinater;ArenaKlusterAdress;Reason\n")

    try:
        err = error_file.open("w", encoding="utf-8")
        try:
            for line_number, source_date, source_ass_id, json_text in iter_raw_fetch_lines(dates, association_ids, get_module=get_module, debug=debug):
                fetched_calls += 1

                if json_text.startswith("ERROR:"):
                    errors += 1
                    err.write(f"{line_number};{source_date};{source_ass_id};;;;;;;;;{cfg.safe_text(json_text)}\n")
                    debug_print(debug, f"Rad {line_number}: {json_text}")
                    continue

                objects = list(cfg.iter_json_objects(json_text))

                if not objects:
                    errors += 1
                    err.write(f"{line_number};{source_date};{source_ass_id};;;;;;;;;INVALID_JSON_OR_EMPTY_RESPONSE\n")
                    debug_print(debug, f"Rad {line_number}: ingen JSON kunde läsas")
                    continue

                for obj in objects:
                    for competition in cfg.iter_competitions(obj):
                        games = competition.get("games", [])
                        if not isinstance(games, list):
                            continue

                        for game in games:
                            if not isinstance(game, dict):
                                continue

                            skip_game, skip_reason = cfg.should_skip_game(game)
                            if skip_game:
                                errors += 1
                                debug_print(debug, f"Hoppar över match gameId={cfg.safe_text(game.get('gameId'))}: {skip_reason}")
                                cfg.write_error(err, line_number, source_date, source_ass_id, competition, game, skip_reason)
                                continue

                            total_games += 1
                            cluster, safe_mapping, reason = cfg.map_game_to_cluster(
                                game,
                                clusters,
                                alias_to_indexes,
                                home_team_to_indexes,
                                debug=debug,
                            )

                            internal_row = cfg.game_to_output_row(source_ass_id, competition, game, cluster, safe_mapping)
                            match_id = row_match_id(internal_row)

                            if match_id in output_rows_by_match_id:
                                duplicate_games += 1
                                existing_row = output_rows_by_match_id[match_id]

                                if duplicate_preference_rank(internal_row) < duplicate_preference_rank(existing_row):
                                    debug_print(
                                        debug,
                                        f"Ersätter duplikat MatchId={match_id}: "
                                        f"Serie_Match_AssId {existing_row[0]} -> {internal_row[0]}",
                                    )
                                    output_rows_by_match_id[match_id] = internal_row
                                else:
                                    debug_print(
                                        debug,
                                        f"Hoppar över duplikat MatchId={match_id}: "
                                        f"Serie_Match_AssId {internal_row[0]} behålls ej",
                                    )
                                continue

                            output_rows_by_match_id[match_id] = internal_row

                            if cluster is None:
                                errors += 1
                                cfg.write_error(err, line_number, source_date, source_ass_id, competition, game, reason)
                            elif safe_mapping == "Y":
                                mapped_safe += 1
                            else:
                                mapped_unsafe += 1
                                cfg.write_error(err, line_number, source_date, source_ass_id, competition, game, reason)

        finally:
            err.close()
    finally:
        if unsafe_handle:
            unsafe_handle.close()

    csv_rows = [output_row_to_csv_row(row, csv_module=csv_module) for row in output_rows_by_match_id.values()]

    stats = {
        "fetched_calls": fetched_calls,
        "total_games_before_dedupe": total_games,
        "duplicate_games": duplicate_games,
        "new_games_after_dedupe": len(csv_rows),
        "mapped_safe": mapped_safe,
        "mapped_unsafe": mapped_unsafe,
        "errors": errors,
    }

    return csv_rows, stats


def read_existing_csv(path: Path) -> Tuple[List[str], List[List[str]]]:
    if not path.exists():
        return CSV_HEADER, []

    csv.field_size_limit(10**9)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        rows = list(reader)

    if not rows:
        return CSV_HEADER, []

    header = rows[0]
    data = rows[1:]

    if header != CSV_HEADER:
        # Behåll existerande header om den åtminstone har Datum och MatchId.
        # Men varna tydligt, eftersom frontend förväntar sig CSV_HEADER.
        print("VARNING: Befintlig CSV-header avviker från förväntad header.", file=sys.stderr)

    return header, data


def write_csv(path: Path, header: List[str], rows: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def date_index(header: List[str]) -> int:
    try:
        return header.index("Datum")
    except ValueError:
        # Fallback enligt football_games.csv-formatet.
        return 1


def match_id_index(header: List[str]) -> int:
    try:
        return header.index("MatchId")
    except ValueError:
        return 7


def merge_replace_dates(
    existing_rows: List[List[str]],
    new_rows: List[List[str]],
    replaced_dates: Set[str],
    header: List[str],
    debug: bool = False,
) -> Tuple[List[List[str]], Dict[str, int]]:
    d_idx = date_index(header)
    m_idx = match_id_index(header)

    kept_rows: List[List[str]] = []
    removed_existing = 0

    for row in existing_rows:
        row_date = row[d_idx].strip() if len(row) > d_idx else ""
        if row_date in replaced_dates:
            removed_existing += 1
        else:
            kept_rows.append(row)

    merged = kept_rows + new_rows

    # Deduplicera hela slutresultatet på MatchId, med AssId 1 som prioritet.
    by_match_id: Dict[str, List[str]] = {}
    no_match_id_rows: List[List[str]] = []
    duplicate_final = 0

    for row in merged:
        match_id = row[m_idx].strip() if len(row) > m_idx else ""
        if not match_id:
            no_match_id_rows.append(row)
            continue

        if match_id in by_match_id:
            duplicate_final += 1
            if duplicate_preference_rank(row) < duplicate_preference_rank(by_match_id[match_id]):
                by_match_id[match_id] = row
        else:
            by_match_id[match_id] = row

    result = list(by_match_id.values()) + no_match_id_rows

    # Sortera stabilt på datum, tid, arena, matchId.
    def sort_key(row: List[str]) -> Tuple[str, str, str, str]:
        datum = row[1] if len(row) > 1 else ""
        tid = row[2] if len(row) > 2 else ""
        arena = row[18] if len(row) > 18 else ""
        match_id = row[7] if len(row) > 7 else ""
        return datum, tid, arena, match_id

    result.sort(key=sort_key)

    debug_print(debug, f"Tog bort {removed_existing} befintliga rader för datum: {','.join(sorted(replaced_dates))}")
    debug_print(debug, f"Deduplicerade {duplicate_final} dubbletter i slutresultatet")

    stats = {
        "existing_rows_before": len(existing_rows),
        "existing_rows_removed_for_dates": removed_existing,
        "final_duplicate_rows_removed": duplicate_final,
        "final_rows": len(result),
    }

    return result, stats




def run_fetch_raw(args: argparse.Namespace, get_module=None) -> int:
    output_path = Path(args.of)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for _line_number, date_text, association_id, json_text in iter_raw_fetch_lines(
            args.dl,
            args.ail,
            get_module=get_module,
            debug=args.dbg,
        ):
            handle.write(f"{date_text};{association_id};{json_text}\n")

    print(f"Skapade {output_path}", file=sys.stderr)
    return 0


def run_map_games(args: argparse.Namespace, cfg) -> int:
    input_games = Path(args.input_games)
    input_klusters = Path(args.ik)
    output_games = Path(args.output_games)
    error_file = Path(args.ef)

    if not input_games.exists():
        print(f"Fel: input games saknas: {input_games}", file=sys.stderr)
        return 2

    if not input_klusters.exists():
        print(f"Fel: input klusters saknas: {input_klusters}", file=sys.stderr)
        return 2

    if hasattr(cfg, "process"):
        return int(cfg.process(input_games, input_klusters, output_games, error_file, debug=args.dbg))

    print("Fel: mappningsmodulen saknar process(...)", file=sys.stderr)
    return 2


def run_make_csv(args: argparse.Namespace, csv_module=None) -> int:
    input_path = Path(args.i)
    output_path = Path(args.o)

    if not input_path.exists():
        print(f"Fel: input saknas: {input_path}", file=sys.stderr)
        return 2

    rows: List[List[str]] = []
    csv.field_size_limit(10**9)

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        for row in reader:
            if not row:
                continue
            rows.append(output_row_to_csv_row(row, csv_module=csv_module))

    write_csv(output_path, CSV_HEADER, rows)
    print(f"Skapade {output_path}", file=sys.stderr)
    print(f"Antal rader: {len(rows)}", file=sys.stderr)
    return 0



def write_unsafe_mappings_from_csv_rows(path: Path, rows: List[List[str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with path.open("w", encoding="utf-8") as handle:
        handle.write("Datum;MatchId;Hemmalag;HemmalagAssId;Location;ArenaKluster;ArenaKlusterKoordinater;ArenaKlusterAdress;Reason\n")

        for row in rows:
            # CSV_HEADER:
            # Datum 1, MatchId 7, Hemmalag 10, HemmalagAssId 12,
            # ArenaNamn 17, ArenaKluster 18, ArenaKlusterAdress 19,
            # SäkerMapping 20, LS_Lat 21, LS_Long 22
            row = row + [""] * (25 - len(row))
            if row[20] != "N":
                continue

            coord = ""
            if row[21] or row[22]:
                coord = f"{row[21]}, {row[22]}".strip(", ")

            fields = [
                row[1],
                row[7],
                row[10],
                row[12],
                row[17],
                row[18],
                coord,
                row[19],
                "UNSAFE_MAPPING_IN_OUTPUT_CSV",
            ]
            handle.write(";".join(safe_semicolon(value) for value in fields) + "\n")
            count += 1

    return count



def looks_like_cluster_ass_id(value: str) -> bool:
    value = str(value or "").strip()

    if value == "0" or value.isdigit() or value.startswith("CONFLICT:"):
        return True

    parts = [part.strip() for part in value.split(",") if part.strip()]
    return bool(parts) and all(part.isdigit() for part in parts)


def split_cluster_master_row(row: List[str]) -> List[str]:
    """
    Returnerar:
      AssId;ArenaKluster;Koordinater;Adress;Planer;Hemmalag

    Stödjer både nytt format:
      assId;klusternamn;koordinater;adress;planer;hemmalag

    och äldre format:
      klusternamn;koordinater;adress;planer;hemmalag
    """
    row = [str(item or "").strip() for item in row]

    if not row:
        return []

    if looks_like_cluster_ass_id(row[0]):
        row += [""] * (6 - len(row))
        return [row[0], row[1], row[2], row[3], row[4], row[5]]

    row += [""] * (5 - len(row))
    return ["0", row[0], row[1], row[2], row[3], row[4]]


def generate_football_clusters_enhanced_csv(cluster_file: Path, output_file: Path) -> int:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0

    with cluster_file.open("r", encoding="utf-8-sig") as inp, output_file.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter=";")
        writer.writerow(["AssId", "ArenaKluster", "Koordinater", "Adress", "Planer", "Hemmalag"])

        for raw_line in inp:
            line = raw_line.rstrip("\n")
            if not line or line.lstrip().startswith("#"):
                continue

            row = line.split(";")
            normalized = split_cluster_master_row(row)

            if not normalized:
                continue

            # Kräv åtminstone klusternamn och koordinater för frontend/settings.
            if not normalized[1] or not normalized[2]:
                continue

            writer.writerow(normalized)
            rows_written += 1

    return rows_written



def today_iso() -> str:
    return date.today().isoformat()


def iso_date_add_days(date_text: str, days: int) -> str:
    return (parse_date(date_text) + timedelta(days=days)).isoformat()


def read_state_file(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state_file(path: Path, state: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def resolve_dates_from_state(args: argparse.Namespace) -> Tuple[List[str], Dict[str, object], str, str]:
    """
    Returnerar:
      dates, state, run_mode, today

    Utan -state:
      -dl används exakt som angivet.

    Med -state:
      första körningen idag -> FULL_WINDOW_REFRESH, använd -dl om angivet,
                               annars idag-3 till idag+8.
      senare körningar idag -> TODAY_ONLY_REFRESH, endast idag.
    """
    today = today_iso()

    if not args.state:
        return args.dl, {}, "MANUAL_DATE_LIST", today

    state_path = Path(args.state)
    state = read_state_file(state_path)

    if state.get("last_full_refresh_date") != today:
        if args.dl:
            return args.dl, state, "FULL_WINDOW_REFRESH", today

        start = iso_date_add_days(today, -3)
        end = iso_date_add_days(today, 8)
        dates = parse_date_list(f"{start}-{end}")
        return dates, state, "FULL_WINDOW_REFRESH", today

    return [today], state, "TODAY_ONLY_REFRESH", today


def append_rows_to_old_csv(old_csv: Path, header: List[str], rows_to_move: List[List[str]]) -> int:
    if not rows_to_move:
        if not old_csv.exists():
            write_csv(old_csv, header, [])
        return 0

    old_header, old_rows = read_existing_csv(old_csv)

    # Om old-filen är tom eller saknar korrekt header, använd aktuell header.
    if not old_rows and old_header != header:
        old_header = header

    m_idx = match_id_index(header)
    existing_ids = {
        row[m_idx].strip()
        for row in old_rows
        if len(row) > m_idx and row[m_idx].strip()
    }

    added = 0
    for row in rows_to_move:
        match_id = row[m_idx].strip() if len(row) > m_idx else ""
        if match_id and match_id in existing_ids:
            continue
        old_rows.append(row)
        if match_id:
            existing_ids.add(match_id)
        added += 1

    def sort_key(row: List[str]) -> Tuple[str, str, str, str]:
        datum = row[1] if len(row) > 1 else ""
        tid = row[2] if len(row) > 2 else ""
        arena = row[18] if len(row) > 18 else ""
        match_id = row[7] if len(row) > 7 else ""
        return datum, tid, arena, match_id

    old_rows.sort(key=sort_key)
    write_csv(old_csv, old_header, old_rows)
    return added


def move_old_games_once_per_day(
    header: List[str],
    existing_rows: List[List[str]],
    old_csv: Path,
    cutoff_date: str,
    state: Dict[str, object],
    today: str,
    debug: bool = False,
) -> Tuple[List[List[str]], int, int]:
    """
    Flyttar matcher med Datum <= cutoff_date från current till old högst en gång per dag.
    Returnerar:
      kept_rows, moved_to_old, removed_from_current
    """
    if state.get("last_old_move_date") == today:
        debug_print(debug, f"Old-move redan gjord idag ({today}), hoppar över")
        return existing_rows, 0, 0

    d_idx = date_index(header)

    rows_to_move: List[List[str]] = []
    kept_rows: List[List[str]] = []

    for row in existing_rows:
        row_date = row[d_idx].strip() if len(row) > d_idx else ""
        if row_date and row_date <= cutoff_date:
            rows_to_move.append(row)
        else:
            kept_rows.append(row)

    moved = append_rows_to_old_csv(old_csv, header, rows_to_move)
    state["last_old_move_date"] = today
    state["last_old_move_cutoff_date"] = cutoff_date

    debug_print(debug, f"Flyttade {moved} rader till old-fil {old_csv}; cutoff={cutoff_date}")
    return kept_rows, moved, len(rows_to_move)


def run_update_csv(args: argparse.Namespace, cfg, get_module=None, csv_module=None) -> int:
    input_csv = Path(args.io or args.i)
    output_csv = Path(args.io or args.o)
    cluster_file = Path(args.ik)
    error_file = Path(args.ef)

    update_dates, state_data, run_mode, today_text = resolve_dates_from_state(args)

    if not cluster_file.exists():
        print(f"Fel: klusterfilen finns inte: {cluster_file}", file=sys.stderr)
        return 2

    debug_print(args.dbg, f"Run mode: {run_mode}")
    debug_print(args.dbg, f"Datum som uppdateras: {update_dates}")
    debug_print(args.dbg, f"AssociationId: {args.ail}")
    debug_print(args.dbg, f"Input CSV: {input_csv}")
    debug_print(args.dbg, f"Output CSV: {output_csv}")

    header, existing_rows = read_existing_csv(input_csv)

    moved_to_old = 0
    removed_for_old = 0

    if args.state and args.old and run_mode == "FULL_WINDOW_REFRESH":
        cutoff_date = iso_date_add_days(today_text, -3)
        existing_rows, moved_to_old, removed_for_old = move_old_games_once_per_day(
            header=header,
            existing_rows=existing_rows,
            old_csv=Path(args.old),
            cutoff_date=cutoff_date,
            state=state_data,
            today=today_text,
            debug=args.dbg,
        )

    new_rows, new_stats = generate_new_csv_rows(
        cfg=cfg,
        dates=update_dates,
        association_ids=args.ail,
        cluster_file=cluster_file,
        error_file=error_file,
        unsafe_mapping_file=Path(args.umf) if args.umf else None,
        get_module=get_module,
        csv_module=csv_module,
        debug=args.dbg,
    )

    if args.umf:
        unsafe_written = write_unsafe_mappings_from_csv_rows(Path(args.umf), new_rows)
        debug_print(args.dbg, f"Skrev {unsafe_written} osäkra/gissade mappningar till {args.umf}")

    final_rows, merge_stats = merge_replace_dates(
        existing_rows=existing_rows,
        new_rows=new_rows,
        replaced_dates=set(update_dates),
        header=header,
        debug=args.dbg,
    )

    write_csv(output_csv, header, final_rows)

    enhanced_clusters_csv = Path(args.ecsv) if args.ecsv else cluster_file.parent / "FootballClustersEnhanced.csv"
    enhanced_cluster_rows = generate_football_clusters_enhanced_csv(cluster_file, enhanced_clusters_csv)

    print(f"Skapade/uppdaterade {output_csv}", file=sys.stderr)
    print(f"Skapade/uppdaterade {enhanced_clusters_csv} ({enhanced_cluster_rows} kluster)", file=sys.stderr)
    print(f"Skapade {error_file}", file=sys.stderr)
    if args.umf:
        print(f"Skapade {args.umf}", file=sys.stderr)
    print(f"Antal API-anrop: {new_stats['fetched_calls']}", file=sys.stderr)
    print(f"Nya matcher före deduplicering: {new_stats['total_games_before_dedupe']}", file=sys.stderr)
    print(f"Nya duplikat borttagna: {new_stats['duplicate_games']}", file=sys.stderr)
    print(f"Nya matcher efter deduplicering: {new_stats['new_games_after_dedupe']}", file=sys.stderr)
    print(f"Befintliga rader före uppdatering: {merge_stats['existing_rows_before']}", file=sys.stderr)
    if args.state and args.old:
        print(f"Old-fil: {args.old}", file=sys.stderr)
        print(f"Rader flyttade till old-fil: {moved_to_old}", file=sys.stderr)
        print(f"Rader borttagna från current pga old-flytt: {removed_for_old}", file=sys.stderr)
    print(f"Befintliga rader borttagna för uppdaterade datum: {merge_stats['existing_rows_removed_for_dates']}", file=sys.stderr)
    print(f"Slutligt antal rader: {merge_stats['final_rows']}", file=sys.stderr)
    print(f"Säkra klustermappningar: {new_stats['mapped_safe']}", file=sys.stderr)
    print(f"Osäkra/gissade klustermappningar: {new_stats['mapped_unsafe']}", file=sys.stderr)
    print(f"Fel/omappade/skip: {new_stats['errors']}", file=sys.stderr)

    if args.state:
        state_path = Path(args.state)
        if run_mode == "FULL_WINDOW_REFRESH":
            state_data["last_full_refresh_date"] = today_text
        state_data["last_run_date"] = today_text
        state_data["last_run_mode"] = run_mode
        state_data["last_run_timestamp"] = datetime.now().isoformat(timespec="seconds")
        state_data["last_window_start"] = update_dates[0] if update_dates else ""
        state_data["last_window_end"] = update_dates[-1] if update_dates else ""

        if state_data.get("runs_today_date") == today_text:
            try:
                state_data["runs_today"] = int(state_data.get("runs_today", 0)) + 1
            except Exception:
                state_data["runs_today"] = 1
        else:
            state_data["runs_today_date"] = today_text
            state_data["runs_today"] = 1

        write_state_file(state_path, state_data)
        print(f"Uppdaterade statefil: {state_path}", file=sys.stderr)

    return 0


def run_enhance_clusters(args: argparse.Namespace) -> int:
    module, module_path = load_enhance_clusters_module()

    if module is None or module_path is None:
        print("Fel: kunde inte hitta enhanceFotballArenaClusterWithHomeTeams.py eller _v8.py", file=sys.stderr)
        return 2

    required = [
        "split_home_team_paths",
        "read_home_team_rows_from_files",
        "merge_home_team_rows",
        "write_home_team_rows",
        "read_clusters",
        "enhance_clusters",
        "write_clusters",
    ]
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        print(f"Fel: enhance-modulen {module_path} saknar: {', '.join(missing)}", file=sys.stderr)
        return 2

    cluster_path = Path(args.cluster_file)
    home_team_paths = module.split_home_team_paths(args.home_team_file)
    output_path = Path(args.of)
    output_team_path = Path(args.output_team_file) if args.output_team_file else None

    if not cluster_path.exists():
        print(f"Fel: klusterfilen finns inte: {cluster_path}", file=sys.stderr)
        return 2

    if not home_team_paths:
        print("Fel: ingen hemmalagsfil angiven med -hf", file=sys.stderr)
        return 2

    try:
        raw_home_team_rows = module.read_home_team_rows_from_files(home_team_paths)
    except FileNotFoundError:
        return 2

    home_team_rows = module.merge_home_team_rows(raw_home_team_rows)

    if output_team_path:
        module.write_home_team_rows(output_team_path, home_team_rows)
        print(f"Skapade mergad hemmalagsfil: {output_team_path}", file=sys.stderr)

    clusters, alias_to_cluster_indexes = module.read_clusters(cluster_path)

    enhanced_clusters, matched_rows, duplicate_rows, unmatched_rows = module.enhance_clusters(
        clusters,
        alias_to_cluster_indexes,
        home_team_rows,
    )

    module.write_clusters(output_path, enhanced_clusters)

    if args.update_cluster_file:
        module.write_clusters(cluster_path, enhanced_clusters)
        print(f"Uppdaterade även klusterfilen: {cluster_path}", file=sys.stderr)

    print(f"Använder enhance-modul: {module_path}", file=sys.stderr)
    print(f"Skapade {output_path}", file=sys.stderr)
    print(f"Antal kluster: {len(clusters)}", file=sys.stderr)
    print(f"Antal hemmalagsfiler: {len(home_team_paths)}", file=sys.stderr)
    print(f"Antal hemmalagsrader före merge: {len(raw_home_team_rows)}", file=sys.stderr)
    print(f"Antal hemmalagsrader efter merge: {len(home_team_rows)}", file=sys.stderr)
    print(f"Matchade entydigt: {matched_rows}", file=sys.stderr)
    print(f"Matchade flera kluster, DUP: {duplicate_rows}", file=sys.stderr)
    print(f"Saknade klusterträff: {unmatched_rows}", file=sys.stderr)

    return 0



def safe_semicolon(value: object) -> str:
    return str(value or "").replace(";", ",").strip()


def add_count(counter: Dict[Tuple[str, ...], int], key: Tuple[str, ...], amount: int = 1) -> None:
    counter[key] = counter.get(key, 0) + amount


def read_semicolon_rows(path: Path) -> List[List[str]]:
    if not path.exists():
        return []

    csv.field_size_limit(10**9)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        return [row for row in reader if row]


def read_cluster_names(path: Path) -> Set[str]:
    names: Set[str] = set()

    if not path.exists():
        return names

    with path.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line:
                continue

            parts = line.split(";")
            if len(parts) >= 2 and (
                parts[0].isdigit()
                or parts[0] == "0"
                or parts[0].startswith("CONFLICT:")
                or "," in parts[0]
            ):
                names.add(parts[1].strip())
            elif parts:
                names.add(parts[0].strip())

    return {name for name in names if name}


def reason_is_normal_skip(reason: str) -> bool:
    reason = str(reason or "")
    normal_prefixes = (
        "SKIP_EMPTY_LOCATION",
        "SKIP_EMPTY_DATE",
        "SKIP_EMPTY_TIME",
        "SKIP_HOME_TEAM_STA_OVER",
        "SKIP_AWAY_TEAM_STA_OVER",
        "SKIP_HOME_ASS_ID_0",
        "SKIP_AWAY_ASS_ID_0",
        "SKIP_HOME_ASS_ID_NOT_ALLOWED_",
    )
    return reason.startswith(normal_prefixes)


def write_proposed_updates(path: Path, unsafe_rows: List[List[str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    home_team_counter: Dict[Tuple[str, str], int] = {}
    home_team_locations: Dict[Tuple[str, str], Set[str]] = {}
    plan_counter: Dict[Tuple[str, str], int] = {}
    plan_home_teams: Dict[Tuple[str, str], Set[str]] = {}

    for row in unsafe_rows:
        if row and row[0] == "Datum":
            continue

        row = row + [""] * (9 - len(row))
        _datum, _match_id, home_team, _home_ass_id, location, cluster, _coord, _address, _reason = row[:9]

        if not cluster:
            continue

        if home_team:
            key = (cluster, f"1,{home_team}")
            add_count(home_team_counter, key)
            home_team_locations.setdefault(key, set()).add(location)

        if location:
            key = (cluster, location)
            add_count(plan_counter, key)
            if home_team:
                plan_home_teams.setdefault(key, set()).add(home_team)

    lines: List[str] = [
        "# Förslag baserade på osäkra/gissade mappningar (-umf).",
        "# Granska manuellt innan FootballFieldsCluster.txt ändras.",
        "# Format:",
        "# UPDATE_HOME_TEAM;Kluster;ADD_HOME_TEAM;antal,lagnamn;matches=N;locations=...",
        "# UPDATE_PLAN;Kluster;ADD_PLAN;location;matches=N;homeTeams=...",
        "",
    ]

    for (cluster, home_entry), count in sorted(home_team_counter.items(), key=lambda item: (item[0][0].casefold(), item[0][1].casefold())):
        locations = "|".join(sorted(home_team_locations.get((cluster, home_entry), set())))
        lines.append(
            f"UPDATE_HOME_TEAM;{safe_semicolon(cluster)};ADD_HOME_TEAM;{safe_semicolon(home_entry)};"
            f"matches={count};locations={safe_semicolon(locations)}"
        )

    if home_team_counter:
        lines.append("")

    for (cluster, location), count in sorted(plan_counter.items(), key=lambda item: (item[0][0].casefold(), item[0][1].casefold())):
        home_teams = "|".join(sorted(plan_home_teams.get((cluster, location), set())))
        lines.append(
            f"UPDATE_PLAN;{safe_semicolon(cluster)};ADD_PLAN;{safe_semicolon(location)};"
            f"matches={count};homeTeams={safe_semicolon(home_teams)}"
        )

    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    return len(home_team_counter) + len(plan_counter)



def looks_like_postcode(value: str) -> bool:
    return bool(re.fullmatch(r"\d{3}\s?\d{2}", str(value or "").strip()))


def normalize_postcode(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace(" ", "")
    if len(value) == 5 and value.isdigit():
        return value[:3] + " " + value[3:]
    return value


def simplify_swedish_address(value: str) -> str:
    """
    Gör OSM/Nominatim-liknande display_name mer LocalSport-vänlig.

    Ex:
      AIK-vallen, Solhagavägen, Arvidstorp, Falkenberg,
      Falkenbergs kommun, Hallands län, 311 39, Sverige

    blir ungefär:
      Solhagavägen, 311 39 Falkenberg

    Om husnummer finns i display_name, t.ex. "Solhagavägen 32" eller
    separat "32", används det. Scriptet hittar däremot inte på husnummer.
    """
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]

    if not parts:
        return ""

    blacklist_words = ("kommun", "län", "sverige")
    useful = [
        part for part in parts
        if not any(word in part.casefold() for word in blacklist_words)
    ]

    postcode = ""
    city = ""
    road = ""

    for part in useful:
        if looks_like_postcode(part):
            postcode = normalize_postcode(part)
            continue

    # City = närmast före kommun/län/postnummer/Sverige, annars sista användbara ortdel.
    for idx, part in enumerate(parts):
        if looks_like_postcode(part) and idx > 0:
            city = parts[idx - 1].strip()
            break

    if not city:
        for part in reversed(useful):
            if not looks_like_postcode(part) and not re.search(r"\b(väg|gatan|gränd|leden|stigen|allén|torget|plan)\b", part, re.I):
                city = part
                break

    # Road = första troliga vägnamn efter eventuell arenanamn.
    for part in useful[1:] if len(useful) > 1 else useful:
        if re.search(r"\b(väg|gatan|gränd|leden|stigen|allén|torget|plan)\b", part, re.I):
            road = part
            break

    if not road and len(useful) >= 2:
        road = useful[1]
    elif not road:
        road = useful[0]

    # Om delarna innehåller separat husnummer direkt efter road, lägg till det.
    try:
        road_idx = parts.index(road)
        if road_idx + 1 < len(parts) and re.fullmatch(r"\d+[A-Za-z]?", parts[road_idx + 1].strip()):
            road = f"{road} {parts[road_idx + 1].strip()}"
    except ValueError:
        pass

    if postcode and city:
        return f"{road}, {postcode} {city}"

    if city and city != road:
        return f"{road}, {city}"

    return road


def extract_coord_guess_from_text(value: str) -> str:
    match = re.search(r"(-?\d{1,2}(?:[.,]\d+)?)\s*,\s*(-?\d{1,3}(?:[.,]\d+)?)", str(value or ""))
    if not match:
        return "0,0"

    lat = match.group(1).replace(",", ".")
    lon = match.group(2).replace(",", ".")

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except ValueError:
        return "0,0"

    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return "0,0"

    return f"{lat_f:.6f}, {lon_f:.6f}"


def write_new_proposed_clusters(path: Path, error_rows: List[List[str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    counter: Dict[Tuple[str, str, str], int] = {}
    away_teams: Dict[Tuple[str, str, str], Set[str]] = {}
    reasons: Dict[Tuple[str, str, str], Set[str]] = {}

    for row in error_rows:
        row = row + [""] * (12 - len(row))
        _source_line, _source_date, _source_ass_id, _competition_id, _competition_name, _game_id, home_team, home_ass_id, away_team, _away_ass_id, location, reason = row[:12]

        if reason_is_normal_skip(reason):
            continue

        if not reason.startswith("NO_CLUSTER_MATCH"):
            continue

        if not location or not home_team:
            continue

        key = (location, home_team, home_ass_id)
        add_count(counter, key)
        if away_team:
            away_teams.setdefault(key, set()).add(away_team)
        if reason:
            reasons.setdefault(key, set()).add(reason)

    lines: List[str] = [
        "# Förslag på nya kluster baserat på NO_CLUSTER_MATCH.",
        "# OBS: koordinater/adress är bara gissningar och måste kontrolleras innan raden läggs in i FootballFieldsCluster.txt.",
        "# Scriptet hittar inte på husnummer. Husnummer finns bara med om det redan finns i input/adresstexten.",
        "# Formatförslag:",
        "# assId;klusternamn;koordinater;adress;planer;hemmalag;metadata",
        "",
    ]

    for (location, home_team, home_ass_id), count in sorted(counter.items(), key=lambda item: (item[0][0].casefold(), item[0][1].casefold())):
        ass_id = home_ass_id if home_ass_id else "0"
        away = "|".join(sorted(away_teams.get((location, home_team, home_ass_id), set())))
        reason_text = "|".join(sorted(reasons.get((location, home_team, home_ass_id), set())))

        coord_guess = extract_coord_guess_from_text(location)
        address_guess = simplify_swedish_address(location)

        metadata = (
            f"matches={count};homeAssIds={safe_semicolon(home_ass_id)};"
            f"awayTeams={safe_semicolon(away)};reason={safe_semicolon(reason_text)};"
            f"coordGuess={'Y' if coord_guess != '0,0' else 'N'};"
            f"addressGuess={'Y' if address_guess else 'N'}"
        )

        lines.append(
            f"{safe_semicolon(ass_id)};NYTT_KLUSTER_BEHÖVS;{safe_semicolon(coord_guess)};"
            f"{safe_semicolon(address_guess)};{safe_semicolon(location)};"
            f"1,{safe_semicolon(home_team)};{metadata}"
        )

    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    return len(counter)


def write_unmatched_home_teams(path: Path, error_rows: List[List[str]], unsafe_rows: List[List[str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    counter: Dict[Tuple[str, str, str, str], int] = {}

    for row in error_rows:
        row = row + [""] * (12 - len(row))
        _source_line, _source_date, _source_ass_id, _competition_id, _competition_name, _game_id, home_team, home_ass_id, _away_team, _away_ass_id, location, reason = row[:12]

        if reason_is_normal_skip(reason):
            continue

        if reason.startswith(("NO_CLUSTER_MATCH", "NO_CLUSTER_WITH_HOME_ASS_ID", "AMBIGUOUS_EXPLICIT_MATCH", "AMBIGUOUS_IMPLICIT_WEAK_MATCH")):
            add_count(counter, (home_team, home_ass_id, location, reason))

    for row in unsafe_rows:
        if row and row[0] == "Datum":
            continue
        row = row + [""] * (9 - len(row))
        _datum, _match_id, home_team, home_ass_id, location, cluster, _coord, _address, reason = row[:9]
        if reason:
            add_count(counter, (home_team, home_ass_id, location, f"UNSAFE:{cluster}:{reason}"))

    lines = ["Hemmalag;HemmalagAssId;Location;Reason;Antal"]

    for (home_team, home_ass_id, location, reason), count in sorted(counter.items(), key=lambda item: (-item[1], item[0][0].casefold(), item[0][2].casefold())):
        lines.append(
            f"{safe_semicolon(home_team)};{safe_semicolon(home_ass_id)};{safe_semicolon(location)};{safe_semicolon(reason)};{count}"
        )

    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    return len(counter)


def run_analyze_mapping(args: argparse.Namespace) -> int:
    error_file = Path(args.ef)
    unsafe_file = Path(args.umf)
    cluster_file = Path(args.ik)

    if not error_file.exists():
        print(f"Fel: errorfil saknas: {error_file}", file=sys.stderr)
        return 2

    if not unsafe_file.exists():
        print(f"Fel: unsafe mapping-fil saknas: {unsafe_file}", file=sys.stderr)
        return 2

    if not cluster_file.exists():
        print(f"Fel: klusterfil saknas: {cluster_file}", file=sys.stderr)
        return 2

    error_rows = read_semicolon_rows(error_file)
    unsafe_rows = read_semicolon_rows(unsafe_file)
    cluster_names = read_cluster_names(cluster_file)

    proposed_count = write_proposed_updates(Path(args.puf), unsafe_rows)
    new_cluster_count = write_new_proposed_clusters(Path(args.npc), error_rows)
    unmatched_count = write_unmatched_home_teams(Path(args.uht), error_rows, unsafe_rows)

    print(f"Läste kluster: {len(cluster_names)} från {cluster_file}", file=sys.stderr)
    print(f"Läste errorrader: {len(error_rows)} från {error_file}", file=sys.stderr)
    print(f"Läste unsafe mapping-rader: {max(0, len(unsafe_rows) - 1)} från {unsafe_file}", file=sys.stderr)
    print(f"Skapade {args.puf} ({proposed_count} förslag)", file=sys.stderr)
    print(f"Skapade {args.npc} ({new_cluster_count} föreslagna nya kluster)", file=sys.stderr)
    print(f"Skapade {args.uht} ({unmatched_count} sammanfattade kontrollrader)", file=sys.stderr)

    return 0


def series_gender_from(name: str, gender_id: str) -> str:
    n = str(name or "").casefold()
    if gender_id == "2":
        return "Herr"
    if gender_id == "3":
        return "Dam"
    if re.search(r"\bdam|damer|flick|f\d|f[0-9]", n):
        return "Dam"
    if re.search(r"\bherr|herrar|pojk|p\d|p[0-9]", n):
        return "Herr"
    return "Mix"


def series_category_from(name: str, age_id: str) -> str:
    n = str(name or "").casefold()
    if "träning" in n or "träningsmatch" in n:
        return "Övrigt"
    if "motion" in n or "7m7" in n:
        return "Motion"
    if age_id == "4":
        return "Senior"
    if age_id == "5":
        return "Motion"
    if re.search(r"\b(p|f)\s?(16|17|18|19)\b", n) or "junior" in n or "p15-19" in n or "f15-19" in n:
        return "Junior"
    if re.search(r"\b(p|f)\s?(13|14|15)\b", n) or "13-14" in n or "15-16" in n or "16-17" in n:
        return "Ungdom"
    if age_id == "3":
        return "Ungdom"
    if age_id == "2":
        return "Barn"
    return "Övrigt"


def series_level_from(name: str, ass_id: str, category: str) -> str:
    n = str(name or "").casefold()
    if ass_id == "1":
        return "Nationell"
    if category == "Övrigt" and "träningsmatch" not in n:
        return "Övrigt"
    if "regional" in n:
        return "Regional"
    if "dm" in n or "cup" in n:
        return "Regional"
    return "Regional"


def series_rank_for(name: str, gender: str, category: str, level: str, ass_id: str) -> int:
    n = str(name or "").casefold()

    if re.match(r"^allsvenskan\b", n):
        return 1000
    if "svenska cupen" in n and gender == "Herr":
        return 975
    if "obos damallsvenskan" in n or re.match(r"^damallsvenskan\b", n):
        return 950
    if re.match(r"^superettan\b", n):
        return 950
    if "svenska cupen" in n and gender == "Dam":
        return 925
    if re.match(r"^ettan\b", n):
        return 900
    if re.match(r"^elitettan\b", n):
        return 900

    # Nationella träningsmatcher ska följa principen Nationell > Regional.
    if "träningsmatch" in n or "träningsmatcher" in n:
        if ass_id == "1":
            if "elit" in n:
                return 695
            if "div. 1" in n or "div 1" in n:
                return 685
            return 680
        if "elit" in n:
            return 180
        if "div. 1" in n or "div 1" in n:
            return 160
        return 100

    if ass_id == "1" and category == "Senior":
        if re.search(r"\bdiv\.?\s*1\b", n) and gender == "Dam":
            return 850
        if re.search(r"\bdiv\.?\s*2\b", n) and gender == "Herr":
            return 840
        if re.search(r"\bdiv\.?\s*2\b", n) and gender == "Dam":
            return 830
        if re.search(r"\bdiv\.?\s*3\b", n) and gender == "Herr":
            return 820
        if re.search(r"\bdiv\.?\s*3\b", n) and gender == "Dam":
            return 810
        if "ligacupen elit" in n:
            return 600
        return 800

    if ass_id == "1" and category in ("Junior", "Ungdom"):
        if "p19 allsvenskan" in n:
            return 780
        if "f19 allsvenskan" in n:
            return 770
        if "p17 allsvenskan" in n:
            return 760
        if "f17 allsvenskan" in n:
            return 750
        if "p16 allsvenskan" in n:
            return 740
        if "superettan" in n:
            return 730
        if re.search(r"p19.*div\.?\s*1", n):
            return 720
        if re.search(r"f19.*div\.?\s*1", n):
            return 715
        if re.search(r"p17.*div\.?\s*1", n):
            return 710
        if re.search(r"f17.*div\.?\s*1", n):
            return 705
        if re.search(r"p16.*div\.?\s*1", n):
            return 700
        if "ligacupen" in n:
            return 600
        return 690

    if category == "Senior":
        if "dm" in n and gender == "Herr":
            return 620
        if "dm" in n and gender == "Dam":
            return 610
        if "utveckling" in n and gender == "Dam":
            return 450
        if "utveckling" in n and gender == "Herr":
            return 440
        if "reserv elit" in n:
            return 500
        if "reservklass 1" in n:
            return 430
        if "reservklass 2" in n:
            return 420
        if "reservklass 3" in n:
            return 410

        m = re.search(r"\bdiv(?:ision|\.)?\s*([2-9])", n)
        if m:
            div = int(m.group(1))
            base = {2: 740, 3: 700, 4: 660, 5: 620, 6: 580, 7: 540, 8: 500, 9: 460}.get(div, 430)
            if gender == "Dam":
                base -= 10
            return base

        if "nivå 2" in n:
            return 620
        if "nivå 3" in n:
            return 580
        return 550

    if category == "Junior":
        if "dm" in n:
            return 560
        if "regional" in n:
            return 650
        m = re.search(r"\bdiv(?:ision|\.)?\s*([1-9])", n)
        if m:
            div = int(m.group(1))
            return max(430, 620 - (div - 1) * 35)
        return 570

    if category == "Ungdom":
        if "regional" in n:
            return 650
        if "svår" in n:
            return 520
        if "medel" in n:
            return 490
        if "lätt" in n:
            return 460
        m = re.search(r"\bdiv(?:ision|\.)?\s*([1-9]|1[0-9])", n)
        if m:
            div = int(m.group(1))
            return max(250, 520 - (div - 1) * 20)
        if re.search(r"\b(p|f)\s?(16|17|18|19)\b", n):
            return 540
        if re.search(r"\b(p|f)\s?(13|14|15)\b", n):
            return 500
        return 470

    if category == "Barn":
        if "röd" in n:
            return 360
        if "blå" in n:
            return 340
        if "grön" in n:
            return 320
        if "vit" in n:
            return 300
        return 310

    if category == "Motion":
        if gender == "Herr":
            return 240
        if gender == "Dam":
            return 230
        return 220

    return 100


def collect_series_from_games_csv(path: Path, counter: Dict[Tuple[str, str, str, str], int]) -> None:
    if not path.exists():
        return

    csv.field_size_limit(10**9)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            name = (row.get("SerieNamn") or "").strip()
            gender_id = (row.get("SerieKönId") or "").strip()
            age_id = (row.get("ÅldersKatId") or "").strip()
            ass_id = (row.get("Serie_Match_AssId") or "").strip()

            if not name or name == "SerieNamn":
                continue

            key = (name, gender_id, age_id, ass_id)
            counter[key] = counter.get(key, 0) + 1



def read_existing_series_ranking(path: Path) -> Dict[Tuple[str, str, str, str], Dict[str, str]]:
    if not path.exists():
        return {}

    csv.field_size_limit(10**9)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        result: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}

        for row in reader:
            name = (row.get("SeriePattern") or "").strip()
            gender_id = (row.get("SerieKönId") or "").strip()
            age_id = (row.get("ÅldersKatId") or "").strip()
            ass_id = (row.get("Serie_Match_AssId") or "").strip()

            if not name:
                continue

            result[(name, gender_id, age_id, ass_id)] = {k: str(v or "") for k, v in row.items()}

        return result


def print_series_ranking_diff(
    old_rows: Dict[Tuple[str, str, str, str], Dict[str, str]],
    new_rows: List[Dict[str, object]],
) -> None:
    new_by_key: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}

    for row in new_rows:
        key = (
            str(row.get("SeriePattern", "")),
            str(row.get("SerieKönId", "")),
            str(row.get("ÅldersKatId", "")),
            str(row.get("Serie_Match_AssId", "")),
        )
        new_by_key[key] = {k: str(v or "") for k, v in row.items()}

    old_keys = set(old_rows)
    new_keys = set(new_by_key)

    added = sorted(new_keys - old_keys, key=lambda key: key[0].casefold())
    removed = sorted(old_keys - new_keys, key=lambda key: key[0].casefold())

    changed: List[Tuple[Tuple[str, str, str, str], Dict[str, str], Dict[str, str], List[str]]] = []

    compare_fields = ["Rank", "Kategori", "Kön", "Nivå", "MatchCount"]

    for key in sorted(old_keys & new_keys, key=lambda key: key[0].casefold()):
        old = old_rows[key]
        new = new_by_key[key]
        changed_fields = [
            field for field in compare_fields
            if str(old.get(field, "")) != str(new.get(field, ""))
        ]

        if changed_fields:
            changed.append((key, old, new, changed_fields))

    unchanged = len(old_keys & new_keys) - len(changed)

    print("DEBUG: FootballSeriesRanking diff", file=sys.stderr)
    print(f"DEBUG:   Nya serier: {len(added)}", file=sys.stderr)
    print(f"DEBUG:   Borttagna serier: {len(removed)}", file=sys.stderr)
    print(f"DEBUG:   Ändrade serier: {len(changed)}", file=sys.stderr)
    print(f"DEBUG:   Oförändrade serier: {unchanged}", file=sys.stderr)

    if added:
        print("DEBUG: Nya serier:", file=sys.stderr)
        for key in added[:100]:
            print(f"DEBUG:   + {key[0]} [{key[1]};{key[2]};{key[3]}]", file=sys.stderr)
        if len(added) > 100:
            print(f"DEBUG:   ... {len(added) - 100} fler", file=sys.stderr)

    if removed:
        print("DEBUG: Borttagna serier:", file=sys.stderr)
        for key in removed[:100]:
            print(f"DEBUG:   - {key[0]} [{key[1]};{key[2]};{key[3]}]", file=sys.stderr)
        if len(removed) > 100:
            print(f"DEBUG:   ... {len(removed) - 100} fler", file=sys.stderr)

    if changed:
        print("DEBUG: Ändrade serier:", file=sys.stderr)
        for key, old, new, fields in changed[:100]:
            print(f"DEBUG:   * {key[0]} [{key[1]};{key[2]};{key[3]}]", file=sys.stderr)
            for field in fields:
                print(f"DEBUG:       {field}: {old.get(field, '')} -> {new.get(field, '')}", file=sys.stderr)
        if len(changed) > 100:
            print(f"DEBUG:   ... {len(changed) - 100} fler", file=sys.stderr)


def run_generate_series_ranking(args: argparse.Namespace) -> int:
    current_file = Path(args.i)
    old_file = Path(args.old)
    output_file = Path(args.o)

    counter: Dict[Tuple[str, str, str, str], int] = {}
    collect_series_from_games_csv(current_file, counter)
    collect_series_from_games_csv(old_file, counter)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    old_ranking_rows = read_existing_series_ranking(output_file) if args.dbg else {}

    rows: List[Dict[str, object]] = []
    for (name, gender_id, age_id, ass_id), match_count in counter.items():
        gender = series_gender_from(name, gender_id)
        category = series_category_from(name, age_id)
        level = series_level_from(name, ass_id, category)
        rank = series_rank_for(name, gender, category, level, ass_id)

        rows.append({
            "SeriePattern": name,
            "Rank": rank,
            "Kategori": category,
            "Kön": gender,
            "Nivå": level,
            "MatchCount": match_count,
            "SerieKönId": gender_id,
            "ÅldersKatId": age_id,
            "Serie_Match_AssId": ass_id,
        })

    rows.sort(key=lambda row: (-int(row["Rank"]), str(row["Kategori"]), str(row["Kön"]), str(row["SeriePattern"]).casefold(), str(row["Serie_Match_AssId"])))

    if args.dbg:
        print_series_ranking_diff(old_ranking_rows, rows)

    with output_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["SeriePattern", "Rank", "Kategori", "Kön", "Nivå", "MatchCount", "SerieKönId", "ÅldersKatId", "Serie_Match_AssId"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Skapade/uppdaterade {output_file}", file=sys.stderr)
    print(f"Antal serier: {len(rows)}", file=sys.stderr)
    print(f"Input current: {current_file}", file=sys.stderr)
    print(f"Input old: {old_file}", file=sys.stderr)
    return 0


def main() -> int:
    args = parse_args()

    cfg = None
    cfg_path = None
    get_module = None
    get_module_path = None
    csv_module = None
    csv_module_path = None

    if args.mode in {"update-csv", "map-games"}:
        try:
            cfg, cfg_path = load_create_football_games_module()
        except Exception as exc:  # noqa: BLE001
            print(f"Fel: {exc}", file=sys.stderr)
            return 2

        debug_print(args.dbg, f"Använder mappningsmodul: {cfg_path}")

    if args.mode in {"update-csv", "fetch-raw"}:
        get_module, get_module_path = load_get_gbg_football_module()
        if get_module_path:
            debug_print(args.dbg, f"Använder hämtningsmodul: {get_module_path}")
        else:
            debug_print(args.dbg, "Hämtningsmodul saknas, använder urllib fallback")

    if args.mode in {"update-csv", "make-csv"}:
        csv_module, csv_module_path = load_create_football_games_csv_module()
        if csv_module_path:
            debug_print(args.dbg, f"Använder CSV-modul: {csv_module_path}")
        else:
            debug_print(args.dbg, "CSV-modul saknas, använder inbyggt CSV-format")

    if args.mode == "fetch-raw":
        return run_fetch_raw(args, get_module=get_module)

    if args.mode == "map-games":
        return run_map_games(args, cfg)

    if args.mode == "make-csv":
        return run_make_csv(args, csv_module=csv_module)

    if args.mode == "update-csv":
        return run_update_csv(args, cfg, get_module=get_module, csv_module=csv_module)

    if args.mode == "enhance-clusters":
        return run_enhance_clusters(args)

    if args.mode == "analyze-mapping":
        return run_analyze_mapping(args)

    if args.mode == "generate-series-ranking":
        return run_generate_series_ranking(args)

    print(f"Fel: okänt mode {args.mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
