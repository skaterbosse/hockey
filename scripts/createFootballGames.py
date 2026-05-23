#!/usr/bin/env python3
"""
createFotballGames.py

Läser matcher från getGbgFotboll_v4.py output:
  date;associationId;json-response

Läser arena-/fotbollskluster:
  assIdLista;klusternamn;koordinater;adress;plan1|plan2|...;hemmalag

Skapar en förädlad matchfil med semikolonseparerade kolumner:
  1  Serie_Match_AssId
  2  Datum
  3  Klockslag
  4  SerieId
  5  SerieNamn
  6  SerieKönId
  7  ÅldersKatId
  8  MatchId
  9  MatchStatus
  10 MatchUrl
  11 HemmalagNamn
  12 HemmalagLogoUrl
  13 HemmalagAssId
  14 BortalagNamn
  15 BortalagLogoUrl
  16 BortalagAssId
  17 MatchResultat
  18 ArenaNamn
  19 ArenaKluster
  20 ArenaKlusterKoordinater
  21 ArenaKlusterAdress
  22 SäkerMatchTillArenaKlusterMapping

SäkerMatchTillArenaKlusterMapping:
  Y = explicit och entydig location/alias-matchning
  N = implicit/gissad matchning eller misslyckad matchning

Fel skrivs till -ef eller default:
  Error_File_createFotballGames.txt

Deduplicering:
  Om samma MatchId finns flera gånger behålls raden med Serie_Match_AssId=1.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_ERROR_FILE = "Error_File_createFotballGames.txt"
VALID_ASS_IDS = {"7", "8", "21", "28"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="createFotballGames.py",
        description="Förädla gbgfotboll-matcher och mappa location till fotbollskluster.",
    )
    parser.add_argument("-ig", "--input-games", dest="input_games", required=True)
    parser.add_argument("-ik", "--input-klusters", dest="input_klusters", required=True)
    parser.add_argument("-og", "--output-games", dest="output_games", required=True)
    parser.add_argument("-ef", "--error-file", dest="error_file", default=DEFAULT_ERROR_FILE)
    parser.add_argument("-dbg", dest="debug", action="store_true")
    return parser.parse_args()


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"DEBUG: {message}", file=sys.stderr)


def clean_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_name(value: object) -> str:
    value = clean_space(value).casefold()
    value = value.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")
    value = re.sub(r"[^0-9a-zåäöéü/\- ]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_location_for_matching(value: object) -> str:
    value = clean_space(value).casefold()
    value = value.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")

    # Ta bort ort/förklaring efter komma.
    value = re.sub(r",.*$", "", value)

    # Ta bort parentesdelar, t.ex. "(plan B)".
    value = re.sub(r"\([^)]*\)", " ", value)

    value = re.sub(r"[^0-9a-zåäöéü/\- ]", " ", value)

    # Vanliga plan-/underplansord som inte ska hindra matchning.
    value = re.sub(
        r"\b(?:plan|a-plan|b-plan|c-plan|d-plan|kg|konstgräs|naturgräs|gräs|huvudplan|mellanplan|överplan|nedre|övre)\b",
        " ",
        value,
    )

    # Planbeteckningar/siffror.
    value = re.sub(r"\b\d+(?::\d+)?\b", " ", value)

    # Enstaka planbokstäver på slutet.
    value = re.sub(r"\b[a-h]\b$", " ", value)

    value = re.sub(r"\s+", " ", value).strip()
    return value


def safe_text(value: object) -> str:
    if value is None:
        return ""
    return clean_space(value).replace(";", ",")


def parse_ass_id_list(value: str) -> List[str]:
    value = clean_space(value)

    if not value or value == "0" or value.startswith("CONFLICT:"):
        return []

    ids = [clean_space(item) for item in value.split(",") if clean_space(item)]
    return [item for item in ids if item.isdigit()]


def parse_coordinates(value: str) -> Optional[Tuple[float, float]]:
    value = clean_space(value)
    if not value or "," not in value:
        return None

    parts = [part.strip() for part in value.split(",", 1)]

    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def haversine_km(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )

    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def base_club_name(team_name: str) -> str:
    value = clean_space(team_name)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(?:F|P|PF|HJ|DJ)\s*-?\s*\d{1,4}(?:/\d{1,4})?\b", " ", value, flags=re.I)
    value = re.sub(r"\b\d{1,4}(?:/\d{1,4})?\s*(?:år)?\b", " ", value, flags=re.I)
    value = re.sub(
        r"\b(?:blå|gul|grön|röd|svart|vit|orange|lila|rosa|grå|vinröd|lag|u|utv-lag|utv|akademi)\b",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(r"\b\d+\b", " ", value)
    return normalize_name(value)


def cluster_has_same_club(cluster: "Cluster", team_name: str) -> bool:
    team_base = base_club_name(team_name)

    if not team_base:
        return False

    for cluster_team in cluster.home_teams:
        cluster_team_base = base_club_name(cluster_team)

        if not cluster_team_base:
            continue

        if cluster_team_base == team_base:
            return True

    return False


def cluster_allows_home_ass_id(cluster: "Cluster", home_ass_id: str) -> bool:
    return bool(home_ass_id) and home_ass_id in cluster.ass_ids


def team_name_from_home_team_entry(entry: str) -> str:
    entry = clean_space(entry)
    if not entry:
        return ""

    parts = entry.split(",", 2)
    if len(parts) >= 3 and parts[0] == "DUP":
        return clean_space(parts[2])
    if len(parts) >= 2:
        return clean_space(parts[1])
    return entry


class Cluster:
    def __init__(
        self,
        line_number: int,
        ass_ids: List[str],
        name: str,
        coordinates: str,
        address: str,
        aliases: List[str],
        home_teams: List[str],
    ) -> None:
        self.line_number = line_number
        self.ass_ids = ass_ids
        self.name = name
        self.coordinates = coordinates
        self.address = address
        self.aliases = aliases
        self.home_teams = home_teams
        self.parsed_coordinates = parse_coordinates(coordinates)


def read_clusters(path: Path, debug: bool = False) -> Tuple[List[Cluster], Dict[str, List[int]], Dict[str, List[int]]]:
    clusters: List[Cluster] = []
    alias_to_indexes: Dict[str, List[int]] = {}
    home_team_to_indexes: Dict[str, List[int]] = {}

    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue

            parts = line.split(";")
            if len(parts) < 5:
                print(f"VARNING: Hoppar över klusterrad {line_number}, för få kolumner: {line!r}", file=sys.stderr)
                continue

            # Nytt format:
            # assIdLista;klusternamn;koordinater;adress;planer;hemmalag
            ass_ids = parse_ass_id_list(parts[0])
            name = clean_space(parts[1])
            coordinates = clean_space(parts[2])
            address = clean_space(parts[3])
            aliases_text = parts[4]
            home_teams_text = parts[5] if len(parts) >= 6 else ""

            aliases = [name]
            aliases.extend(clean_space(item) for item in aliases_text.split("|") if item.strip())

            seen_aliases: Set[str] = set()
            for alias in aliases:
                for norm_alias in (normalize_name(alias), normalize_location_for_matching(alias)):
                    if not norm_alias or norm_alias in seen_aliases:
                        continue
                    seen_aliases.add(norm_alias)
                    alias_to_indexes.setdefault(norm_alias, []).append(len(clusters))

            home_teams: List[str] = []
            seen_home_teams: Set[str] = set()
            for entry in home_teams_text.split("|"):
                team = team_name_from_home_team_entry(entry)
                norm_team = normalize_name(team)
                if not norm_team or norm_team in seen_home_teams:
                    continue
                seen_home_teams.add(norm_team)
                home_teams.append(team)
                home_team_to_indexes.setdefault(norm_team, []).append(len(clusters))

            clusters.append(Cluster(line_number, ass_ids, name, coordinates, address, aliases, home_teams))

    debug_print(debug, f"Läste {len(clusters)} kluster från {path}")
    return clusters, alias_to_indexes, home_team_to_indexes


def iter_json_objects(text: str) -> Iterable[dict]:
    decoder = json.JSONDecoder()
    index = 0

    while True:
        start = text.find("{", index)
        if start < 0:
            break

        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue

        if isinstance(obj, dict):
            yield obj

        index = start + end


def read_input_game_lines(path: Path) -> Iterable[Tuple[int, str, str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue

            parts = line.split(";", 2)
            if len(parts) == 3 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]) and parts[1].isdigit():
                yield line_number, parts[0], parts[1], parts[2]
            else:
                # Tillåt även ren JSON-rad.
                yield line_number, "", "", line


def iter_competitions(obj: dict) -> Iterable[dict]:
    if "competitions" in obj and isinstance(obj.get("competitions"), list):
        for competition in obj.get("competitions", []):
            if isinstance(competition, dict):
                yield competition

    elif "games" in obj and isinstance(obj.get("games"), list):
        # Objektet är redan en competition.
        yield obj


def parse_game_datetime(value: str) -> Tuple[str, str]:
    value = clean_space(value)
    if "T" in value:
        date_text, time_text = value.split("T", 1)
        return date_text, time_text[:5]
    return value[:10], ""


def match_result(game: dict) -> str:
    score = game.get("score")
    if not isinstance(score, dict):
        return ""

    home = score.get("home")
    away = score.get("away")

    if home is None or away is None:
        return ""

    return f"{home}-{away}"


def is_bye_team_name(value: str) -> bool:
    return normalize_name(value).replace(" ", "") == "ståöver"


def should_skip_game(game: dict) -> Tuple[bool, str]:
    location = clean_space(game.get("location", ""))
    game_date, game_time = parse_game_datetime(safe_text(game.get("date")))

    home_team = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
    away_team = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}

    home_team_name = clean_space(home_team.get("name", "")) if isinstance(home_team, dict) else ""
    away_team_name = clean_space(away_team.get("name", "")) if isinstance(away_team, dict) else ""

    home_ass_id = safe_text(game.get("homeTeamClubAssociationId"))
    away_ass_id = safe_text(game.get("awayTeamClubAssociationId"))

    if not location:
        return True, "SKIP_EMPTY_LOCATION"

    if not game_date:
        return True, "SKIP_EMPTY_DATE"

    if not game_time:
        return True, "SKIP_EMPTY_TIME"

    if is_bye_team_name(home_team_name):
        return True, "SKIP_HOME_TEAM_STA_OVER"

    if is_bye_team_name(away_team_name):
        return True, "SKIP_AWAY_TEAM_STA_OVER"

    if home_ass_id == "0":
        return True, "SKIP_HOME_ASS_ID_0"

    if away_ass_id == "0":
        return True, "SKIP_AWAY_ASS_ID_0"

    if home_ass_id not in VALID_ASS_IDS:
        return True, f"SKIP_HOME_ASS_ID_NOT_ALLOWED_{home_ass_id}"

    return False, ""


def cluster_ass_id_rank(cluster: Cluster, ass_id: str) -> Optional[int]:
    if not ass_id or not cluster.ass_ids:
        return None

    try:
        return cluster.ass_ids.index(str(ass_id))
    except ValueError:
        return None


def filter_by_home_ass_id(candidates: List[int], clusters: List[Cluster], home_ass_id: str) -> List[int]:
    return [index for index in candidates if cluster_allows_home_ass_id(clusters[index], home_ass_id)]


def choose_by_ass_id(candidates: List[int], clusters: List[Cluster], wanted_ass_ids: List[str]) -> List[int]:
    if not candidates:
        return []

    scored: List[Tuple[int, int]] = []

    for index in candidates:
        best_rank: Optional[int] = None

        for ass_id in wanted_ass_ids:
            rank = cluster_ass_id_rank(clusters[index], ass_id)
            if rank is not None and (best_rank is None or rank < best_rank):
                best_rank = rank

        if best_rank is not None:
            scored.append((best_rank, index))

    if not scored:
        return candidates

    min_rank = min(rank for rank, _index in scored)
    return [index for rank, index in scored if rank == min_rank]


def choose_by_home_team(candidates: List[int], clusters: List[Cluster], home_team_name: str) -> List[int]:
    norm_home_team = normalize_name(home_team_name)
    if not norm_home_team:
        return candidates

    matching = [
        index
        for index in candidates
        if any(normalize_name(team) == norm_home_team for team in clusters[index].home_teams)
    ]

    return matching if matching else candidates


def find_normal_home_clusters(
    clusters: List[Cluster],
    home_team_to_indexes: Dict[str, List[int]],
    home_team_name: str,
    home_ass_id: str,
) -> List[int]:
    norm_home_team = normalize_name(home_team_name)
    exact_indexes = home_team_to_indexes.get(norm_home_team, [])
    exact_indexes = filter_by_home_ass_id(exact_indexes, clusters, home_ass_id)

    if exact_indexes:
        return exact_indexes

    team_base = base_club_name(home_team_name)
    if not team_base:
        return []

    candidates: List[int] = []
    seen: Set[int] = set()

    for index, cluster in enumerate(clusters):
        if index in seen:
            continue
        if not cluster_allows_home_ass_id(cluster, home_ass_id):
            continue
        if cluster_has_same_club(cluster, home_team_name):
            seen.add(index)
            candidates.append(index)

    return candidates


def candidates_within_20_km_of_normal_home(
    candidates: List[int],
    normal_home_indexes: List[int],
    clusters: List[Cluster],
) -> List[int]:
    if not candidates or not normal_home_indexes:
        return []

    normal_coords = [
        clusters[index].parsed_coordinates
        for index in normal_home_indexes
        if clusters[index].parsed_coordinates is not None
    ]

    if not normal_coords:
        return []

    close_candidates: List[int] = []

    for index in candidates:
        candidate_coord = clusters[index].parsed_coordinates
        if candidate_coord is None:
            continue

        if any(haversine_km(candidate_coord, normal_coord) <= 20.0 for normal_coord in normal_coords):
            close_candidates.append(index)

    return close_candidates


def map_game_to_cluster(
    game: dict,
    clusters: List[Cluster],
    alias_to_indexes: Dict[str, List[int]],
    home_team_to_indexes: Dict[str, List[int]],
    debug: bool = False,
) -> Tuple[Optional[Cluster], str, str]:
    location = clean_space(game.get("location", ""))
    norm_location = normalize_location_for_matching(location)

    home_team = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
    home_team_name = clean_space(home_team.get("name", "")) if isinstance(home_team, dict) else ""

    home_ass_id = safe_text(game.get("homeTeamClubAssociationId"))
    away_ass_id = safe_text(game.get("awayTeamClubAssociationId"))
    wanted_ass_ids = [home_ass_id, away_ass_id]

    direct_candidates = alias_to_indexes.get(norm_location, [])
    direct_candidates = filter_by_home_ass_id(direct_candidates, clusters, home_ass_id)

    if direct_candidates:
        candidates = choose_by_home_team(direct_candidates, clusters, home_team_name)
        candidates = choose_by_ass_id(candidates, clusters, wanted_ass_ids)

        if len(candidates) == 1:
            cluster = clusters[candidates[0]]
            debug_print(debug, f"Explicit match: location={location!r} -> {cluster.name!r}")
            return cluster, "Y", ""

        reason = (
            f"AMBIGUOUS_EXPLICIT_MATCH location={location!r} "
            f"homeTeam={home_team_name!r} homeAssId={home_ass_id} candidates="
            + "|".join(clusters[index].name for index in candidates)
        )
        debug_print(debug, reason)
        return None, "N", reason

    if alias_to_indexes.get(norm_location):
        reason = (
            f"NO_CLUSTER_WITH_HOME_ASS_ID location={location!r} "
            f"homeTeam={home_team_name!r} homeAssId={home_ass_id}"
        )
        debug_print(debug, reason)
        return None, "N", reason

    # Implicit fallback: använd hemmalagets kända kluster, filtrerat med HomeTeamAssId.
    normal_home_indexes = find_normal_home_clusters(clusters, home_team_to_indexes, home_team_name, home_ass_id)

    if normal_home_indexes:
        same_club_candidates = [
            index
            for index, cluster in enumerate(clusters)
            if cluster_allows_home_ass_id(cluster, home_ass_id)
            and cluster_has_same_club(cluster, home_team_name)
        ]

        location_like_candidates = [
            index
            for index, cluster in enumerate(clusters)
            if cluster_allows_home_ass_id(cluster, home_ass_id)
            and any(
                normalize_location_for_matching(alias).startswith(norm_location)
                or norm_location.startswith(normalize_location_for_matching(alias))
                for alias in cluster.aliases
                if normalize_location_for_matching(alias)
            )
        ]

        implicit_candidates: List[int] = []
        seen_implicit: Set[int] = set()

        for index in location_like_candidates:
            if index not in seen_implicit:
                implicit_candidates.append(index)
                seen_implicit.add(index)

        for index in same_club_candidates:
            if index not in seen_implicit:
                implicit_candidates.append(index)
                seen_implicit.add(index)

        close_candidates = candidates_within_20_km_of_normal_home(
            implicit_candidates,
            normal_home_indexes,
            clusters,
        )

        # En svag implicit matchning räknas som lyckad om:
        # 1) klustret har annat lag i samma förening i hemmalagslistan, eller
        # 2) klustret ligger inom 20 km från lagets normala hemmakluster.
        accepted_candidates: List[int] = []
        seen_accepted: Set[int] = set()

        for index in same_club_candidates:
            if index not in seen_accepted:
                accepted_candidates.append(index)
                seen_accepted.add(index)

        for index in close_candidates:
            if index not in seen_accepted:
                accepted_candidates.append(index)
                seen_accepted.add(index)

        # Om location delvis matchar ett accepterat kluster, prioritera dessa.
        location_accepted = [index for index in location_like_candidates if index in set(accepted_candidates)]
        candidates = location_accepted or accepted_candidates

        candidates = choose_by_ass_id(candidates, clusters, [home_ass_id])

        if len(candidates) == 1:
            cluster = clusters[candidates[0]]
            reason = f"IMPLICIT_WEAK_MATCH location={location!r} homeTeam={home_team_name!r} -> {cluster.name!r}"
            debug_print(debug, reason)
            return cluster, "N", reason

        if candidates:
            reason = (
                f"AMBIGUOUS_IMPLICIT_WEAK_MATCH location={location!r} "
                f"homeTeam={home_team_name!r} homeAssId={home_ass_id} candidates="
                + "|".join(clusters[index].name for index in candidates)
            )
            debug_print(debug, reason)
            return None, "N", reason

    reason = f"NO_CLUSTER_MATCH location={location!r} homeTeam={home_team_name!r} homeAssId={home_ass_id}"
    debug_print(debug, reason)
    return None, "N", reason


def game_to_output_row(
    source_ass_id: str,
    competition: dict,
    game: dict,
    cluster: Optional[Cluster],
    safe_mapping: str,
) -> List[str]:
    game_date, game_time = parse_game_datetime(safe_text(game.get("date")))

    home_team = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
    away_team = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}

    arena_name = safe_text(game.get("location"))

    return [
        safe_text(source_ass_id or competition.get("associationId", "")),
        safe_text(game_date),
        safe_text(game_time),
        safe_text(competition.get("competitionId")),
        safe_text(competition.get("name")),
        safe_text(competition.get("genderId")),
        safe_text(competition.get("ageCategoryId")),
        safe_text(game.get("gameId")),
        safe_text(game.get("status")),
        safe_text(game.get("url")),
        safe_text(home_team.get("name") if isinstance(home_team, dict) else ""),
        safe_text(home_team.get("teamImageUrl") if isinstance(home_team, dict) else ""),
        safe_text(game.get("homeTeamClubAssociationId")),
        safe_text(away_team.get("name") if isinstance(away_team, dict) else ""),
        safe_text(away_team.get("teamImageUrl") if isinstance(away_team, dict) else ""),
        safe_text(game.get("awayTeamClubAssociationId")),
        safe_text(match_result(game)),
        arena_name,
        safe_text(cluster.name if cluster else ""),
        safe_text(cluster.coordinates if cluster else ""),
        safe_text(cluster.address if cluster else ""),
        safe_mapping,
    ]


def write_error(error_handle, source_line: int, source_date: str, source_ass_id: str, competition: dict, game: dict, reason: str) -> None:
    game_id = safe_text(game.get("gameId"))
    location = safe_text(game.get("location"))

    home_team = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
    away_team = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}

    fields = [
        safe_text(source_line),
        safe_text(source_date),
        safe_text(source_ass_id),
        safe_text(competition.get("competitionId")),
        safe_text(competition.get("name")),
        game_id,
        safe_text(home_team.get("name") if isinstance(home_team, dict) else ""),
        safe_text(game.get("homeTeamClubAssociationId")),
        safe_text(away_team.get("name") if isinstance(away_team, dict) else ""),
        safe_text(game.get("awayTeamClubAssociationId")),
        location,
        safe_text(reason),
    ]
    error_handle.write(";".join(fields) + "\n")



def duplicate_preference_rank(row: List[str]) -> int:
    # Lägre värde = bättre rad att behålla.
    # Om samma MatchId finns med flera Serie_Match_AssId behåller vi AssId 1.
    if row and row[0] == "1":
        return 0
    return 1


def row_match_id(row: List[str]) -> str:
    # Kolumn 8 = MatchId, index 7.
    if len(row) > 7:
        return row[7]
    return ""



def process(input_games: Path, input_klusters: Path, output_games: Path, error_file: Path, debug: bool = False) -> int:
    clusters, alias_to_indexes, home_team_to_indexes = read_clusters(input_klusters, debug=debug)

    output_games.parent.mkdir(parents=True, exist_ok=True)
    error_file.parent.mkdir(parents=True, exist_ok=True)

    total_games = 0
    mapped_safe = 0
    mapped_unsafe = 0
    errors = 0
    duplicate_games = 0

    # Samla först alla outputrader per MatchId så att vi kan deduplicera.
    # Exempel: samma MatchId kan komma från serie-AssId 1 och 7.
    # Då behåller vi raden med Serie_Match_AssId=1.
    output_rows_by_match_id: Dict[str, List[str]] = {}

    with error_file.open("w", encoding="utf-8") as err:
        for line_number, source_date, source_ass_id, json_text in read_input_game_lines(input_games):
            objects = list(iter_json_objects(json_text))

            if not objects:
                errors += 1
                err.write(f"{line_number};{source_date};{source_ass_id};;;;;;;;;INVALID_JSON_OR_EMPTY_RESPONSE\n")
                debug_print(debug, f"Rad {line_number}: ingen JSON kunde läsas")
                continue

            for obj in objects:
                for competition in iter_competitions(obj):
                    for game in competition.get("games", []):
                        if not isinstance(game, dict):
                            continue

                        skip_game, skip_reason = should_skip_game(game)
                        if skip_game:
                            errors += 1
                            debug_print(debug, f"Hoppar över match gameId={safe_text(game.get('gameId'))}: {skip_reason}")
                            write_error(err, line_number, source_date, source_ass_id, competition, game, skip_reason)
                            continue

                        total_games += 1
                        cluster, safe_mapping, reason = map_game_to_cluster(
                            game,
                            clusters,
                            alias_to_indexes,
                            home_team_to_indexes,
                            debug=debug,
                        )

                        row = game_to_output_row(source_ass_id, competition, game, cluster, safe_mapping)
                        match_id = row_match_id(row)

                        if match_id in output_rows_by_match_id:
                            duplicate_games += 1
                            existing_row = output_rows_by_match_id[match_id]

                            if duplicate_preference_rank(row) < duplicate_preference_rank(existing_row):
                                debug_print(
                                    debug,
                                    f"Ersätter duplikat MatchId={match_id}: "
                                    f"Serie_Match_AssId {existing_row[0]} -> {row[0]}"
                                )
                                output_rows_by_match_id[match_id] = row
                            else:
                                debug_print(
                                    debug,
                                    f"Hoppar över duplikat MatchId={match_id}: "
                                    f"Serie_Match_AssId {row[0]} behålls ej"
                                )
                            continue

                        output_rows_by_match_id[match_id] = row

                        if cluster is None:
                            errors += 1
                            write_error(err, line_number, source_date, source_ass_id, competition, game, reason)
                        elif safe_mapping == "Y":
                            mapped_safe += 1
                        else:
                            mapped_unsafe += 1
                            write_error(err, line_number, source_date, source_ass_id, competition, game, reason)

    with output_games.open("w", encoding="utf-8") as out:
        for row in output_rows_by_match_id.values():
            out.write(";".join(row) + "\n")

    print(f"Skapade {output_games}", file=sys.stderr)
    print(f"Skapade {error_file}", file=sys.stderr)
    print(f"Antal matcher före deduplicering: {total_games}", file=sys.stderr)
    print(f"Antal duplikat borttagna: {duplicate_games}", file=sys.stderr)
    print(f"Antal matcher efter deduplicering: {len(output_rows_by_match_id)}", file=sys.stderr)
    print(f"Säkra klustermappningar: {mapped_safe}", file=sys.stderr)
    print(f"Osäkra/gissade klustermappningar: {mapped_unsafe}", file=sys.stderr)
    print(f"Fel/omappade matcher: {errors}", file=sys.stderr)

    return 0

def main() -> int:
    args = parse_args()

    input_games = Path(args.input_games)
    input_klusters = Path(args.input_klusters)
    output_games = Path(args.output_games)
    error_file = Path(args.error_file)

    if not input_games.exists():
        print(f"Fel: input games saknas: {input_games}", file=sys.stderr)
        return 2

    if not input_klusters.exists():
        print(f"Fel: input klusters saknas: {input_klusters}", file=sys.stderr)
        return 2

    return process(input_games, input_klusters, output_games, error_file, debug=args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
