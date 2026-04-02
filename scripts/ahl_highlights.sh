#!/bin/bash
set -euo pipefail

# AHL highlights
# Output:
# datum;hemmalag;bortalag;name;videolank

BASE_URL="https://theahl.com/video-category/ahl-highlights"

month_to_num() {
  case "$1" in
    jan) echo "01" ;;
    feb) echo "02" ;;
    mar) echo "03" ;;
    apr) echo "04" ;;
    may) echo "05" ;;
    jun) echo "06" ;;
    jul) echo "07" ;;
    aug) echo "08" ;;
    sep) echo "09" ;;
    oct) echo "10" ;;
    nov) echo "11" ;;
    dec) echo "12" ;;
    *)   echo "" ;;
  esac
}

extract_teams_from_title() {
  local title="$1"
  local clean normalized home away

  # Ta bort datumsuffix, t.ex.
  # "Roadrunners vs. Gulls | Apr. 1, 2026" -> "Roadrunners vs. Gulls"
  clean="$(printf '%s' "$title" \
    | sed -E 's/[[:space:]]*\|[[:space:]]*[A-Z][a-z]{2}\.[[:space:]]+[0-9]{1,2},[[:space:]]+[0-9]{4}$//' \
    | sed -E 's/[[:space:]]+/ /g' \
    | sed -E 's/^ //; s/ $//')"

  # Normalisera både "vs." och "vs" till samma separator
  normalized="$(printf '%s' "$clean" | sed -E 's/[[:space:]]+vs\.[[:space:]]+/ vs /I')"

  if printf '%s' "$normalized" | grep -q ' vs '; then
    home="$(printf '%s' "$normalized" | awk -F' vs ' '{print $1}')"
    away="$(printf '%s' "$normalized" | awk -F' vs ' '{print $2}')"
    printf '%s;%s\n' "$home" "$away"
    return 0
  fi

  printf ';\n'
}

curl -fsSL "$BASE_URL" \
| egrep '\-vs\-' \
| sed 's/\" class.*//' \
| sed 's/.*=\"//' \
| awk '!seen[$0]++' \
| while read -r page_url; do
    [ -z "$page_url" ] && continue

    slug="${page_url##*/}"

    # Exempel: roadrunners-vs-gulls-apr-1-2026
    mon="$(printf '%s' "$slug" | sed -E 's/^.*-([a-z][a-z][a-z])-[0-9]{1,2}-20[0-9]{2}$/\1/')"
    day="$(printf '%s' "$slug" | sed -E 's/^.*-[a-z][a-z][a-z]-([0-9]{1,2})-20[0-9]{2}$/\1/')"
    year="$(printf '%s' "$slug" | sed -E 's/^.*-[a-z][a-z][a-z]-[0-9]{1,2}-(20[0-9]{2})$/\1/')"
    month="$(month_to_num "$mon")"

    [ -z "$month" ] && continue
    [ -z "$day" ] && continue
    [ -z "$year" ] && continue

    game_date="$(printf '%04d-%02d-%02d' "$year" "$month" "$day")"

    raw="$(curl -fsSL "$page_url")"

    # Din verifierade extraction
    pair="$(printf '%s' "$raw" \
      | egrep 'https://theahl.com/player-embed/id' \
      | sed -E "s/\" /\"\n/g" \
      | egrep 'src="https://theahl.com/player-embed/id/|title=' \
      | sed 's/^src="//' \
      | sed 's/^title="/;/' \
      | sed 's/"$//' \
      | tr -d '\n' \
      | awk -F';' '{print $2 ";" $1}')"

    title="${pair%%;*}"
    video_url="${pair#*;}"

    [ -z "$title" ] && continue
    [ -z "$video_url" ] && continue

    teams="$(extract_teams_from_title "$title")"
    home="${teams%%;*}"
    away="${teams#*;}"

    [ -z "$home" ] && continue
    [ -z "$away" ] && continue

    printf '%s;%s;%s;%s;%s\n' \
      "$game_date" \
      "$home" \
      "$away" \
      "$title" \
      "$video_url"
  done
