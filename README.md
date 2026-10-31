# WoW Forever — Offline World Map (remake of wowhead.com/forever/world-map)

A fully offline remake of the Wowhead Forever world map, plus a makeshift
third-party "Questie" replacement (quest log, pins, leveling plan). No game
client, no network, no addon — safe to run, nothing talks to Blizzard.

This repo is **the map only**. Lua addon: [decades_lua](https://github.com/bottlefedchaney808/decades_lua). Sim: [wow4_sims](https://github.com/bottlefedchaney808/wow4_sims).

## Run it

    python -m http.server 8731 --bind 127.0.0.1

Then open:  http://127.0.0.1:8731/index.html

(Any static server works — the http.server above is what's used here.)

## Tests

    /usr/bin/python3 -m pytest tests/
    node --test tests/questlog_schema.test.js
    node verify_sha256.js

(Invoke `node --test` with the file, not the directory — the Node in use here
rejects directory arguments. `verify_sha256.js` is a known-answer check for the
quest-log versionHash and exits non-zero on mismatch.)

## What's in it

- **Map** — both continents (Kalimdor + Eastern Kingdoms), all 9,288 tiles at
  full native resolution (z7 = 256 px). Custom Leaflet CRS so tiles line up
  exactly with the Wowhead canvas (44544 x 29696 px).
- **Overlays** — zone labels, landmark labels, POIs (dungeons, raids,
  zeppelins/ships, inns, banks, flight masters, graveyards, class trainers,
  rares), gather nodes with per-node toggles in five categories (herb / ore /
  fish / leather / cloth, discovered from the dataset key prefixes), and —
  when `data/routes.js` / `data/voyages.js` are present — travel-route
  polylines plus dashed voyage itineraries. The panel footer prints the exact
  counts of whatever datasets loaded, so it never drifts from the shipped
  generation.
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

- World map data: Wowhead Nether `forever/data/world-map` (tree 16, captured
  2026-10-30), parsed to `data/places.js` (50 zones including Zephras Isle,
  269 landmarks), `data/pois.js` (4,469), `data/nodes.js` (99 groups / 32,900
  points), `data/routes.js` (160), `data/voyages.js` (14). Pixel coords use
  the shipped canvas 44544×29696, not the live canvasHeight 37888.
- Tiles: `wow.zamimg.com/images/wow/classicplus/world-map/v1/...` webp, all
  downloaded to `tiles/`.
- Level brackets: Wowhead Forever guides (zones overview + content roadmap,
  Sept 2026). Classic-zone brackets are standard vanilla ranges.

## Tile archive (PMTiles v3)

Create a single-file archive from the original WebP tiles (no dependencies; source
files are left intact):

    python convert_tiles.py

This writes `wow-forever.pmtiles`. Pass `--tiles PATH` / `--output PATH` to
select paths. The default input and output folders are resolved relative to the
script location, so the command works from other current directories too. It
stores the tile image bytes unchanged and gzips only metadata
and index directories. The PMTiles v3 header declares WebP tile type, gzip
internal compression, and clustered Hilbert tile IDs; the directory format uses
varint-delta TileIDs, run length, byte length, and relative offsets. Larger
indices use leaf directories so the compressed root stays within the PMTiles
16 KiB limit. Specification: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md

The two source maps have 66 overlapping source z/x/y addresses. To preserve
both without a custom/nonstandard index, archive addresses namespace the source
grid one zoom deeper: archive z = source z + 1; Kalimdor archive x = source x;
Eastern Kingdoms archive x = source x + 2^source_z; archive y = source y. This
is documented in archive metadata (`addressing`, `archive_zoom_offset`) and
retains a reversible source zoom/tile lookup. Use archive coordinates for
PMTiles requests, or keep the app's existing tile URL pattern with the included
adapter server:

    python serve_tiles.py --host 127.0.0.1 --port 8731

The server serves the whole app from the repo root — open
http://127.0.0.1:8731/ — and answers `/tiles/{contig}/{source_z}/{y}_{x}.webp`
from the archive, so the current `index.html` uses the single PMTiles file
without changes. It also serves `/wow-forever.pmtiles` with HTTP byte ranges,
for PMTiles-aware clients. The adapter uses Python's standard library; set
`--archive PATH` to select a different archive. A plain `python -m http.server`
can only serve the PMTiles file as a download and does not provide tile lookup.

## Files

- `index.html` — the app (map + quest log + leveling plan).
- `data/*.js` — extracted Wowhead map data.
- `tiles/` — 9,288 source WebP tiles (kalimdor/ + eastern-kingdoms/).
- `convert_tiles.py` — dependency-free PMTiles v3 packer.
- `serve_tiles.py` — adapter/HTTP byte-range server reading tiles from the archive.
- `wow-forever.pmtiles` — generated archive (create with `python convert_tiles.py`).
- `vendor/leaflet.*` — Leaflet 1.9.4 (offline copy).
- `kalimdor_z7.jpg`, `eastern-kingdoms_z7.jpg` — stitched full-res references.
