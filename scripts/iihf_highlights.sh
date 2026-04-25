#!/usr/bin/env bash
set -euo pipefail

YEAR="${1:-}"
TOURNAMENT="${2:-}"
COUNTRY="${3:--1}"
MAINTAG="${4:--1}"

if [[ -z "$YEAR" || -z "$TOURNAMENT" ]]; then
  echo "Usage: $0 YEAR TOURNAMENT [COUNTRY=-1] [MAINTAG=-1]" >&2
  exit 1
fi

URL="https://www.iihf.com/en/video?year=${YEAR}&tournament=${TOURNAMENT}&country=${COUNTRY}&maintag=${MAINTAG}"

IIHF_URL="$URL" node <<'EOF' | jq -r '
def month(m):
  {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
   "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}[m];

.[] |
(
  .date | split(" ") |
  "\(.[2])-\(month(.[1]))-\(.[0])"
) as $date |
(
  .description | split(" vs. ") |
  "\(.[0]);\(.[1])"
) as $teams |
"\($date);;\($teams);\(.title);\(.url
 | sub("https://www.youtube.com/embed/"; "https://www.youtube.com/watch?v=")
 | sub("https://youtu.be/"; "https://www.youtube.com/watch?v=")
)"
'
const { chromium } = require("playwright");

(async () => {
  const url = process.env.IIHF_URL;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
  });

  const page = await context.newPage();

  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-video-url]", { timeout: 30000 });

  const videos = await page.$$eval("[data-video-url]", els =>
    els.map(el => {
      const card =
        el.closest(".b-card") ||
        el.closest(".b-card--video") ||
        el.parentElement;

      return {
        title: card?.querySelector(".s-title")?.textContent.trim() || "",
        description: card?.querySelector(".s-text")?.textContent.trim() || "",
        date: card?.querySelector(".s-publish-date")?.textContent.trim() || "",
        url: el.getAttribute("data-video-url")
      };
    })
  );

  console.log(JSON.stringify(videos));
  await browser.close();
})();
EOF
