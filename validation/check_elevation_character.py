"""Run the real app with four-direction input, TCP peers and mountain screenshots.
python3 validation/check_elevation_character.py --window
"""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--window', action='store_true')
args = parser.parse_args()
if not args.window:
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pygame
import main
from server import GameServer
from modules.multiplayer import NetworkClient

OUT = Path(__file__).resolve().parent / 'elevation_character'
OUT.mkdir(exist_ok=True)
app = main.AutumnGameApp()
report = {'driver': pygame.display.get_driver()}
polls = []
start = time.perf_counter()
while app.preloader.status not in (main.PreloadStatus.READY, main.PreloadStatus.ERROR):
    assert time.perf_counter() - start < 20, 'preload timeout'
    app.clock.tick(60)
    app.handle_events()
    t = time.perf_counter()
    app.preloader.poll(app.customization)
    polls.append(1000 * (time.perf_counter() - t))
    app.render()
assert app.preloader.status == main.PreloadStatus.READY, app.preloader.status_text
report['preload_seconds'] = time.perf_counter() - start
report['preload_max_poll_ms'] = max(polls)
pygame.image.save(app.menu_surface, str(OUT / 'menu.png'))
app.trigger_menu_action('Customize')
app.render()
pygame.image.save(app.menu_surface, str(OUT / 'customization.png'))
app.trigger_menu_action('Start Game')
session = app.preloader.game_session
atlas, sheet = session.atlas, session.character_sheet
assert sheet and sheet.path.name == 'manchar.jpeg'
report['character_asset'] = sheet.path.name

# Real TCP peers sharing the same world as the actual gameplay window.
server = GameServer(session.world)
listener = socket.socket()
listener.bind(('127.0.0.1', 0))
listener.listen()

def accept_pair():
    for pid in range(2):
        conn, addr = listener.accept()
        threading.Thread(target=server.handle_client, args=(conn, addr, pid), daemon=True).start()

threading.Thread(target=accept_pair, daemon=True).start()
clients = [NetworkClient('127.0.0.1', listener.getsockname()[1]) for _ in range(2)]
for client in clients:
    assert client.try_connect()
session.network = clients[0]
island = session.world.islands[0]
session.player.update(island.x + .5, island.y + .5)
session.previous_pos = tuple(session.player)
session.cam_x, session.cam_y = main.get_local_camera(session.player)
contact = pygame.Surface((4 * 144, 4 * 166))
contact.fill((35, 29, 24))
font = pygame.font.Font(None, 22)
timings = []
for row, (direction, key) in enumerate((('down', pygame.K_s), ('right', pygame.K_d), ('up', pygame.K_w), ('left', pygame.K_a))):
    captured = set()
    for frame in range(65):
        app.clock.tick(60 if args.window else 0)
        app.handle_events()
        clients[1].send_and_receive(session.player.x + 1.5, session.player.y + .5, direction, True, False)
        t = time.perf_counter()
        with patch('pygame.key.get_pressed', return_value=defaultdict(bool, {key: True})):
            session.update(1 / 60, (0, 0))
        app.render()
        timings.append(1000 * (time.perf_counter() - t))
        pose = session.player_animation.frame
        assert session.player_animation.facing == direction
        if pose not in captured:
            x = round(session.player.x * 48) - round(session.cam_x)
            y = round(session.player.y * 48) - round(session.cam_y)
            contact.blit(app.game_surface, (pose * 144 + 8, row * 166 + 25), (x - 64, y - 96, 128, 128))
            contact.blit(font.render(f'{direction} {pose}', True, 'white'), (pose * 144 + 8, row * 166 + 3))
            captured.add(pose)
    assert captured == {0, 1, 2, 3}, (direction, captured)
    assert session.remote_animations['1'].facing == direction
pygame.image.save(contact, str(OUT / 'walking_in_game.png'))
pygame.image.save(app.game_surface, str(OUT / 'multiplayer.png'))
for _ in range(20):
    app.clock.tick(60 if args.window else 0)
    clients[1].send_and_receive(session.player.x + 1.5, session.player.y + .5, 'left', False, False)
    with patch('pygame.key.get_pressed', return_value=defaultdict(bool)):
        session.update(1 / 60, (0, 0))
    app.render()
assert session.player_animation.frame == 0 and not session.player_animation.moving
assert not session.remote_animations['1'].moving
report['tcp_peer_animation'] = 'four directions and idle passed'
for client in clients:
    client.close()
listener.close()

# Four seeds, nested peaks and roads near mountain areas.
report['seeds'] = {}
cold_views = []
travel_times = []
for seed in (0, 42, 137, 2026):
    world = main.make_world(seed)
    tiles = pygame.image.frombuffer(main.compute_tile_pixels(world), (main.COLS, main.ROWS), 'RGB').convert()
    session = main.GameSession(world, world.ports, main.find_spawn(world), tiles, None, seed, {}, atlas, sheet)
    app.preloader.game_session = session
    peak_y, peak_x = np.unravel_index(np.argmax(world.heights), (main.ROWS, main.COLS))
    positions = {'mountain': (peak_x + .5, peak_y + 3.5), 'village': main.find_spawn(world)}
    for name, pos in positions.items():
        session.player.update(pos)
        session.previous_pos = tuple(session.player)
        session.cam_x, session.cam_y = main.get_local_camera(session.player)
        app.render()
        pygame.image.save(app.game_surface, str(OUT / f'seed_{seed}_{name}.png'))
    levels = world.elevation_data[0]
    report['seeds'][seed] = {str(tier): int((levels == tier).sum()) for tier in (1, 2, 3)}
    # Continuous movement into cold terrain chunks, including new mountain faces.
    session.terrain_renderer.chunks.clear()
    for frame in range(160):
        app.clock.tick(60 if args.window else 0)
        app.handle_events()
        session.player.update(max(15, peak_x - 15) + frame * .14, peak_y + 3.5)
        session.previous_pos = tuple(session.player)
        session.cam_x, session.cam_y = main.get_local_camera(session.player)
        t = time.perf_counter()
        app.render()
        elapsed = 1000 * (time.perf_counter() - t)
        timings.append(elapsed)
        (cold_views if frame == 0 else travel_times).append(elapsed)

for size in ((800, 600), (1537, 999), (1200, 780)):
    app.window = pygame.display.set_mode(size, pygame.RESIZABLE)
    app.update_letterbox()
    app.render()
for key in (pygame.K_m, pygame.K_m, pygame.K_ESCAPE, pygame.K_ESCAPE):
    session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key), (0, 0))
    app.render()
report['measured_frames'] = len(timings)
report['cold_view_max_ms'] = max(cold_views)
report['continuous_travel_max_ms'] = max(travel_times)
report['frame_mean_ms'] = float(np.mean(timings))
report['frame_p95_ms'] = float(np.percentile(timings, 95))
report['frame_max_ms'] = max(timings)
report['composite_cache'] = len(atlas.composites)
(OUT / ('window_report.json' if args.window else 'headless_report.json')).write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if app.preloader.network:
    app.preloader.network.close()
pygame.quit()
