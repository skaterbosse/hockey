#!/usr/bin/env python3
import argparse,json
from urllib.request import Request,urlopen

COMPETITIONS={"PL":"premier-league"}

def build_refooty_url(source):
    if not source or "match=" not in source:
        return None
    return "https://refooty.com/video/" + source.split("match=",1)[1].replace("_","-")

def fetch_competition(slug):
    page=1
    rows=[]
    while True:
        url=f"https://a.refooty.com/api/videos/by-competition/{slug}?page={page}&per_page=50"
        req=Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urlopen(req,timeout=30) as resp:
            payload=json.loads(resp.read().decode("utf-8"))
        items=payload.get("data",[])
        if not items:
            break
        rows.extend(items)
        if len(items)<50:
            break
        page+=1
    return rows

ap=argparse.ArgumentParser()
ap.add_argument("league",choices=COMPETITIONS.keys())
args=ap.parse_args()

highlights=[]
seen=set()

for item in fetch_competition(COMPETITIONS[args.league]):
    source=item.get("source","")
    if "match=" not in source:
        continue
    date=(item.get("event_at") or "")[:10]
    home=((item.get("team1") or {}).get("name") or "").strip()
    away=((item.get("team2") or {}).get("name") or "").strip()
    key=(date,home,away)
    if key in seen:
        continue
    seen.add(key)

    highlights.append({
        "Matchstart": date,
        "Serie": "Premier League",
        "Titel": item.get("title",""),
        "Hemmalag": home,
        "Logo hemmalag": (item.get("team1") or {}).get("logo_url",""),
        "Bortalag": away,
        "Logo bortalag": (item.get("team2") or {}).get("logo_url",""),
        "Videolänk": build_refooty_url(source),
        "highlightslängd": ""
    })

highlights.sort(key=lambda x:x["Matchstart"], reverse=True)
print(json.dumps(highlights,ensure_ascii=False,indent=2))
