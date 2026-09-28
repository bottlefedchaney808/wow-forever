# WoW Forever — Offline World Map (remake of wowhead.com/forever/world-map)

A fully offline remake of the Wowhead Forever world map, plus a makeshift
third-party "Questie" replacement (quest log, pins, leveling plan). No game
client, no network, no addon — safe to run, nothing talks to Blizzard.

This repo is **the map only**. Lua addon: [decades_lua](https://github.com/bottlefedchaney808/decades_lua). Sim: [wow4_sims](https://github.com/bottlefedchaney808/wow4_sims).

## Run it

    python -m http.server 8731 --bind 127.0.0.1

Then open:  http://127.0.0.1:8731/index.html

(Any static server works — the http.server above is what's used here.)

## What's in it

- **Map** — both continents (Kalimdor + Eastern Kingdoms), all 9,288 tiles at
  full native resolution (z7 = 256 px). Custom Leaflet CRS so tiles line up
  exactly with the Wowhead canvas (44544 x 29696 px).
- **Overlays** — 49 zone labels, 263 landmarks, 1,285 POIs (dungeons, raids,
  zeppelins/ships, inns, banks, flight masters, graveyards, class trainers,
  rares), and 17,637 gather nodes (herbs + ore, per-node toggles).
- **Quest log** — click any pin / zone label / search result (or a zone/dungeon
  name in the leveling plan) to pin it. Numbered markers appear on the map and
  in the panel. Right-click removes. Saved in browser localStorage, survives
  reloads. This is the makeshift Questie: build your own route.
- **Leveling plan (1→60)** — Horde/Alliance zone brackets plus all 9 new
  launch dungeons, with correct new-zone brackets from the Wowhead Forever
  guides (Zephras Isle 1–12, Riverglades 35–45, Mount Hyjal 60 endgame,
  Shen'Dralas between Mulgore & Desolace).
- **Search** — zones, landmarks, NPCs, dungeons.
- **Deep links** — `#<lat>/<lng>/<zoom>` (this map) or `#<zoom>/<px>/<py>`
  (Wowhead style, e.g. `#1.5/22288/17604`).

## Data provenance

- World map data: Wowhead Nether `world-map` endpoint (dv=14), parsed to
  `data/places.js`, `data/pois.js`, `data/nodes.js`.
- Tiles: `wow.zamimg.com/images/wow/classicplus/world-map/v1/...` webp, all
  downloaded to `tiles/`.
- Level brackets: Wowhead Forever guides (zones overview + content roadmap,
  Sept 2026). Classic-zone brackets are standard vanilla ranges.

## Files

- `index.html` — the app (map + quest log + leveling plan).
- `data/*.js` — extracted Wowhead map data.
- `tiles/` — 9,288 webp tiles (kalimdor/ + eastern-kingdoms/).
- `vendor/leaflet.*` — Leaflet 1.9.4 (offline copy).
- `kalimdor_z7.jpg`, `eastern-kingdoms_z7.jpg` — stitched full-res references.
