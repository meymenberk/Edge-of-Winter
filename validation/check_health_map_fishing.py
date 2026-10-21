"""Offscreen visual and interaction check for the current HUD/map/fishing patch."""
import json
import os
import argparse
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--window", action="store_true")
args = parser.parse_args()
if not args.window:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pygame
import numpy as np
import main
from modules.terrain_render import TileAtlas, prepare_terrain

OUT = Path(__file__).resolve().parent / "health_map_fishing"
OUT.mkdir(exist_ok=True)
pygame.init()
pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
world = main.make_world(42)
prepare_terrain(world)
atlas = TileAtlas(main.find_tileset_file())
tiles = pygame.image.frombuffer(main.compute_tile_pixels(world),
                                (main.COLS, main.ROWS), "RGB").convert()
session = main.GameSession(world, world.ports, main.find_spawn(world), tiles,
                           None, 42, {}, atlas)
canvas = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))


def place(position):
    session.player.update(position)
    session.previous_pos = tuple(session.player)
    session.cam_x, session.cam_y = main.get_local_camera(session.player, session.fishing)


def capture(name, mouse=(0, 0)):
    session.render(canvas, mouse)
    if args.window:
        pygame.display.get_surface().blit(canvas, (0, 0))
        pygame.display.flip()
    pygame.image.save(canvas, str(OUT / f"{name}.png"))


report = {}
try:
    # A named village island gives useful HUD/minimap context.
    island = next(item for item in world.islands if item.village)
    place((island.village.center[0] + .5, island.village.center[1] + 1.5))
    session.health = session.max_health / 2
    capture("hearts_minimap")

    session.set_map_open(True)
    capture("full_map_1x")
    center = session.map_ui.full_rect.center
    session.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=3), center)
    session.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1), center)
    moved = (center[0] + 120, center[1] + 50)
    session.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=moved,
                                             rel=(120, 50), buttons=(1, 0, 0)), moved)
    session.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), moved)
    capture("full_map_zoom_pan", moved)
    report["full_map_zoom"] = session.map_ui.views["full"]["zoom"]
    session.set_map_open(False)

    session.inventory_open = True
    capture("inventory_rescue_map", session.inventory_rescue_map_rect.center)
    session.inventory_open = False
    session.rescue_map_open = True
    session.map_ui.focus("rescue", session.player)
    capture("lower_rescue_map", session.rescue_map_rect.center)
    session.rescue_map_open = False

    # Render the corrected dark forest floor with actual canopy sprites.
    oak = max((node for node in world.nodes if node.type == "Odun" and node.species == "oak"),
              key=lambda node: world.woodland.get((int(node.x), int(node.y)), 0))
    place((oak.x, oak.y + .6))
    session.health = session.max_health
    capture("forest_floor")

    # Open the real fishing entry point and let all four fish begin moving.
    port = world.ports[0]
    place((port.x + .5, port.y + .5))
    session.fishing.open(port, session.player)
    mouse_world = (session.fishing.rod_x + port.dx * 150,
                   session.fishing.rod_y + port.dy * 150)
    frame_times = []
    for frame in range(240):
        if frame == 120:
            session.fishing.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=2))
        started = time.perf_counter()
        session.fishing.update(1 / 60, *mouse_world, world)
        session.cam_x, session.cam_y = main.get_local_camera(session.player, session.fishing)
        session.render(canvas, (600, 390))
        frame_times.append((time.perf_counter() - started) * 1000)
    capture("fishing_school", (600, 390))
    report.update(fish_count=len(session.fishing.fishes),
                  fish_variants=len({fish["variant"] for fish in session.fishing.fishes}),
                  line_length=session.fishing.line_length,
                  frame_p95_ms=float(np.percentile(frame_times, 95)),
                  frame_max_ms=max(frame_times),
                  island_names=[item.name for item in world.islands],
                  unique_names=len({item.name for item in world.islands}) == len(world.islands))
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
finally:
    pygame.quit()
