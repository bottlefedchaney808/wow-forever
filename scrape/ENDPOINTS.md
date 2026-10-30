# World-map endpoint pin (2026-10-30)

Probe UA (plan): `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36`

The HTML page on `www.wowhead.com` is CloudFront-blocked from this host, so in-page API paths could not be grepped. The working route was found by trying the Forever Nether prefix already used by the sim (`nether.wowhead.com/forever/data/…`).

## Working URL (all five datasets in one document)

| | |
|---|---|
| URL | `https://nether.wowhead.com/forever/data/world-map` |
| Status | **200** `text/javascript; charset=UTF-8` (nginx, CloudFront hit) |
| Bytes | **1,828,413** |
| Capture | `scrape/raw/world-map.js` |
| Wrapper | twelve `WH.setPageData("wow.worldMap.classicplus.<key>", <json>);` statements. No cookies. Referer `https://www.wowhead.com/forever/world-map` was sent; not required to be proven (first successful call included it). |

Same body size (1,828,413) also returned for `?tree=16` and `?dv=16`. Those query strings do not select a different payload. They were not saved as extra files.

Config inside the document (not from the HTML page):

```json
{"tree":16,"tileVersion":"v3","staticPath":"/images/wow/classicplus/world-map/v3","tileSize":256,"nativeZoom":7,"tileMinZoom":2,"hasBaseline":true,"canvasLeft":8192,"canvasWidth":44544,"canvasHeight":37888}
```

Manifest `generated`: `2026-09-22`, `version`: `v3`. Continents: kalimdor (map 1, 25088×28672), zephras-isle (map 2991, 6656×4096, canvasX 24576, canvasY 8192), eastern-kingdoms (map 0, 11776×21504, canvasX 32768, canvasY 8192).

Split JSON under `scrape/raw/*.json` is extracted from that one response for the adapter. It is not a second HTTP fetch.

## Counts vs 2026-10-29 audit

| dataset | pageData key | capture | records | audit target | vs target |
|---|---|---|---|---|---|
| places | `places` | `places.json` (96,697 B) | **894** | ≈894 | exact |
| pois | `pois` | `pois.json` (860,267 B) | **4,469** | ≈4,469 | exact |
| nodes | `nodes` | `nodes.json` (848,739 B) | **99 groups / 32,900 points** | ≈99 / ≈32,906 | −6 points (0.02%) |
| routes | `routes` | `routes.json` (126,788 B) | **160** | 160 | exact |
| voyages | `voyages` | `voyages.json` (3,995 B) | **14** | 14 | exact |

`zones.json` is **not** the places zone list. `wow.worldMap.classicplus.zones` is a 3-element tile-occupancy grid (`map`, `cell`, `rows`). Do not map it to `places.js` `zones`.

## Places → shipped `places.js` (Step 2b)

Shipped file is `{"zones":[…49], "landmarks":[…256]}` with records `{n, ll, mz}`. The live list is one array of 894 objects. **`kind` is the split. Do not dump all 894 into either array.**

| endpoint `kind` | count (records / unique names) | shipped bucket | evidence |
|---|---|---|---|
| `zone` | 44 / 44 | **`zones`** | 43/44 names are in shipped `zones` |
| `capital` | 6 / 6 | **`zones`** | all 6 names are in shipped `zones` (Orgrimmar, Thunder Bluff, Darnassus, and the other three capitals) |
| `town` | 52 / 52 | **`landmarks`** | all 52 names are in shipped `landmarks`, none in `zones` |
| `landmark` | 224 / 188 | **`landmarks`** | 165/188 unique names overlap shipped `landmarks`; 0 overlap `zones` |
| `subzone` | 568 / 556 | **neither** | 0 name overlap with shipped zones or landmarks. This is why 894 ≠ 49+256. Leave them out of `places.js` unless a later task adds a third array. |

Proposed writer inputs (do not invent a fourth kind filter):

- `zones` = places where `kind` in `{"zone","capital"}` → **50** records today (shipped 49). The only extra name is **Zephras Isle** (`kind:"zone"`, `new:true`, `uiMap:2521`, `area:16593`).
- `landmarks` = places where `kind` in `{"town","landmark"}` → **276** records / 240 unique names (shipped 256 records, 218 unique — shipped itself has 38 duplicate names). Name-level extras vs shipped landmarks: 23 landmark names, all new geography (Fairweather Stables, Falaath Village, Shen'dar Highlands, Skywall, Valanaar, …). Shipped landmarks **not** in live town|landmark: `Sandworm!`, `Under Attack` (2). Duplicate live landmark names (13 names, 2 records each) include Timbermaw Hold, The Talondeep Path, and the faction base camps — the adapter must not collapse them blindly or it will drop a second entrance.

Field mapping:

| endpoint | shipped | rule |
|---|---|---|
| `name` | `n` | string, unchanged |
| `x`, `y` | `ll` | **pixels, not 0–1.** See coordinate section. `ll` is `[lat, lng]` = `[y_norm, x_norm]`. |
| *(absent)* | `mz` | not in this payload. Shipped values are only `0` and `4`. Do not invent `mz` from `uiMap` / `area` / `side`. Keep a documented default only if a later task says so. |
| `kind` | *(array choice)* | see table above. Not a stored field. |
| `rect`, `area`, `uiMap`, `side`, `levels`, `minZoom`, `roomZoom`, `new` | *(drop for places.js)* | not in the shipped record. Useful for Zephras (`new`, `levels`) but out of the current schema. |

Coordinate check: for all **49/49** shipped zone names, rounding to 6 decimals of

```
lat = (29696 - y) / 29696
lng = x / 44544
```

reproduces shipped `ll`. That 29696 is the **old** canvas height (README / 2026-10-29 audit), **not** live `canvasHeight` (37888). Using 37888 does not reproduce shipped coords. Live `x`/`y` for current places still fall inside the old half-open window (`y` 5936–28464, `x` 12906–43024), including Zephras Isle (`x:28816`, `y:10334`). Node/route/voyage points were not re-checked against the half-open rule in this probe.

## Other dataset field mapping (for the adapter; not a second URL)

### pois (`pois` → `window.WH_POIS` objects)

4,469 objects. Always present: `npc`, `name`, `x`, `y`, `category`, `side`, `level`.

| endpoint | shipped | notes |
|---|---|---|
| `name` | `n` | |
| `category` | `c` | e.g. `innkeeper`, `stable-master`, `flight-master`. Top categories include `quest-giver` (1569), `rare` (326), `dungeon-quest-giver` (190). |
| `x`,`y` | `ll` | same pixel → 0–1 rule as places |
| `npc` | `npc` | int |
| `side` | `side` | 0/1/2 as shipped |
| `model`,`body`,`quests`,`levels`,`new`,`newLevel`,`instance`,`item`,`image`,`paths`,`wraps`,`group`,`groupName`,`groupWraps`,`slot` | *(not in shipped pois.js)* | present on subsets. Do not require them. |

### nodes (`nodes` → `window.WH_NODES` dict)

99 groups. Each element is `{category, points}` where `points` is `[[x, y, spawnIndex], …]` — **pixels plus a third integer 0–9** (counts: 0:1084, 1:1001, 2:2125, 3:4368, 4:6853, 5:7490, 6:5607, 7:2853, 8:1176, 9:343). Shipped `pts` are `[lat, lng]` pairs only. Drop index 2 unless a later task stores it. Group by `category` (already `herb-<slug>` / `ore-<slug>` / `fish-<slug>` / `leather-<slug>` / `cloth-<slug>`).

| prefix | groups | points |
|---|---|---|
| herb | 34 | 10,686 |
| ore | 27 | 9,137 |
| fish | 28 | 12,203 |
| leather | 5 | 598 |
| cloth | 5 | 276 |
| **total** | **99** | **32,900** |

Leather categories: `leather-light-leather`, `leather-medium-leather`, `leather-heavy-leather`, `leather-thick-leather`, `leather-rugged-leather`. Cloth: `cloth-linen-cloth`, `cloth-wool-cloth`, `cloth-silk-cloth`, `cloth-mageweave-cloth`, `cloth-runecloth`.

### routes (`routes` → `window.WH_ROUTES`, no shipped file yet)

160 objects: `{path, category, vessel, color, points}`. `points` are `[[x,y], …]` pixels (no third component). `category` is `"routes"` on the sample. Vessels: flight-master 145, ship 9, zeppelin 5, tram 1.

### voyages (`voyages` → `window.WH_VOYAGES`, no shipped file yet)

14 objects: `{path, vessel, stops, legs, yards, dwell, rides}`. `stops[]` is `{x, y, name, side, dwell}` in pixels. Vessels: ship 8, zeppelin 3, airship 2, tram 1. `path` joins to `routes[].path` (sample path 241 = Ratchet ↔ Booty Bay ship).

## URLs tried that did not yield datasets

Headers: UA above. Where noted, also `Referer: https://www.wowhead.com/` or `https://www.wowhead.com/forever/world-map`, `Accept` for HTML or JSON, and an empty cookie jar (`--cookie ""`). No cookies were stored or sent.

| URL | status | bytes | notes |
|---|---|---|---|
| `https://www.wowhead.com/forever/world-map` | **403** | 919 | UA only. CloudFront "Request blocked." Saved `raw/page.html` + `page.headers`. |
| same URL | **403** | 919 | retry: Referer `https://www.wowhead.com/`, Accept HTML, empty cookie jar. Saved `raw/page-referer.html` + `page-referer.headers`. Still CloudFront, different `x-amz-cf-id`. |
| `https://www.wowhead.com/forever/world-map/data` | 403 | 919 | CloudFront |
| `https://www.wowhead.com/data/world-map?tree=16` | 403 | 919 | CloudFront |
| `https://www.wowhead.com/nether/data/world-map` | 403 | 919 | CloudFront |
| `https://nether.wowhead.com/data/world-map` | 404 | 2152 | Wowhead "Twisting Nether" 404, not WAF |
| `https://nether.wowhead.com/data/world-map?tree=16` | 404 | 2152 | same |
| `https://nether.wowhead.com/forever/data/{maps,places,pois,nodes,routes,voyages}` | 404 | 2152 each | separate dataset paths do not exist |
| `https://nether.wowhead.com/classicplus/data/world-map?tree=16` | 404 | 2152 | product segment is `forever`, not `classicplus` |
| `https://wow.zamimg.com/images/wow/classicplus/world-map/v3/` | 403 | 548 | nginx directory listing forbidden. Not a JSON endpoint. Tile pattern not fetched (out of scope). |
| `https://wow.zamimg.com/data/world-map` | 404 | 548 | nginx |

`https://nether.wowhead.com/forever/data/gear-planner?dv=100` returned 200 / 6,811,912 bytes during the probe and was **deleted**. It is not a map dataset.
