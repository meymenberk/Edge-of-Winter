# PLATANUS Boss Encounter Integration

## Files and dependency

Keep the reusable module in the runtime package and the two verified atlases in
the dedicated PLATANUS asset directory:

- `modules/treant_boss.py`
- `assets/bosses/platanus/bossanim.png`
- `assets/bosses/platanus/bosstile.png`
- `TREANT_INTEGRATION.md`

Runtime dependencies are Pygame and NumPy. The module does not import `main.py`, initialize Pygame, create a window, connect to a server, or access save data during import.

Production loading is intentionally strict. `bossanim.png` must be the verified 1536x1024 atlas and `bosstile.png` the verified 1448x1086 atlas. Missing or resized files raise a descriptive exception; the standalone demo never silently substitutes placeholder artwork. Paths use `modules.paths.PROJECT_ROOT`, never the process working directory. Existing callers may still pass the project root or the atlas directory directly; if both a dedicated folder and loose legacy files exist, the dedicated folder wins. An explicit `allow_test_assets=True` constructor option exists only for isolated automated tests where the image files are deliberately absent.

Run the client, server, and standalone encounter from the project root with:

```bash
python3 main.py
python3 server.py
python3 -m modules.treant_boss
```

For a launch from another working directory, pass the absolute path for the two
root entry points and use `-m` with the project root as the working directory for
the package demo. No `PYTHONPATH` changes are needed. Application code imports the
encounter as `from modules.treant_boss import ...`; code already inside `modules/`
uses package-relative imports.

All production animation, material-tile, and mixed-size prop rectangles are hand-measured for these exact files. They are exposed for diagnostics as `encounter.assets.source_rects`, `tile_source_rects`, and `prop_source_rects`.

## Coordinate and ownership rules

Encounter coordinates are tile-space foot anchors, matching the current game. The default tile size is 48 pixels. A `BossPlayerState` is a read-only snapshot; the encounter never mutates the real player or maintains a second authoritative player-health value.

The encounter owns boss health. Player attacks enter through `register_player_attack()`. Boss attacks leave through one `PLAYER_HIT` event per player and unique attack ID. The host validates and applies those events. This split is important for multiplayer authority.

The arena entry point is available as `encounter.portal_spawn`, and `start()` also returns it. Move the real player there when transitioning from the overworld.

## Minimal existing-game integration

```python
from modules.treant_boss import (
    BOSS_DAMAGED,
    ENCOUNTER_COMPLETED,
    PLAYER_HIT,
    BossPlayerState,
    EncounterResult,
    PlayerAttack,
    TreantBossEncounter,
    TreantConfig,
)

# Run after the host has initialized Pygame and created its display.
encounter = TreantBossEncounter(
    config=TreantConfig(tile_size=48),
)

player.x, player.y = encounter.start(
    BossPlayerState(
        player_id=str(local_player_id),
        x=player.x,
        y=player.y,
        health=session.health,
        max_health=session.max_health,
    )
)

# In the host update loop, create a fresh snapshot from current authoritative data.
snapshot = BossPlayerState(
    player_id=str(local_player_id),
    x=player.x,
    y=player.y,
    width=0.36,
    height=0.72,
    health=session.health,
    max_health=session.max_health,
    facing=(facing_dx, facing_dy),
    invulnerable=session.damage_cooldown > 0,
)
encounter.update(dt, snapshot)

# Use the main combat system's already-computed active sword rectangle. Submit the
# same swing ID on multiple frames if convenient; duplicate IDs cannot damage twice.
if combat.attacking and sword_is_in_active_frames:
    x, y, width, height = combat.hitbox(player, session.facing)
    encounter.register_player_attack(PlayerAttack(
        attack_id=f"{local_player_id}:{swing_sequence}",
        player_id=str(local_player_id),
        x=x,
        y=y,
        width=width,
        height=height,
        damage=sword_damage,
    ))

for boss_event in encounter.consume_events():
    if boss_event.type == PLAYER_HIT:
        # Validate attack_id on the authority, then use the real health system.
        data = boss_event.data
        session.health = max(0, session.health - data["damage"])
        session.damage_cooldown = max(
            session.damage_cooldown, data["invulnerability"]
        )
        session.player_knockback.update(data["knockback"])
    elif boss_event.type == BOSS_DAMAGED:
        # This is a confirmed hit: award XP here if desired. Empty swings emit none.
        confirmed_damage = boss_event.data["damage"]
    elif boss_event.type == ENCOUNTER_COMPLETED:
        if boss_event.data["result"] == EncounterResult.VICTORY.value:
            return_to_overworld_after_victory()
        else:
            use_existing_player_defeat_flow()

# Render into the existing display. Camera values are pixel offsets, as in main.py.
encounter.render(display_surface, (camera_x, camera_y))
```

The main game can keep ownership of its player sprite and attack effects while
letting the encounter depth-sort them against the foreground gate:

```python
encounter.render(
    display_surface,
    camera,
    (player.y, lambda target, cam: draw_real_player(target, cam)),
    lambda target, cam: draw_real_attack_effects(target, cam),
)
```

The two transition calls in the example deliberately stand for project-owned behavior: the encounter emits the result but does not own overworld state, quests, rewards, menus, saves, or respawning.

## Player movement and collision

Use the host's normal movement input and animation. For arena boundaries, apply the encounter's axis-separated helper before committing the new position:

```python
player.x, player.y = encounter.constrain_motion(
    (player.x, player.y),
    (desired_x, desired_y),
    half_width=0.18,
)
```

This prevents leaving the finite island and blocks its large decorative trees/ruins. The camera does not enforce gameplay boundaries.

## Existing sword combat

Keep the main game's input, combo timing, cooldown, animation, and active-frame calculation. During an active frame, translate its hitbox to `PlayerAttack`. Use a stable unique ID for the entire swing, such as player ID plus a monotonically increasing swing sequence. `register_player_attack()` returns `True` only for a newly accepted boss hit. Once an ID lands, that ID cannot damage again. A collision miss may be resubmitted during the same active swing window, while a non-positive hit, phase transition, or defeated boss returns `False` and emits no damage event.

Award combat XP only from `BOSS_DAMAGED`, never from the attack button or empty swing. Walking into the boss does not call `register_player_attack()` and therefore does no damage.

## Boss damage to players

Every `PLAYER_HIT` payload contains:

- `player_id`
- unique `attack_id`
- `attack` (`arm` or `earthquake`)
- `damage`
- `knockback` as a world-space `(x, y)` velocity
- suggested `invulnerability` duration

The module emits at most one hit for a given player and boss attack. The host remains free to reject the event (for example because the server knows the player dodged), scale damage, apply armor, start its own invulnerability timer, and replicate the outcome.

Pass the real current health back in the next `BossPlayerState`. When it reaches zero, the encounter emits `PLAYER_DEFEATED` once. If no living supplied players remain, it sets `EncounterResult.DEFEAT` and emits `ENCOUNTER_COMPLETED` once.

## Camera and rendering

`render(surface, camera)` accepts:

- `None`: center the arena relative to the supplied surface;
- `(camera_pixel_x, camera_pixel_y)`;
- an object with numeric `x` and `y` pixel-offset attributes.

The encounter caches its arena, tiles, props, animation frames, and shadow. Rendering performs no atlas cropping. The boss uses a logical foot-anchored hitbox independent of antlers, leaves, arms, and visual jump height. `camera_shake` changes rendering only; world coordinates remain stable.

If the host depth-sorts every world object itself, render the encounter to its own transparent/world layer or keep the encounter arena as a dedicated game state. The public API intentionally does not expose private animation fields as gameplay signals; consume events for all state changes.

## Optional custom-atlas crop override

The shipped atlas needs no configuration. If a later art revision keeps the same 1536x1024 canvas but moves one animation, supply rectangles only for the sequence being replaced; omitted names retain the verified defaults:

```python
rects = {
    "arm": [(x, y, width, height), ...],
}
encounter = TreantBossEncounter(assets_dir, animation_rects=rects)
```

These are real constructor parameters and animation keys. Rectangles are clipped safely to the image and exact frame counts are validated. The loader cleans faint background haze while preserving dark wood outlines, scales with nearest-neighbor sampling, and foot-aligns every frame to an identical canvas.

The painted source contains seven distinct roar poses, three distinct hurt poses, and seven usable jump positions despite its headings advertising 8/4/8. The loader deliberately holds the roar peak, hurt impact, and jump apex once to provide the expected counts without inventing frames or including labels. This affects timing only; all visible poses still come from `bossanim.png`.

## Current three-key portal quest

`main.py` now owns key inventory and quest checks through `TreantQuestProgress`.
Each distinct rescued village can award one key, capped at three. Once it confirms
three keys and the player activates the overworld portal:

1. Switch the host game state to its boss-arena state.
2. Construct or reset the encounter.
3. Call `start()` and place the real player at the returned portal spawn.
4. Run the normal adapter/update/event/render flow.
5. On `ENCOUNTER_COMPLETED`, record quest/reward state in the host and transition back to an overworld spawn selected by the host.

The encounter module itself still makes no key, portal-quest, reward, or save-format
assumptions. `GameSession` keeps the same world and inventory objects across the
encounter, grants **Lanet Kıran** once after victory, shows the PLATANUS result
overlay, and restores the player beside the Kızılkök portal.

## Authoritative multiplayer boundary

Run boss AI and `register_player_attack()` only on the authority (normally the server or elected host). Send it all current `BossPlayerState` snapshots and unique player attack IDs. Broadcast:

- events from `consume_events()` for reliable one-shot outcomes;
- periodic `get_state_snapshot()` data for boss position, state, phase, HP, attack ID/direction, and jump center.

Clients render replicated state and send attack intents; they should not independently subtract boss HP. The snapshot is plain data and event objects provide `to_dict()`. Do not reuse an attack ID after reconnect. Server-side deduplication should persist for at least the encounter lifetime, even though the encounter also deduplicates locally.

The current protocol authoritatively validates village rescues, portal unlocking,
encounter entry, movement bounds, attack timing/hitboxes/damage, player damage,
victory, and return position. It advertises `treant_boss_authority=True`; clients
submit attack intents and render the server's `get_state_snapshot()` payload. Boss
HP and achievement eligibility are never accepted from a client payload.

Call `cleanup()` when permanently leaving the arena. For a retry, creating a new encounter or calling `start()` resets all combat state and one-shot guards.
