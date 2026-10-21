# World rendering and forest changes

The subsequent mountain/character update is documented in `CHARACTER_ELEVATION.md`.
The validation measurements below describe the initial terrain revision.

The game still starts with `python3 main.py`; multiplayer starts with `python3 server.py`.
Use the updated server and client together for synchronized harvesting. No new packages
or generated image assets are required. `main2.py` remains unchanged as the original reference.
Original source backups are in `.backups/terrain-original/`.

## Findings

- World generation uses seed-driven island placement, a radial coastline function and
  two Perlin noise layers. `heights[y][x]` determines ocean, shallow water, sand, grass
  and mountain. `owners[y][x]` identifies islands. Roads and buildings are coordinate
  sets; resources are independent objects. There were no iron-resource entities,
  elevation tiers, or explicit forest biome IDs.
- `assets/terrain/overworld/Fall Tile Set.png` is a **1448 × 1086 illustrated atlas**, not a uniform sprite sheet.
  The old coordinates crossed artwork categories, white gutters and printed labels.
  For example, the old path rectangle `(818,178,64,62)` sampled forest-floor artwork;
  the old oak rectangle `(20,352,78,94)` sampled cliffs. Houses and resource nodes
  also used unrelated sections. The problem was crop definitions and grouping,
  not a terrain-enum off-by-one error.
- Cropping the pictured tile frames included their white corners/borders. Scaling
  those frames to 48 × 48 created a visible grid even where destination rectangles
  abutted correctly. Independently selecting incompatible shoreline illustrations
  compounded the problem; the old `if/elif` handled only one shore configuration.
- A separate `world.trees` list rendered non-harvestable objects. Ports were created
  after resources/trees, so newly added port roads could cross existing objects.
- All resources were nonblocking. Only water/land boundaries and buildings prevent
  walking; mountains slow movement. These collision rules are preserved.
- The original server relayed only player positions. Harvests and 30–40 second respawns
  existed independently on each client. There were no persistent resource IDs.
- The installed noise library interprets seed zero as a random seed. Zero now uses
  explicit deterministic noise seeds, while nonzero positive-seed geography stays intact.

## Implementation

### Shared world generation (`modules/worldgen.py`)

The original world structures, terrain generation, villages, ports, minimap data and
collision queries now have one implementation shared by client and server. Heights,
buildings and roads for seed 42 match `main2.py`, including its port routes.

Ports are finalized before resources, and generation is idempotent. Seeded broad/fine
woodland noise creates stands, sparse edges, clearings and occasional lone trees.
Trunks have jittered positions and minimum separation. Road/building surroundings,
village props and spawn/landing areas are reserved. Resource positions also pass the
existing player-footprint collision query. Autumn oaks dominate lowland; pines appear
on upper grass slopes. Palms are not used.

Every tree is now an `Odun` resource. A stable `type:x:y` ID, species and variant are
stored on each node. Chopping replaces its canopy with a stump until respawn. Grain
and stone remain the existing gameplay types, with their original minigames and
30–40 second respawn range. The interaction key chooses the nearest active resource.

### Verified atlas and transitions (`modules/terrain_render.py`)

`GROUND_RECTS` and `OBJECT_RECTS` document every source region. Terrain samples only
verified interiors. Objects use isolated complete crops with ivory-paper removal;
only actual stone artwork represents `Tas`, and only wheat represents `Tahil`.

Ground materials are quilted from atlas pixels into continuous 16 × 16 tile patches,
with irregular, binary patch masks and periodic wrapping. They preserve sampled
colors and avoid independently randomized tile borders. All gameplay terrain is
composed at 24 art pixels then scaled to 48 screen pixels with nearest-neighbor scaling.

A nine-bit occupancy mask (center plus eight neighbors) selects cached transition
masks. Interpolated occupancy is thresholded into **binary pixel coverage**, not blurred
color. Cumulative layers cover multi-material junctions; irregular vegetation masks
soften forest/grass/dirt boundaries. Shoreline foam follows the land mask and handles
straight shores, concave/convex corners, opposite shores and diagonal joins. Paths
use all eight neighbors: cardinal arms connect, and matching diagonal neighbors fill
plazas. Rock wall bands are confined to south-facing mountain edges. Roads suppress
rock overlays even beside high ground.

All tall objects and players share one sort by their ground/foot position. Ground
chunks contain no trees, harvested resources, buildings or players. Rendering rounds
the camera once, and tile/chunk destinations are integer multiples of 48. Resizing
scales the completed framebuffer rather than independently resizing tiles.

### Networking (`modules/multiplayer.py`, `server.py`)

The server uses the same generator and owns depleted-resource deadlines. Updated
clients negotiate world version 2, send sequenced harvest requests, and receive sparse
resource snapshots and acknowledgements. The server validates IDs, gathering distance,
sailing state and already-depleted nodes. Duplicate requests cannot extend cooldowns.
Partial writes, fragmented reads and multiple newline-delimited messages are retained.
Late joins receive current resource state, and synchronization continues during pause.
Reconnection to a different seed is rejected rather than attaching another world's
resource state to an already-loaded map.

Legacy position-only clients still receive the old player dictionary. They do **not**
receive the new forests/resource synchronization; use updated clients for shared
harvesting. Movement and minigame completion remain client-driven as before: this is
resource-state authority, not an anti-cheat or persistence system.

### Loading and performance

CPU world/neighbor data is prepared in the existing preload worker. Pygame surface
operations remain on the display thread, with atlas construction and initial viewport
warming spread across menu frames. Terrain is cached in 8 × 8 tile chunks; only
visible chunks draw. Chunk caches are bounded to 96 entries and composed variants to
4,096 entries. Per-frame work does not regenerate texture pixels or transition masks.

## Validation

Run the regression suite:

```sh
python3 -m unittest discover -s tests -v
```

Run the actual resizable Pygame window and regenerate screenshots/performance results:

```sh
python3 validation/visual_check.py --window
```

Omit `--window` for the SDL offscreen driver. Tests automatically use that driver.

All **17 tests passed**. They cover repeated generation at four seeds (including zero),
terrain restrictions, clustered density, unique IDs, original geography/collision,
port access, real chopping input/canopy removal/respawn, nearest-node interaction,
atlas-gutter checks, all 512 neighborhood configurations, connected paths/plazas,
pixel-grid camera shifts, resizing, depth order, atlas fallback, sailing, map/pause,
real TCP clients, late join, authoritative respawn, paused synchronization, partial
socket writes, duplicate/rejected requests, seed mismatch and legacy framing.

The real macOS Cocoa window was exercised through menu, customization, background
preloading, gameplay, harvesting, resizing, map, pause and return to menu. The actual
`server.py` entry point was also started and tested with two clients and a shared harvest.

| Seed | Harvestable trees |
| --- | ---: |
| 0 | 892 |
| 42 | 1,058 |
| 137 | 1,025 |
| 2026 | 777 |

Seed 42 originally had 49 harvestable trees, plus unrelated non-harvestable decorations.
On this machine, 540 gameplay update/render/display samples averaged **2.94 ms**
(p95 **4.33 ms**). An additional 480 frames traversing uncached chunks had p95
**4.46 ms**, maximum **6.92 ms**. These measure work per frame, excluding the 60 Hz
frame limiter; they are not a hardware-independent FPS guarantee. Background preload
completed in **2.49 seconds**; the largest main-thread preload poll was **43.6 ms**,
including image decode/setup. Initial visible chunks are ready before entering gameplay.

Artifacts:

- `validation/window_report.json`, `validation/tests.log`, `validation/server_startup.log`
- `validation/menu.png`, `validation/customization.png`, `validation/world_map.png`
- `validation/seed_<seed>_village.png`, `_forest.png`, `_coast.png`
- `validation/seed_<seed>_tree_before.png`, `_tree_after.png`
- `validation/objects.png`, `validation/shoreline_masks.png`

## Atlas limitations

The source has only one complete oak, one pine and two complete usable houses; variation
uses those real sprites and flips, without substituting bushes/palms/ores. It does not
provide a complete matching terrain/shore/cliff autotile set. Missing connections use
pixel masks and appropriate source textures; cliffs are modest terrain edge bands,
not a new elevation/collision system. Large ground materials eventually repeat.
Trees remain nonblocking. The subsequent character update uses `manchar` in gameplay;
the compact procedural player is now only a missing-asset fallback.
