# Python Module Migration

The project has no Git metadata. This manifest records the completed structural
migration and preserves the original-to-final mapping.

## Entry points kept at project root

- `main.py`
- `server.py`

## Runtime package moves

| Original | Destination |
|---|---|
| New centralized audio runtime | `modules/audio_manager.py` |
| `autumn_leaves.py` | `modules/autumn_leaves.py` |
| `character_animation.py` | `modules/character_animation.py` |
| `economy.py` | `modules/economy.py` |
| `elevation.py` | `modules/elevation.py` |
| `game_ui.py` | `modules/game_ui.py` |
| `gameplay_systems.py` | `modules/gameplay_systems.py` |
| `multiplayer.py` | `modules/multiplayer.py` |
| `pixel_sprites.py` | `modules/pixel_sprites.py` |
| `progression.py` | `modules/progression.py` |
| `terrain_render.py` | `modules/terrain_render.py` |
| `treant_boss.py` | `modules/treant_boss.py` |
| `worldgen.py` | `modules/worldgen.py` |
| New persistent launch settings (world seed, server address/port) | `modules/settings.py` |
| New English player-facing text, story and labels | `modules/localization.py` |
| New window scaling, letterboxing and mouse mapping | `modules/display.py` |
| New crash-safe offline save file (validated load, atomic write, backups) | `modules/save_game.py` |

## Preserved legacy reference

`main2.py` is an older self-contained client, is not imported by the current game,
and is preserved as `legacy/main2.py` rather than deleted or placed in the runtime
package.

New runtime code should use `modules.*` from root scripts/tests and package-relative
imports such as `from .worldgen import ...` from inside `modules/`. Shared filesystem
locations come from `modules.paths`; no `sys.path` modification is required.

Player-facing text lives in `modules/localization.py`; inventory keys, quest and
achievement IDs and network fields keep their original values for save and
protocol compatibility. `python tests/test_english_audit.py` reports any Turkish
literal that reaches runtime code. The server accepts `--host`, `--port` and
`--seed` (numeric or text) options.

Optional menu assets: the title logo is `assets/ui/menus/edge_of_winter_logo.png`
(text title if absent; an opaque logo's flat backdrop is keyed out at load) and the
menu soundtrack is `assets/audio/music/main_menu.wav` (.ogg/.mp3/.flac with the same
name also work; the menu is silent if absent or undecodable).

Offline progress is saved to `savegame.json` on return to the menu, on quit, every
60 s of play and shortly after rescues, keys and boss results. The previous save is
kept as `savegame.json.bak`, a save for another world seed is archived as
`savegame.seed-<seed>.json`, and an unreadable save is renamed to
`savegame.corrupt-<time>.json` instead of being overwritten. Online progress stays
server-owned and is never written locally.

Diagnostic scripts remain in `validation/`, tests remain in `tests/`, and the
older self-contained client remains in `legacy/`. Root-level diagnostic images
were preserved in `validation/root_diagnostics/`. Exactly `main.py` and
`server.py` are Python files at project root.
