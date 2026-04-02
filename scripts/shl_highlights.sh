#!/bin/bash
set -euo pipefail

# SHL highlights
# Output:
# datum;tid;hemmalag;bortalag;name;videolank

API_URL="${API_URL:-https://www.shl.se/api/feeds?page=0&pageSize=30&contentTypes=videos&requiredTags=custom.highlights&siteInstanceIds=shl1_shl&showHiddenItems=false}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Fel: jq saknas. Installera med: brew install jq" >&2
  exit 1
fi

response="$(curl -fsS "$API_URL")"

printf '%s' "$response" \
| jq -r '.[] | [.header, .publishedAt, .id] | @tsv' \
| while IFS=$'\t' read -r header published_at id; do
    [ -z "$header" ] && continue
    [ -z "$id" ] && continue

    # Normalisera lagseparator
    normalized="$(printf '%s' "$header" \
      | sed -E 's/[[:space:]]*-[[:space:]]*/ - /g' \
      | sed -E 's/[[:space:]]+/ /g' \
      | sed -E 's/^ //; s/ $//')"

    home="$(printf '%s' "$normalized" | awk -F' - ' '{print $1}')"
    away="$(printf '%s' "$normalized" | awk -F' - ' '{print $2}')"

    [ -z "$home" ] && continue
    [ -z "$away" ] && continue

    # Datum och tid
    date="${published_at%%T*}"
    time="$(printf '%s' "$published_at" | cut -d'T' -f2 | cut -d':' -f1,2)"

    # Bygg videolänk
    encoded_id="$(printf '%s' "$id" | sed 's/|/%7C/g')"
    video_url="https://www.shl.se/single-video/${encoded_id}"

    printf '%s;%s;%s;%s;%s;%s\n' \
      "$date" \
      "$time" \
      "$home" \
      "$away" \
      "$header" \
      "$video_url"
  done
