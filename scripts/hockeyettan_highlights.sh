#!/bin/bash
set -euo pipefail

# Hockeyettan highlights -> senaste 50 klipp
# Output:
# datum;hemmalag;bortalag;name;videolank

BASE_URL="https://api.staylive.tv/collection/videos/category/9"
LIMIT=50

if ! command -v jq >/dev/null 2>&1; then
  echo "Fel: jq saknas. Installera med: brew install jq" >&2
  exit 1
fi

cleanup_team_part() {
  local part="$1"

  printf '%s' "$part" \
    | sed -E 's/^Higlights[[:space:]]+/Highlights /I' \
    | sed -E 's/^Highlights[[:space:]]+//' \
    | sed -E 's/^[[:space:]]*-[[:space:]]*//' \
    | sed -E 's/,[[:space:]]*Highlights$//I' \
    | sed -E 's/[[:space:]]+Highlights$//I' \
    | sed -E 's/[[:space:]]+Match[[:space:]]+[0-9]+$//' \
    | sed -E 's/[[:space:]]+Kvartsfinal[[:space:]]+[0-9]+$//I' \
    | sed -E 's/[[:space:]]+[Mm][0-9]+$//' \
    | sed -E 's/[[:space:]]+[0-9]{6,8}$//' \
    | sed -E 's/[[:space:]]+[0-9]+$//' \
    | sed -E 's/[[:space:]]+/ /g' \
    | sed -E 's/^ //; s/ $//'
}

extract_teams() {
  local name="$1"
  local matchup
  local home away

  matchup="$(printf '%s' "$name" \
    | sed -E 's/^Higlights[[:space:]]+/Highlights /I' \
    | sed -E 's/_/ /g' \
    | sed -E 's/^Highlights[[:space:]]*-[[:space:]]*M[0-9]+[[:space:]]*-[[:space:]]*//' \
    | sed -E 's/^Highlights[[:space:]]*:[[:space:]]*//' \
    | sed -E 's/^.*:[[:space:]]*//' \
    | sed -E 's/[[:space:]]+/ /g' \
    | sed -E 's/^ //; s/ $//')"

  if printf '%s' "$matchup" | grep -q ' - '; then
    home="$(printf '%s' "$matchup" | awk -F' - ' '{print $1}')"
    away="$(printf '%s' "$matchup" | awk -F' - ' '{print $2}')"
  else
    home="$(printf '%s' "$matchup" | awk -F'-' '{print $1}')"
    away="$(printf '%s' "$matchup" | awk -F'-' '{print $2}')"
  fi

  home="$(cleanup_team_part "$home")"
  away="$(cleanup_team_part "$away")"

  if [ -n "$home" ] && [ -n "$away" ]; then
    printf '%s;%s\n' "$home" "$away"
    return 0
  fi

  printf ';\n'
}

response="$(curl -fsS "${BASE_URL}?limit=${LIMIT}&page=1")"

printf '%s' "$response" \
| jq -r '
  .message.videos
  | unique_by(.seo_string)
  | sort_by(.created_at)
  | reverse
  | .[]
  | [.name, .created_at, .seo_string]
  | @tsv
' \
| while IFS=$'\t' read -r name created_at seo; do
    [ -z "$seo" ] && continue

    teams="$(extract_teams "$name")"
    home="${teams%%;*}"
    away="${teams#*;}"

    [ -z "$home" ] && continue
    [ -z "$away" ] && continue

    date="${created_at%%T*}"
    video_url="https://live.hockeyettan.se/sv/video/${seo}"

    printf '%s;%s;%s;%s;%s\n' \
      "$date" \
      "$home" \
      "$away" \
      "$name" \
      "$video_url"
  done
