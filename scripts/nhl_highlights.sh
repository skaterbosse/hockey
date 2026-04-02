#!/bin/bash
set -euo pipefail

# NHL 5-minute recaps
# Output:
# datum;tid;hemmalag;bortalag;name;videolank
#
# Exempel:
# 2026-03-28;01:58;Chicago Blackhawks;New York Rangers;chi-at-nyr-recap;https://www.nhl.com/video/topic/game-recaps/chi-at-nyr-recap-6391906143112

SOURCE_URL="${SOURCE_URL:-https://www.nhl.com/video/topic/game-recaps/}"

# Team code -> team name
team_name() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    ana) echo "Anaheim Ducks" ;;
    bos) echo "Boston Bruins" ;;
    buf) echo "Buffalo Sabres" ;;
    car) echo "Carolina Hurricanes" ;;
    cbj) echo "Columbus Blue Jackets" ;;
    cgy) echo "Calgary Flames" ;;
    chi) echo "Chicago Blackhawks" ;;
    col) echo "Colorado Avalanche" ;;
    dal) echo "Dallas Stars" ;;
    det) echo "Detroit Red Wings" ;;
    edm) echo "Edmonton Oilers" ;;
    fla) echo "Florida Panthers" ;;
    lak) echo "Los Angeles Kings" ;;
    min) echo "Minnesota Wild" ;;
    mtl) echo "Montréal Canadiens" ;;
    njd) echo "New Jersey Devils" ;;
    nsh) echo "Nashville Predators" ;;
    nyi) echo "New York Islanders" ;;
    nyr) echo "New York Rangers" ;;
    ott) echo "Ottawa Senators" ;;
    phi) echo "Philadelphia Flyers" ;;
    pit) echo "Pittsburgh Penguins" ;;
    sea) echo "Seattle Kraken" ;;
    sjs) echo "San Jose Sharks" ;;
    stl) echo "St. Louis Blues" ;;
    tbl) echo "Tampa Bay Lightning" ;;
    tor) echo "Toronto Maple Leafs" ;;
    uta) echo "Utah Hockey Club" ;;
    van) echo "Vancouver Canucks" ;;
    vgk) echo "Vegas Golden Knights" ;;
    wpg) echo "Winnipeg Jets" ;;
    wsh) echo "Washington Capitals" ;;
    *)
      printf '%s' "$1"
      ;;
  esac
}

curl -L -s "$SOURCE_URL" \
| egrep '/video/topic/game-recaps/.*-at-.*recap|time datetime=' \
| sed 's/.*href=\"/https:\/\/www\.nhl\.com/' \
| sed 's/\"$//' \
| sed -E 's/.*(20[0-9][0-9]\-[0-9][0-9]\-[0-9][0-9])T([0-2][0-9]:[0-5][0-9]).*/;\1;\2;;/g' \
| tr -d '\n' \
| sed 's/;;/\n/g' \
| awk -F';' '{print $2 ";" $3 ";" $1}' \
| while IFS=';' read -r date time url; do
    [ -z "$date" ] && continue
    [ -z "$time" ] && continue
    [ -z "$url" ] && continue

    slug="$(basename "$url")"
    # remove trailing numeric id
    base="$(printf '%s' "$slug" | sed -E 's/-[0-9]+$//')"

    away_code="$(printf '%s' "$base" | awk -F'-at-' '{print $1}')"
    rest="$(printf '%s' "$base" | awk -F'-at-' '{print $2}')"
    home_code="$(printf '%s' "$rest" | sed -E 's/-recap$//')"

    [ -z "$away_code" ] && continue
    [ -z "$home_code" ] && continue

    away="$(team_name "$away_code")"
    home="$(team_name "$home_code")"

    printf '%s;%s;%s;%s;%s;%s\n' \
      "$date" \
      "$time" \
      "$home" \
      "$away" \
      "$base" \
      "$url"
  done
