"""Reproducible screenshots, real app startup, and frame measurements.

python3 validation/visual_check.py --window    # real resizable Pygame window
python3 validation/visual_check.py             # offscreen SDL, same game renderer
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--window', action='store_true')
args = parser.parse_args()
if not args.window:
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pygame
import numpy as np
import main
from modules.terrain_render import TileAtlas

OUT = Path(__file__).resolve().parent
app = main.AutumnGameApp()
report = {'display_driver': pygame.display.get_driver(), 'seeds': {}}
poll_times = []
start = time.perf_counter()
app.render()
pygame.image.save(app.menu_surface, str(OUT / 'menu.png'))
while app.preloader.status not in (main.PreloadStatus.READY, main.PreloadStatus.ERROR):
    if time.perf_counter() - start > 20:
        raise TimeoutError('Preloader failed to become ready')
    app.clock.tick(60)
    app.handle_events()
    t = time.perf_counter()
    app.preloader.poll(app.customization)
    poll_times.append((time.perf_counter() - t) * 1000)
    app.render()
assert app.preloader.status == main.PreloadStatus.READY, app.preloader.status_text
report['preload_seconds'] = time.perf_counter() - start
report['preload_poll_max_ms'] = max(poll_times)
app.trigger_menu_action('Customize')
app.render()
pygame.image.save(app.menu_surface, str(OUT / 'customization.png'))
app.trigger_menu_action('Start Game')
assert app.state == 'GAME'
session = app.preloader.game_session
atlas = session.atlas
assert atlas is not None


def at(pos):
    session.player.update(pos)
    session.previous_pos = tuple(session.player)
    session.cam_x, session.cam_y = main.get_local_camera(session.player)
    session.fishing.close()
    session.fishing.zoom_level = 1
    session.is_sailing = False
    session.map_open = session.paused = False


def capture(name):
    app.render()
    pygame.image.save(app.game_surface, str(OUT / f'{name}.png'))


frame_ms = []
for seed in (0, 42, 137, 2026):
    world = main.make_world(seed)
    tiles = pygame.image.frombuffer(main.compute_tile_pixels(world), (main.COLS, main.ROWS), 'RGB').convert()
    session = main.GameSession(world, world.ports, main.find_spawn(world), tiles, None, seed, app.customization, atlas)
    app.preloader.game_session = session
    report['seeds'][seed] = dict(Counter(n.type for n in world.nodes))
    locations = {'village': main.find_spawn(world), 'forest': max(world.woodland, key=world.woodland.get),
                 'coast': (world.ports[0].x + .5, world.ports[0].y + .5)}
    for name, pos in locations.items():
        at(pos)
        capture(f'seed_{seed}_{name}')
        # Move the camera through fractional coordinates and chunk boundaries.
        for frame in range(45):
            app.clock.tick(60 if args.window else 0)
            app.handle_events()
            session.cam_x += .75
            t = time.perf_counter()
            session.update(1 / 60, (0, 0))
            app.render()
            frame_ms.append((time.perf_counter() - t) * 1000)
    # Exercise harvesting through the actual event handler and draw both states.
    tree = next(n for n in world.nodes if n.type == 'Odun' and
                all(np.hypot(n.x - p.x, n.y - p.y) > 4 for p in world.ports))
    at((tree.x, tree.y))
    capture(f'seed_{seed}_tree_before')
    session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e), (0, 0))
    assert session.wood_game.node is tree
    session.wood_game.bar_pos = 200
    session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE), (0, 0))
    assert not tree.active
    capture(f'seed_{seed}_tree_after')

# Resizing, map, pause and return-to-menu use the real app state / scaling pipeline.
for size in ((800, 600), (1537, 999), (1200, 780)):
    app.window = pygame.display.set_mode(size, pygame.RESIZABLE)
    app.update_letterbox()
    app.render()
    assert app.window_to_logical((app.offset_x, app.offset_y)) == (0, 0)
session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m), (0, 0))
capture('world_map')
session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m), (0, 0))
session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE), (0, 0))
capture('pause')
action = session.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1), session.pause_menu_rect.center)
assert action == 'MENU'
app.state = action
app.update_letterbox()
app.render()

# Explicit transition gallery: 256 8-neighbor shoreline configurations with land centers.
gallery = pygame.Surface((16 * 48, 16 * 48))
for index in range(256):
    low, high = index & 15, (index >> 4) << 5
    mask = low | high | 16
    tile = atlas.compose((511, mask, 0, 0, 0, 0), -1, index, False)
    gallery.blit(tile, ((index % 16) * 48, (index // 16) * 48))
pygame.image.save(gallery, str(OUT / 'shoreline_masks.png'))
# Traverse uncached chunks at sailing speed; include composition costs in timings.
at((100, 110))
session.terrain_renderer.chunks.clear()
traversal_ms = []
for frame in range(480):
    app.clock.tick(60 if args.window else 0)
    app.state = 'GAME'
    app.update_letterbox()
    session.player.update(100 + frame * .14, 110)
    session.previous_pos = tuple(session.player)
    session.cam_x, session.cam_y = main.get_local_camera(session.player)
    t = time.perf_counter()
    app.render()
    traversal_ms.append((time.perf_counter() - t) * 1000)
report['traversal_p95_ms'] = float(np.percentile(traversal_ms, 95))
report['traversal_max_ms'] = max(traversal_ms)
report['game_frame_mean_ms'] = float(np.mean(frame_ms))
report['game_frame_p95_ms'] = float(np.percentile(frame_ms, 95))
report['game_frame_max_ms'] = max(frame_ms)
report['frames_measured'] = len(frame_ms)
report['composite_cache_entries'] = len(atlas.composites)
(OUT / ('window_report.json' if args.window else 'headless_report.json')).write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if app.preloader.network:
    app.preloader.network.close()
pygame.quit()
