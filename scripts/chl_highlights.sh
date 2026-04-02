#!/bin/bash
set -euo pipefail

# CHL highlights
# Output:
# datum;tid;hemmalag;bortalag;name;videolank
#
# Exempel:
# 2026-03-03;22:06;Frölunda Gothenburg;Luleå Hockey;F Highlights | Frölunda Gothenburg vs Luleå Hockey;https://www.chl.hockey/en/highlights/f-highlights-frolunda-gothenburg-vs-lulea-hockey

BASE_URL="${BASE_URL:-https://www.chl.hockey/api/cards/en}"
MAX_PAGES="${MAX_PAGES:-5}"
LIMIT="${LIMIT:-30}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Fel: jq saknas. Installera med: brew install jq" >&2
  exit 1
fi

Q='{"_type":"Corebine.Core.Feed.Corebine.Cards","types":["Corebine.Core.Card.Video"],"sources":[],"tags":["599f261d938838233a5a6f37"],"readOnly":false,"matchAllTags":false}'

tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT

page=1
while [ "$page" -le "$MAX_PAGES" ]; do
  response="$(curl -fsSG "${BASE_URL}/${page}.json" --data-urlencode "q=${Q}")"
  count="$(printf '%s' "$response" | jq '(.data // []) | length')"

  if [ "$count" -eq 0 ]; then
    break
  fi

  printf '%s' "$response" >> "$tmpfile"
  printf '\n' >> "$tmpfile"

  # Om sidan verkar kort är vi sannolikt klara
  if [ "$count" -lt 12 ]; then
    break
  fi

  page=$((page + 1))
done

jq -rs --argjson limit "$LIMIT" '
  map(.data // []) 
  | add
  | unique_by(._entityId)
  | sort_by(.displayDate)
  | reverse
  | .[:$limit]
  | .[]
  | [
      .title,
      .displayDate,
      (.link.localizedUrl // .link.url // "")
    ]
  | @tsv
' "$tmpfile" \
| while IFS=$'\t' read -r title display_date localized_url; do
    [ -z "$title" ] && continue
    [ -z "$display_date" ] && continue
    [ -z "$localized_url" ] && continue

    matchup="$(printf '%s' "$title" | sed -E 's/^[^|]+\|[[:space:]]*//')"

    home="$(printf '%s' "$matchup" | awk -F' vs ' '{print $1}')"
    away="$(printf '%s' "$matchup" | awk -F' vs ' '{print $2}')"

    [ -z "$home" ] && continue
    [ -z "$away" ] && continue

    date="${display_date%%T*}"
    time="$(printf '%s' "$display_date" | cut -d'T' -f2 | cut -d':' -f1,2)"
    video_url="https://www.chl.hockey${localized_url}"

    printf '%s;%s;%s;%s;%s;%s\n' \
      "$date" \
      "$time" \
      "$home" \
      "$away" \
      "$title" \
      "$video_url"
  done
