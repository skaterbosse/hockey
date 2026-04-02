#!/bin/bash
set -euo pipefail

# HockeyAllsvenskan highlights
# Output:
# datum;tid;hemmalag;bortalag;name;videolank

API_URL="${API_URL:-https://www.hockeyallsvenskan.se/api/media/videos-list?page=0&pageSize=24&type=video&showOwnedMediaOnly=true&tags=visible.lists&searchToken=&dateFrom=&dateTo=&sortKeys=desc}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Fel: jq saknas. Installera med: brew install jq" >&2
  exit 1
fi

extract_teams() {
  local name="$1"
  local matchup
  local home away

  matchup="$(printf '%s' "$name" \
    | sed -E 's/^.*:[[:space:]]*//' \
    | sed -E 's/,[[:space:]]*Highlights$//I' \
    | sed -E 's/[[:space:]]+/ /g' \
    | sed -E 's/^ //; s/ $//')"

  if printf '%s' "$matchup" | grep -q ' - '; then
    home="$(printf '%s' "$matchup" | awk -F' - ' '{print $1}')"
    away="$(printf '%s' "$matchup" | awk -F' - ' '{print $2}')"
    printf '%s;%s\n' "$home" "$away"
    return 0
  fi

  printf ';\n'
}

response="$(curl -fsS "$API_URL")"

printf '%s' "$response" \
| jq -r '
  .items
  | map(select((.tags // []) | index("custom.highlights")))
  | unique_by(.mediaString)
  | sort_by(.publishedAt)
  | reverse
  | .[]
  | [.name, .publishedAt, .mediaString]
  | @tsv
' \
| while IFS=$'\t' read -r name published_at media_string; do
    [ -z "$name" ] && continue
    [ -z "$published_at" ] && continue
    [ -z "$media_string" ] && continue

    teams="$(extract_teams "$name")"
    home="${teams%%;*}"
    away="${teams#*;}"

    [ -z "$home" ] && continue
    [ -z "$away" ] && continue

    date="${published_at%%T*}"
    time="$(printf '%s' "$published_at" | cut -d'T' -f2 | cut -d':' -f1,2)"
    encoded_media="$(printf '%s' "$media_string" | sed 's/|/%7C/g')"
    video_url="https://www.hockeyallsvenskan.se/single-video/${encoded_media}?tags=custom.highlights"

    printf '%s;%s;%s;%s;%s;%s\n' \
      "$date" \
      "$time" \
      "$home" \
      "$away" \
      "$name" \
      "$video_url"
  done
