The current `main.py` gameplay session uses `modules/game_ui.py` for the resource strip,
five-heart health display and charts, and `modules/autumn_leaves.py` for local canopy
particles. Inventory accounting, harvesting, character animation, network
messages, and the server remain on their existing gameplay paths. Snapshots from
before both UI passes are in `.backups/`.

The HUD has original 16×16 pixel icons enlarged to 32×32 with nearest-neighbor
scaling: bag, trade, wood, stone, wheat, fish, rescued islands, and cost inflation.
A bundled code-defined bitmap alphabet supports Turkish accents. Counts come
directly from the existing inventory and economy state. Hovering reveals names
and exact values; very large values use smaller digits or a shortened display.
The bag and trade buttons retain I/Tab and T controls. The sailing wind indicator
has moved below the minimap to avoid overlap.

The north-up minimap displays a local 128×76-tile area around the player in a
200×120 image. Both map sizes use the same cached terrain artwork, including
coastlines, water depth, roads, buildings and woodland tint. Live overlays show
the player, other players, island ownership, ports, and the camera footprint.
Nearby medieval island names are placed with overlap rejection. Woodland tint
represents terrain coverage, not live individual tree counts.

Click the minimap or press M to open the full chart. The wheel zooms around the
cursor and left-drag pans; M, ESC, or the close button returns to gameplay. The
lower island-rescue drawer and the rescue chart in the inventory use the same
wheel/drag camera. Closing a panel releases any active drag. The chart consumes
local movement/combat input while open, while timers and multiplayer sync keep
their existing behavior.

Health now renders as exactly five crisp pixel hearts. The existing 0–8 health
scale is preserved and converted at display time into ten half-heart units, so
damage, healing, saves and multiplayer values do not change. Each heart has full,
half and empty art drawn on a 9×8 grid and enlarged with integer scaling.

World generation assigns seed-stable, unique medieval names such as Dawnrest,
Whitekeep and Ironwatch. Naming uses its own seeded random stream, so it does not
shift island placement or resource generation. `WORLD_VERSION` is 6 because the
generated island metadata changed.

The darkest grass and forest-floor pixels receive a selective warm ochre lift
during tile extraction. Midtones and highlights stay intact, keeping the original
texture while separating the floor from dark trunks and evergreen foliage.

Open-water fishing now keeps four moving fish with three pixel-art silhouettes.
One interested fish approaches and circles the hook while nearby fish avoid it;
high tension can make the hooked fish flee. The mouse wheel changes line length,
adds or releases tension, and reels a close fish toward a catch. The rod has a
wood shaft, highlight, handle, reel, line, bobber and hook. Existing entry/exit
and inventory reward callbacks are retained.

Leaves emit from active nearby oak nodes, using the actual canopy sprite size.
Pines are evergreen and do not emit broad autumn leaves. Sources are indexed in
8-tile buckets; candidate selection refreshes every quarter-second within
12 tiles of the player and is culled to the camera. Harvested trees stop
immediately and resume after their existing respawn system reactivates them.
Particles are anchored in world coordinates and remain on land, outside house
footprints. Modal screens suppress the effect. Density scales with local oaks,
with at most 32 particles and cached pixel sprites. Menu ambience is separate
and retains its existing behavior.

Validation commands:

```sh
python3 -m unittest discover -s tests -p test_hud_map_leaves.py -v
python3 -m unittest tests.test_health_map_fishing -v
python3 validation/check_hud_map_leaves.py --window
python3 validation/check_health_map_fishing.py --window
```

All 16 focused tests pass, including resource count rendering, map input/close/reopen,
movement recovery, multiplayer updates while viewing the map, world-edge marker
projection, tree harvest/respawn, coast restrictions, particle camera anchoring,
UI suppression, health states, deterministic names, both map cameras, terrain
tone, fish variants, reeling, escape and rewards. The real Cocoa/Pygame app was launched through
its normal menu and background preloader. Screenshots and results are in
`validation/hud_map_leaves/` and `validation/health_map_fishing/`. Window clicks were verified at 800×600 and 1537×999.
The final 210-frame forest sample measured 4.52 ms p95 for update/render/display,
with 15 leaves around 16 oaks; ocean and bare-mountain checks had zero leaves.
These measurements cover the sampled scene, not every world/combat scenario.

The complete 65-test regression run passed 62 tests. Remaining failures are
existing issues, verified using the saved original implementation:

- Naval firing test: its 0.1 + 0.7 second updates fall just below the 0.8 second
  firing threshold because of floating-point rounding.
- Legacy geography test: compares the current 640×384 world against `main2.py`'s
  older 400×240 world. The runner used ordinary list equality for this assertion
  to avoid spending minutes constructing a giant nested-list diff; the assertion
  still ran and failed. No tests were skipped or changed.
- Multiplayer respawn test: intermittent queued sailing state races with the
  test's direct server-state manipulation. The original build reproduced both
  passing and failing runs. A rejected finishing attack had `sailing=True` on
  the target. See `pvp_diagnosis.log`; network/server code was not modified.

`baseline_confirmed.log` records the original 49-test suite (47 passing, two
deterministic failures). `regression_tests.log` records the current 60-test run.
`final_focused_tests.log` includes all 11 new passing tests and three reproductions
of the existing intermittent network failure.
