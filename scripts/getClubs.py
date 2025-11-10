#!/usr/bin/env python3
import csv
import argparse
from pathlib import Path
import re


def _normalize_header(name: str) -> str:
    if name is None:
        return ""
    s = name.replace("\ufeff", "").strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    return s


def read_csv(file_path, has_header=True, fieldnames=None, normalize_headers=False):
    with open(file_path, encoding="utf-8") as f:
        if has_header:
            reader = csv.DictReader(f, delimiter=";")
            if normalize_headers:
                reader.fieldnames = [_normalize_header(h) for h in reader.fieldnames]
                rows = []
                for raw in reader:
                    rows.append({_normalize_header(k): v for k, v in raw.items()})
                return rows
            else:
                return list(reader)
        else:
            reader = csv.DictReader(f, delimiter=";", fieldnames=fieldnames)
            return list(reader)


def find_club(team_name, clubs, slash_clubs, debug=False, no_warning=False):
    team_name = (team_name or "").strip()
    if not team_name:
        return "" if no_warning else "no_club_found"

    for club in clubs:
        if team_name.lower() == (club.get("club_org", "") or "").strip().lower():
            if debug:
                print(f"[MATCH Club_Org] {team_name} -> {club.get('club_org','')}")
            return club.get("club_org", "")

    for club in clubs:
        sub_teams = [t.strip().lower() for t in (club.get("sub_team_list", "") or "").split(",") if t.strip()]
        if team_name.lower() in sub_teams:
            if debug:
                print(f"[MATCH Sub_Team_List] {team_name} -> {club.get('club_org','')}")
            return club.get("club_org", "")

    matched_clubs = []
    for club in clubs:
        slash_teams = [t.strip().lower() for t in (club.get("slash_team_list", "") or "").split(",") if t.strip()]
        if team_name.lower() in slash_teams:
            org = (club.get("club_org", "") or "").strip()
            if org:
                matched_clubs.append(org)

    if matched_clubs:
        if debug:
            print(f"[MATCH slash_team_list] {team_name} -> {', '.join(matched_clubs)}")
        return ", ".join(matched_clubs)

    for sclub in slash_clubs:
        if team_name.lower() == (sclub.get("slash_team_name", "") or "").strip().lower():
            if debug:
                print(f"[MATCH Slash Club file] {team_name} -> {sclub.get('club_list','')}")
            return (sclub.get("club_list", "") or "").strip()

    if debug:
        print(f"[NO MATCH] {team_name} -> {'empty' if no_warning else 'no_club_found'}")

    return "" if no_warning else "no_club_found"


def _split_alt_names(cell: str):
    if cell is None:
        return []
    raw = str(cell)
    if "|" in raw:
        parts = raw.split("|")
    else:
        parts = raw.split(",")
    return [p.strip() for p in parts if p.strip()]


def build_arena_indexes(arenas):
    primary = {}
    alt = {}
    for row in arenas:
        name = (row.get("arena", "") or "").strip().lower()
        if name:
            primary[name] = row
        alt_names_cell = (row.get("altoroldnames", "") or "")
        for alt_name in _split_alt_names(alt_names_cell):
            alt_key = _normalize_header(alt_name)
            if alt_key:
                alt[alt_key] = row
    return primary, alt


def match_arena(game_arena, arenas_primary, arenas_alt, debug=False):
    val = (game_arena or "").strip()
    if not val:
        return "0", "", "", ""

    key_primary = val.lower()
    key_alt = _normalize_header(val)

    row = arenas_primary.get(key_primary)
    source = "Arena"
    if not row:
        row = arenas_alt.get(key_alt)
        source = "AltOrOldNames" if row else None

    if not row:
        if debug:
            print(f"[ARENA NO MATCH] {val} -> 0, '', '', ''")
        return "0", "", "", ""

    # If PreferedName exists, use it; otherwise use Arena column value (not the input or alt name)
    prefered = (row.get("preferedname", "") or "").strip()
    arena_out = prefered if prefered else (row.get("arena", "") or val).strip()

    nbr_raw = row.get("arena_nbr")
    nbr = (str(nbr_raw).strip() if nbr_raw is not None else "0")
    if not nbr or nbr == "None":
        nbr = "0"
    lat = (row.get("lat", "") or "").strip()
    lng = (row.get("long", "") or "").strip()

    if debug:
        print(f"[ARENA MATCH {source}] {val} -> nbr={nbr!r}, name='{arena_out}', lat={lat}, long={lng}")

    return nbr, arena_out, lat, lng


def main():
    parser = argparse.ArgumentParser(description="Update hockey games with club and arena info")
    parser.add_argument("-gf", required=True, help="path to Game File")
    parser.add_argument("-cf", required=True, help="path to Club File")
    parser.add_argument("-af", required=True, help="path to Arena File")
    parser.add_argument("-scf", required=True, help="path to Slash Club File")
    parser.add_argument("-ogf", help="path to updated Game File")
    parser.add_argument("-dbg", action="store_true", help="Debug output")
    parser.add_argument("-nw", action="store_true", help="No Warning: leave unmatched clubs empty")
    args = parser.parse_args()

    game_fieldnames = [
        "date", "time", "series_name", "link_to_series", "admin_host",
        "home_team", "away_team", "result", "result_link", "arena",
        "status", "iteration_fetched", "iterations_total"
    ]

    games = read_csv(args.gf, has_header=False, fieldnames=game_fieldnames)
    clubs = read_csv(args.cf, normalize_headers=True)
    slash_clubs = read_csv(args.scf, normalize_headers=True)
    arenas = read_csv(args.af, has_header=True, normalize_headers=True)

    arenas_primary, arenas_alt = build_arena_indexes(arenas)

    output_file = args.ogf or str(Path(args.gf).with_name(Path(args.gf).stem + "_updated.csv"))

    fieldnames = game_fieldnames + ["home_club_list", "away_club_list", "arena_nbr", "PreferedName", "Lat", "Long"]

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for game in games:
            home_team = game["home_team"]
            away_team = game["away_team"]
            arena_val = game["arena"]

            game["home_club_list"] = find_club(home_team, clubs, slash_clubs, args.dbg, args.nw)
            game["away_club_list"] = find_club(away_team, clubs, slash_clubs, args.dbg, args.nw)

            arena_nbr, arena_name_out, lat, lng = match_arena(arena_val, arenas_primary, arenas_alt, args.dbg)
            game["arena_nbr"] = arena_nbr
            game["PreferedName"] = arena_name_out
            game["Lat"] = lat
            game["Long"] = lng

            writer.writerow(game)

    print(f"Updated file written to: {output_file}")


if __name__ == "__main__":
    main()
