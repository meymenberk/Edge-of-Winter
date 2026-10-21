"""Launch the real app, drive HUD/map events, capture scenes and time frames.

python3 validation/check_hud_map_leaves.py --window
python3 validation/check_hud_map_leaves.py  # same rendering using offscreen SDL
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--window", action="store_true")
args = parser.parse_args()
if not args.window:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pygame
import numpy as np
import main

OUT = Path(__file__).resolve().parent / "hud_map_leaves"
OUT.mkdir(exist_ok=True)
app = main.AutumnGameApp()
report = {"driver": pygame.display.get_driver()}
start = time.perf_counter()
try:
    while app.preloader.status not in (main.PreloadStatus.READY, main.PreloadStatus.ERROR):
        if time.perf_counter() - start > 40:
            raise TimeoutError(app.preloader.status_text)
        app.clock.tick(60)
        app.handle_events()
        app.preloader.poll(app.customization)
        app.render()
    assert app.preloader.status == main.PreloadStatus.READY, app.preloader.status_text
    report["startup_seconds"] = time.perf_counter() - start
    app.trigger_menu_action("Start Game")
    assert app.state == "GAME"
    s = app.preloader.game_session

    def capture(name):
        app.render()
        pygame.image.save(app.game_surface, str(OUT / f"{name}.png"))

    def key(code):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=code))
        app.handle_events()

    def click(rect):
        pos = (round(rect.centerx * app.scale + app.offset_x),
               round(rect.centery * app.scale + app.offset_y))
        pygame.mouse.set_pos(pos)
        pygame.event.pump()
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
        app.handle_events()

    def at(position, sailing=False):
        s.player.update(position)
        s.previous_pos = tuple(s.player)
        s.cam_x, s.cam_y = main.get_local_camera(s.player)
        s.fishing.close()
        s.fishing.zoom_level = 1
        s.is_sailing = sailing
        s.boat_speed = 0
        s.map_open = s.paused = False

    capture("startup")
    # Choose an actual oak stand, away from NPCs and automatic fishing triggers.
    candidates = [n for n in s.world.nodes if n.type == "Odun" and n.species == "oak"
                  and all((n.x - p.x)**2 + (n.y - p.y)**2 > 25 for p in s.ports)]
    tree = max(candidates, key=lambda n: s.world.woodland.get((int(n.x), int(n.y)), 0))
    at((tree.x, tree.y + .6))
    samples, leaf_samples = [], []
    for frame in range(240):
        app.clock.tick(60 if args.window else 0)
        app.handle_events()
        t = time.perf_counter()
        s.update(1 / 60, (600, 390))
        app.render()
        if frame >= 30:
            samples.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            s.leaves.update(0, s.player, (s.cam_x, s.cam_y))
            leaf_samples.append((time.perf_counter() - t) * 1000)
    report["forest_leaves"] = len(s.leaves.leaves)
    report["nearby_oaks"] = len(s.leaves.emitters)
    assert s.leaves.leaves
    capture("forest")
    for kind in s.inventory:
        s.add_resource(kind, 12)
    capture("resource_reward")
    key(pygame.K_m)
    assert s.map_open
    capture("full_map")
    key(pygame.K_m)
    assert not s.map_open
    key(pygame.K_m)
    key(pygame.K_ESCAPE)
    assert not s.map_open and not s.paused
    # Exercise app-level logical coordinate conversion at two window sizes.
    if args.window:
        for size in ((800, 600), (1537, 999)):
            app.window = pygame.display.set_mode(size, pygame.RESIZABLE)
            app.update_letterbox()
            app.render()
            click(s.map_button)
            assert s.map_open
            click(s.map_ui.close_rect)
            assert not s.map_open
            app.render()
            pygame.image.save(app.window, str(OUT / f"window_{size[0]}.png"))
        app.window = pygame.display.set_mode((1200, 780), pygame.RESIZABLE)
        app.update_letterbox()
        click(s.inventory_button)
        assert s.inventory_open
        capture("inventory")
        key(pygame.K_ESCAPE)
        click(s.trade_button)
        assert s.trade_open
        key(pygame.K_ESCAPE)
    key(pygame.K_ESCAPE)
    assert s.paused
    capture("pause")
    key(pygame.K_ESCAPE)
    assert not s.paused

    # Ocean and bare mountain have no leaf emitters, including after teleporting.
    for name, position, sailing in (("ocean", (3.5, 3.5), True),):
        at(position, sailing)
        s.update(1 / 60, (600, 390))
        assert not s.leaves.leaves
        capture(name)
    bare = next((x + .5, y + .5) for y, row in enumerate(s.world.heights)
                for x, height in enumerate(row) if height >= main.MOUNTAIN_LEVEL
                and all((n.x - x)**2 + (n.y - y)**2 > 13**2 for n in candidates))
    at(bare)
    s.update(1 / 60, (600, 390))
    assert not s.leaves.leaves
    capture("bare_mountain")
    report.update(frame_mean_ms=float(np.mean(samples)), frame_p95_ms=float(np.percentile(samples, 95)),
                  frame_max_ms=max(samples), leaf_update_p95_ms=float(np.percentile(leaf_samples, 95)),
                  frames_measured=len(samples), ocean_leaves=0, bare_mountain_leaves=0,
                  map_keys_passed=True, window_clicks_passed=args.window)
    name = "window_report.json" if args.window else "headless_report.json"
    (OUT / name).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
finally:
    if app.preloader.network:
        app.preloader.network.close()
    pygame.quit()
