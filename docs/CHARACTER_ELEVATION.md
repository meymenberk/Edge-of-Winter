# Character animation and mountain elevation

Start the game with `python3 main.py`. The server protocol, authoritative terrain,
resource IDs, forests, collisions and harvesting rules have not changed.

## `manchar` extraction and animation

`modules/character_animation.py` resolves the canonical gameplay sheet at
`assets/characters/player/manchar.jpeg`. Its compatibility lookup still accepts
PNG/JPG/JPEG/WebP files beginning with `manchar` for isolated tools and tests. The
current file is 1448 × 1086 pixels.

The actual artwork contains four rows of four poses, with substantial outer margins
and uneven spacing. Row order is **down, right, up, left**. Both side directions are
present and used directly. Foreground projections identify the row/column bands;
individual silhouette bounds are recorded in `CharacterSheet.source_rects`. The
image is not divided into sixteen equal cells. JPEG paper/ringing is removed with
binary transparency, preserving colored pixels.

All frames use one scale, a 40 × 56 canvas, and the same feet anchor `(20, 54)`.
Torso alignment avoids horizontal shifts caused by different arm/boot silhouettes.
Every visible frame ends on the same baseline. Nearest-neighbor scaling uses two
screen pixels per art pixel; no filtering is applied.

Each actor owns a `CharacterAnimator`. `GameSession.update()` advances the local
animation from actual movement and delta time, including the existing mountain/road
speed modifiers. Blocked movement, idle and pause stop the local cycle. Direction
switches select the corresponding row. Rendering only selects/blits the current
cached pose; additional render calls cannot advance animation.

Remote players have independent animation state, driven by the existing synchronized
`moving`, `facing`, position and sailing fields. Disconnected actors are removed.
Boats retain their existing rendering. The sheet loads during preload on the display
thread and is shared by local and remote actors. A missing file retains the old
fallback; an invalid supplied sheet reports a preload error instead of silently
ignoring it.

## Mountain geometry

`elevation.py` derives connected visual tiers from the existing height field:

| Tier | Height threshold | Maximum south face |
| --- | ---: | ---: |
| Lower mountain | 0.48 | 44 screen pixels |
| Upper terrace | 0.65 | 32 screen pixels |
| Summit | 0.81 | 24 screen pixels |

Small isolated spikes and tiny fragments left by access clearings do not become
standalone pillars. The larger nested contours follow actual mountain heights.
Roads, buildings and their immediate access aprons are excluded from tall faces.

The renderer uses a verified interior of the tall cliff column in `Fall Tile Set`
for vertical faces. Plateaus keep their separate stony top material, with lighter
upper tiers, narrow cap highlights, darker side faces and basal contact shadows.
Faces are inset within mountain footprints, so they cannot cover roads or normal
land, and world/player anchors need no coordinate offsets. Existing mountain
walkability and slower movement remain intact.

Geometry includes neighboring terrain beyond the chunk boundary, so top/face masks
are identical whether rendered in an 8-tile chunk or a larger region. Composition
runs when building a cached chunk, not every frame. The existing preload warms the
initial viewport; spare draw time prepares one neighboring chunk for walking/sailing.
Caches remain bounded.

## Validation

```sh
python3 -m unittest discover -s tests -v
python3 validation/check_elevation_character.py --window
```

Omit `--window` for offscreen SDL rendering. The checks cover:

- All sixteen actual poses, directional row mapping, true left-facing artwork,
  transparency, common feet baseline, crisp scaling and asset lookup variants.
- Delta-time consistency, idle/turn/slope speed, render independence, real directional
  movement, collision-blocked idle and independent remote-player state.
- Deterministic tiers, unchanged authoritative world data, exact road/building pixel
  preservation and pixel-identical mountain composition across chunk boundaries.
- The previous terrain/resource/network regression suite.
- Real macOS Pygame startup, menu/customization, actual movement input, two TCP peers
  walking in all four directions and stopping, four world seeds, resizing, map/pause,
  and traversal through uncached mountain terrain.

Results and captures are in `validation/elevation_character/`:

- `tests.log` — complete test result.
- `window_report.json` — current measurements, including forced cold viewport rebuilds.
- `walking_in_game.png` — all sixteen poses captured during actual gameplay updates.
- `multiplayer.png` — two TCP-connected actors using `manchar`.
- `seed_<seed>_mountain.png`, `seed_<seed>_village.png` — seeds 0, 42, 137 and 2026.

## Remaining asset/gameplay limits

The sheet provides four poses per direction and no separate idle set; idle freezes
its first pose. JPEG compression and the supplied pose differences limit animation
detail. The menu customization artwork remains its existing system; it does not
recolor the flattened `manchar` sheet.

Cliffs reuse the supplied rock-face material, so close inspection reveals repetition.
Elevation is a terrain-derived visual representation, not a new 3D physics system:
there are no blocked drops, fall damage or new climbing mechanics. Players retain
the original ability to traverse mountain terrain at its slower movement speed.
