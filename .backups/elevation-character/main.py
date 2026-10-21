#!/usr/bin/env python3
"""
Autumn Island Exploration - Main Menu & Integrated Multiplayer Game Client
------------------------------------------------------------------------
A complete, integrated client combining:
- The polished autumn pixel-art main menu, character preview, customization panel,
  wooden menu buttons, and dynamic ambient lighting effects.
- The full playable island exploration game with Perlin-noise terrain, island generation,
  villages, ports, sailing, resource gathering, minigames, and world map.
- Upgraded in-game visuals using the provided 'Fall Tile Set' sprite atlas:
  * Auto-tiled water & shoreline transitions (deep ocean, shallow water, shore edges & corners).
  * Eight-neighbor paths, including filled plazas and connected corners/junctions.
  * Autumn grass terrain with deterministic organic foliage variants.
  * Mountain rock terrain with elevated cliff drop-offs.
  * Real pixel-art village cottages with warm autumn roofs and chimneys.
  * Continuous wooden piers and moorings.
  * Wooden rowboat sprite with rotation during sailing.
  * Harvestable autumn oaks and highland pines, stumps, stone boulders, and wheat.
  * Village campfires, street lamps, water wells, barrels, and signposts.
- Background game preloading at application launch: expensive terrain generation, noise
  calculations, map data, and entity setup complete silently while the player is on
  the main menu, allowing an instant transition when "Start Game" is pressed.
- Thread-safe Pygame architecture: display and surface operations remain strictly on the
  main thread, while non-display data preparation runs smoothly in background workers.
- Multiplayer client compatible with server.py, featuring non-blocking I/O and graceful
  offline singleplayer fallback.
"""

import os
import sys
import math
import time
import random
import socket
import json
import queue
import threading
import unicodedata
from enum import Enum
from pathlib import Path

import pygame
import numpy as np

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
MENU_WIDTH = 1024
MENU_HEIGHT = 576

GAME_WIDTH = 1200
GAME_HEIGHT = 780

DEFAULT_WIN_W = 1200
DEFAULT_WIN_H = 780
FPS = 60

BASE_DIR = Path(__file__).resolve().parent

# Color Palette (Warm Autumn Theme - Menu)
COLOR_BG_DARK = (18, 10, 8)
COLOR_PANEL_BG = (28, 16, 12, 225)
COLOR_PANEL_HEADER = (55, 30, 20, 240)
COLOR_BORDER_OUTER = (165, 100, 50)
COLOR_BORDER_INNER = (90, 50, 25)
COLOR_SLOT_BG = (22, 13, 10, 230)
COLOR_SLOT_BORDER = (95, 60, 38)
COLOR_SLOT_HOVER = (200, 140, 70)
COLOR_SLOT_SELECTED = (255, 212, 55)
COLOR_TEXT_GOLD = (255, 225, 145)
COLOR_TEXT_WARM = (235, 190, 130)
COLOR_TEXT_MUTED = (180, 140, 100)
COLOR_TEXT_SHADOW = (20, 10, 6)

# Gameplay World & Terrain Constants
COLS, ROWS = 400, 240
ISLAND_COUNT = 25
MIN_RADIUS, MAX_RADIUS = 19, 36
MAP_TILE_SIZE = 3
LOCAL_TILE_SIZE = 48

PLAYER_SPEED = 4.5
PLAYER_HALF_SIZE = 0.17

SEA_LEVEL = 0.0
SAND_LEVEL = 0.09
MOUNTAIN_LEVEL = 0.48

VILLAGE_CHANCE = 0.60
RESOURCES = ("Odun", "Tahil", "Tas")

# Colors matching the Fall Tile Set palette for world map
DEEP_WATER = (17, 88, 158)
SHALLOW_WATER = (50, 173, 201)
SAND = (246, 192, 114)
GRASS = (208, 128, 34)
MOUNTAIN = (158, 126, 116)
ROAD = (148, 76, 36)

# Customization option labels
OPTION_NAMES = {
    "hair": [
        "Short Spiky Brown",
        "Shoulder Wavy Brown",
        "High Bun Brown (Default)",
        "Wavy Auburn",
        "Blonde Bob",
    ],
    "skin": [
        "Porcelain Tone",
        "Fair Tone (Default)",
        "Warm Tan Tone",
        "Rich Bronze Tone",
        "Deep Dark Tone",
    ],
    "shirt": [
        "Green Jacket & Scarf (Default)",
        "Cream Knit Sweater",
        "Red Warm Hoodie",
        "Navy Sweater & Shirt",
        "Brown Flannel Cardigan",
    ],
    "pants": [
        "Olive Cargo Pants",
        "Dark Ripped Jeans",
        "Brown Cargo Pants (Default)",
        "Khaki Work Pants",
        "Charcoal Cargo & Belt",
    ],
}


# ---------------------------------------------------------------------------
# Robust Asset Discovery (Handles macOS Unicode NFD/NFC Normalization)
# ---------------------------------------------------------------------------
def find_asset(pattern: str) -> Path:
    """Locates an asset in BASE_DIR using exact matching or Unicode normalization."""
    direct = BASE_DIR / pattern
    if direct.exists():
        return direct

    norm_pattern = unicodedata.normalize("NFC", pattern).lower()
    for entry in os.listdir(BASE_DIR):
        entry_norm = unicodedata.normalize("NFC", entry).lower()
        if norm_pattern == entry_norm:
            return BASE_DIR / entry

    for entry in os.listdir(BASE_DIR):
        entry_norm = unicodedata.normalize("NFC", entry).lower()
        if norm_pattern in entry_norm or entry_norm in norm_pattern:
            return BASE_DIR / entry

    keywords = {
        "bg": ["bg(1).jpeg", "bg.jpeg"],
        "char": ["19_34_26"],
        "menu": ["19_43_03"],
        "hair": ["retro", "karakter"],
        "cloth": ["kıyafet", "kiyafet", "panel"],
        "tileset": ["fall tile set"],
    }
    for key, candidates in keywords.items():
        if key in pattern.lower():
            for entry in os.listdir(BASE_DIR):
                entry_norm = unicodedata.normalize("NFC", entry).lower()
                for c in candidates:
                    if c in entry_norm:
                        return BASE_DIR / entry

    raise FileNotFoundError(f"Could not locate required asset for pattern: '{pattern}' in {BASE_DIR}")


def find_tileset_file() -> Path:
    """Finds the 'Fall Tile Set' image file with any supported extension."""
    for ext in ['.png', '.jpg', '.jpeg', '.webp']:
        p = BASE_DIR / f"Fall Tile Set{ext}"
        if p.exists():
            return p
    for entry in os.listdir(BASE_DIR):
        entry_norm = unicodedata.normalize("NFC", entry).lower()
        if entry_norm.startswith('fall tile set') or 'fall tile set' in entry_norm:
            return BASE_DIR / entry
    raise FileNotFoundError(f"Could not locate Fall Tile Set in {BASE_DIR}")


# ---------------------------------------------------------------------------
# Tile Atlas & Sprite Sheet Manager
# ---------------------------------------------------------------------------
from terrain_render import TileAtlas, TerrainRenderer, prepare_terrain


# ---------------------------------------------------------------------------
# Multiplayer Networking Client
# ---------------------------------------------------------------------------
from multiplayer import NetworkClient


# ---------------------------------------------------------------------------
# World Generation & Data Structures (from main2.py)
# ---------------------------------------------------------------------------
# Shared by the server; generation and resource IDs have a single implementation.
from worldgen import (
    WORLD_VERSION, Island, Village, ResourceNode, World, Port, terrain, make_world,
    generate_villages, compute_tile_pixels, generate_ports, can_stand, find_spawn,
)


def movement_multiplier(world, player, is_sailing):
    if is_sailing:
        return 1.8
    x, y = int(player.x), int(player.y)
    if (x, y) in world.roads: return 1.30
    height = world.heights[y][x]
    if height >= MOUNTAIN_LEVEL: return 0.55
    if height < SAND_LEVEL: return 0.80
    return 1.0


def move_player(world, player, direction, dt, is_sailing):
    if direction.length_squared() == 0: return
    speed = PLAYER_SPEED * movement_multiplier(world, player, is_sailing)
    movement = direction.normalize() * speed * dt
    steps = max(1, math.ceil(movement.length() / 0.12))
    movement /= steps

    for _ in range(steps):
        if can_stand(world, player.x + movement.x, player.y, is_sailing): player.x += movement.x
        if can_stand(world, player.x, player.y + movement.y, is_sailing): player.y += movement.y


# ---------------------------------------------------------------------------
# Gameplay Drawing Functions (Enhanced with Fall Tile Set)
# ---------------------------------------------------------------------------
def draw_text(screen, font, text, position, color=(235, 240, 245)):
    screen.blit(font.render(text, True, color), position)


def draw_house(screen, rect, atlas, variant=0):
    """Draws pixel-art cottage from Fall Tile Set with soft ground shadow."""
    if atlas is None:
        pygame.draw.rect(screen, (133, 83, 47), rect)
        pygame.draw.polygon(screen, (103, 46, 32), [rect.topleft, rect.topright, (rect.centerx, rect.top - 20)])
        return
    house_surf = atlas.houses[variant % len(atlas.houses)]
    hw, hh = house_surf.get_size()
    hx = rect.centerx - hw // 2
    hy = rect.bottom - hh + 4

    # Drop shadow
    shadow_surf = pygame.Surface((hw - 10, 14), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow_surf, (20, 16, 12, 70), (0, 0, hw - 10, 14))
    screen.blit(shadow_surf, (hx + 5, rect.bottom - 8))

    screen.blit(house_surf, (hx, hy))


def draw_node(screen, node, camera_x, camera_y, atlas):
    """Draws authentic nature / resource nodes from Fall Tile Set."""
    screen_x = round(node.x * LOCAL_TILE_SIZE) - round(camera_x)
    screen_y = round(node.y * LOCAL_TILE_SIZE) - round(camera_y)
    if not (-60 <= screen_x <= GAME_WIDTH + 60 and -60 <= screen_y <= GAME_HEIGHT + 110): return

    if atlas is None:
        if node.active:
            colors = {"Odun": (186, 105, 28), "Tas": (125, 125, 126), "Tahil": (225, 185, 65)}
            pygame.draw.circle(screen, colors[node.type], (screen_x, screen_y - 12), 14)
        return
    idx = node.variant

    if node.type == "Odun":
        if node.active:
            tree_surf = atlas.tree_variants[node.species][idx % 2]
            tw, th = tree_surf.get_size()
            screen.blit(tree_surf, (screen_x - tw // 2, screen_y - th + 8))
        else:
            stump = atlas.stump
            sw, sh = stump.get_size()
            screen.blit(stump, (screen_x - sw // 2, screen_y - sh + 4))

    elif node.type == "Tas":
        if node.active:
            rock_surf = atlas.rocks[idx % len(atlas.rocks)]
            rw, rh = rock_surf.get_size()
            screen.blit(rock_surf, (screen_x - rw // 2, screen_y - rh + 4))
        else:
            rubble = atlas.mined_rubble
            rw, rh = rubble.get_size()
            screen.blit(rubble, (screen_x - rw // 2, screen_y - rh + 4))

    elif node.type == "Tahil":
        if node.active:
            crop_surf = atlas.crops[idx % len(atlas.crops)]
            cw, ch = crop_surf.get_size()
            screen.blit(crop_surf, (screen_x - cw // 2, screen_y - ch + 4))
        else:
            # Cut stubble
            pygame.draw.rect(screen, (160, 125, 45), (screen_x - 12, screen_y - 4, 24, 6))


def draw_player(screen, position, moving, facing, color_override=None, is_sailing=False, boat_angle=0.0, atlas=None):
    scale = 1.6

    if is_sailing and atlas and hasattr(atlas, 'boat'):
        boat = atlas.boat
        angle_deg = math.degrees(-boat_angle) - 90
        rot_boat = pygame.transform.rotate(boat, angle_deg)
        rect = rot_boat.get_rect(center=(round(position[0]), round(position[1])))
        screen.blit(rot_boat, rect.topleft)
        return
    elif is_sailing:
        boat = pygame.Surface((20 * scale, 30 * scale), pygame.SRCALPHA)
        pygame.draw.ellipse(boat, (120, 80, 50), (0, 0, 20 * scale, 30 * scale))
        pygame.draw.rect(boat, (200, 190, 180), (4 * scale, 10 * scale, 12 * scale, 10 * scale))
        angle_deg = math.degrees(-boat_angle) - 90
        boat = pygame.transform.rotate(boat, angle_deg)
        rect = boat.get_rect(center=(round(position[0]), round(position[1])))
        screen.blit(boat, rect.topleft)
        return

    sprite = pygame.Surface((16, 20), pygame.SRCALPHA)
    step = int(pygame.time.get_ticks() / 150) % 2 if moving else 0

    outline = (49, 40, 36)
    coat = color_override if color_override else (123, 85, 57)
    coat_light = (min(255, coat[0] + 40), min(255, coat[1] + 30), min(255, coat[2] + 15))
    skin = (224, 178, 133)
    hair = (72, 49, 35)
    scarf = (153, 57, 48)
    scarf_light = (190, 81, 57)
    boots = (56, 45, 39)

    pygame.draw.ellipse(sprite, (24, 25, 22, 75), (3, 16, 11, 3))
    left_foot = 16 + step
    right_foot = 17 - step if moving else 16

    pygame.draw.rect(sprite, outline, (5, 13, 3, 4))
    pygame.draw.rect(sprite, outline, (9, 13, 3, 4))
    pygame.draw.rect(sprite, boots, (4, left_foot, 4, 2))
    pygame.draw.rect(sprite, boots, (9, right_foot, 4, 2))

    pygame.draw.rect(sprite, outline, (4, 8, 9, 7))
    pygame.draw.rect(sprite, coat, (5, 8, 7, 6))
    pygame.draw.rect(sprite, coat_light, (5, 9, 2, 4))

    pygame.draw.rect(sprite, coat, (3, 9 + step, 2, 4))
    pygame.draw.rect(sprite, coat, (12, 10 - step, 2, 4))
    pygame.draw.rect(sprite, skin, (3, 12 + step, 2, 1))
    pygame.draw.rect(sprite, skin, (12, 13 - step, 2, 1))

    pygame.draw.rect(sprite, outline, (5, 2, 7, 7))
    pygame.draw.rect(sprite, skin, (6, 3, 5, 5))
    pygame.draw.rect(sprite, hair, (5, 2, 7, 2))
    pygame.draw.rect(sprite, hair, (5, 4, 1, 2))

    if facing == "up":
        pygame.draw.rect(sprite, hair, (6, 4, 5, 4))
        pygame.draw.rect(sprite, outline, (6, 9, 5, 5))
        pygame.draw.rect(sprite, (104, 111, 74), (7, 9, 3, 4))
        pygame.draw.rect(sprite, (157, 146, 97), (7, 10, 3, 1))
    else:
        eyes = [(6, 5)] if facing == "left" else [(10, 5)] if facing == "right" else [(7, 5), (10, 5)]
        for eye in eyes: sprite.set_at(eye, outline)
        sprite.set_at((9, 10), outline)
        sprite.set_at((9, 12), outline)

    pygame.draw.rect(sprite, scarf, (5, 7, 7, 2))
    pygame.draw.rect(sprite, scarf_light, (6, 7, 4, 1))
    flutter = int(pygame.time.get_ticks() / 220) % 2 if moving else 0
    pygame.draw.rect(sprite, scarf, (11, 8, 2 + flutter, 3))

    sprite = pygame.transform.scale(sprite, (int(16 * scale), int(20 * scale)))
    screen.blit(sprite, (round(position[0] - 8 * scale), round(position[1] - 17 * scale)))


def get_local_camera(player, fishing=None):
    target_x = player.x * LOCAL_TILE_SIZE
    target_y = player.y * LOCAL_TILE_SIZE

    if fishing and fishing.active and fishing.port:
        target_x += fishing.port.dx * LOCAL_TILE_SIZE * 4
        target_y += fishing.port.dy * LOCAL_TILE_SIZE * 4

    camera_x = max(0, min(target_x - GAME_WIDTH / 2, COLS * LOCAL_TILE_SIZE - GAME_WIDTH))
    camera_y = max(0, min(target_y - GAME_HEIGHT / 2, ROWS * LOCAL_TILE_SIZE - GAME_HEIGHT))
    return camera_x, camera_y


def draw_world_map(screen, world, map_surface, map_rect, player, network):
    screen.blit(map_surface, map_rect)

    for island in world.islands:
        if island.village:
            x, y = island.village.center
            pos = (round(map_rect.x + (x + 0.5) * MAP_TILE_SIZE), round(map_rect.y + (y + 0.5) * MAP_TILE_SIZE))
            pygame.draw.circle(screen, (44, 32, 23), pos, 4)
            pygame.draw.circle(screen, (245, 201, 107), pos, 3)

    if network and network.connected:
        with network.lock:
            for pid, pdata in network.other_players.items():
                marker = pygame.Rect(0, 0, 7, 7)
                marker.center = (round(map_rect.x + pdata["x"] * MAP_TILE_SIZE), round(map_rect.y + pdata["y"] * MAP_TILE_SIZE))
                pygame.draw.rect(screen, (255, 255, 255), marker.inflate(4, 4))
                pygame.draw.rect(screen, (220, 50, 50), marker)

    marker = pygame.Rect(0, 0, 7, 7)
    marker.center = (round(map_rect.x + player.x * MAP_TILE_SIZE), round(map_rect.y + player.y * MAP_TILE_SIZE))
    pygame.draw.rect(screen, (255, 255, 255), marker.inflate(4, 4))
    pygame.draw.rect(screen, (0, 0, 0), marker)


def draw_ports(screen, ports, player, camera_x, camera_y, atlas=None):
    tile = LOCAL_TILE_SIZE

    for port in ports:
        shore_x = round((port.x + 0.5) * tile - camera_x)
        shore_y = round((port.y + 0.5) * tile - camera_y)

        if not (-tile * 4 < shore_x < GAME_WIDTH + tile * 4 and -tile * 4 < shore_y < GAME_HEIGHT + tile * 4): continue

        for step in range(1, 4):
            cx = shore_x + port.dx * step * tile
            cy = shore_y + port.dy * step * tile

            if atlas:
                dock_tile = atlas.dock_h if port.dx != 0 else atlas.dock_v
                screen.blit(dock_tile, dock_tile.get_rect(center=(cx, cy)))
                # Add mooring post at the end
                if step == 3:
                    post = atlas.lamp
                    pw, ph = post.get_size()
                    screen.blit(post, (cx - pw // 2, cy - ph // 2))
            else:
                if port.dx:
                    rect = pygame.Rect(cx - tile // 2, cy - 7, tile, 14)
                else:
                    rect = pygame.Rect(cx - 7, cy - tile // 2, 14, tile)

                pygame.draw.rect(screen, (30, 40, 40), rect.move(3, 4))
                pygame.draw.rect(screen, (135, 93, 57), rect)
                pygame.draw.rect(screen, (81, 57, 38), rect, 1)


# ---------------------------------------------------------------------------
# Gameplay Drifting Autumn Leaves
# ---------------------------------------------------------------------------
class AutumnLeaves:
    def __init__(self, seed, count=36):
        self.rng = random.Random(seed + 9981)
        self.leaves = []
        for _ in range(count): self.leaves.append(self.new_leaf(initial=True))

    def new_leaf(self, initial=False):
        return {
            "x": self.rng.uniform(0, GAME_WIDTH) if initial else self.rng.uniform(-150, GAME_WIDTH),
            "y": self.rng.uniform(0, GAME_HEIGHT) if initial else self.rng.uniform(-100, -15),
            "speed_x": self.rng.uniform(18, 45),
            "speed_y": self.rng.uniform(20, 45),
            "phase": self.rng.uniform(0, math.tau),
            "angle": self.rng.uniform(0, 360),
            "spin": self.rng.uniform(-100, 100),
            "size": self.rng.randint(5, 9),
            "color": self.rng.choice([(211, 118, 43), (190, 81, 37), (232, 154, 53), (169, 91, 40), (218, 133, 57)]),
        }

    def update(self, dt):
        for index, leaf in enumerate(self.leaves):
            leaf["phase"] += dt * 2.2
            leaf["angle"] += leaf["spin"] * dt
            leaf["x"] += (leaf["speed_x"] + math.sin(leaf["phase"]) * 24) * dt
            leaf["y"] += leaf["speed_y"] * dt
            if leaf["y"] > GAME_HEIGHT + 20 or leaf["x"] > GAME_WIDTH + 30: self.leaves[index] = self.new_leaf()

    def draw(self, screen):
        for leaf in self.leaves:
            size = leaf["size"]
            image = pygame.Surface((size * 2 + 4, size * 2 + 4), pygame.SRCALPHA)
            center = size + 2
            pygame.draw.polygon(image, leaf["color"],
                                [(center, 1), (center + size // 2, center - 2), (center + size, center),
                                 (center + 2, center + size), (center - size // 2, center + 2),
                                 (center - size, center - 2)])
            pygame.draw.line(image, (122, 70, 35), (center - 2, center + size), (center + 1, 3), 1)
            image = pygame.transform.rotate(image, leaf["angle"])
            screen.blit(image, image.get_rect(center=(round(leaf["x"]), round(leaf["y"]))))


# ---------------------------------------------------------------------------
# Interactive Minigames (from main2.py)
# ---------------------------------------------------------------------------
class GrainHarvesting:
    def __init__(self, seed):
        self.rng = random.Random(seed + 5555)
        self.active = False
        self.node = None
        self.message = ""

        self.track_w = 500
        self.track_h = 120
        self.start_rect = pygame.Rect(0, 0, 60, self.track_h)
        self.end_rect = pygame.Rect(0, 0, 60, self.track_h)
        self.valid_rect = pygame.Rect(0, 0, self.track_w, self.track_h)

        self.dragging = False
        self.wind_timer = 0.0

    def open(self, node):
        self.active = True
        self.node = node
        self.dragging = False
        self.message = "Tirpan icin fareyi soldaki yesil alandan saga surukle. Ruzgara DIKKAT!"
        self.valid_rect.center = (GAME_WIDTH // 2, GAME_HEIGHT // 2)
        self.start_rect.topleft = self.valid_rect.topleft
        self.end_rect.topright = self.valid_rect.topright

    def close(self):
        self.active = False
        self.dragging = False

    def handle_event(self, event, logical_mouse_pos=None):
        pos = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.start_rect.collidepoint(pos):
                self.dragging = True
                self.message = "Surukle! Ruzgara karsi diren!"
            else:
                self.message = "Once soldaki yesil alana basili tutmalisin!"
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                if self.end_rect.collidepoint(pos):
                    self.message = "Harika! Tahili topladin."
                    self.node.harvest()
                    self.close()
                else:
                    self.message = "Yarim biraktin! Ekinler ziyan oldu."
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                if not self.valid_rect.collidepoint(pos):
                    self.dragging = False
                    self.message = "Tirpan elinden kaydi! Ruzgar ekinleri ezdi."

    def update(self, dt, logical_mouse_pos=None):
        if not self.active: return
        self.wind_timer -= dt
        if self.wind_timer <= 0:
            self.wind_timer = self.rng.uniform(0.15, 0.3)
            if self.dragging:
                mx, my = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
                push = self.rng.choice([-1, 1]) * self.rng.uniform(30, 70)
                try:
                    pygame.mouse.set_pos((mx, int(my + push)))
                except Exception:
                    pass

    def draw_ui(self, screen, font, logical_mouse_pos=None):
        if not self.active: return
        panel_rect = pygame.Rect(GAME_WIDTH // 2 - 320, GAME_HEIGHT // 2 - 120, 640, 240)
        pygame.draw.rect(screen, (32, 39, 41, 230), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (186, 149, 91), panel_rect, width=2, border_radius=8)
        pygame.draw.rect(screen, (70, 90, 60), self.valid_rect)
        pygame.draw.rect(screen, (100, 120, 90), self.valid_rect, width=2)
        pygame.draw.rect(screen, (100, 200, 100) if not self.dragging else (60, 140, 60), self.start_rect)
        pygame.draw.rect(screen, (200, 100, 100), self.end_rect)
        draw_text(screen, font, self.message, (GAME_WIDTH // 2 - 300, GAME_HEIGHT // 2 - 100), (244, 218, 165))
        if self.dragging:
            mx, my = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
            pygame.draw.circle(screen, (240, 240, 240), (mx, my), 6)
            pygame.draw.line(screen, (200, 200, 200), (mx, my), (mx - 20, my + 20), 3)


class StoneMining:
    def __init__(self):
        self.active = False
        self.node = None
        self.targets = []
        self.message = ""

    def open(self, node):
        self.active = True
        self.node = node
        self.message = "Catlaklara tikla! (Geri tepmeye hazir ol)"
        self.targets = []
        for _ in range(3):
            tx = random.randint(GAME_WIDTH // 2 - 200, GAME_WIDTH // 2 + 200)
            ty = random.randint(GAME_HEIGHT // 2 - 150, GAME_HEIGHT // 2 + 150)
            self.targets.append(pygame.Rect(tx, ty, 40, 40))

    def close(self):
        self.active = False

    def handle_event(self, event, logical_mouse_pos=None):
        pos = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = False
            for t in self.targets[:]:
                if t.collidepoint(pos):
                    self.targets.remove(t)
                    hit = True
                    break

            corners = [(50, 50), (GAME_WIDTH - 50, 50), (50, GAME_HEIGHT - 50), (GAME_WIDTH - 50, GAME_HEIGHT - 50)]
            rx, ry = random.choice(corners)
            rx += random.randint(-20, 20)
            ry += random.randint(-20, 20)
            try:
                pygame.mouse.set_pos([rx, ry])
            except Exception:
                pass

            if hit and len(self.targets) == 0:
                self.node.harvest()
                self.close()

    def draw_ui(self, screen, font):
        if not self.active: return
        panel_rect = pygame.Rect(GAME_WIDTH // 2 - 250, GAME_HEIGHT // 2 - 200, 500, 400)
        pygame.draw.rect(screen, (50, 50, 50, 230), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (100, 100, 100), panel_rect, width=2, border_radius=8)
        draw_text(screen, font, self.message, (GAME_WIDTH // 2 - 180, GAME_HEIGHT // 2 - 180), (255, 255, 255))

        for t in self.targets:
            pygame.draw.circle(screen, (200, 50, 50), t.center, 20)
            pygame.draw.line(screen, (50, 50, 50), (t.centerx - 10, t.centery - 10), (t.centerx + 10, t.centery + 10), 3)
            pygame.draw.line(screen, (50, 50, 50), (t.centerx - 10, t.centery + 10), (t.centerx + 10, t.centery - 10), 3)


class WoodChopping:
    def __init__(self):
        self.active = False
        self.node = None
        self.bar_pos = 0.0
        self.bar_speed = 600.0
        self.direction = 1
        self.state = "QTE"
        self.message = "BOŞLUK ile yesil alanda durdur!"
        self.stuck_timer = 3.0
        self.zc_count = 0
        self.last_key = None

    def open(self, node):
        self.active = True
        self.node = node
        self.state = "QTE"
        self.bar_pos = 0.0
        self.direction = 1
        self.message = "BOŞLUK ile yesil alanda durdur!"

    def close(self):
        self.active = False

    def handle_event(self, event, player_exhaust_timer):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q) and self.state != "STUCK":
                self.close()
            elif self.state == "QTE" and event.key == pygame.K_SPACE:
                if 180 <= self.bar_pos <= 220:
                    self.node.harvest()
                    self.close()
                else:
                    self.state = "STUCK"
                    self.stuck_timer = 3.0
                    self.zc_count = 0
                    self.last_key = None
                    self.message = "Balta sıkıştı! 3 saniye icinde ard arda 20 kez Z ve C'ye bas!"
            elif self.state == "STUCK":
                if event.key in (pygame.K_z, pygame.K_c):
                    if event.key != self.last_key:
                        self.zc_count += 1
                        self.last_key = event.key
                        if self.zc_count >= 20:
                            self.node.harvest()
                            self.close()
        return player_exhaust_timer

    def update(self, dt):
        if not self.active: return 0.0
        if self.state == "QTE":
            self.bar_pos += self.bar_speed * self.direction * dt
            if self.bar_pos >= 400 or self.bar_pos <= 0:
                self.direction *= -1
        elif self.state == "STUCK":
            self.stuck_timer -= dt
            if self.stuck_timer <= 0:
                self.close()
                return 4.0
        return 0.0

    def draw_ui(self, screen, font):
        if not self.active: return
        panel_rect = pygame.Rect(GAME_WIDTH // 2 - 250, GAME_HEIGHT // 2 - 100, 500, 200)
        pygame.draw.rect(screen, (60, 40, 30, 230), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (150, 100, 50), panel_rect, width=2, border_radius=8)

        draw_text(screen, font, self.message, (GAME_WIDTH // 2 - 230, GAME_HEIGHT // 2 - 80), (255, 255, 255))

        if self.state == "QTE":
            pygame.draw.rect(screen, (100, 100, 100), (GAME_WIDTH // 2 - 200, GAME_HEIGHT // 2, 400, 30))
            pygame.draw.rect(screen, (50, 200, 50), (GAME_WIDTH // 2 - 20, GAME_HEIGHT // 2, 40, 30))
            pygame.draw.rect(screen, (200, 200, 200), (GAME_WIDTH // 2 - 200 + self.bar_pos, GAME_HEIGHT // 2 - 5, 10, 40))
        elif self.state == "STUCK":
            draw_text(screen, font, f"Zaman: {self.stuck_timer:.1f} | Basim: {self.zc_count}/20",
                      (GAME_WIDTH // 2 - 100, GAME_HEIGHT // 2 + 20), (255, 50, 50))


class OpenWaterFishing:
    def __init__(self, seed):
        self.rng = random.Random(seed + 45677)
        self.active = False
        self.port = None
        self.fish_count = 0

        self.fish_x, self.fish_y = 0.0, 0.0
        self.bobber_x, self.bobber_y = 0.0, 0.0
        self.fish_target_x, self.fish_target_y = 0.0, 0.0
        self.fish_timer = 0.0
        self.progress = 0.0
        self.message = ""
        self.state = "waiting"
        self.wait_timer = 0.0
        self.escape_timer = 0.0
        self.zoom_level = 1.0
        self.target_zoom = 1.0

    def open(self, port, player):
        self.active = True
        self.port = port
        self.bobber_x = player.x * LOCAL_TILE_SIZE
        self.bobber_y = player.y * LOCAL_TILE_SIZE
        self.target_zoom = 1.6
        self.set_waiting(escaped=False)

    def close(self):
        self.active = False
        self.target_zoom = 1.0

    def set_waiting(self, escaped=False):
        self.state = "waiting"
        self.progress = 0.0
        self.escape_timer = 0.0
        self.fish_x, self.fish_y = -9999, -9999
        self.wait_timer = self.rng.uniform(1.5, 3.5)
        self.message = "Balik kacti! Yeni balik bekleniyor..." if escaped else "Olta suda, balik bekleniyor..."

    def spawn_fish(self, world):
        self.state = "fishing"
        self.message = "Balik vurdu! Fareyi ustune gotur ve SCROLL yap!"
        base_x = (self.port.x + self.port.dx * 3 + 0.5) * LOCAL_TILE_SIZE
        base_y = (self.port.y + self.port.dy * 3 + 0.5) * LOCAL_TILE_SIZE

        for _ in range(20):
            angle = self.rng.uniform(0, math.tau)
            distance = self.rng.uniform(40, 130)
            tx = base_x + math.cos(angle) * distance
            ty = base_y + math.sin(angle) * distance
            grid_x, grid_y = int(tx / LOCAL_TILE_SIZE), int(ty / LOCAL_TILE_SIZE)

            if 0 <= grid_x < COLS and 0 <= grid_y < ROWS:
                if world.heights[grid_y][grid_x] < SEA_LEVEL:
                    self.fish_x, self.fish_y = tx, ty
                    self.fish_target_x, self.fish_target_y = tx, ty
                    return

        self.fish_x, self.fish_y = base_x, base_y
        self.fish_target_x, self.fish_target_y = base_x, base_y

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e):
            self.close()
        elif event.type == pygame.MOUSEWHEEL and self.state == "fishing":
            dist = math.hypot(self.fish_x - self.bobber_x, self.fish_y - self.bobber_y)
            if dist < 45:
                self.progress += abs(event.y) * 0.05
                self.progress = min(1.0, self.progress)
                if self.progress >= 1.0:
                    self.fish_count += 1
                    self.set_waiting(escaped=False)
                    self.message = f"Harika! Toplam {self.fish_count} balik. Yenisi bekleniyor..."

    def update(self, dt, mouse_world_x, mouse_world_y, world):
        self.zoom_level += (self.target_zoom - self.zoom_level) * 4 * dt
        if not self.active: return

        dx = mouse_world_x - self.bobber_x
        dy = mouse_world_y - self.bobber_y
        dist_to_mouse = math.hypot(dx, dy)
        speed = dist_to_mouse * 5.0
        if dist_to_mouse > 1.0:
            self.bobber_x += (dx / dist_to_mouse) * speed * dt
            self.bobber_y += (dy / dist_to_mouse) * speed * dt

        if self.state == "waiting":
            self.wait_timer -= dt
            if self.wait_timer <= 0: self.spawn_fish(world)
            return

        self.fish_timer -= dt
        if self.fish_timer <= 0:
            self.fish_timer = self.rng.uniform(0.2, 0.9)
            base_x = (self.port.x + self.port.dx * 3 + 0.5) * LOCAL_TILE_SIZE
            base_y = (self.port.y + self.port.dy * 3 + 0.5) * LOCAL_TILE_SIZE

            for _ in range(15):
                tx = base_x + self.rng.uniform(-160, 160)
                ty = base_y + self.rng.uniform(-160, 160)
                grid_x, grid_y = int(tx / LOCAL_TILE_SIZE), int(ty / LOCAL_TILE_SIZE)

                if 0 <= grid_x < COLS and 0 <= grid_y < ROWS:
                    if world.heights[grid_y][grid_x] < SEA_LEVEL:
                        self.fish_target_x = tx
                        self.fish_target_y = ty
                        break

        fdx = self.fish_target_x - self.fish_x
        fdy = self.fish_target_y - self.fish_y
        fdist = math.hypot(fdx, fdy)
        if fdist > 1.0:
            fspeed = 75.0
            self.fish_x += (fdx / fdist) * fspeed * dt
            self.fish_y += (fdy / fdist) * fspeed * dt

        dist_to_fish = math.hypot(self.fish_x - self.bobber_x, self.fish_y - self.bobber_y)
        decay_rate = 0.08 + (dist_to_fish * 0.003)
        self.progress -= decay_rate * dt

        if self.progress <= 0.0:
            self.progress = 0.0
            self.escape_timer += dt
            if self.escape_timer > 1.5: self.set_waiting(escaped=True)
        else:
            self.escape_timer = 0.0

    def draw_world(self, screen, camera_x, camera_y, player):
        if not self.active: return
        screen_fish_x = int(self.fish_x - camera_x)
        screen_fish_y = int(self.fish_y - camera_y)
        screen_bobber_x = int(self.bobber_x - camera_x)
        screen_bobber_y = int(self.bobber_y - camera_y)
        screen_player_x = int(player.x * LOCAL_TILE_SIZE - camera_x)
        screen_player_y = int(player.y * LOCAL_TILE_SIZE - camera_y)

        pygame.draw.line(screen, (210, 210, 210), (screen_player_x, screen_player_y - 10),
                         (screen_bobber_x, screen_bobber_y), 1)
        if self.state == "fishing": pygame.draw.circle(screen, (220, 60, 60), (screen_fish_x, screen_fish_y), 5)
        pygame.draw.circle(screen, (240, 210, 50), (screen_bobber_x, screen_bobber_y), 6)
        pygame.draw.circle(screen, (240, 210, 50), (screen_bobber_x, screen_bobber_y), 45, 1)

        bar_w, bar_h = 40, 6
        bar_x = screen_player_x - bar_w // 2
        bar_y = screen_player_y - 35
        pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
        if self.progress > 0:
            fill_w = int(bar_w * self.progress)
            pygame.draw.rect(screen, (100, 220, 100), (bar_x, bar_y, fill_w, bar_h))

    def draw_ui(self, screen, font):
        if not self.active: return
        pygame.draw.rect(screen, (32, 39, 41, 200), (GAME_WIDTH // 2 - 200, GAME_HEIGHT - 100, 400, 60), border_radius=8)
        pygame.draw.rect(screen, (186, 149, 91), (GAME_WIDTH // 2 - 200, GAME_HEIGHT - 100, 400, 60), width=2, border_radius=8)
        draw_text(screen, font, self.message, (GAME_WIDTH // 2 - 180, GAME_HEIGHT - 80), (244, 218, 165))


# ---------------------------------------------------------------------------
# Active Gameplay Session Manager
# ---------------------------------------------------------------------------
class GameSession:
    """Manages active gameplay systems, player state, camera, minigames, and rendering."""
    def __init__(self, world, ports, spawn, tiles, network, seed, customization, atlas=None):
        self.world = world
        self.ports = ports
        self.player = pygame.Vector2(spawn)
        self.tiles = tiles
        self.network = network
        if network:
            network.expected_seed = world.seed
        self.seed = seed
        self.customization = customization
        self.atlas = atlas
        self.terrain_renderer = TerrainRenderer(world, atlas) if atlas else None

        self.world_map = pygame.transform.scale(self.tiles, (COLS * MAP_TILE_SIZE, ROWS * MAP_TILE_SIZE))
        self.map_rect = self.world_map.get_rect(center=(GAME_WIDTH // 2, GAME_HEIGHT // 2))

        self.leaves = AutumnLeaves(seed)
        self.fishing = OpenWaterFishing(seed)
        self.grain_game = GrainHarvesting(seed)
        self.stone_game = StoneMining()
        self.wood_game = WoodChopping()

        self.map_button = pygame.Rect(GAME_WIDTH - 174, 14, 160, 44)
        self.map_open = False
        self.is_sailing = False
        self.boat_angle = 0.0
        self.boat_speed = 0.0
        self.turn_speed = 0.0
        self.player_exhaust_timer = 0.0
        self.port_trigger_ready = True

        self.cam_x, self.cam_y = get_local_camera(self.player)
        self.facing = "down"
        self.moving = False
        self.previous_pos = (self.player.x, self.player.y)
        self.net_timer = 0.0
        self.resource_revision = 0

        # Fonts
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 21)

        # In-game pause modal state
        self.paused = False
        self.pause_resume_rect = pygame.Rect(GAME_WIDTH // 2 - 120, GAME_HEIGHT // 2 - 40, 240, 40)
        self.pause_menu_rect = pygame.Rect(GAME_WIDTH // 2 - 120, GAME_HEIGHT // 2 + 15, 240, 40)

    def nearby_port(self):
        closest, closest_distance = None, float("inf")
        for port in self.ports:
            distance = math.hypot(self.player.x - (port.x + 0.5), self.player.y - (port.y + 0.5))
            if distance < closest_distance:
                closest_distance, closest = distance, port
        return closest, closest_distance

    def handle_event(self, event, logical_pos) -> str:
        if self.paused:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.paused = False
                return None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.pause_resume_rect.collidepoint(logical_pos):
                    self.paused = False
                elif self.pause_menu_rect.collidepoint(logical_pos):
                    self.paused = False
                    return "MENU"
            return None

        # Minigames
        if self.fishing.active:
            self.fishing.handle_event(event)
            return None
        if self.grain_game.active:
            self.grain_game.handle_event(event, logical_pos)
            return None
        if self.stone_game.active:
            self.stone_game.handle_event(event, logical_pos)
            return None
        if self.wood_game.active:
            penalty = self.wood_game.handle_event(event, self.player_exhaust_timer)
            if penalty > 0:
                self.player_exhaust_timer = penalty
            return None

        if event.type == pygame.KEYDOWN:
            if self.is_sailing and not self.map_open:
                if event.key == pygame.K_a:
                    self.boat_speed += 3.5
                    self.turn_speed -= 2.0
                elif event.key == pygame.K_d:
                    self.boat_speed += 3.5
                    self.turn_speed += 2.0

            if event.key == pygame.K_m:
                self.map_open = not self.map_open
            elif event.key == pygame.K_ESCAPE:
                if self.map_open:
                    self.map_open = False
                else:
                    self.paused = True
            elif event.key == pygame.K_e and not self.map_open and not self.is_sailing:
                port, distance = self.nearby_port()
                if port and distance < 1.6:
                    self.fishing.open(port, self.player)
                    self.port_trigger_ready = False
                else:
                    nearby = [node for node in self.world.nodes if node.active
                              and math.hypot(self.player.x - node.x, self.player.y - node.y) < 1.5]
                    if nearby:
                        node = min(nearby, key=lambda n: math.hypot(self.player.x - n.x, self.player.y - n.y))
                        if node.type == "Odun": self.wood_game.open(node)
                        elif node.type == "Tas": self.stone_game.open(node)
                        elif node.type == "Tahil": self.grain_game.open(node)

            elif event.key == pygame.K_f and not self.map_open:
                port, distance = self.nearby_port()
                if port and distance < 2.5:
                    self.is_sailing = not self.is_sailing
                    if self.is_sailing:
                        self.player.x = port.x + port.dx * 1.5 + 0.5
                        self.player.y = port.y + port.dy * 1.5 + 0.5
                        self.boat_speed = 0.0
                        self.turn_speed = 0.0
                    else:
                        self.player.x = port.spawn[0]
                        self.player.y = port.spawn[1]

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.map_button.collidepoint(logical_pos):
                self.map_open = not self.map_open

        return None

    def sync_resources(self, dt):
        online = self.network and self.network.connected and self.network.resource_sync
        for node in self.world.nodes:
            if node.harvest_pending:
                if online:
                    self.network.harvest(node.id)
                node.harvest_pending = False
            if not node.active and (online or not self.paused):
                node.cooldown = max(0, node.cooldown - dt)
                if not online and node.cooldown <= 0:
                    node.active = True
        if online and self.network.resource_revision > 0 and self.network.resource_revision != self.resource_revision:
            with self.network.lock:
                depleted = self.network.resource_states
                pending = self.network.pending_harvests
                for node in self.world.nodes:
                    if node.id in pending:
                        continue
                    node.cooldown = depleted.get(node.id, 0.0)
                    node.active = node.id not in depleted
                self.resource_revision = self.network.resource_revision
            for game in (self.wood_game, self.stone_game, self.grain_game):
                if game.active and not game.node.active:
                    game.close()

    def update(self, dt: float, logical_mouse_pos: tuple):
        # Pump shared resources even while the pause modal is open.
        self.sync_resources(dt)
        self.net_timer += dt
        if self.net_timer >= 0.05 and self.network:
            self.network.send_and_receive(self.player.x, self.player.y, self.facing,
                                          self.moving, self.is_sailing, self.boat_angle)
            self.net_timer = 0.0
            self.sync_resources(0)
        if self.paused:
            return

        if self.player_exhaust_timer > 0:
            self.player_exhaust_timer -= dt

        # Camera
        target_cam_x, target_cam_y = get_local_camera(self.player, self.fishing)
        self.cam_x += (target_cam_x - self.cam_x) * 4 * dt
        self.cam_y += (target_cam_y - self.cam_y) * 4 * dt

        # Player Movement
        any_minigame = (self.fishing.active or self.grain_game.active or self.stone_game.active or self.wood_game.active)
        if not self.map_open and not any_minigame:
            if self.is_sailing:
                self.boat_speed *= 0.95
                self.turn_speed *= 0.88
                self.boat_angle += self.turn_speed * dt
                dx = math.cos(self.boat_angle) * self.boat_speed * dt
                dy = math.sin(self.boat_angle) * self.boat_speed * dt

                if can_stand(self.world, self.player.x + dx, self.player.y, self.is_sailing):
                    self.player.x += dx
                else:
                    self.boat_speed *= 0.2

                if can_stand(self.world, self.player.x, self.player.y + dy, self.is_sailing):
                    self.player.y += dy
                else:
                    self.boat_speed *= 0.2
            else:
                if self.player_exhaust_timer <= 0:
                    keys = pygame.key.get_pressed()
                    direction = pygame.Vector2(
                        int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT]),
                        int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]),
                    )
                    move_player(self.world, self.player, direction, dt, self.is_sailing)

            port, distance = self.nearby_port()
            if distance > 2.2: self.port_trigger_ready = True
            if port is not None and distance < 1.4 and self.port_trigger_ready and not self.is_sailing:
                self.fishing.open(port, self.player)
                self.port_trigger_ready = False

        if not self.map_open:
            self.leaves.update(dt)
            mx, my = logical_mouse_pos
            real_mx, real_my = mx, my
            if self.fishing.zoom_level > 1.01:
                cx, cy = GAME_WIDTH // 2, GAME_HEIGHT // 2
                real_mx = cx + (mx - cx) / self.fishing.zoom_level
                real_my = cy + (my - cy) / self.fishing.zoom_level

            self.fishing.update(dt, real_mx + self.cam_x, real_my + self.cam_y, self.world)
            self.grain_game.update(dt, logical_mouse_pos)
            if self.wood_game.active:
                res = self.wood_game.update(dt)
                if res and res > 0: self.player_exhaust_timer = res

        dx = self.player.x - self.previous_pos[0]
        dy = self.player.y - self.previous_pos[1]
        self.moving = abs(dx) + abs(dy) > 0.0001
        if self.moving:
            self.facing = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up")
        self.previous_pos = (self.player.x, self.player.y)

    def render(self, screen: pygame.Surface, logical_mouse_pos: tuple):
        camera_x, camera_y = round(self.cam_x), round(self.cam_y)
        screen.fill((32, 39, 41))

        if self.map_open:
            draw_world_map(screen, self.world, self.world_map, self.map_rect, self.player, self.network)
        else:
            # Viewport tile boundaries
            start_x = int(camera_x // LOCAL_TILE_SIZE)
            start_y = int(camera_y // LOCAL_TILE_SIZE)
            visible_cols = min(COLS - start_x, math.ceil(GAME_WIDTH / LOCAL_TILE_SIZE) + 2)
            visible_rows = min(ROWS - start_y, math.ceil(GAME_HEIGHT / LOCAL_TILE_SIZE) + 2)

            # ---------------------------------------------------------------
            # 1. GROUND & AUTO-TILED TERRAIN (Using Fall Tile Set)
            # ---------------------------------------------------------------
            if self.terrain_renderer:
                self.terrain_renderer.draw(screen, camera_x, camera_y)
            else:
                # Fallback primitive renderer if atlas unavailable
                if visible_cols > 0 and visible_rows > 0:
                    region = self.tiles.subsurface((start_x, start_y, visible_cols, visible_rows))
                    enlarged = pygame.transform.scale(region, (visible_cols * LOCAL_TILE_SIZE, visible_rows * LOCAL_TILE_SIZE))
                    screen.blit(enlarged, (round(start_x * LOCAL_TILE_SIZE - camera_x), round(start_y * LOCAL_TILE_SIZE - camera_y)))

            # ---------------------------------------------------------------
            # 2. DOCKS & PIERS
            # ---------------------------------------------------------------
            draw_ports(screen, self.ports, self.player, camera_x, camera_y, self.atlas)

            moving = self.moving

            players_to_draw = [{
                "y": self.player.y,
                "pos": (round(self.player.x * LOCAL_TILE_SIZE) - camera_x, round(self.player.y * LOCAL_TILE_SIZE) - camera_y),
                "moving": moving,
                "facing": self.facing,
                "color": None,
                "is_sailing": self.is_sailing,
                "is_me": True,
                "boat_angle": self.boat_angle
            }]

            if self.network and self.network.connected:
                with self.network.lock:
                    for pid, pdata in self.network.other_players.items():
                        other_screen_pos = (round(pdata["x"] * LOCAL_TILE_SIZE) - camera_x, round(pdata["y"] * LOCAL_TILE_SIZE) - camera_y)
                        players_to_draw.append({
                            "y": pdata["y"],
                            "pos": other_screen_pos,
                            "moving": pdata.get("moving", False),
                            "facing": pdata.get("facing", "down"),
                            "color": (60, 100, 150),
                            "is_sailing": pdata.get("sailing", False),
                            "is_me": False,
                            "boat_angle": pdata.get("boat_angle", 0.0)
                        })

            # One foot-position sort for ALL tall objects and characters.
            objects = []
            for node in self.world.nodes:
                if (camera_x - 80 <= node.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 80
                        and camera_y - 60 <= node.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 110):
                    objects.append((node.y, "node", node))
            for x, y in self.world.buildings:
                if start_x - 2 <= x <= start_x + visible_cols + 2 and start_y - 2 <= y <= start_y + visible_rows + 2:
                    objects.append((y + 1, "house", (x, y)))
            if self.atlas:
                for kind, x, y in self.world.village_props:
                    if (camera_x - 60 <= x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 60
                            and camera_y - 60 <= y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 80):
                        objects.append((y, "prop", (kind, x, y)))
            objects.extend((p["y"], "player", p) for p in players_to_draw)
            objects.sort(key=lambda obj: obj[0])
            for _, kind, obj in objects:
                if kind == "node":
                    draw_node(screen, obj, camera_x, camera_y, self.atlas)
                elif kind == "house":
                    x, y = obj
                    rect = pygame.Rect(x * LOCAL_TILE_SIZE - camera_x, y * LOCAL_TILE_SIZE - camera_y,
                                       LOCAL_TILE_SIZE, LOCAL_TILE_SIZE)
                    draw_house(screen, rect, self.atlas, x * 13 + y * 29)
                elif kind == "prop":
                    prop, x, y = obj
                    sprite = getattr(self.atlas, prop)
                    screen.blit(sprite, (round(x * LOCAL_TILE_SIZE) - camera_x - sprite.get_width() // 2,
                                         round(y * LOCAL_TILE_SIZE) - camera_y - sprite.get_height() + 4))
                else:
                    p = obj
                    p["pos"] = tuple(round(v) for v in p["pos"])
                    draw_player(screen, p["pos"], p["moving"], p["facing"], p["color"], p["is_sailing"], p["boat_angle"], self.atlas)
                    if not p["is_me"]:
                        tag = self.small_font.render("Diger Oyuncu", True, (255, 255, 255))
                        screen.blit(tag, (p["pos"][0] - 25, p["pos"][1] - 55))

            # ---------------------------------------------------------------
            # 8. ATMOSPHERIC PARTICLES & MINIGAMES UI
            # ---------------------------------------------------------------
            self.leaves.draw(screen)
            self.fishing.draw_world(screen, camera_x, camera_y, self.player)

            if self.fishing.zoom_level > 1.01:
                zoom = self.fishing.zoom_level
                w, h = GAME_WIDTH, GAME_HEIGHT
                new_w, new_h = int(w / zoom), int(h / zoom)
                sub_rect = pygame.Rect((w - new_w) // 2, (h - new_h) // 2, new_w, new_h)
                zoomed_surface = pygame.transform.scale(screen.subsurface(sub_rect).copy(), (w, h))
                screen.blit(zoomed_surface, (0, 0))

            self.fishing.draw_ui(screen, self.font)
            self.grain_game.draw_ui(screen, self.font, logical_mouse_pos)
            self.stone_game.draw_ui(screen, self.font)
            self.wood_game.draw_ui(screen, self.font)

            if self.player_exhaust_timer > 0:
                draw_text(screen, self.font, f"YORGUNLUK! ({self.player_exhaust_timer:.1f}s)",
                          (GAME_WIDTH // 2 - 70, GAME_HEIGHT // 2 - 50), (255, 50, 50))

        # Bottom status bar
        pygame.draw.rect(screen, (32, 39, 41), (0, GAME_HEIGHT - 30, GAME_WIDTH, 30))
        px, py = int(self.player.x), int(self.player.y)
        owner = self.world.owners[py][px] if 0 <= px < COLS and 0 <= py < ROWS else -1
        current_island = self.world.islands[owner] if owner >= 0 else None
        location = current_island.name if current_island else "Deniz"

        net_status = "Tek Oyuncu (Cevrimdisi)"
        if self.network and self.network.connected:
            net_status = f"Cevrimici: {len(self.network.other_players) + 1} Oyuncu"

        info = f"{location} | {net_status}"
        port, distance = self.nearby_port()
        if port is not None and distance < 2.5:
            info += " | E: balik tut | F: gemiye bin/in"
        elif self.is_sailing:
            info += " | A: Sol Kurek | D: Sag Kurek"
        else:
            info += " | WASD: Yuru | Kaynak yaninda E: Topla | ESC: Menü"

        draw_text(screen, self.small_font, info, (12, GAME_HEIGHT - 23), (229, 219, 193))

        # Map Button top right
        hovered = self.map_button.collidepoint(logical_mouse_pos)
        button_color = (100, 91, 67) if hovered else (65, 66, 54)
        pygame.draw.rect(screen, button_color, self.map_button, border_radius=7)
        pygame.draw.rect(screen, (181, 158, 111), self.map_button, width=1, border_radius=7)
        label = "Haritayi kapat" if self.map_open else "Harita [M]"
        label_surface = self.font.render(label, True, (241, 228, 198))
        screen.blit(label_surface, label_surface.get_rect(center=self.map_button.center))

        # In-Game Pause Modal
        if self.paused:
            overlay = pygame.Surface((GAME_WIDTH, GAME_HEIGHT), pygame.SRCALPHA)
            overlay.fill((10, 6, 4, 180))
            screen.blit(overlay, (0, 0))

            mw, mh = 360, 220
            mx = (GAME_WIDTH - mw) // 2
            my = (GAME_HEIGHT - mh) // 2
            pygame.draw.rect(screen, (38, 22, 16), (mx, my, mw, mh), border_radius=10)
            pygame.draw.rect(screen, COLOR_BORDER_OUTER, (mx, my, mw, mh), width=2, border_radius=10)

            title = self.font.render("OYUN DURAKLATILDI", True, COLOR_TEXT_GOLD)
            screen.blit(title, title.get_rect(center=(GAME_WIDTH // 2, my + 30)))

            r_hov = self.pause_resume_rect.collidepoint(logical_mouse_pos)
            pygame.draw.rect(screen, (85, 45, 28) if r_hov else (60, 30, 20), self.pause_resume_rect, border_radius=6)
            pygame.draw.rect(screen, COLOR_BORDER_OUTER, self.pause_resume_rect, width=1, border_radius=6)
            r_txt = self.font.render("DEVAM ET (ESC)", True, (255, 230, 160))
            screen.blit(r_txt, r_txt.get_rect(center=self.pause_resume_rect.center))

            m_hov = self.pause_menu_rect.collidepoint(logical_mouse_pos)
            pygame.draw.rect(screen, (85, 45, 28) if m_hov else (60, 30, 20), self.pause_menu_rect, border_radius=6)
            pygame.draw.rect(screen, COLOR_BORDER_OUTER, self.pause_menu_rect, width=1, border_radius=6)
            m_txt = self.font.render("ANA MENÜYE DÖN", True, (255, 230, 160))
            screen.blit(m_txt, m_txt.get_rect(center=self.pause_menu_rect.center))


# ---------------------------------------------------------------------------
# Background Preloader System
# ---------------------------------------------------------------------------
class PreloadStatus(Enum):
    NOT_STARTED = 0
    LOADING = 1
    READY = 2
    ERROR = 3


class BackgroundPreloader:
    """
    Asynchronously executes expensive world generation and networking checks in a
    background daemon thread, safely passing prepared data to the main thread via a queue.
    """
    def __init__(self, host='127.0.0.1', port=5555):
        self.host = host
        self.port = port
        self.status = PreloadStatus.NOT_STARTED
        self.progress = 0.0
        self.status_text = "Not started"
        self.data_queue = queue.Queue()
        self.worker_thread = None
        self.network = NetworkClient(host=self.host, port=self.port)
        self.game_session = None
        self.atlas = None
        self.finalizer = None

    def start(self):
        self.status = PreloadStatus.LOADING
        self.status_text = "Preparing World..."
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def _worker(self):
        try:
            self.progress = 0.05
            self.status_text = "Checking network..."

            connected = self.network.try_connect(timeout=0.6)
            seed = self.network.seed

            self.status_text = "Generating island terrain..."
            self.progress = 0.10

            def on_progress(p):
                self.progress = 0.10 + p * 0.70

            world = make_world(seed, on_progress)

            self.status_text = "Building ports & waterways..."
            self.progress = 0.82
            ports = generate_ports(world)

            self.status_text = "Locating player spawn point..."
            self.progress = 0.88
            spawn = find_spawn(world)

            self.status_text = "Preparing tile map buffer..."
            self.progress = 0.94
            tile_bytes = compute_tile_pixels(world)
            prepare_terrain(world)

            self.progress = 0.99
            self.status_text = "Finalizing..."

            self.data_queue.put({
                "world": world,
                "ports": ports,
                "spawn": spawn,
                "tile_bytes": tile_bytes,
                "seed": seed,
                "network": self.network,
            })
        except Exception as e:
            print(f"[PRELOAD ERROR] Background generation failed: {e}")
            self.status = PreloadStatus.ERROR
            self.status_text = f"Error: {e}"

    def _finalize(self, data, customization):
        tiles = pygame.image.frombuffer(data["tile_bytes"], (COLS, ROWS), "RGB").convert()
        try:
            self.atlas = TileAtlas(find_tileset_file(), deferred=True)
            yield from self.atlas.build_steps
        except Exception as exc:
            print(f"[WARNING] Could not load TileAtlas: {exc}")
            self.atlas = None
        self.game_session = GameSession(data["world"], data["ports"], data["spawn"], tiles,
                                        data["network"], data["seed"], customization, atlas=self.atlas)
        if self.game_session.terrain_renderer:
            yield from self.game_session.terrain_renderer.warm_view(self.game_session.cam_x, self.game_session.cam_y)
        self.status = PreloadStatus.READY
        self.progress = 1.0
        self.status_text = "Ready!"

    def poll(self, customization) -> bool:
        if self.status == PreloadStatus.READY:
            return True
        if self.finalizer is None and not self.data_queue.empty():
            self.status_text = "Preparing autumn artwork..."
            self.finalizer = self._finalize(self.data_queue.get_nowait(), customization)
        if self.finalizer is not None:
            # All Surface operations stay on the display thread, spread across menu frames.
            deadline = time.perf_counter() + 0.006
            try:
                while time.perf_counter() < deadline:
                    next(self.finalizer)
            except StopIteration:
                self.finalizer = None
            except Exception as exc:
                self.finalizer = None
                self.status = PreloadStatus.ERROR
                self.status_text = f"Error: {exc}"
                print(f"[PRELOAD ERROR] {exc}")
        return self.status == PreloadStatus.READY


# ---------------------------------------------------------------------------
# Menu UI & Visual Effects (from main.py)
# ---------------------------------------------------------------------------
class PixelFontRenderer:
    """Renders crisp retro pixel-art styled text with shadows and highlights."""
    def __init__(self):
        pygame.font.init()
        preferred = ["monaco", "menlo", "consolas", "couriernew", "dejavusansmono", "arial"]
        self.font_small = pygame.font.SysFont(preferred, 11, bold=True)
        self.font_med = pygame.font.SysFont(preferred, 13, bold=True)
        self.font_title = pygame.font.SysFont(preferred, 16, bold=True)
        self.font_large = pygame.font.SysFont(preferred, 22, bold=True)

    def draw_text(self, surface: pygame.Surface, text: str, pos: tuple,
                  font_type="med", color=COLOR_TEXT_WARM, shadow=True, shadow_color=COLOR_TEXT_SHADOW):
        f = getattr(self, f"font_{font_type}", self.font_med)
        x, y = pos
        if shadow:
            s_surf = f.render(text, False, shadow_color)
            surface.blit(s_surf, (x + 1, y + 1))
        t_surf = f.render(text, False, color)
        surface.blit(t_surf, (x, y))
        return t_surf.get_rect(topleft=(x, y))

    def draw_text_centered(self, surface: pygame.Surface, text: str, center: tuple,
                           font_type="med", color=COLOR_TEXT_WARM, shadow=True, shadow_color=COLOR_TEXT_SHADOW):
        f = getattr(self, f"font_{font_type}", self.font_med)
        cx, cy = center
        t_surf = f.render(text, False, color)
        rect = t_surf.get_rect(center=(cx, cy))
        if shadow:
            s_surf = f.render(text, False, shadow_color)
            surface.blit(s_surf, (rect.x + 1, rect.y + 1))
        surface.blit(t_surf, rect)
        return rect


class LeafParticle:
    """Menu ambient fluttering autumn leaf particle."""
    def __init__(self, w=MENU_WIDTH, h=MENU_HEIGHT):
        self.reset(w, h, initial=True)

    def reset(self, w, h, initial=False):
        self.x = random.uniform(0, w + 100)
        self.y = random.uniform(0, h) if initial else random.uniform(-30, -5)
        self.speed_y = random.uniform(20.0, 50.0)
        self.speed_x = random.uniform(-35.0, -15.0)
        self.amplitude = random.uniform(15.0, 35.0)
        self.frequency = random.uniform(1.2, 2.5)
        self.time = random.uniform(0, 100)
        self.size = random.choice([2, 3, 3, 4])
        self.color = random.choice([
            (235, 110, 30),
            (210, 75, 30),
            (245, 170, 40),
            (195, 60, 35),
            (160, 45, 25),
            (255, 195, 60),
        ])

    def update(self, dt: float, w=MENU_WIDTH, h=MENU_HEIGHT):
        self.time += dt
        self.y += self.speed_y * dt
        self.x += (self.speed_x + math.sin(self.time * self.frequency) * self.amplitude) * dt
        if self.y > h + 10 or self.x < -30:
            self.reset(w, h, initial=False)

    def draw(self, surface: pygame.Surface):
        ix, iy = int(self.x), int(self.y)
        if self.size <= 2:
            surface.set_at((ix, iy), self.color)
            surface.set_at((ix + 1, iy), self.color)
        elif self.size == 3:
            surface.fill(self.color, (ix, iy, 2, 2))
            surface.set_at((ix + 1, iy - 1), self.color)
        else:
            surface.fill(self.color, (ix, iy, 3, 2))
            surface.set_at((ix + 1, iy - 1), self.color)
            surface.set_at((ix + 1, iy + 2), self.color)


class FireEmber:
    """Rising ember spark particle emitted by the campfire."""
    def __init__(self, cx=114, cy=308):
        self.cx = cx
        self.cy = cy
        self.reset(initial=True)

    def reset(self, initial=False):
        self.x = self.cx + random.uniform(-6, 6)
        self.y = self.cy - random.uniform(2, 10) if initial else self.cy - random.uniform(0, 3)
        self.vy = random.uniform(-22.0, -42.0)
        self.vx = random.uniform(-6.0, 4.0)
        self.wobble_freq = random.uniform(4.0, 7.5)
        self.wobble_amp = random.uniform(5.0, 12.0)
        self.lifetime = random.uniform(1.1, 2.2)
        self.age = random.uniform(0.0, self.lifetime) if initial else 0.0
        self.size = random.choice([1, 1, 1, 2])

    def update(self, dt: float):
        self.age += dt
        if self.age >= self.lifetime:
            self.reset(initial=False)
            return
        self.y += self.vy * dt
        self.x += (self.vx + math.sin(self.age * self.wobble_freq) * self.wobble_amp) * dt

    def draw(self, surface: pygame.Surface):
        progress = self.age / self.lifetime
        if progress < 0.25:
            color = (255, 245, 170)
        elif progress < 0.60:
            color = (255, 145, 35)
        elif progress < 0.85:
            color = (210, 60, 20)
        else:
            color = (140, 35, 15)

        ix, iy = int(self.x), int(self.y)
        if 0 <= ix < MENU_WIDTH and 0 <= iy < MENU_HEIGHT:
            surface.set_at((ix, iy), color)
            if self.size == 2 and progress < 0.5:
                if 0 <= ix + 1 < MENU_WIDTH:
                    surface.set_at((ix + 1, iy), color)
                if 0 <= iy + 1 < MENU_HEIGHT:
                    surface.set_at((ix, iy + 1), (255, 180, 50))


class AmbientLightingSystem:
    """Manages window candlelight flicker, platform/cottage lanterns, campfire flames and water shimmer."""
    def __init__(self):
        self.time = 0.0
        self.glow_lantern = self._create_smooth_glow(20, 20, (110, 80, 22), falloff=2.0)
        self.glow_fire_core = self._create_smooth_glow(30, 24, (120, 65, 15), falloff=1.8)
        self.glow_fire_ground = self._create_smooth_glow(42, 22, (80, 35, 8), falloff=2.2)
        self.glow_small_lantern = self._create_smooth_glow(14, 14, (90, 65, 18), falloff=2.0)
        self.glow_window_halo = self._create_smooth_glow(16, 16, (60, 40, 10), falloff=2.2)
        self.embers = [FireEmber(cx=114, cy=308) for _ in range(12)]

        self.windows = [
            {"name": "Cottage1_Main", "rect": pygame.Rect(73, 255, 17, 23), "base_rgb": (38, 25, 5), "s1": 1.9, "s2": 5.7, "phase": 0.3},
            {"name": "Shed_L", "rect": pygame.Rect(178, 226, 13, 18), "base_rgb": (34, 22, 4), "s1": 2.3, "s2": 4.8, "phase": 1.8},
            {"name": "Shed_R", "rect": pygame.Rect(214, 223, 13, 16), "base_rgb": (36, 24, 4), "s1": 1.6, "s2": 6.3, "phase": 3.1},
            {"name": "House_Upper", "rect": pygame.Rect(308, 146, 20, 22), "base_rgb": (42, 28, 6), "s1": 1.4, "s2": 5.1, "phase": 0.9},
            {"name": "House_Lower", "rect": pygame.Rect(280, 204, 15, 21), "base_rgb": (36, 24, 5), "s1": 2.1, "s2": 6.8, "phase": 4.2},
            {"name": "House_Attic", "rect": pygame.Rect(249, 155, 11, 13), "base_rgb": (30, 20, 4), "s1": 2.8, "s2": 7.2, "phase": 2.5},
            {"name": "Hill_Window", "rect": pygame.Rect(50, 96, 14, 15), "base_rgb": (32, 20, 4), "s1": 1.7, "s2": 4.3, "phase": 5.0},
        ]

        self.water_shimmers = [
            (880, 150, 4, 1.2, 0.0),
            (915, 158, 5, 1.7, 1.5),
            (940, 164, 4, 2.1, 3.2),
            (895, 172, 6, 1.5, 0.8),
            (930, 178, 5, 2.4, 2.7),
            (955, 184, 4, 1.9, 4.1),
            (875, 165, 3, 2.6, 1.1),
            (920, 190, 5, 1.4, 3.8),
        ]

    def _create_smooth_glow(self, rx: int, ry: int, max_rgb: tuple, falloff=2.0) -> pygame.Surface:
        surf = pygame.Surface((rx * 2, ry * 2), pygame.SRCALPHA)
        for y in range(ry * 2):
            dy = (y - ry) / ry
            for x in range(rx * 2):
                dx = (x - rx) / rx
                d2 = dx * dx + dy * dy
                if d2 < 1.0:
                    dist = math.sqrt(d2)
                    factor = (1.0 - dist) ** falloff
                    surf.set_at((x, y), (int(max_rgb[0] * factor), int(max_rgb[1] * factor), int(max_rgb[2] * factor), 255))
        return surf

    def update(self, dt: float):
        self.time += dt
        for e in self.embers:
            e.update(dt)

    def draw(self, surface: pygame.Surface, time_elapsed: float):
        t = time_elapsed

        # 1. Coastal Water Shimmer
        for sx, sy, length, speed, phase in self.water_shimmers:
            val = math.sin(t * speed * 3.0 + phase)
            if val > 0.35:
                alpha = int(120 * (val - 0.35) / 0.65)
                shimmer_surf = pygame.Surface((length, 1), pygame.SRCALPHA)
                shimmer_surf.fill((255, 220, 130, alpha))
                surface.blit(shimmer_surf, (sx, sy), special_flags=pygame.BLEND_RGBA_ADD)

        # 2. Window Candlelight Flicker
        for win in self.windows:
            r = win["rect"]
            flicker = (
                0.60 * math.sin(t * win["s1"] * 2.0 + win["phase"])
                + 0.30 * math.sin(t * win["s2"] * 3.5 + win["phase"] * 2.0)
                + 0.10 * math.sin(t * 11.0 + win["phase"] * 4.0)
            )
            mult = 0.80 + 0.20 * flicker
            base_r, base_g, base_b = win["base_rgb"]
            add_color = (int(base_r * mult), int(base_g * mult), int(base_b * mult), 255)

            win_surf = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
            win_surf.fill(add_color)
            surface.blit(win_surf, r.topleft, special_flags=pygame.BLEND_RGBA_ADD)

            halo_x = r.centerx - self.glow_window_halo.get_width() // 2
            halo_y = r.centery - self.glow_window_halo.get_height() // 2
            surface.blit(self.glow_window_halo, (halo_x, halo_y), special_flags=pygame.BLEND_RGBA_ADD)

        # 3. Campfire Glow & Embers
        ground_pulse = 0.85 + 0.15 * math.sin(t * 3.2)
        gw = int(self.glow_fire_ground.get_width() * ground_pulse)
        gh = int(self.glow_fire_ground.get_height() * ground_pulse)
        if gw > 0 and gh > 0:
            g_scaled = pygame.transform.scale(self.glow_fire_ground, (gw, gh))
            surface.blit(g_scaled, (114 - gw // 2, 318 - gh // 2), special_flags=pygame.BLEND_RGBA_ADD)

        flame_flicker = (
            0.55 * math.sin(t * 5.0)
            + 0.30 * math.sin(t * 9.2 + 1.2)
            + 0.15 * math.sin(t * 17.5 + 2.5)
        )
        core_scale = 0.88 + 0.16 * flame_flicker
        cw = int(self.glow_fire_core.get_width() * core_scale)
        ch = int(self.glow_fire_core.get_height() * core_scale)
        if cw > 0 and ch > 0:
            c_scaled = pygame.transform.scale(self.glow_fire_core, (cw, ch))
            surface.blit(c_scaled, (114 - cw // 2, 306 - ch // 2), special_flags=pygame.BLEND_RGBA_ADD)

        tongue_shift = int(1.2 * math.sin(t * 12.0))
        flame_pts = [
            (113 + tongue_shift, 298),
            (114 + tongue_shift, 297),
            (115, 299),
            (112, 301),
            (116, 300),
        ]
        flame_color = (255, 225, 120) if (flame_flicker > 0) else (255, 175, 40)
        for fx, fy in flame_pts:
            surface.set_at((fx, fy), flame_color)

        for e in self.embers:
            e.draw(surface)

        # 4. Lanterns
        plat_pulse = 0.90 + 0.10 * math.sin(t * 2.8)
        lw = int(self.glow_lantern.get_width() * plat_pulse)
        lh = int(self.glow_lantern.get_height() * plat_pulse)
        if lw > 0 and lh > 0:
            l_scaled = pygame.transform.scale(self.glow_lantern, (lw, lh))
            surface.blit(l_scaled, (546 - lw // 2, 316 - lh // 2), special_flags=pygame.BLEND_RGBA_ADD)

        core_bright = int(220 + 35 * math.sin(t * 6.5))
        surface.fill((core_bright, core_bright - 30, 110), (545, 315, 2, 3))

        c1_pulse = 0.92 + 0.08 * math.sin(t * 3.5 + 2.0)
        c1w = int(self.glow_small_lantern.get_width() * c1_pulse)
        c1h = int(self.glow_small_lantern.get_height() * c1_pulse)
        if c1w > 0 and c1h > 0:
            c1_scaled = pygame.transform.scale(self.glow_small_lantern, (c1w, c1h))
            surface.blit(c1_scaled, (43 - c1w // 2, 284 - c1h // 2), special_flags=pygame.BLEND_RGBA_ADD)

        p_pulse = 0.90 + 0.10 * math.sin(t * 2.2 + 1.1)
        pw = int(self.glow_small_lantern.get_width() * p_pulse)
        ph = int(self.glow_small_lantern.get_height() * p_pulse)
        if pw > 0 and ph > 0:
            p_scaled = pygame.transform.scale(self.glow_small_lantern, (pw, ph))
            surface.blit(p_scaled, (414 - pw // 2, 160 - ph // 2), special_flags=pygame.BLEND_RGBA_ADD)


# ---------------------------------------------------------------------------
# Integrated Main Application Class
# ---------------------------------------------------------------------------
class AutumnGameApp:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Autumn Island Exploration - Multiplayer Edition")

        # Logical surfaces for menu and game
        self.menu_surface = pygame.Surface((MENU_WIDTH, MENU_HEIGHT))
        self.game_surface = pygame.Surface((GAME_WIDTH, GAME_HEIGHT))

        # Main resizable window
        self.window = pygame.display.set_mode((DEFAULT_WIN_W, DEFAULT_WIN_H), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.is_running = True
        self.is_fullscreen = False

        # State management: "MENU" or "GAME"
        self.state = "MENU"
        self.show_customize = False
        self.show_settings = False
        self.show_credits = False

        # Display scaling / letterboxing variables
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.update_letterbox()

        # Typography & Visual Systems
        self.font_renderer = PixelFontRenderer()
        self.particles = [LeafParticle() for _ in range(40)]
        self.ambient_lighting = AmbientLightingSystem()

        # Character customization dictionary
        self.customization = {
            "hair": 2,
            "skin": 1,
            "shirt": 0,
            "pants": 2,
        }

        # Timers & Hover state
        self.time_elapsed = 0.0
        self.hovered_menu_button = -1
        self.hovered_custom_slot = None
        self.hovered_close_btn = False

        # Load menu assets
        self.load_menu_assets()

        # Start background preloading immediately!
        print("[INIT] Starting background game preloader...")
        self.preloader = BackgroundPreloader()
        self.preloader.start()

    # -----------------------------------------------------------------------
    # Asset Loading & Slicing
    # -----------------------------------------------------------------------
    def load_menu_assets(self):
        print("Loading menu assets...")

        # 1. Background
        bg_path = find_asset("bg(1).jpeg")
        bg_raw = pygame.image.load(str(bg_path)).convert()
        self.bg_surface = pygame.transform.scale(bg_raw, (MENU_WIDTH, MENU_HEIGHT))

        # 2. Base Character
        char_path = find_asset("19_34_26")
        char_raw = pygame.image.load(str(char_path)).convert_alpha()
        f0_rect = pygame.Rect(92, 36, 238, 483)
        self.char_orig = char_raw.subsurface(f0_rect).copy()

        char_h = 190
        char_scale = char_h / self.char_orig.get_height()
        char_w = round(self.char_orig.get_width() * char_scale)
        self.char_scaled = pygame.transform.scale(self.char_orig, (char_w, char_h))
        self.char_pos = (430 - char_w // 2, 370 - char_h)

        # 3. Wooden Menu Asset
        menu_path = find_asset("19_43_03")
        menu_raw = pygame.image.load(str(menu_path)).convert_alpha()
        menu_crop_rect = pygame.Rect(76, 46, 901, 1464)
        self.menu_orig = menu_raw.subsurface(menu_crop_rect).copy()

        self.menu_h = 490
        self.menu_scale = self.menu_h / 1464.0
        self.menu_w = round(901 * self.menu_scale)
        self.menu_scaled = pygame.transform.scale(self.menu_orig, (self.menu_w, self.menu_h))
        self.menu_pos = (MENU_WIDTH - self.menu_w, 576 - self.menu_h - 10)

        raw_buttons = [
            ("Start Game", 241, 442, 74, 900),
            ("Customize", 465, 663, 36, 890),
            ("Settings", 688, 886, 59, 879),
            ("Credits", 912, 1104, 87, 882),
            ("Quit", 1125, 1301, 64, 886),
        ]
        self.menu_buttons = []
        for name, y1, y2, x1, x2 in raw_buttons:
            sy = round(y1 * self.menu_scale)
            sh = round((y2 - y1) * self.menu_scale)
            sx = round(x1 * self.menu_scale)
            sw = round((x2 - x1) * self.menu_scale)
            btn_rect = pygame.Rect(sx, sy, sw, sh)

            sign_slice = self.menu_scaled.subsurface(btn_rect).copy()
            arr_rgb = pygame.surfarray.pixels3d(sign_slice)
            arr_alpha = pygame.surfarray.pixels_alpha(sign_slice)
            mask = arr_alpha > 80
            for c_idx, add_val in enumerate([32, 20, 5]):
                cur = arr_rgb[:, :, c_idx].astype(np.int32)
                cur[mask] = np.clip(cur[mask] + add_val, 0, 255)
                arr_rgb[:, :, c_idx] = cur.astype(np.uint8)
            del arr_rgb
            del arr_alpha

            self.menu_buttons.append({
                "name": name,
                "local_rect": btn_rect,
                "hover_surf": sign_slice,
            })

        # 4. Hair & Skin Sheet
        hair_path = find_asset("retro")
        self.hair_sheet = pygame.image.load(str(hair_path)).convert_alpha()

        # 5. Cloth Sheet
        cloth_path = find_asset("kıyafet")
        self.cloth_sheet = pygame.image.load(str(cloth_path)).convert_alpha()

        self.thumbnails = {"hair": [], "skin": [], "shirt": [], "pants": []}

        hair_boxes = [
            (38, 114, 210, 260),
            (463, 114, 202, 260),
            (880, 114, 205, 260),
            (1300, 114, 205, 260),
            (1720, 114, 205, 260),
        ]
        for box in hair_boxes:
            sub = self.hair_sheet.subsurface(pygame.Rect(*box)).copy()
            self.thumbnails["hair"].append(pygame.transform.smoothscale(sub, (36, 36)))

        skin_boxes = [
            (38, 490, 202, 194),
            (463, 490, 202, 194),
            (893, 490, 197, 194),
            (1318, 490, 197, 194),
            (1743, 490, 197, 194),
        ]
        for box in skin_boxes:
            sub = self.hair_sheet.subsurface(pygame.Rect(*box)).copy()
            self.thumbnails["skin"].append(pygame.transform.smoothscale(sub, (36, 36)))

        top_boxes = [
            (53, 91, 415, 247),
            (489, 91, 390, 247),
            (898, 91, 386, 247),
            (1301, 91, 402, 247),
            (1722, 91, 412, 247),
        ]
        for box in top_boxes:
            sub = self.cloth_sheet.subsurface(pygame.Rect(*box)).copy()
            self.thumbnails["shirt"].append(pygame.transform.smoothscale(sub, (36, 36)))

        pants_boxes = [
            (53, 430, 414, 263),
            (489, 430, 390, 263),
            (898, 430, 386, 263),
            (1301, 430, 402, 263),
            (1722, 430, 412, 263),
        ]
        for box in pants_boxes:
            sub = self.cloth_sheet.subsurface(pygame.Rect(*box)).copy()
            self.thumbnails["pants"].append(pygame.transform.smoothscale(sub, (36, 36)))

        # Customization Panel Layout Coordinates
        self.panel_rect = pygame.Rect(476, 68, 242, 440)
        self.close_btn_rect = pygame.Rect(self.panel_rect.right - 24, self.panel_rect.top + 6, 18, 18)

        self.category_defs = [
            ("hair", "Hair Style"),
            ("skin", "Skin Tone"),
            ("shirt", "Top (Outfit)"),
            ("pants", "Pants"),
        ]
        self.panel_slots = {}
        slot_w, slot_h = 40, 40
        slot_gap = 6
        start_x = self.panel_rect.x + (self.panel_rect.width - (5 * slot_w + 4 * slot_gap)) // 2

        for cat_idx, (cat_key, cat_title) in enumerate(self.category_defs):
            cat_y = self.panel_rect.y + 40 + cat_idx * 98
            self.panel_slots[cat_key] = {
                "title": cat_title,
                "label_pos": (start_x, cat_y),
                "slots": [],
            }
            row_y = cat_y + 18
            for opt_idx in range(5):
                sx = start_x + opt_idx * (slot_w + slot_gap)
                rect = pygame.Rect(sx, row_y, slot_w, slot_h)
                self.panel_slots[cat_key]["slots"].append(rect)

        print("Menu assets loaded successfully!")

    # -----------------------------------------------------------------------
    # Coordinate Conversion & Window Letterboxing
    # -----------------------------------------------------------------------
    def update_letterbox(self):
        win_w, win_h = self.window.get_size()
        cur_w, cur_h = (GAME_WIDTH, GAME_HEIGHT) if self.state == "GAME" else (MENU_WIDTH, MENU_HEIGHT)
        scale_x = win_w / cur_w
        scale_y = win_h / cur_h
        self.scale = min(scale_x, scale_y)
        self.target_w = int(cur_w * self.scale)
        self.target_h = int(cur_h * self.scale)
        self.offset_x = (win_w - self.target_w) // 2
        self.offset_y = (win_h - self.target_h) // 2

    def window_to_logical(self, pos: tuple) -> tuple:
        wx, wy = pos
        lx = (wx - self.offset_x) / self.scale
        ly = (wy - self.offset_y) / self.scale
        return int(lx), int(ly)

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.window = pygame.display.set_mode((DEFAULT_WIN_W, DEFAULT_WIN_H), pygame.RESIZABLE)
        self.update_letterbox()

    # -----------------------------------------------------------------------
    # Event Handling
    # -----------------------------------------------------------------------
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.is_running = False
                return

            elif event.type == pygame.VIDEORESIZE:
                self.update_letterbox()

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                self.toggle_fullscreen()

            if self.state == "GAME" and self.preloader.game_session:
                lx, ly = self.window_to_logical(pygame.mouse.get_pos())
                action = self.preloader.game_session.handle_event(event, (lx, ly))
                if action == "MENU":
                    self.state = "MENU"
                    self.update_letterbox()

            elif self.state == "MENU":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self.show_settings:
                            self.show_settings = False
                        elif self.show_credits:
                            self.show_credits = False
                        elif self.show_customize:
                            self.show_customize = False
                        elif self.preloader.game_session:
                            self.state = "GAME"
                            self.update_letterbox()

                elif event.type == pygame.MOUSEMOTION:
                    lx, ly = self.window_to_logical(event.pos)
                    self.on_menu_mouse_move(lx, ly)

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    lx, ly = self.window_to_logical(event.pos)
                    self.on_menu_mouse_click(lx, ly)

    def on_menu_mouse_move(self, lx: int, ly: int):
        self.hovered_menu_button = -1
        if self.state == "MENU" and not self.show_settings and not self.show_credits:
            mx, my = self.menu_pos
            for idx, btn in enumerate(self.menu_buttons):
                rect = btn["local_rect"]
                screen_rect = pygame.Rect(mx + rect.x, my + rect.y, rect.width, rect.height)
                if screen_rect.collidepoint(lx, ly):
                    self.hovered_menu_button = idx
                    break

        self.hovered_custom_slot = None
        self.hovered_close_btn = False
        if self.show_customize and not self.show_settings and not self.show_credits:
            if self.close_btn_rect.collidepoint(lx, ly):
                self.hovered_close_btn = True
            for cat_key, cat_data in self.panel_slots.items():
                for opt_idx, slot_rect in enumerate(cat_data["slots"]):
                    if slot_rect.collidepoint(lx, ly):
                        self.hovered_custom_slot = (cat_key, opt_idx)
                        break

    def on_menu_mouse_click(self, lx: int, ly: int):
        if self.show_settings:
            if pygame.Rect(MENU_WIDTH // 2 - 60, 390, 120, 32).collidepoint(lx, ly):
                self.show_settings = False
            elif pygame.Rect(MENU_WIDTH // 2 - 20, 192, 175, 28).collidepoint(lx, ly):
                self.toggle_fullscreen()
            elif pygame.Rect(MENU_WIDTH // 2 - 20, 292, 175, 28).collidepoint(lx, ly):
                if self.preloader.network:
                    threading.Thread(target=self.preloader.network.try_connect, daemon=True).start()
            return

        if self.show_credits:
            if pygame.Rect(MENU_WIDTH // 2 - 60, 370, 120, 32).collidepoint(lx, ly):
                self.show_credits = False
            return

        if self.show_customize:
            if self.close_btn_rect.collidepoint(lx, ly):
                self.show_customize = False
                return
            for cat_key, cat_data in self.panel_slots.items():
                for opt_idx, slot_rect in enumerate(cat_data["slots"]):
                    if slot_rect.collidepoint(lx, ly):
                        self.customization[cat_key] = opt_idx
                        return

        mx, my = self.menu_pos
        for idx, btn in enumerate(self.menu_buttons):
            rect = btn["local_rect"]
            screen_rect = pygame.Rect(mx + rect.x, my + rect.y, rect.width, rect.height)
            if screen_rect.collidepoint(lx, ly):
                self.trigger_menu_action(btn["name"])
                return

    def trigger_menu_action(self, action_name: str):
        if action_name == "Start Game":
            if self.preloader.status == PreloadStatus.READY and self.preloader.game_session:
                self.state = "GAME"
                self.show_customize = False
                self.show_settings = False
                self.show_credits = False
                self.update_letterbox()
            else:
                print(f"[MENU] Start Game clicked, but world is still preparing ({self.preloader.progress:.0%})...")
        elif action_name == "Customize":
            self.show_customize = not self.show_customize
        elif action_name == "Settings":
            self.show_settings = True
        elif action_name == "Credits":
            self.show_credits = True
        elif action_name == "Quit":
            self.is_running = False

    # -----------------------------------------------------------------------
    # Menu Rendering
    # -----------------------------------------------------------------------
    def render_wooden_menu(self):
        mx, my = self.menu_pos
        self.menu_surface.blit(self.menu_scaled, (mx, my))

        if self.hovered_menu_button >= 0 and self.state == "MENU" and not self.show_settings and not self.show_credits:
            btn = self.menu_buttons[self.hovered_menu_button]
            rect = btn["local_rect"]
            sx = mx + rect.x
            sy = my + rect.y

            self.menu_surface.blit(btn["hover_surf"], (sx, sy))

            bx1, by1 = sx + 8, sy + 4
            bx2, by2 = sx + rect.width - 8, sy + rect.height - 4
            gold = (255, 215, 60)
            bracket_len = 10
            pygame.draw.line(self.menu_surface, gold, (bx1, by1), (bx1 + bracket_len, by1), 2)
            pygame.draw.line(self.menu_surface, gold, (bx1, by1), (bx1, by1 + bracket_len), 2)
            pygame.draw.line(self.menu_surface, gold, (bx2 - bracket_len, by1), (bx2, by1), 2)
            pygame.draw.line(self.menu_surface, gold, (bx2, by1), (bx2, by1 + bracket_len), 2)
            pygame.draw.line(self.menu_surface, gold, (bx1, by2), (bx1 + bracket_len, by2), 2)
            pygame.draw.line(self.menu_surface, gold, (bx1, by2), (bx1, by2 - bracket_len), 2)
            pygame.draw.line(self.menu_surface, gold, (bx2 - bracket_len, by2), (bx2, by2), 2)
            pygame.draw.line(self.menu_surface, gold, (bx2, by2), (bx2, by2 - bracket_len), 2)

            lx = sx - 16
            ly = sy + rect.height // 2 - 4
            leaf_pts = [(lx, ly + 3), (lx + 4, ly), (lx + 8, ly + 3), (lx + 4, ly + 6)]
            pygame.draw.polygon(self.menu_surface, (255, 175, 40), leaf_pts)
            pygame.draw.polygon(self.menu_surface, (255, 225, 80), [(lx + 2, ly + 3), (lx + 4, ly + 1), (lx + 6, ly + 3), (lx + 4, ly + 5)])

            if btn["name"] == "Start Game" and self.preloader.game_session and self.preloader.status == PreloadStatus.READY:
                hint_rect = pygame.Rect(sx + 20, sy + rect.height - 14, rect.width - 40, 12)
                self.font_renderer.draw_text_centered(self.menu_surface, "[ Click to Enter / Resume ]", hint_rect.center,
                                                     font_type="small", color=(255, 235, 140))

    def render_preload_status_badge(self):
        badge_x = 24
        badge_y = MENU_HEIGHT - 38

        if self.preloader.status == PreloadStatus.READY:
            badge_rect = pygame.Rect(badge_x, badge_y, 160, 24)
            pygame.draw.rect(self.menu_surface, (26, 36, 22, 230), badge_rect, border_radius=6)
            pygame.draw.rect(self.menu_surface, (100, 180, 90), badge_rect, width=1, border_radius=6)
            self.font_renderer.draw_text_centered(self.menu_surface, "✔ DÜNYA HAZIR", badge_rect.center,
                                                  font_type="small", color=(180, 240, 160))
        elif self.preloader.status == PreloadStatus.LOADING:
            badge_rect = pygame.Rect(badge_x, badge_y, 220, 26)
            pygame.draw.rect(self.menu_surface, (40, 24, 16, 230), badge_rect, border_radius=6)
            pygame.draw.rect(self.menu_surface, (190, 110, 40), badge_rect, width=1, border_radius=6)

            pct = int(self.preloader.progress * 100)
            label = f"DÜNYA HAZIRLANIYOR... {pct}%"
            self.font_renderer.draw_text(self.menu_surface, label, (badge_x + 8, badge_y + 4),
                                         font_type="small", color=COLOR_TEXT_GOLD)

            bar_w = 204
            bar_h = 4
            bar_x = badge_x + 8
            bar_y = badge_y + 18
            pygame.draw.rect(self.menu_surface, (20, 12, 8), (bar_x, bar_y, bar_w, bar_h), border_radius=2)
            fill_w = int(bar_w * self.preloader.progress)
            if fill_w > 0:
                pygame.draw.rect(self.menu_surface, (225, 130, 45), (bar_x, bar_y, fill_w, bar_h), border_radius=2)
        elif self.preloader.status == PreloadStatus.ERROR:
            badge_rect = pygame.Rect(badge_x, badge_y, 200, 24)
            pygame.draw.rect(self.menu_surface, (50, 16, 16, 230), badge_rect, border_radius=6)
            pygame.draw.rect(self.menu_surface, (220, 60, 60), badge_rect, width=1, border_radius=6)
            self.font_renderer.draw_text_centered(self.menu_surface, "Yükleme Hatası!", badge_rect.center,
                                                  font_type="small", color=(255, 120, 120))

    def render_customization_panel(self):
        if not self.show_customize: return

        pw, ph = self.panel_rect.width, self.panel_rect.height
        px, py = self.panel_rect.x, self.panel_rect.y

        panel_surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel_surf.fill(COLOR_PANEL_BG)

        header_rect = pygame.Rect(3, 3, pw - 6, 26)
        pygame.draw.rect(panel_surf, COLOR_PANEL_HEADER, header_rect)

        pygame.draw.rect(panel_surf, COLOR_BORDER_OUTER, (0, 0, pw, ph), 2)
        pygame.draw.rect(panel_surf, COLOR_BORDER_INNER, (2, 2, pw - 4, ph - 4), 1)
        pygame.draw.line(panel_surf, COLOR_BORDER_OUTER, (0, 30), (pw, 30), 1)
        self.menu_surface.blit(panel_surf, (px, py))

        self.font_renderer.draw_text(self.menu_surface, "CHARACTER CUSTOMIZE", (px + 10, py + 8),
                                     font_type="med", color=COLOR_TEXT_GOLD)

        cb = self.close_btn_rect
        btn_bg = (120, 45, 30) if self.hovered_close_btn else (80, 32, 22)
        pygame.draw.rect(self.menu_surface, btn_bg, cb)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, cb, 1)
        self.font_renderer.draw_text_centered(self.menu_surface, "X", cb.center,
                                              font_type="med", color=(255, 235, 215))

        pulse_val = 0.5 + 0.5 * math.sin(self.time_elapsed * 5.0)

        for cat_key, cat_data in self.panel_slots.items():
            lx, ly = cat_data["label_pos"]
            self.font_renderer.draw_text(self.menu_surface, cat_data["title"], (lx, ly),
                                         font_type="med", color=COLOR_TEXT_WARM)

            selected_idx = self.customization.get(cat_key, 0)
            for opt_idx, slot_rect in enumerate(cat_data["slots"]):
                sx, sy = slot_rect.x, slot_rect.y
                sw, sh = slot_rect.width, slot_rect.height

                pygame.draw.rect(self.menu_surface, COLOR_SLOT_BG, slot_rect)

                if opt_idx < len(self.thumbnails[cat_key]):
                    thumb = self.thumbnails[cat_key][opt_idx]
                    tx = sx + (sw - thumb.get_width()) // 2
                    ty = sy + (sh - thumb.get_height()) // 2
                    self.menu_surface.blit(thumb, (tx, ty))

                is_selected = (opt_idx == selected_idx)
                is_hovered = (self.hovered_custom_slot == (cat_key, opt_idx))

                if is_selected:
                    gold_r = 255
                    gold_g = int(200 + 35 * pulse_val)
                    gold_b = int(40 + 30 * pulse_val)
                    pygame.draw.rect(self.menu_surface, (gold_r, gold_g, gold_b),
                                     (sx - 1, sy - 1, sw + 2, sh + 2), 2)
                    self.menu_surface.set_at((sx - 1, sy - 1), (255, 255, 180))
                    self.menu_surface.set_at((sx + sw, sy - 1), (255, 255, 180))
                    self.menu_surface.set_at((sx - 1, sy + sh), (255, 255, 180))
                    self.menu_surface.set_at((sx + sw, sy + sh), (255, 255, 180))
                elif is_hovered:
                    pygame.draw.rect(self.menu_surface, COLOR_SLOT_HOVER, slot_rect, 1)
                else:
                    pygame.draw.rect(self.menu_surface, COLOR_SLOT_BORDER, slot_rect, 1)

    def render_settings_modal(self):
        if not self.show_settings: return

        dim = pygame.Surface((MENU_WIDTH, MENU_HEIGHT), pygame.SRCALPHA)
        dim.fill((10, 5, 4, 160))
        self.menu_surface.blit(dim, (0, 0))

        mw, mh = 440, 310
        mx = (MENU_WIDTH - mw) // 2
        my = (MENU_HEIGHT - mh) // 2

        surf = pygame.Surface((mw, mh), pygame.SRCALPHA)
        surf.fill((28, 16, 12, 245))
        pygame.draw.rect(surf, COLOR_BORDER_OUTER, (0, 0, mw, mh), 2)
        pygame.draw.rect(surf, COLOR_BORDER_INNER, (2, 2, mw - 4, mh - 4), 1)
        pygame.draw.rect(surf, COLOR_PANEL_HEADER, (3, 3, mw - 6, 28))
        self.menu_surface.blit(surf, (mx, my))

        self.font_renderer.draw_text_centered(self.menu_surface, "SETTINGS & NETWORK", (MENU_WIDTH // 2, my + 17),
                                              font_type="title", color=COLOR_TEXT_GOLD)

        # 1. Display Mode
        self.font_renderer.draw_text(self.menu_surface, "Display Mode:", (mx + 25, my + 46),
                                     font_type="med", color=COLOR_TEXT_WARM)
        mode_btn_rect = pygame.Rect(MENU_WIDTH // 2 - 20, my + 40, 175, 28)
        mode_str = "Fullscreen (F11)" if self.is_fullscreen else "Windowed (16:9)"
        pygame.draw.rect(self.menu_surface, (55, 30, 20), mode_btn_rect)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, mode_btn_rect, 1)
        self.font_renderer.draw_text_centered(self.menu_surface, f"[ {mode_str} ]", mode_btn_rect.center,
                                              font_type="small", color=COLOR_TEXT_GOLD)

        # 2. Target FPS
        self.font_renderer.draw_text(self.menu_surface, "Target FPS:", (mx + 25, my + 82),
                                     font_type="med", color=COLOR_TEXT_WARM)
        self.font_renderer.draw_text(self.menu_surface, "60 FPS (V-Sync)", (mx + 170, my + 82),
                                     font_type="small", color=COLOR_TEXT_MUTED)

        # 3. Multiplayer Server Status
        net_conn = self.preloader.network.connected if self.preloader.network else False
        status_str = f"Online (ID: {self.preloader.network.id})" if net_conn else "Offline (Singleplayer)"
        status_col = (100, 220, 100) if net_conn else (220, 150, 80)

        self.font_renderer.draw_text(self.menu_surface, "Multiplayer Server:", (mx + 25, my + 114),
                                     font_type="med", color=COLOR_TEXT_WARM)
        self.font_renderer.draw_text(self.menu_surface, f"127.0.0.1:5555 ({status_str})", (mx + 170, my + 114),
                                     font_type="small", color=status_col)

        recon_btn = pygame.Rect(MENU_WIDTH // 2 - 20, my + 140, 175, 28)
        pygame.draw.rect(self.menu_surface, (55, 30, 20), recon_btn)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, recon_btn, 1)
        recon_label = "Baglantiyi Yenile" if not net_conn else "Bagli (Yeniden Dene)"
        self.font_renderer.draw_text_centered(self.menu_surface, recon_label, recon_btn.center,
                                              font_type="small", color=COLOR_TEXT_GOLD)

        # 4. Controls Note
        self.font_renderer.draw_text(self.menu_surface, "Controls: WASD / Arrows = Move | E = Gather / Fish",
                                     (mx + 25, my + 185), font_type="small", color=COLOR_TEXT_MUTED)
        self.font_renderer.draw_text(self.menu_surface, "F = Sail Boat | M = Map | ESC = Pause Menu",
                                     (mx + 25, my + 205), font_type="small", color=COLOR_TEXT_MUTED)

        # Back Button
        back_btn = pygame.Rect(MENU_WIDTH // 2 - 60, my + 250, 120, 32)
        pygame.draw.rect(self.menu_surface, (70, 35, 22), back_btn)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, back_btn, 1)
        self.font_renderer.draw_text_centered(self.menu_surface, "BACK", back_btn.center,
                                              font_type="med", color=COLOR_TEXT_GOLD)

    def render_credits_modal(self):
        if not self.show_credits: return

        dim = pygame.Surface((MENU_WIDTH, MENU_HEIGHT), pygame.SRCALPHA)
        dim.fill((10, 5, 4, 160))
        self.menu_surface.blit(dim, (0, 0))

        mw, mh = 440, 280
        mx = (MENU_WIDTH - mw) // 2
        my = (MENU_HEIGHT - mh) // 2

        surf = pygame.Surface((mw, mh), pygame.SRCALPHA)
        surf.fill((28, 16, 12, 245))
        pygame.draw.rect(surf, COLOR_BORDER_OUTER, (0, 0, mw, mh), 2)
        pygame.draw.rect(surf, COLOR_BORDER_INNER, (2, 2, mw - 4, mh - 4), 1)
        pygame.draw.rect(surf, COLOR_PANEL_HEADER, (3, 3, mw - 6, 28))
        self.menu_surface.blit(surf, (mx, my))

        self.font_renderer.draw_text_centered(self.menu_surface, "CREDITS", (MENU_WIDTH // 2, my + 17),
                                              font_type="title", color=COLOR_TEXT_GOLD)

        lines = [
            ("Autumn Island Exploration", "title", COLOR_TEXT_GOLD),
            ("Resource Gathering & Coastal Island Adventure", "small", COLOR_TEXT_WARM),
            ("", "small", COLOR_TEXT_MUTED),
            ("Pixel Art & Artwork: Fall Tile Set Collection", "small", COLOR_TEXT_WARM),
            ("Game Engine: Python 3 & Pygame 2", "small", COLOR_TEXT_WARM),
            ("Multiplayer Architecture: Standalone TCP Server & Client", "small", COLOR_TEXT_MUTED),
            ("Background Preloader: Real-time Noise & World Generation", "small", COLOR_TEXT_MUTED),
        ]

        curr_y = my + 46
        for text, ftype, col in lines:
            if text:
                self.font_renderer.draw_text_centered(self.menu_surface, text, (MENU_WIDTH // 2, curr_y),
                                                      font_type=ftype, color=col)
            curr_y += 20

        back_btn = pygame.Rect(MENU_WIDTH // 2 - 60, my + 225, 120, 32)
        pygame.draw.rect(self.menu_surface, (70, 35, 22), back_btn)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, back_btn, 1)
        self.font_renderer.draw_text_centered(self.menu_surface, "BACK", back_btn.center,
                                              font_type="med", color=COLOR_TEXT_GOLD)

    # -----------------------------------------------------------------------
    # Main Render & Loop
    # -----------------------------------------------------------------------
    def render(self):
        lx, ly = self.window_to_logical(pygame.mouse.get_pos())

        if self.state == "MENU":
            # 1. Background
            self.menu_surface.blit(self.bg_surface, (0, 0))
            # 2. Ambient lighting & effects
            self.ambient_lighting.draw(self.menu_surface, self.time_elapsed)
            # 3. Central Character standing on stone platform
            idle_offset_y = 1 if math.sin(self.time_elapsed * 2.5) > 0.8 else 0
            cx, cy = self.char_pos
            self.menu_surface.blit(self.char_scaled, (cx, cy + idle_offset_y))
            # 4. Drifting autumn leaves
            for p in self.particles:
                p.draw(self.menu_surface)
            # 5. Wooden Menu & UI
            self.render_wooden_menu()
            self.render_preload_status_badge()
            self.render_customization_panel()
            self.render_settings_modal()
            self.render_credits_modal()

            scaled_surf = pygame.transform.scale(self.menu_surface, (self.target_w, self.target_h))

        elif self.state == "GAME" and self.preloader.game_session:
            # Render full gameplay with Fall Tile Set sprites onto game_surface
            self.preloader.game_session.render(self.game_surface, (lx, ly))

            scaled_surf = pygame.transform.scale(self.game_surface, (self.target_w, self.target_h))

        self.window.fill(COLOR_BG_DARK)
        self.window.blit(scaled_surf, (self.offset_x, self.offset_y))
        pygame.display.flip()

    def run(self):
        print("Starting Autumn Island Game application loop...")
        while self.is_running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            self.time_elapsed += dt

            # 1. Poll background preloader
            self.preloader.poll(self.customization)

            # 2. Update ambient effects
            for p in self.particles:
                p.update(dt)
            self.ambient_lighting.update(dt)

            # 3. Update gameplay state if in GAME
            if self.state == "GAME" and self.preloader.game_session:
                lx, ly = self.window_to_logical(pygame.mouse.get_pos())
                self.preloader.game_session.update(dt, (lx, ly))

            # 4. Handle events & render
            self.handle_events()
            self.render()

        # Clean shutdown
        if self.preloader.network:
            self.preloader.network.close()
        pygame.quit()
        sys.exit(0)


# ---------------------------------------------------------------------------
# Program Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = AutumnGameApp()
    app.run()
