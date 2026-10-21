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
COLS, ROWS = 640, 384
ISLAND_COUNT = 42
MIN_RADIUS, MAX_RADIUS = 26, 46
LOCAL_TILE_SIZE = 48

PLAYER_SPEED = 4.5
PLAYER_HALF_SIZE = 0.17
DEBUG_STARTING_EQUIPMENT = True

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
from game_ui import PixelHUD, WorldMapUI
from autumn_leaves import AutumnLeaves
from character_animation import CharacterAnimator, load_character_sheet
from gameplay_systems import (CombatSystem, DialogueBox, EnemyAISystem,
                              NavalEncounterSystem, QuestSystem)


# ---------------------------------------------------------------------------
# World Generation & Data Structures (from main2.py)
# ---------------------------------------------------------------------------
# Shared by the server; generation and resource IDs have a single implementation.
from worldgen import (
    WORLD_VERSION, Island, Village, ResourceNode, World, Port, terrain, make_world,
    generate_villages, compute_tile_pixels, generate_ports, can_stand, find_spawn, SpawnPool,
)

_OFFLINE_SPAWN_POOLS = {}


def acquire_offline_spawn(world):
    pool = _OFFLINE_SPAWN_POOLS.setdefault(world.seed, SpawnPool(world))
    return pool.acquire()


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


def draw_player(screen, position, moving, facing, color_override=None, is_sailing=False, boat_angle=0.0,
                atlas=None, character_sheet=None, animation=None, boat_hull=None, sail_angle=0.0,
                sail_raised=True):
    scale = 1.6

    if is_sailing and boat_hull is not None:
        angle_deg = math.degrees(-boat_angle) - 90
        rotated_hull = pygame.transform.rotate(boat_hull, angle_deg)
        screen.blit(rotated_hull, rotated_hull.get_rect(center=(round(position[0]), round(position[1]))))
        if character_sheet is not None and animation is not None:
            sailor = pygame.transform.scale(character_sheet.frames[animation.facing][animation.frame], (18, 25))
            screen.blit(sailor, sailor.get_rect(midbottom=(round(position[0]), round(position[1] + 14))))
        # Separate world-space sail layer: the mouse rotates this around the mast.
        sail_canvas = pygame.Surface((90, 90), pygame.SRCALPHA)
        pivot = (45, 45)
        pygame.draw.line(sail_canvas, (78, 48, 27), pivot, (80, 45), 4)
        if sail_raised:
            pygame.draw.polygon(sail_canvas, (232, 220, 181), [(48, 43), (78, 27), (78, 59)])
            pygame.draw.polygon(sail_canvas, (157, 118, 73), [(48, 43), (78, 27), (78, 59)], 2)
            pygame.draw.line(sail_canvas, (185, 150, 100), (51, 43), (75, 32), 1)
        else:
            pygame.draw.line(sail_canvas, (224, 208, 168), (52, 43), (77, 43), 8)
            for wrap_x in range(55, 78, 6):
                pygame.draw.line(sail_canvas, (143, 105, 67), (wrap_x, 38), (wrap_x, 48), 2)
        rotated_sail = pygame.transform.rotate(sail_canvas, math.degrees(-sail_angle))
        screen.blit(rotated_sail, rotated_sail.get_rect(center=(round(position[0]), round(position[1]))))
        pygame.draw.circle(screen, (194, 143, 62), (round(position[0]), round(position[1])), 4)
        return
    elif is_sailing and atlas and hasattr(atlas, 'boat'):
        boat = atlas.boat
        # Build the sailor and boat as one sprite before rotating.  The character
        # is drawn first, so the opaque gunwales cover their lower body and make
        # them look seated inside the boat instead of replacing/disappearing in it.
        padding = 22
        vessel = pygame.Surface((boat.get_width() + padding * 2,
                                 boat.get_height() + padding * 2), pygame.SRCALPHA)
        center_x = vessel.get_width() // 2
        center_y = vessel.get_height() // 2
        vessel.blit(boat, boat.get_rect(center=(center_x, center_y)))
        if character_sheet is not None and animation is not None:
            sailor = character_sheet.frames[animation.facing][animation.frame]
            sailor = pygame.transform.scale(sailor, (24, 34))
            vessel.blit(sailor, sailor.get_rect(midbottom=(center_x, center_y + 13)))
        else:
            pygame.draw.circle(vessel, (224, 178, 133), (center_x, center_y - 7), 5)
            pygame.draw.rect(vessel, color_override or (123, 85, 57),
                             (center_x - 6, center_y - 2, 12, 15), border_radius=3)
        # Repaint the near half of the hull over the legs as the foreground rim.
        front_y = boat.get_height() // 2
        front = boat.subsurface((0, front_y, boat.get_width(), boat.get_height() - front_y))
        vessel.blit(front, (center_x - boat.get_width() // 2, center_y - boat.get_height() // 2 + front_y))
        angle_deg = math.degrees(-boat_angle) - 90
        rot_boat = pygame.transform.rotate(vessel, angle_deg)
        rect = rot_boat.get_rect(center=(round(position[0]), round(position[1])))
        screen.blit(rot_boat, rect.topleft)
        return
    elif is_sailing:
        boat = pygame.Surface((20 * scale, 30 * scale), pygame.SRCALPHA)
        pygame.draw.ellipse(boat, (120, 80, 50), (0, 0, 20 * scale, 30 * scale))
        pygame.draw.circle(boat, (224, 178, 133), (round(10 * scale), round(10 * scale)), round(4 * scale))
        pygame.draw.rect(boat, color_override or (123, 85, 57),
                         (round(6 * scale), round(12 * scale), round(8 * scale), round(10 * scale)))
        pygame.draw.arc(boat, (200, 190, 180), (2 * scale, 7 * scale, 16 * scale, 18 * scale), 0, math.pi, 3)
        angle_deg = math.degrees(-boat_angle) - 90
        boat = pygame.transform.rotate(boat, angle_deg)
        rect = boat.get_rect(center=(round(position[0]), round(position[1])))
        screen.blit(boat, rect.topleft)
        return

    if character_sheet is not None:
        character_sheet.draw(screen, position, animation)
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


def draw_sea_ship(screen, ship, camera_x, camera_y, boat_hull, font):
    x = round(ship.x * LOCAL_TILE_SIZE) - camera_x
    y = round(ship.y * LOCAL_TILE_SIZE) - camera_y
    heading_x, heading_y = math.cos(ship.angle), math.sin(ship.angle)
    wake_x, wake_y = -heading_x, -heading_y
    wake_color = (170, 225, 235) if ship.kind == "merchant" else (210, 215, 218)
    for spread in (-1, 1):
        end = (round(x + wake_x * 35 - heading_y * spread * 11),
               round(y + wake_y * 35 + heading_x * spread * 11))
        pygame.draw.line(screen, wake_color, (x, y), end, 2)

    if boat_hull is not None:
        hull = boat_hull.copy()
        if ship.hit_flash > 0:
            hull.fill((90, 90, 90, 0), special_flags=pygame.BLEND_RGBA_ADD)
        rotated = pygame.transform.rotate(hull, math.degrees(-ship.angle) - 90)
        screen.blit(rotated, rotated.get_rect(center=(x, y)))
    else:
        color = (133, 85, 43) if ship.kind == "merchant" else (72, 48, 42)
        pygame.draw.ellipse(screen, color, (x - 18, y - 29, 36, 58))

    # A bright pennant communicates role without recolouring the wooden hull.
    flag_color = (55, 205, 220) if ship.kind == "merchant" else (205, 42, 48)
    mast_top = (round(x + heading_x * 7), round(y + heading_y * 7 - 22))
    pygame.draw.line(screen, (64, 39, 24), (x, y), mast_top, 3)
    pygame.draw.polygon(screen, flag_color,
                        [mast_top, (mast_top[0] + 14, mast_top[1] + 5),
                         (mast_top[0], mast_top[1] + 10)])

    label = "TÜCCAR [E]" if ship.kind == "merchant" else "KORSAN"
    label_color = (125, 245, 235) if ship.kind == "merchant" else (255, 115, 95)
    tag = font.render(label, True, label_color)
    screen.blit(tag, tag.get_rect(midbottom=(x, y - 47)))
    if ship.kind == "pirate" and ship.aggro_timer > 0:
        warning = font.render("!", True, (255, 235, 95))
        pygame.draw.circle(screen, (145, 35, 30), (x + 30, y - 57), 12)
        screen.blit(warning, warning.get_rect(center=(x + 30, y - 58)))
    pygame.draw.rect(screen, (35, 20, 20), (x - 22, y - 44, 44, 5), border_radius=2)
    pygame.draw.rect(screen, (75, 220, 145) if ship.kind == "merchant" else (220, 65, 58),
                     (x - 22, y - 44, round(44 * max(0, ship.health) / ship.max_health), 5), border_radius=2)


def draw_villager(screen, npc, camera_x, camera_y):
    x, y = round(npc.x * LOCAL_TILE_SIZE) - camera_x, round(npc.y * LOCAL_TILE_SIZE) - camera_y
    pygame.draw.ellipse(screen, (32, 24, 20), (x - 13, y - 5, 26, 9))
    pygame.draw.circle(screen, (224, 177, 132), (x, y - 29), 8)
    pygame.draw.rect(screen, (74, 112, 76), (x - 10, y - 22, 20, 22), border_radius=5)
    pygame.draw.polygon(screen, (114, 68, 42), [(x - 9, y - 35), (x + 9, y - 35), (x + 6, y - 27), (x - 7, y - 27)])
    pygame.draw.circle(screen, (255, 226, 90), (x + 13, y - 39), 5)


def draw_monster(screen, monster, camera_x, camera_y):
    x, y = round(monster.x * LOCAL_TILE_SIZE) - camera_x, round(monster.y * LOCAL_TILE_SIZE) - camera_y
    colors = {"wolf": (100, 103, 112), "pirate": (125, 48, 42), "bandit": (83, 65, 55),
              "thief": (62, 68, 82), "boar": (116, 76, 54)}
    color = (255, 245, 220) if monster.hit_flash > 0 else colors.get(monster.kind, (108, 164, 73))
    pygame.draw.ellipse(screen, (25, 22, 18), (x - 17, y - 5, 34, 10))
    if monster.kind in ("wolf", "boar"):
        pygame.draw.ellipse(screen, color, (x - 19, y - 23, 31, 21))
        pygame.draw.polygon(screen, color, [(x + 5, y - 21), (x + 19, y - 18), (x + 16, y - 7), (x + 5, y - 9)])
        pygame.draw.polygon(screen, color, [(x + 7, y - 21), (x + 11, y - 31), (x + 15, y - 20)])
        pygame.draw.circle(screen, (245, 190, 55), (x + 14, y - 15), 2)
    else:
        pygame.draw.circle(screen, (211, 165, 124), (x, y - 30), 7)
        pygame.draw.rect(screen, color, (x - 11, y - 23, 22, 22), border_radius=5)
        if monster.kind == "pirate":
            pygame.draw.polygon(screen, (35, 31, 38), [(x - 10, y - 35), (x + 12, y - 35), (x + 7, y - 28), (x - 7, y - 28)])
        elif monster.kind == "thief":
            pygame.draw.rect(screen, (35, 34, 43), (x - 8, y - 34, 16, 5))
    pygame.draw.rect(screen, (45, 25, 24), (x - 16, y - 40, 32, 4))
    pygame.draw.rect(screen, (210, 70, 55), (x - 16, y - 40,
                                           round(32 * monster.health / monster.max_health), 4))
    if monster.state == "windup":
        charge = min(1.0, monster.attack_timer / max(.01, monster.attack_windup))
        radius = round(22 + charge * 8)
        pygame.draw.circle(screen, (255, 65 + round(charge * 90), 45), (x, y - 14), radius, 3)
        pygame.draw.arc(screen, (255, 225, 105), (x - 19, y - 48, 38, 38),
                        -math.pi / 2, -math.pi / 2 + math.tau * charge, 4)
    elif monster.state == "flank":
        pygame.draw.arc(screen, (245, 165, 65), (x - 22, y - 12, 44, 18), 0, math.pi, 2)


def draw_sword_attack(screen, position, facing, combat):
    if not combat.attacking:
        return
    x, y = position
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(facing, (0, 1))
    attack = combat.attack_profile()
    progress = min(1.0, combat.timer / attack["duration"])
    frame_index = min(23, int(progress * 24))
    eased = progress * progress * (3.0 - 2.0 * progress)
    base_angle = math.atan2(dy, dx)
    combo = combat.combo_step
    if combat.attack_kind == "dash":
        start_offset, sweep_size = -1.75, 3.5
    elif combat.attack_kind == "crouch":
        start_offset, sweep_size = -2.5, math.tau * 1.18
    elif combo == 2:
        start_offset, sweep_size = 1.25, -2.55
    elif combo >= 3:
        start_offset, sweep_size = -1.75, 3.45
    else:
        start_offset, sweep_size = -1.25, 2.45
    angle = base_angle + start_offset + eased * sweep_size
    length = 58 if combat.attack_kind == "dash" else (40 if combo >= 3 else (36 if combat.attack_kind == "normal" else 34))
    start = (round(x + dx * 7), round(y - 18 + dy * 7))
    active = attack["active"][0] <= combat.timer <= attack["active"][1]

    # Persistent curved afterimage: every combo step has a different sweep direction.
    if active:
        trail_size = 190 if combat.attack_kind == "dash" else 140
        trail = pygame.Surface((trail_size, trail_size), pygame.SRCALPHA)
        center = (trail_size // 2, trail_size // 2)
        direction = 1 if sweep_size > 0 else -1
        for band, radius in enumerate((length + 8, length + 2, length - 5)):
            points = []
            for i in range(15):
                trail_angle = angle - direction * i * .075
                points.append((round(center[0] + math.cos(trail_angle) * radius),
                               round(center[1] + math.sin(trail_angle) * radius)))
            color = ((80, 205, 255, 55), (120, 225, 255, 100), (245, 245, 220, 165))[band]
            pygame.draw.lines(trail, color, False, points, 7 - band * 2)
        if combo >= 3:
            pygame.draw.circle(trail, (255, 198, 70, 90), center, 48, 4)
        screen.blit(trail, (round(start[0] - center[0]), round(start[1] - center[1])),
                    special_flags=pygame.BLEND_RGBA_ADD)

        # Speed lines and a brief impact ring sell the hack-and-slash hit stop.
        for offset in (-.22, .22):
            ray_angle = angle + offset
            ray_start = (round(start[0] + math.cos(ray_angle) * 18),
                         round(start[1] + math.sin(ray_angle) * 18))
            ray_end = (round(start[0] + math.cos(ray_angle) * (length + 16)),
                       round(start[1] + math.sin(ray_angle) * (length + 16)))
            pygame.draw.line(screen, (115, 205, 245), ray_start, ray_end, 2)

        palette = ((80, 225, 255), (185, 115, 255)) if combat.attack_kind == "crouch" else (
            ((55, 215, 255), (245, 255, 255)) if combat.attack_kind == "dash" else
            (((255, 190, 65), (255, 245, 185)) if combo >= 3 else ((95, 205, 255), (235, 255, 255))))
        # Six blade ghosts produce a readable 24-frame slash instead of a single rotating line.
        for ghost in range(1, 7):
            ghost_angle = angle - direction * ghost * (.055 + frame_index * .0015)
            ghost_length = length - ghost * 2
            ghost_start = (round(start[0] + math.cos(ghost_angle) * ghost * 1.5),
                           round(start[1] + math.sin(ghost_angle) * ghost * 1.5))
            ghost_end = (round(start[0] + math.cos(ghost_angle) * ghost_length),
                         round(start[1] + math.sin(ghost_angle) * ghost_length))
            pygame.draw.line(screen, palette[ghost % 2], ghost_start, ghost_end,
                             max(1, 5 - ghost // 2))

        tip_x, tip_y = start[0] + math.cos(angle) * length, start[1] + math.sin(angle) * length
        for spark in range(8 if combat.attack_kind == "dash" else 5):
            spark_angle = angle + math.sin((frame_index + spark * 7) * 1.7) * 1.15
            spark_len = 8 + (frame_index * 3 + spark * 5) % 17
            spark_end = (round(tip_x + math.cos(spark_angle) * spark_len),
                         round(tip_y + math.sin(spark_angle) * spark_len))
            pygame.draw.line(screen, palette[spark % 2], (round(tip_x), round(tip_y)), spark_end, 2)
        if combat.impact_pulse > 0:
            radius = round(10 + 18 * (1 - combat.impact_pulse / .16))
            pygame.draw.circle(screen, (255, 230, 135),
                               (round(start[0] + math.cos(angle) * length),
                                round(start[1] + math.sin(angle) * length)), radius, 3)

    end = (round(start[0] + math.cos(angle) * length), round(start[1] + math.sin(angle) * length))
    pygame.draw.line(screen, (35, 33, 40), start, end, 9)
    pygame.draw.line(screen, (205, 225, 238), start, end, 5)
    pygame.draw.line(screen, (255, 255, 245), start, end, 2)
    guard_a = angle + math.pi / 2
    guard_1 = (round(start[0] + math.cos(guard_a) * 7), round(start[1] + math.sin(guard_a) * 7))
    guard_2 = (round(start[0] - math.cos(guard_a) * 7), round(start[1] - math.sin(guard_a) * 7))
    pygame.draw.line(screen, (236, 178, 62), guard_1, guard_2, 5)
    pygame.draw.circle(screen, (255, 215, 90), start, 4)

    if combo > 1:
        badge_text = "DALGA DASH!" if combat.attack_kind == "dash" else f"KOMBO x{combo}"
        badge = pygame.font.Font(None, 22).render(badge_text, True,
                                                  (255, 220, 105) if combo >= 3 else (175, 225, 255))
        screen.blit(badge, badge.get_rect(center=(round(x), round(y - 64))))


def draw_dash_effects(screen, effects, camera_x, camera_y):
    """Layered crescent waves and afterimages inspired by arcade slash VFX."""
    for effect in effects:
        life_ratio = max(0.0, effect["life"] / effect["max_life"])
        progress = 1.0 - life_ratio
        x = round(effect["x"] * LOCAL_TILE_SIZE) - camera_x
        y = round(effect["y"] * LOCAL_TILE_SIZE) - camera_y - 15
        angle = effect["angle"]
        layer = pygame.Surface((190, 190), pygame.SRCALPHA)
        center = (95, 95)
        alpha = round(210 * life_ratio)

        # Expanding nested crescents wrap around the character and surge forward.
        for band in range(4):
            radius = 25 + band * 12 + progress * (28 + band * 5)
            forward = 9 + band * 5 + progress * 20
            cx = center[0] + math.cos(angle) * forward
            cy = center[1] + math.sin(angle) * forward
            points = []
            for index in range(19):
                arc_angle = angle - 1.55 + index / 18 * 3.10
                points.append((round(cx + math.cos(arc_angle) * radius),
                               round(cy + math.sin(arc_angle) * radius)))
            color = ((55, 180, 255, alpha // 2), (35, 220, 255, alpha),
                     (175, 245, 255, alpha), (255, 255, 255, alpha))[band]
            pygame.draw.lines(layer, color, False, points, max(2, 8 - band))

        # Long speed streaks make the dash direction readable.
        for side in (-1, 0, 1):
            side_x, side_y = -math.sin(angle) * side * 24, math.cos(angle) * side * 24
            start_x = center[0] + side_x - math.cos(angle) * (35 + progress * 30)
            start_y = center[1] + side_y - math.sin(angle) * (35 + progress * 30)
            end_x = center[0] + side_x + math.cos(angle) * 44
            end_y = center[1] + side_y + math.sin(angle) * 44
            pygame.draw.line(layer, (105, 225, 255, alpha),
                             (round(start_x), round(start_y)), (round(end_x), round(end_y)), 3)
        screen.blit(layer, (x - 95, y - 95), special_flags=pygame.BLEND_RGBA_ADD)


def draw_execution_effect(screen, execution, camera_x, camera_y, font):
    if execution is None:
        return
    progress = min(1.0, execution["timer"] / execution["duration"])
    pulse = math.sin(progress * math.pi)
    x = round(execution["x"] * LOCAL_TILE_SIZE) - camera_x
    y = round(execution["y"] * LOCAL_TILE_SIZE) - camera_y - 16
    layer = pygame.Surface((300, 300), pygame.SRCALPHA)
    center = (150, 150)
    angle = execution["angle"]

    # Alternating cross-cuts, radial shards, and expanding shock rings create
    # three deterministic finisher variants without depending on external art.
    variant = execution["variant"]
    cut_count = (4, 6, 9)[variant]
    for index in range(cut_count):
        cut_angle = angle + (index - cut_count / 2) * (.32 if variant != 2 else .48)
        reach = 58 + index % 3 * 17 + pulse * 34
        side = -1 if index % 2 else 1
        start = (round(center[0] - math.cos(cut_angle) * reach * .48 + math.sin(cut_angle) * side * 18),
                 round(center[1] - math.sin(cut_angle) * reach * .48 - math.cos(cut_angle) * side * 18))
        end = (round(center[0] + math.cos(cut_angle) * reach),
               round(center[1] + math.sin(cut_angle) * reach))
        pygame.draw.line(layer, (65, 205, 255, round(150 * pulse)), start, end, 10)
        pygame.draw.line(layer, (235, 255, 255, round(240 * pulse)), start, end, 3)

    for ring_index in range(3):
        radius = round(25 + ring_index * 25 + progress * (65 + ring_index * 12))
        pygame.draw.circle(layer, (70, 210, 255, round(155 * (1 - progress))), center, radius, 5)
    for ray in range(16):
        ray_angle = ray * math.tau / 16 + angle
        inner = 42 + progress * 18
        outer = inner + 22 + (ray % 3) * 11
        pygame.draw.line(layer, (255, 224, 115, round(210 * pulse)),
                         (round(center[0] + math.cos(ray_angle) * inner),
                          round(center[1] + math.sin(ray_angle) * inner)),
                         (round(center[0] + math.cos(ray_angle) * outer),
                          round(center[1] + math.sin(ray_angle) * outer)), 3)
    screen.blit(layer, (x - 150, y - 150), special_flags=pygame.BLEND_RGBA_ADD)

    if .12 < progress < .78:
        label = font.render("BİTİRİCİ!", True, (255, 235, 135))
        shadow = font.render("BİTİRİCİ!", True, (40, 20, 25))
        rect = label.get_rect(center=(x, y - 92))
        screen.blit(shadow, rect.move(3, 3))
        screen.blit(label, rect)


def draw_dialogue_box(screen, dialogue, font, small_font):
    if not dialogue.active:
        return
    panel = pygame.Rect(55, GAME_HEIGHT - 190, GAME_WIDTH - 110, 145)
    pygame.draw.rect(screen, (25, 15, 11), panel, border_radius=9)
    pygame.draw.rect(screen, (212, 162, 86), panel, width=4, border_radius=9)
    speaker = font.render(dialogue.speaker, True, (255, 221, 135))
    screen.blit(speaker, (panel.x + 22, panel.y + 15))
    words, lines, current = dialogue.visible_text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if small_font.size(candidate)[0] > panel.width - 44:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    for i, line in enumerate(lines[:3]):
        screen.blit(small_font.render(line, True, (244, 235, 213)), (panel.x + 22, panel.y + 51 + i * 24))
    hint = "E / ENTER: devam" if dialogue.page_complete else "E / ENTER: yazıyı tamamla"
    hint_surf = small_font.render(hint, True, (174, 151, 114))
    screen.blit(hint_surf, (panel.right - hint_surf.get_width() - 18, panel.bottom - 25))


def draw_combat_arena(screen, arena, font, small_font, character_sheet, background=None):
    if background:
        screen.blit(background, (0, 0))
        shade = pygame.Surface((GAME_WIDTH, GAME_HEIGHT), pygame.SRCALPHA)
        shade.fill((10, 8, 14, 42))
        screen.blit(shade, (0, 0))
    else:
        screen.fill((13, 10, 15))
    arena_rect = pygame.Rect(72, 76, GAME_WIDTH - 144, GAME_HEIGHT - 142)
    pygame.draw.rect(screen, (212, 151, 76), arena_rect, width=4, border_radius=18)
    scale_x, scale_y = arena_rect.width / arena.WIDTH, arena_rect.height / arena.HEIGHT
    origin_x, origin_y = arena_rect.x, arena_rect.y
    for monster in arena.monsters:
        if monster.alive:
            px, py = monster.x * scale_x + origin_x, monster.y * scale_y + origin_y
            wolf_col = (255, 235, 220) if monster.hit_flash else (92, 96, 105)
            pygame.draw.ellipse(screen, (20, 16, 18), (px - 23, py - 6, 46, 11))
            pygame.draw.ellipse(screen, wolf_col, (px - 21, py - 25, 35, 22))
            pygame.draw.polygon(screen, wolf_col, [(px + 5, py - 24), (px + 23, py - 20),
                                                    (px + 20, py - 8), (px + 7, py - 9)])
            pygame.draw.polygon(screen, (70, 72, 80), [(px + 9, py - 23), (px + 12, py - 34), (px + 17, py - 22)])
            pygame.draw.polygon(screen, (70, 72, 80), [(px + 17, py - 21), (px + 22, py - 31), (px + 23, py - 18)])
            pygame.draw.circle(screen, (245, 190, 55), (round(px + 17), round(py - 17)), 2)
            for leg_x in (-13, 2, 13):
                pygame.draw.line(screen, (61, 60, 66), (px + leg_x, py - 8), (px + leg_x - 2, py + 2), 4)
            # Individual health and attack-windup bars.
            pygame.draw.rect(screen, (38, 20, 22), (px - 20, py - 42, 40, 5), border_radius=2)
            pygame.draw.rect(screen, (205, 65, 62), (px - 20, py - 42,
                                                    round(40 * monster.health / monster.max_health), 5), border_radius=2)
            if monster.attack_timer > 0:
                pygame.draw.arc(screen, (255, 180, 70), (px - 25, py - 47, 50, 50),
                                -math.pi / 2, -math.pi / 2 + math.tau * min(1, monster.attack_timer / .45), 3)
    player_pos = (arena.player.x * scale_x + origin_x, arena.player.y * scale_y + origin_y)
    animator = CharacterAnimator()
    animator.facing = arena.facing
    draw_player(screen, player_pos, False, arena.facing, character_sheet=character_sheet, animation=animator)
    draw_sword_attack(screen, player_pos, arena.facing, arena.combat)
    title = font.render("ADA TEHLİKESİ — SAVAŞ ARENASI", True, (255, 220, 140))
    screen.blit(title, (arena_rect.x + 18, arena_rect.y - 40))
    pygame.draw.rect(screen, (55, 25, 28), (arena_rect.right - 220, arena_rect.y - 35, 200, 18), border_radius=5)
    pygame.draw.rect(screen, (205, 65, 65), (arena_rect.right - 220, arena_rect.y - 35,
                                               round(200 * arena.health / arena.max_health), 18), border_radius=5)
    info = small_font.render("WASD: Hareket  |  J/BOŞLUK: Normal  |  K: Eğilerek Saldırı", True, (235, 222, 198))
    screen.blit(info, info.get_rect(center=(GAME_WIDTH // 2, GAME_HEIGHT - 35)))


def get_local_camera(player, fishing=None):
    target_x = player.x * LOCAL_TILE_SIZE
    target_y = player.y * LOCAL_TILE_SIZE

    if fishing and fishing.active and fishing.port:
        target_x += fishing.port.dx * LOCAL_TILE_SIZE * 4
        target_y += fishing.port.dy * LOCAL_TILE_SIZE * 4

    camera_x = max(0, min(target_x - GAME_WIDTH / 2, COLS * LOCAL_TILE_SIZE - GAME_WIDTH))
    camera_y = max(0, min(target_y - GAME_HEIGHT / 2, ROWS * LOCAL_TILE_SIZE - GAME_HEIGHT))
    return camera_x, camera_y


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
# Island Conquest & Economy Mechanics
# ---------------------------------------------------------------------------
NEUTRAL_ISLAND_COST = {"Odun": 12, "Tas": 8, "Tahil": 6, "Balik": 2}
ENEMY_ISLAND_COST = {"Odun": 20, "Tas": 14, "Tahil": 10, "Balik": 4}
WINNING_ISLAND_COUNT = 6
ISLAND_INFLATION_PER_MINUTE = 0.05


def get_island_cost(is_enemy=False, inflation=1.0):
    base = ENEMY_ISLAND_COST if is_enemy else NEUTRAL_ISLAND_COST
    mult = max(1.0, float(inflation))
    return {k: max(1, int(round(v * mult))) for k, v in base.items()}


RESOURCE_ICONS = {
    "Odun": "Odun",
    "Tas": "Tas",
    "Tahil": "Tahil",
    "Balik": "Balik",
}

RESOURCE_COLORS = {
    "Odun": (235, 155, 75),
    "Tas": (205, 215, 225),
    "Tahil": (250, 215, 70),
    "Balik": (110, 215, 255),
}


class FloatingText:
    def __init__(self, text, pos, color=(255, 235, 120), duration=2.0):
        self.text = text
        self.x, self.y = float(pos[0]), float(pos[1])
        self.color = color
        self.timer = duration
        self.duration = duration

    def update(self, dt):
        self.timer -= dt
        self.y -= 28.0 * dt
        return self.timer > 0

    def draw(self, screen, font):
        if self.timer <= 0:
            return
        alpha = max(0, min(255, int(255 * (self.timer / self.duration))))
        surf = font.render(self.text, True, self.color)
        shadow = font.render(self.text, True, (15, 10, 8))
        surf.set_alpha(alpha)
        shadow.set_alpha(alpha)
        screen.blit(shadow, (round(self.x) + 1, round(self.y) + 1))
        screen.blit(surf, (round(self.x), round(self.y)))


class ToastNotification:
    def __init__(self, message, duration=3.5, color=(255, 235, 160)):
        self.message = message
        self.timer = duration
        self.duration = duration
        self.color = color

    def update(self, dt):
        self.timer -= dt
        return self.timer > 0

    def draw(self, screen, font, y_offset=0):
        if self.timer <= 0:
            return
        if self.timer > self.duration - 0.3:
            alpha = int(255 * (self.duration - self.timer) / 0.3)
        elif self.timer < 0.5:
            alpha = int(255 * (self.timer / 0.5))
        else:
            alpha = 255
        alpha = max(0, min(255, alpha))

        surf = font.render(self.message, True, self.color)
        tw, th = surf.get_size()
        pw, ph = tw + 32, th + 12
        px = (GAME_WIDTH - pw) // 2
        py = 56 + y_offset

        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(bg, (25, 17, 13, int(225 * (alpha / 255))), (0, 0, pw, ph), border_radius=8)
        pygame.draw.rect(bg, (210, 155, 75, int(255 * (alpha / 255))), (0, 0, pw, ph), width=1, border_radius=8)
        screen.blit(bg, (px, py))
        surf.set_alpha(alpha)
        screen.blit(surf, (px + 16, py + 6))


# ---------------------------------------------------------------------------
# Interactive Minigames (from main2.py)
# ---------------------------------------------------------------------------
class GrainHarvesting:
    """
    Wheat path-following minigame.

    A random wavy cut-line is shown over a wheat field illustration.
    The player must hold LMB and drag the cursor along that line.
    Accuracy is measured each frame; the final score (0-3 grain) depends
    on how closely the path was followed.

    Scoring thresholds (mean deviation in pixels):
        < 18 px  → 3 grain  (perfect)
        < 35 px  → 2 grain  (good)
        < 55 px  → 1 grain  (poor)
        >= 55 px → 0 grain  (missed)
    """

    _TOLERANCE_PERFECT = 18
    _TOLERANCE_GOOD    = 35
    _TOLERANCE_POOR    = 55

    def __init__(self, seed):
        self.rng = random.Random(seed + 5555)
        self.active   = False
        self.node     = None
        self.message  = ""
        self.on_harvest = None

        # Path state
        self._path_pts   = []   # list of (x,y) world points along the curve
        self._path_total = 0    # length of _path_pts
        self._cursor_idx = 0    # how far along the path the player has reached
        self._deviations = []   # per-sample deviation distance
        self._dragging   = False
        self._done       = False
        self._result_timer = 0.0

        # Panel geometry (set in open)
        self._panel = pygame.Rect(0, 0, 560, 360)
        self._start_x = 0
        self._end_x   = 0
        self._path_y_center = 0

        # Wheat stalk appearance (pre-built in open)
        self._stalks = []   # list of (x, base_y, height, sway_phase)

    # ── Geometry helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _bezier(p0, p1, p2, p3, t):
        """Cubic Bezier point at parameter t."""
        u = 1 - t
        return (
            u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0],
            u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1],
        )

    def _build_path(self):
        """Generate a random wavy Bezier cut-path across the wheat panel."""
        px = self._panel.x
        py = self._panel.y
        pw = self._panel.width
        ph = self._panel.height

        mid_y = py + ph // 2
        amp   = self.rng.randint(30, 65)

        # Two control points create a gentle S-curve
        p0 = (px + 40,      mid_y + self.rng.randint(-10, 10))
        p1 = (px + pw//3,   mid_y - amp)
        p2 = (px + 2*pw//3, mid_y + amp)
        p3 = (px + pw - 40, mid_y + self.rng.randint(-10, 10))

        self._start_x = p0[0]
        self._end_x   = p3[0]

        pts = []
        steps = 200
        for i in range(steps + 1):
            t  = i / steps
            pt = self._bezier(p0, p1, p2, p3, t)
            pts.append((int(pt[0]), int(pt[1])))
        self._path_pts   = pts
        self._path_total = len(pts)

    def _build_stalks(self):
        """Pre-compute random wheat stalk positions inside the panel."""
        self._stalks = []
        px, py = self._panel.x, self._panel.y
        pw, ph = self._panel.width, self._panel.height
        for _ in range(55):
            sx = self.rng.randint(px + 30, px + pw - 30)
            sy = py + ph - self.rng.randint(10, 35)
            ht = self.rng.randint(50, 90)
            ph2 = self.rng.uniform(0, 2 * math.pi)
            self._stalks.append((sx, sy, ht, ph2))

    def _nearest_path_distance(self, pos):
        """Return (distance, closest_index) from pos to the path polyline."""
        best_d   = float('inf')
        best_idx = 0
        for i, pt in enumerate(self._path_pts):
            d = math.hypot(pos[0] - pt[0], pos[1] - pt[1])
            if d < best_d:
                best_d   = d
                best_idx = i
        return best_d, best_idx

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def open(self, node):
        self.active   = True
        self.node     = node
        self._dragging   = False
        self._done       = False
        self._result_timer = 0.0
        self._deviations = []
        self._cursor_idx = 0

        self._panel.center = (GAME_WIDTH // 2, GAME_HEIGHT // 2)
        self._build_path()
        self._build_stalks()
        self.message = "Tirpanı çizginin üzerinde tutarak sürükle!"

    def close(self):
        self.active   = False
        self._dragging = False

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_event(self, event, logical_mouse_pos=None):
        if not self.active:
            return
        pos = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()

        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
            return

        if self._done:
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Must start near the beginning of the path
            sx, sy = self._path_pts[0]
            if math.hypot(pos[0] - sx, pos[1] - sy) < 38:
                self._dragging   = True
                self._deviations = []
                self._cursor_idx = 0
                self.message = "Çizgiyi takip et!"
            else:
                self.message = "Önce çizginin sol ucundan başla!"

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging:
                self._dragging = False
                self._finish()

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, dt, logical_mouse_pos=None):
        if not self.active:
            return

        if self._done:
            self._result_timer -= dt
            if self._result_timer <= 0:
                self.close()
            return

        if self._dragging:
            pos = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
            d, idx = self._nearest_path_distance(pos)
            self._deviations.append(d)
            if idx > self._cursor_idx:
                self._cursor_idx = idx
            # Auto-finish when player reaches the end zone
            if self._cursor_idx >= self._path_total - 5:
                self._dragging = False
                self._finish()

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _finish(self):
        self._done = True
        self._result_timer = 2.2

        if not self._deviations:
            mean_dev = 999.0
        else:
            mean_dev = sum(self._deviations) / len(self._deviations)

        # Coverage: what fraction of the path was reached
        coverage = self._cursor_idx / max(1, self._path_total - 1)

        if coverage < 0.4:
            count = 0
            self.message = "Çok erken bıraktın! Buğday ziyan oldu."
        elif mean_dev < self._TOLERANCE_PERFECT:
            count = 3
            self.message = "Mükemmel kesim! 3 buğday kazandın!"
        elif mean_dev < self._TOLERANCE_GOOD:
            count = 2
            self.message = "İyi kesim! 2 buğday kazandın."
        elif mean_dev < self._TOLERANCE_POOR:
            count = 1
            self.message = "Sallantılı kesim... 1 buğday kazandın."
        else:
            count = 0
            self.message = "Tirpan kaçtı! Buğday ziyan oldu."

        if count > 0:
            self.node.harvest()
            if hasattr(self, 'on_harvest') and callable(self.on_harvest):
                self.on_harvest(count)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_wheat_stalks(self, screen, elapsed):
        """Draw simple wheat stalks using lines + ear shapes."""
        for (sx, sy, ht, phase) in self._stalks:
            sway = int(6 * math.sin(elapsed * 1.8 + phase))
            tip  = (sx + sway, sy - ht)
            # Stalk
            pygame.draw.line(screen, (160, 130, 40), (sx, sy), tip, 2)
            # Ear (small diamond)
            ear_col = (210, 175, 60)
            ear_sz  = 5
            ear_pts = [
                (tip[0],          tip[1] - ear_sz*2),
                (tip[0] + ear_sz, tip[1] - ear_sz),
                (tip[0],          tip[1]),
                (tip[0] - ear_sz, tip[1] - ear_sz),
            ]
            pygame.draw.polygon(screen, ear_col, ear_pts)
            # Two side grains
            for side in (-1, 1):
                gp = (tip[0] + side * ear_sz, tip[1] - ear_sz * 3 // 2)
                pygame.draw.line(screen, ear_col, tip, gp, 1)

    def draw_ui(self, screen, font, logical_mouse_pos=None):
        if not self.active:
            return

        elapsed = pygame.time.get_ticks() / 1000.0

        # ── Dark panel ───────────────────────────────────────────────────────
        ov = pygame.Surface((self._panel.width, self._panel.height), pygame.SRCALPHA)
        ov.fill((22, 28, 18, 215))
        screen.blit(ov, self._panel.topleft)
        pygame.draw.rect(screen, (140, 115, 55), self._panel, width=2, border_radius=8)

        # ── Wheat field illustration ──────────────────────────────────────────
        # Ground strip
        ground_rect = pygame.Rect(self._panel.x, self._panel.bottom - 40,
                                  self._panel.width, 40)
        pygame.draw.rect(screen, (70, 55, 25), ground_rect)
        self._draw_wheat_stalks(screen, elapsed)

        # ── Cut path ─────────────────────────────────────────────────────────
        if len(self._path_pts) > 1:
            # Glow behind the dashed line (thick dim gold — no alpha needed)
            for i in range(0, len(self._path_pts) - 1, 4):
                pygame.draw.line(screen, (120, 100, 30),
                                 self._path_pts[i], self._path_pts[i+1], 10)
            # Dashed bright guide line
            for i in range(0, len(self._path_pts) - 1, 6):
                if (i // 6) % 2 == 0:
                    pygame.draw.line(screen, (245, 235, 160),
                                     self._path_pts[i], self._path_pts[i+1], 2)

        # ── Start / end markers ───────────────────────────────────────────────
        if self._path_pts:
            sx, sy = self._path_pts[0]
            ex, ey = self._path_pts[-1]
            pygame.draw.circle(screen, (80, 220, 100), (sx, sy), 12)
            pygame.draw.circle(screen, (255, 255, 255), (sx, sy), 12, 2)
            draw_text(screen, font, "▶", (sx - 6, sy - 10), (20, 20, 20))
            pygame.draw.circle(screen, (220, 80, 80), (ex, ey), 12)
            pygame.draw.circle(screen, (255, 255, 255), (ex, ey), 12, 2)

        # ── Progress trail ────────────────────────────────────────────────────
        if self._dragging and self._cursor_idx > 1:
            trail_pts = self._path_pts[:self._cursor_idx]
            if len(trail_pts) > 1:
                pygame.draw.lines(screen, (120, 240, 120), False, trail_pts, 3)

        # ── Scythe cursor ─────────────────────────────────────────────────────
        if self._dragging:
            pos = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
            # Blade
            blade_pts = [
                (pos[0],      pos[1]),
                (pos[0] - 20, pos[1] + 12),
                (pos[0] - 14, pos[1] + 16),
                (pos[0] +  6, pos[1] +  4),
            ]
            pygame.draw.polygon(screen, (200, 210, 220), blade_pts)
            pygame.draw.polygon(screen, (130, 140, 150), blade_pts, 1)
            # Handle
            pygame.draw.line(screen, (140, 100, 50),
                             (pos[0] - 20, pos[1] + 12),
                             (pos[0] - 40, pos[1] + 30), 3)

            # Deviation ring colour
            d, _ = self._nearest_path_distance(pos)
            if d < self._TOLERANCE_PERFECT:
                ring_col = (80, 230, 80)
            elif d < self._TOLERANCE_GOOD:
                ring_col = (230, 200, 50)
            elif d < self._TOLERANCE_POOR:
                ring_col = (230, 120, 50)
            else:
                ring_col = (220, 60, 60)
            pygame.draw.circle(screen, ring_col, pos, 14, 2)

        # ── Accuracy bar ──────────────────────────────────────────────────────
        if self._dragging and self._deviations:
            mean_d = sum(self._deviations) / len(self._deviations)
            ratio  = max(0.0, 1.0 - mean_d / self._TOLERANCE_POOR)
            bar_w  = 300
            bar_x  = GAME_WIDTH // 2 - bar_w // 2
            bar_y  = self._panel.top + 14
            bar_col = (
                int(220 * (1 - ratio)),
                int(200 * ratio),
                40,
            )
            pygame.draw.rect(screen, (50, 48, 40), (bar_x, bar_y, bar_w, 10), border_radius=4)
            pygame.draw.rect(screen, bar_col,      (bar_x, bar_y, int(bar_w * ratio), 10), border_radius=4)
            pygame.draw.rect(screen, (140, 130, 100), (bar_x, bar_y, bar_w, 10), width=1, border_radius=4)
            draw_text(screen, font, "Doğruluk", (bar_x - 70, bar_y - 2), (210, 195, 140))

        # ── Message ───────────────────────────────────────────────────────────
        msg_col = (255, 220, 100) if self._done else (220, 210, 175)
        draw_text(screen, font, self.message,
                  (self._panel.x + 16, self._panel.top + 8), msg_col)


class StoneMining:
    # Crack shapes: list of (rel_x, rel_y, angle_deg, length) — drawn as branching lines on the rock
    _CRACK_PATTERNS = [
        # Each pattern: list of (dx, dy) segments from a start offset on the rock
        [(0, 0), (12, -8), (20, -18), (14, -28)],
        [(0, 0), (-10, 5), (-22, 12), (-18, 24)],
        [(0, 0), (8, 10), (18, 6), (28, 14)],
    ]

    def __init__(self):
        self.active = False
        self.node = None
        self.targets = []          # list of dicts: {rect, crack_idx, hit, flash_timer}
        self.message = ""
        self.on_harvest = None
        self.time_limit = 8.0
        self.time_remaining = 8.0
        # Rock geometry (set in open())
        self.rock_cx = GAME_WIDTH // 2
        self.rock_cy = GAME_HEIGHT // 2 + 20
        self.rock_rx = 140        # horizontal radius
        self.rock_ry = 100        # vertical radius
        # Pre-baked rock polygon (16-sided)
        self._rock_poly = []
        self._crack_start_offsets = [
            (-40, -30), (20, -50), (-10, 40)
        ]
        self._recoil_vx = 0.0
        self._recoil_vy = 0.0

    def _build_rock_poly(self):
        pts = []
        n = 16
        for i in range(n):
            angle = 2 * math.pi * i / n
            # Slightly randomise radius per vertex for natural look (seeded by cx)
            jitter = 1 + 0.12 * math.sin(angle * 3 + self.rock_cx * 0.01)
            rx = self.rock_rx * jitter
            ry = self.rock_ry * jitter
            pts.append((
                int(self.rock_cx + rx * math.cos(angle)),
                int(self.rock_cy + ry * math.sin(angle)),
            ))
        return pts

    def open(self, node):
        self.active = True
        self.node = node
        self.message = "Catlaklara tikla! (Geri tepmeye hazir ol)"
        self.time_remaining = self.time_limit
        self.rock_cx = GAME_WIDTH // 2
        self.rock_cy = GAME_HEIGHT // 2 + 30
        self._rock_poly = self._build_rock_poly()
        self._recoil_vx = 0.0
        self._recoil_vy = 0.0

        # Place hit targets at crack start positions (relative to rock centre)
        self.targets = []
        for i, (ox, oy) in enumerate(self._crack_start_offsets):
            tx = self.rock_cx + ox - 18
            ty = self.rock_cy + oy - 18
            self.targets.append({
                'rect': pygame.Rect(tx, ty, 36, 36),
                'crack_idx': i,
                'hit': False,
                'flash_timer': 0.0,
            })

    def close(self):
        self.active = False

    def update(self, dt):
        if not self.active:
            return
        # Countdown timer
        self.time_remaining -= dt
        if self.time_remaining <= 0:
            self.message = "Süre doldu! Taş kırılamadı."
            self.close()
            return
        # Decay flash timers
        for t in self.targets:
            if t['flash_timer'] > 0:
                t['flash_timer'] = max(0.0, t['flash_timer'] - dt)

    def handle_event(self, event, logical_mouse_pos=None):
        if not self.active:
            return
        pos = logical_mouse_pos if logical_mouse_pos else pygame.mouse.get_pos()
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = False
            for t in self.targets:
                if not t['hit'] and t['rect'].collidepoint(pos):
                    t['hit'] = True
                    t['flash_timer'] = 0.25
                    hit = True
                    break

            # Smooth recoil: push cursor 50-90 px in a random direction
            angle = random.uniform(0, 2 * math.pi)
            dist = random.randint(50, 90)
            try:
                cx, cy = pygame.mouse.get_pos()
                nx = int(cx + dist * math.cos(angle))
                ny = int(cy + dist * math.sin(angle))
                nx = max(10, min(GAME_WIDTH - 10, nx))
                ny = max(10, min(GAME_HEIGHT - 10, ny))
                pygame.mouse.set_pos([nx, ny])
            except Exception:
                pass

            remaining = [t for t in self.targets if not t['hit']]
            if hit and len(remaining) == 0:
                self.node.harvest()
                if hasattr(self, 'on_harvest') and callable(self.on_harvest):
                    self.on_harvest(3)
                self.close()

    def draw_ui(self, screen, font):
        if not self.active:
            return

        # ── Dark overlay panel ────────────────────────────────────────────────
        panel_rect = pygame.Rect(GAME_WIDTH // 2 - 260, GAME_HEIGHT // 2 - 210, 520, 420)
        overlay = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
        overlay.fill((30, 28, 24, 210))
        screen.blit(overlay, panel_rect.topleft)
        pygame.draw.rect(screen, (90, 85, 75), panel_rect, width=2, border_radius=10)

        # ── Title ─────────────────────────────────────────────────────────────
        draw_text(screen, font, self.message, (GAME_WIDTH // 2 - 210, panel_rect.top + 12), (230, 220, 190))

        # ── Timer bar ────────────────────────────────────────────────────────
        bar_w = 400
        bar_h = 12
        bar_x = GAME_WIDTH // 2 - bar_w // 2
        bar_y = panel_rect.top + 40
        ratio = max(0.0, self.time_remaining / self.time_limit)
        bar_color = (
            int(50 + 180 * (1 - ratio)),
            int(200 * ratio),
            40,
        )
        pygame.draw.rect(screen, (60, 55, 50), (bar_x, bar_y, bar_w, bar_h), border_radius=5)
        if ratio > 0:
            pygame.draw.rect(screen, bar_color, (bar_x, bar_y, int(bar_w * ratio), bar_h), border_radius=5)
        pygame.draw.rect(screen, (110, 105, 95), (bar_x, bar_y, bar_w, bar_h), width=1, border_radius=5)
        secs_left = max(0, int(math.ceil(self.time_remaining)))
        draw_text(screen, font, f"{secs_left}s", (bar_x + bar_w + 8, bar_y - 2), (220, 210, 180))

        # ── Boulder body ─────────────────────────────────────────────────────
        # Shadow
        shadow_pts = [(x + 6, y + 8) for x, y in self._rock_poly]
        pygame.draw.polygon(screen, (20, 18, 14), shadow_pts)
        # Main rock — dark stone base
        pygame.draw.polygon(screen, (105, 100, 92), self._rock_poly)
        # Mid-tone fill (slightly lighter stripe near top-left for depth)
        highlight_pts = [
            (self.rock_cx - self.rock_rx * 0.55, self.rock_cy - self.rock_ry * 0.55),
            (self.rock_cx + self.rock_rx * 0.10, self.rock_cy - self.rock_ry * 0.70),
            (self.rock_cx + self.rock_rx * 0.35, self.rock_cy - self.rock_ry * 0.35),
            (self.rock_cx - self.rock_rx * 0.15, self.rock_cy - self.rock_ry * 0.05),
        ]
        pygame.draw.polygon(screen, (135, 130, 120), [tuple(map(int, p)) for p in highlight_pts])
        # Rock outline
        pygame.draw.polygon(screen, (70, 65, 58), self._rock_poly, width=3)

        # ── Crack lines on rock ───────────────────────────────────────────────
        crack_colors = [(55, 50, 44), (45, 42, 36), (65, 60, 52)]
        for i, (ox, oy) in enumerate(self._crack_start_offsets):
            t_data = self.targets[i]
            pts_pattern = self._CRACK_PATTERNS[i % len(self._CRACK_PATTERNS)]
            sx = self.rock_cx + ox
            sy = self.rock_cy + oy
            if t_data['hit']:
                # Destroyed crack — wider, lighter split
                c = (180, 160, 130)
                w = 3
            else:
                c = crack_colors[i % len(crack_colors)]
                w = 2
            prev = (sx, sy)
            for seg in pts_pattern[1:]:
                nxt = (sx + seg[0], sy + seg[1])
                pygame.draw.line(screen, c, prev, nxt, w)
                # Branch
                pygame.draw.line(screen, c,
                    (prev[0] + (nxt[0]-prev[0])//2, prev[1] + (nxt[1]-prev[1])//2),
                    (prev[0] + (nxt[0]-prev[0])//2 + random.randint(-6, 6),
                     prev[1] + (nxt[1]-prev[1])//2 + random.randint(-8, 8)),
                    max(1, w - 1))
                prev = nxt

        # ── Hit targets (crack glow zones) ───────────────────────────────────
        mouse_pos = pygame.mouse.get_pos()
        for t_data in self.targets:
            if t_data['hit']:
                continue
            r = t_data['rect']
            dist = math.hypot(mouse_pos[0] - r.centerx, mouse_pos[1] - r.centery)
            hovering = dist < 40

            # Glow halo when hovering
            if hovering:
                glow_surf = pygame.Surface((80, 80), pygame.SRCALPHA)
                pygame.draw.circle(glow_surf, (255, 200, 80, 70), (40, 40), 38)
                screen.blit(glow_surf, (r.centerx - 40, r.centery - 40))

            # Flash on hit
            if t_data['flash_timer'] > 0:
                alpha = int(200 * t_data['flash_timer'] / 0.25)
                flash_surf = pygame.Surface((50, 50), pygame.SRCALPHA)
                pygame.draw.circle(flash_surf, (255, 240, 120, alpha), (25, 25), 24)
                screen.blit(flash_surf, (r.centerx - 25, r.centery - 25))

            # Clickable indicator: small dark crevice marker
            col = (220, 180, 60) if hovering else (160, 140, 100)
            pygame.draw.circle(screen, col, r.center, 8, 2)
            pygame.draw.line(screen, col,
                (r.centerx - 5, r.centery), (r.centerx + 5, r.centery), 2)
            pygame.draw.line(screen, col,
                (r.centerx, r.centery - 5), (r.centerx, r.centery + 5), 2)

        # ── Progress dots (how many cracks hit) ──────────────────────────────
        hits_done = sum(1 for t in self.targets if t['hit'])
        total = len(self.targets)
        dot_y = panel_rect.bottom - 28
        for i in range(total):
            dot_x = GAME_WIDTH // 2 - (total - 1) * 18 + i * 36
            color = (100, 220, 100) if i < hits_done else (80, 75, 65)
            pygame.draw.circle(screen, color, (dot_x, dot_y), 9)
            pygame.draw.circle(screen, (150, 145, 130), (dot_x, dot_y), 9, 1)


# ---------------------------------------------------------------------------
# Wood-chopping sprite helpers
# ---------------------------------------------------------------------------
_TREE_CACHE = {}


def wood_tree_sprite(variant=0, damage=0):
    key = (variant % 3, damage)
    if key in _TREE_CACHE:
        return _TREE_CACHE[key]
    s = pygame.Surface((96, 112), pygame.SRCALPHA)
    ink, bark, light = (61, 40, 38), (128, 75, 48), (181, 113, 65)
    palettes = [
        ((120, 53, 46),  (185, 77, 47),  (230, 131, 64), (249, 181, 89)),
        ((136, 83, 43),  (200, 133, 52), (235, 176, 69), (252, 211, 116)),
        ((100, 66, 53),  (158, 82, 53),  (201, 110, 61), (235, 155, 84)),
    ]
    colors = palettes[variant % 3]

    def rect(c, r): pygame.draw.rect(s, c, r)

    # Roots, tapering trunk and little side branches
    pygame.draw.polygon(s, ink,  [(39,37),(55,37),(57,99),(65,105),(32,105),(38,98)])
    rect(bark,  (40, 40, 14, 61))
    rect(light, (41, 45,  4, 53))
    pygame.draw.polygon(s, bark, [(39,96),(34,103),(60,103),(53,96)])
    pygame.draw.lines(s, ink,  False, [(43,62),(34,52),(32,42)], 5)
    pygame.draw.lines(s, bark, False, [(51,57),(63,47),(64,39)], 5)
    for x, y, h in [(48,52,9),(51,66,7),(46,85,10),(40,73,8),(52,92,8)]:
        rect((99, 58, 42), (x, y, 2, h))

    # Stepped leaf clusters
    clusters = [(30,35,19,15),(62,35,20,16),(46,17,22,15),
                (24,23,16,14),(67,20,15,15),(45,36,24,17),(46,8,14,9)]
    rng = random.Random(731 + variant * 83)
    for cx, cy, w, h in clusters:
        cx += rng.randint(-3, 3)
        for col, inset, dy in [(ink, 0, 0), (colors[0], 2, -1), (colors[1], 4, -3)]:
            pygame.draw.polygon(s, col, [
                (cx-w+inset,   cy-h//2+dy), (cx-w+5+inset, cy-h+dy),
                (cx+w-6-inset, cy-h+dy),   (cx+w-inset,   cy-h//2+dy),
                (cx+w-inset,   cy+h//2+dy),(cx+w-6-inset, cy+h+dy),
                (cx-w+6+inset, cy+h+dy),   (cx-w+inset,   cy+h//2+dy)])
        for _ in range(12):
            x2 = cx + rng.randint(-w+6, w-6)
            y2 = cy + rng.randint(-h+4, h-3)
            rect(rng.choice(colors[1:]), (x2, y2, rng.choice([2, 3, 4]), 2))

    # Axe cut wedge + cracks
    depth = [3, 6, 9, 12, 14][min(4, damage)]
    pygame.draw.polygon(s, ink,            [(55, 75), (55-depth, 79), (55, 84)])
    pygame.draw.polygon(s, (241, 184, 111), [(54, 77), (56-depth, 79), (54, 81)])
    if damage:
        pygame.draw.lines(s, ink, False, [(54-depth,79),(49-depth,74),(50-depth,69)], 1)
    if damage >= 2:
        pygame.draw.lines(s, ink, False, [(51-depth,78),(48-depth,85),(49-depth,91)], 1)

    _TREE_CACHE[key] = s
    return s


def wood_axe_sprite():
    s = pygame.Surface((46, 30), pygame.SRCALPHA)
    pygame.draw.polygon(s, (48, 38, 38),
                        [(13,12),(43,21),(45,26),(41,29),(11,18)])
    pygame.draw.line(s, (157,  94, 54), (15,16), (41,25), 4)
    pygame.draw.line(s, (222, 161, 91), (17,15), (41,23), 1)
    pygame.draw.polygon(s, (43, 47, 54),
                        [(0,3),(8,5),(19,9),(18,20),(7,23),(0,25)])
    pygame.draw.polygon(s, (127,155,158),
                        [(2,6),(8,8),(16,11),(15,18),(7,20),(2,22)])
    pygame.draw.rect(s, (224,237,219), (1, 7, 3,14))
    pygame.draw.rect(s, (179,201,193), (5, 9, 3,10))
    pygame.draw.rect(s, (74,  87, 90), (12,12, 5, 5))
    return s


class WoodChopping:
    TIME_LIMIT = 12.0
    MISS_PENALTY = 1.5

    def __init__(self):
        self.active  = False
        self.node    = None
        self.on_harvest = None
        self.axe     = wood_axe_sprite()
        # Runtime state (reset in open)
        self.variant = 0
        self.hits    = 0
        self.phase   = 0.0
        self.timer   = 0.0
        self.state   = 'AIM'
        self.axe_y   = 79.0
        self.good_hit = False
        self.particles = []
        self.message = ''
        self.time_remaining = self.TIME_LIMIT
        self.result = None

    def open(self, node):
        self.active   = True
        self.node     = node
        self.variant  = int(node.x * 31 + node.y * 17) % 3
        self.hits     = 0
        self.phase    = 0.0
        self.timer    = 0.0
        self.state    = 'AIM'
        self.axe_y    = 79.0
        self.good_hit = False
        self.particles = []
        self.message  = 'Balta yarığa hizalanınca BOŞLUK!'
        self.time_remaining = self.TIME_LIMIT
        self.result = None

    def close(self, result=None):
        if result is not None:
            self.result = result
        self.active = False

    def handle_event(self, event, player_exhaust_timer):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
                if self.state not in ('FALL',):
                    self.close(False)
            elif event.key == pygame.K_SPACE and not getattr(event, 'repeat', False):
                if hasattr(self, 'bar_pos'):
                    if 180 <= self.bar_pos <= 220:
                        self.node.harvest()
                        if hasattr(self, 'on_harvest') and callable(self.on_harvest):
                            self.on_harvest(4)
                        self.close(True)
                        return player_exhaust_timer
                if self.state == 'AIM':
                    self.good_hit = abs(self.axe_y - 79) <= 4.5
                    self.state, self.timer = 'SWING', 0.0
        return player_exhaust_timer

    def update(self, dt):
        if not self.active:
            return self.result
        elapsed_dt = max(0.0, dt)
        dt = min(dt, 0.1)
        self.timer += dt

        # Age particles
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 90 * dt   # gravity
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]

        if self.state == 'AIM':
            self.phase += dt * (2.5 + self.hits * 0.25)
            self.axe_y  = 79 + math.sin(self.phase) * 22

        elif self.state == 'SWING' and self.timer >= 0.14:
            self.state, self.timer = 'IMPACT', 0.0
            if self.good_hit:
                self.hits += 1
                self.message = 'Tam isabet! Yarığı derinleştirdin.'
                for _ in range(15):
                    self.particles.append([
                        54.0, 79.0,
                        random.uniform(15, 65), random.uniform(-65, 10),
                        random.uniform(0.3, 0.7),
                    ])
            else:
                self.message = 'Iskaladın! Kesici ucu yarığa hizala.'
                self.time_remaining = max(0.0, self.time_remaining - self.MISS_PENALTY)

        elif self.state == 'IMPACT' and self.timer >= 0.3:
            self.state, self.timer = 'RETURN', 0.0

        elif self.state == 'RETURN' and self.timer >= 0.22:
            if self.hits >= 4:
                # ── Tree is felled ─────────────────────────────────────────
                self.state, self.timer = 'FALL', 0.0
                self.message = 'Harika! Ağaç kesildi.'
                # Mark node inactive so it vanishes from the world map
                self.node.active  = False
                self.node.cooldown = random.uniform(30, 40)
                # Give resources
                self.node.harvest()
                if hasattr(self, 'on_harvest') and callable(self.on_harvest):
                    self.on_harvest(4)
            else:
                self.state, self.timer = 'AIM', 0.0

        elif self.state == 'FALL' and self.timer >= 1.4:
            self.close(True)

        if self.active and self.state != 'FALL':
            self.time_remaining = max(0.0, self.time_remaining - elapsed_dt)
            if self.time_remaining <= 0:
                self.message = 'Süre doldu! Ağaç kesilemedi.'
                self.close(False)
                return False

        return self.result if not self.active else None

    def draw_ui(self, screen, font):
        if not self.active:
            return

        # ── Full-screen veil ──────────────────────────────────────────────────
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((19, 24, 29, 185))
        screen.blit(veil, (0, 0))

        # ── Outer panel ───────────────────────────────────────────────────────
        panel = pygame.Rect(GAME_WIDTH//2 - 340, GAME_HEIGHT//2 - 305, 680, 610)
        pygame.draw.rect(screen, (39, 34, 39),    panel.move(6, 7))
        pygame.draw.rect(screen, (108, 70, 50),   panel)
        pygame.draw.rect(screen, (226, 178, 112), panel.inflate(-8, -8), 3)
        pygame.draw.rect(screen, (48, 48, 49),    panel.inflate(-20, -20))

        # ── Header text ───────────────────────────────────────────────────────
        draw_text(screen, font, 'SONBAHAR ORMANI',
                  (panel.x + 28, panel.y + 23), (247, 206, 133))
        draw_text(screen, font, f'AĞAÇ KESME   /   {self.hits} / 4 vuruş',
                  (panel.x + 28, panel.y + 55), (210, 185, 147))
        draw_text(screen, font, f'Süre: {self.time_remaining:04.1f}',
                  (panel.right - 145, panel.y + 55),
                  (255, 110, 90) if self.time_remaining <= 3 else (245, 220, 160))

        # ── Pixel-art scene (210×132 → scaled to 630×396) ────────────────────
        scene = pygame.Surface((210, 132))
        scene.fill((64, 73, 69))
        pygame.draw.rect(scene, (75, 85, 70), (0, 54, 210, 60))
        for i in range(13):
            x = i * 19 - 12
            pygame.draw.rect(scene, (58,  65, 61), (x,   0, 5, 112))
            pygame.draw.rect(scene, (91,  95, 71), (x+7, 25, 2,  83))
        pygame.draw.rect(scene, (111, 109, 70), (0, 109, 210, 23))
        rng2 = random.Random(50)
        for _ in range(95):
            pygame.draw.rect(scene,
                rng2.choice([(156,119,63),(186,123,66),(88,94,63)]),
                (rng2.randrange(210), rng2.randrange(110, 132), 3, 1))

        # Side trees
        for v, pos in [((self.variant+1) % 3, (0, 34)),
                       ((self.variant+2) % 3, (164, 31))]:
            scene.blit(pygame.transform.scale(wood_tree_sprite(v), (42, 60)), pos)

        tx, ty = 56, 7
        tree = wood_tree_sprite(self.variant, self.hits)

        shake = 0
        if self.state == 'IMPACT' and self.good_hit and self.timer < 0.3:
            shake = round(math.sin(self.timer * 70) * 2 * (1 - self.timer / 0.3))

        if self.state == 'FALL':
            # Draw stump
            pygame.draw.rect(scene, (78,  49, 39), (tx+38, ty+80, 19, 24))
            pygame.draw.rect(scene, (226,171,101), (tx+38, ty+80, 19,  3))
            # Rotate crown around cut point
            crown  = tree.subsurface((0, 0, 96, 80)).copy()
            canvas = pygame.Surface((192, 160), pygame.SRCALPHA)
            canvas.blit(crown, (96-48, 80-79))
            angle  = -min(92, (self.timer / 0.85) ** 2 * 92)
            fallen = pygame.transform.rotate(canvas, angle)
            scene.blit(fallen, fallen.get_rect(center=(tx+48, ty+79)))
        else:
            scene.blit(tree, (tx + shake, ty))

            # Aim guide line
            near = abs(self.axe_y - 79) <= 4.5
            if self.state == 'AIM':
                col = (249, 211, 128) if near else (174, 151, 104)
                pygame.draw.rect(scene, col, (tx+58, ty+75, 2, 9))

            # Axe offset by state
            offset = 0
            if   self.state == 'SWING':  offset = int(17 * min(1.0, self.timer / 0.14))
            elif self.state == 'IMPACT': offset = 17
            elif self.state == 'RETURN': offset = int(17 * (1 - min(1.0, self.timer / 0.22)))
            scene.blit(self.axe, (round(tx + 69 - offset), round(ty + self.axe_y - 14)))

        # Wood chip particles
        for x, y, vx, vy, life in self.particles:
            pygame.draw.rect(scene, (245, 188, 111),
                             (round(tx+x), round(ty+y), 2, 2))

        screen.blit(pygame.transform.scale(scene, (630, 396)),
                    (panel.x + 25, panel.y + 96))

        # ── Hit pips ──────────────────────────────────────────────────────────
        for i in range(4):
            r = pygame.Rect(panel.x + 28 + i*47, panel.y + 510, 36, 9)
            pygame.draw.rect(screen,
                (233, 173, 93) if i < self.hits else (91, 78, 64), r)

        # ── Footer ────────────────────────────────────────────────────────────
        draw_text(screen, font, self.message,
                  (panel.x + 28, panel.y + 535), (248, 220, 171))
        draw_text(screen, font, 'BOŞLUK: vur     ESC / E / Q: kapat',
                  (panel.x + 28, panel.y + 567), (174, 171, 148))


class OpenWaterFishing:
    def __init__(self, seed):
        self.rng = random.Random(seed + 45677)
        self.active = False
        self.port = None
        self.fish_count = 0
        self.on_catch = None

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
                    if hasattr(self, 'on_catch') and callable(self.on_catch):
                        self.on_catch(1)

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


def draw_island_flag(screen, screen_x, screen_y, owner, my_id):
    # Wooden Flagpole
    pole_color = (130, 85, 45)
    pygame.draw.rect(screen, pole_color, (screen_x + 8, screen_y - 36, 4, 38), border_radius=1)
    pygame.draw.circle(screen, (220, 180, 80), (screen_x + 10, screen_y - 36), 3)

    # Fluttering Banner
    flag_rect = pygame.Rect(screen_x + 12, screen_y - 34, 28, 18)
    if owner is None:
        flag_color = (160, 165, 175)
        border_color = (200, 205, 215)
    elif owner == my_id:
        flag_color = (255, 205, 50)
        border_color = (255, 245, 180)
    else:
        flag_color = (220, 50, 50)
        border_color = (255, 120, 120)

    pts = [
        flag_rect.topleft,
        (flag_rect.right, flag_rect.top),
        (flag_rect.right - 6, flag_rect.centery),
        (flag_rect.right, flag_rect.bottom),
        flag_rect.bottomleft
    ]
    pygame.draw.polygon(screen, flag_color, pts)
    pygame.draw.polygon(screen, border_color, pts, 1)


# ---------------------------------------------------------------------------
# Active Gameplay Session Manager
# ---------------------------------------------------------------------------
class GameSession:
    """Manages active gameplay systems, player state, camera, minigames, and rendering."""
    def __init__(self, world, ports, spawn, tiles, network, seed, customization, atlas=None, character_sheet=None):
        self.world = world
        self.ports = ports
        if network and network.connected and getattr(network, 'spawn', None):
            self.spawn_island, assigned_spawn = network.spawn_island, network.spawn
        else:
            self.spawn_island, assigned_spawn = acquire_offline_spawn(world)
        self.player = pygame.Vector2(assigned_spawn)
        self.tiles = tiles
        self.network = network
        if network:
            network.expected_seed = world.seed
        self.seed = seed
        self.customization = customization
        self.atlas = atlas
        self.character_sheet = character_sheet if character_sheet is not None else load_character_sheet(BASE_DIR)
        try:
            hull = pygame.image.load(str(BASE_DIR / "assets" / "sailboat_hull.png")).convert_alpha()
            # Chroma-key removal left much of the wooden hull semi-transparent.
            # Make the actual vessel opaque so ocean pixels cannot tint it blue;
            # scaling below will still recreate a thin antialiased outer edge.
            hull_alpha = pygame.surfarray.pixels_alpha(hull)
            hull_alpha[hull_alpha > 18] = 255
            hull_alpha[hull_alpha <= 18] = 0
            del hull_alpha
            self.sailboat_hull = pygame.transform.smoothscale(hull, (54, 86))
            scaled_alpha = pygame.surfarray.pixels_alpha(self.sailboat_hull)
            scaled_alpha[scaled_alpha > 18] = 255
            scaled_alpha[scaled_alpha <= 18] = 0
            del scaled_alpha
        except (pygame.error, FileNotFoundError):
            self.sailboat_hull = None
        self.player_animation = CharacterAnimator()
        self.remote_animations = {}
        self.remote_combats = {}
        self.pvp_hit_flashes = {}
        self.terrain_renderer = TerrainRenderer(world, atlas) if atlas else None

        self.hud = PixelHUD()
        self.map_ui = WorldMapUI(world, tiles, GAME_WIDTH, GAME_HEIGHT)
        self.world_map = self.map_ui.full_surface
        self.map_rect = self.map_ui.full_rect
        self.leaves = AutumnLeaves(seed, world, atlas, LOCAL_TILE_SIZE, (GAME_WIDTH, GAME_HEIGHT))
        self.fishing = OpenWaterFishing(seed)
        self.grain_game = GrainHarvesting(seed)
        self.stone_game = StoneMining()
        self.wood_game = WoodChopping()
        self.dialogue = DialogueBox()
        self.quest_system = QuestSystem(world)
        self.combat = CombatSystem()
        self.enemy_ai = EnemyAISystem()
        self.naval = NavalEncounterSystem(
            world, seed, lambda x, y: can_stand(world, x, y, True))

        # Connect minigame harvest callbacks
        self.grain_game.on_harvest = lambda count=3: self.harvest_reward("Tahil", count)
        self.stone_game.on_harvest = lambda count=3: self.harvest_reward("Tas", count)
        self.wood_game.on_harvest = lambda count=4: self.harvest_reward("Odun", count)
        self.fishing.on_catch = lambda count=1: self.add_resource("Balik", count)

        # Inventory & Conquest Economy
        self.inventory = {
            "Odun": 8,
            "Tas": 6,
            "Tahil": 4,
            "Balik": 2,
        }
        self.equipment = {"sword": DEBUG_STARTING_EQUIPMENT, "bow": DEBUG_STARTING_EQUIPMENT}
        self.loot_rng = random.Random(seed + 44017)
        self.max_health = 8
        self.health = self.max_health
        self.damage_cooldown = 0.0
        self.arrows = []
        self.arrow_cooldown = 0.0
        self.sail_angle = 0.0
        self.sail_raised = True
        self.wind_angle = random.Random(seed + 8181).uniform(0, math.tau)
        self.wind_strength = 1.0
        self.wind_timer = 0.0
        self.island_owners = dict(self.network.island_owners) if (self.network and hasattr(self.network, 'island_owners')) else {}
        self.winner = self.network.winner if (self.network and hasattr(self.network, 'winner')) else None
        self.victory_dismissed = False
        self.WINNING_COUNT = WINNING_ISLAND_COUNT
        self.income_timer = 20.0
        self.floating_texts = []
        self.toasts = []

        self.map_button = self.map_ui.minimap_rect
        self.map_open = False
        self.is_sailing = False
        self.boat_angle = 0.0
        self.boat_speed = 0.0
        self.turn_speed = 0.0
        self.player_exhaust_timer = 0.0
        self.port_trigger_ready = True

        # UI elements
        self.inventory_button = self.hud.inventory_button
        self.inventory_open = False
        self.inventory_close_rect = pygame.Rect(0, 0, 32, 32)
        self.trade_button = self.hud.trade_button
        self.trade_open = False
        self.trade_close_rect = pygame.Rect(0, 0, 32, 32)
        self.trade_selected_partner = None
        self.trade_offer = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
        self.trade_request = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
        self.trade_send_btn = pygame.Rect(0, 0, 160, 36)
        self.trade_action_rects = []
        self.processed_trades = set()
        self.conquer_action_rect = pygame.Rect(0, 0, 220, 38)
        self.hud_conquer_rect = pygame.Rect(GAME_WIDTH // 2 - 180, GAME_HEIGHT - 74, 360, 38)
        self.victory_continue_rect = pygame.Rect(GAME_WIDTH // 2 - 190, GAME_HEIGHT // 2 + 100, 180, 42)
        self.victory_menu_rect = pygame.Rect(GAME_WIDTH // 2 + 10, GAME_HEIGHT // 2 + 100, 180, 42)
        self.game_time = 0.0
        self.last_direction_tap = {"up": -10.0, "down": -10.0, "left": -10.0, "right": -10.0}
        self.held_direction_keys = set()
        self.dash_timer = 0.0
        self.dash_cooldown = 0.0
        self.dash_direction = pygame.Vector2(0, -1)
        self.dash_effect_timer = 0.0
        self.dash_effects = []
        self.execution = None
        self.combat_rng = random.Random(seed + 99173)
        self.local_inflation = 1.0
        self.capture_count = (self.network.capture_count if self.network and hasattr(self.network, 'capture_count')
                              else len(self.island_owners))

        self.cam_x, self.cam_y = get_local_camera(self.player)
        self.facing = "down"
        self.moving = False
        self.previous_pos = (self.player.x, self.player.y)
        self.net_timer = 0.0
        self.resource_revision = 0
        self.spawn_revision = getattr(network, 'spawn_revision', 0) if network else 0
        self.network_combat_revision = getattr(network, 'combat_revision', 0) if network else 0
        self.network_deaths = getattr(network, 'deaths', 0) if network else 0

        # Fonts
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 21)

        # In-game pause modal state
        self.paused = False
        self.pause_resume_rect = pygame.Rect(GAME_WIDTH // 2 - 120, GAME_HEIGHT // 2 - 40, 240, 40)
        self.pause_menu_rect = pygame.Rect(GAME_WIDTH // 2 - 120, GAME_HEIGHT // 2 + 15, 240, 40)

    def my_player_id(self):
        if self.network and self.network.connected and self.network.id is not None:
            return self.network.id
        return 0

    def add_resource(self, item_name, count):
        self.inventory[item_name] = self.inventory.get(item_name, 0) + count
        screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
        screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 45
        color = RESOURCE_COLORS.get(item_name, (255, 235, 120))
        self.floating_texts.append(FloatingText(f"+{count} {item_name}", (screen_x, screen_y), color))
        self.add_toast(f"+{count} {item_name} toplandi!")

    def harvest_reward(self, item_name, count):
        self.add_resource(item_name, count)
        # Production mode starts without gear; gathering then has a rare 4% drop.
        missing = [name for name, owned in self.equipment.items() if not owned]
        if missing and self.loot_rng.random() < 0.04:
            item = self.loot_rng.choice(missing)
            self.equipment[item] = True
            display = "Kılıç" if item == "sword" else "Yay"
            self.add_toast(f"NADİR GANİMET: {display} buldun!", color=(255, 220, 90))

    def add_toast(self, message, color=(255, 235, 160)):
        self.toasts.append(ToastNotification(message, color=color))
        if len(self.toasts) > 3:
            self.toasts.pop(0)

    def handle_monster_defeated(self, monster):
        self.quest_system.monster_defeated(monster)
        finisher_chance = .68 if self.combat.attack_kind == "dash" else (.48 if self.combat.combo_step >= 3 else .28)
        if self.execution is not None or self.combat_rng.random() >= finisher_chance:
            return
        angle = math.atan2(monster.y - self.player.y, monster.x - self.player.x)
        self.execution = {
            "x": monster.x, "y": monster.y, "angle": angle,
            "timer": 0.0, "duration": .78,
            "variant": self.combat_rng.randrange(3), "kind": monster.kind,
        }
        self.damage_cooldown = max(self.damage_cooldown, .85)
        # Seed a ring of opposing wave trails around the finishing point.
        for index in range(10):
            wave_angle = angle + index * math.tau / 10
            self.dash_effects.append({"x": monster.x, "y": monster.y, "angle": wave_angle,
                                      "life": .38 + index * .012, "max_life": .38 + index * .012})

    def grant_quest_reward(self, reward):
        for item, amount in reward.items():
            self.inventory[item] = self.inventory.get(item, 0) + amount
        reward_text = ", ".join(f"+{amount} {item}" for item, amount in reward.items())
        self.add_toast(f"Görev tamamlandı! {reward_text}", color=(130, 245, 145))

    def respawn_player(self):
        """Respawn on a new island; online allocation remains server-authoritative."""
        if self.network and self.network.connected:
            self.network.request_respawn()
            return
        self.spawn_island, spawn = acquire_offline_spawn(self.world)
        self.player.update(spawn)
        self.previous_pos = tuple(self.player)
        self.cam_x, self.cam_y = get_local_camera(self.player)

    def complete_quest_rescue(self, quest):
        if self.island_owners.get(quest.island_index) == self.my_player_id():
            return True
        return self.try_rescue_island(quest.island_index)

    def current_island_info(self):
        if self.is_sailing:
            return None, None, None
        px, py = int(self.player.x), int(self.player.y)
        if 0 <= px < COLS and 0 <= py < ROWS:
            idx = self.world.owners[py][px]
            if 0 <= idx < len(self.world.islands):
                island = self.world.islands[idx]
                owner = self.island_owners.get(idx, None)
                return idx, island, owner
        return None, None, None

    def can_afford(self, cost):
        return all(self.inventory.get(item, 0) >= amount for item, amount in cost.items())

    def get_missing_resources(self, cost):
        missing = []
        for item, amount in cost.items():
            have = self.inventory.get(item, 0)
            if have < amount:
                missing.append(f"{amount - have} {item}")
        return missing

    def get_inflation_rate(self):
        if self.network and self.network.connected and hasattr(self.network, 'inflation'):
            return self.network.inflation
        return round(1.0 + max(0.0, self.game_time / 60.0) * ISLAND_INFLATION_PER_MINUTE, 3)

    def get_current_island_cost(self, is_enemy=False):
        return get_island_cost(is_enemy, self.get_inflation_rate())

    def try_rescue_island(self, island_index=None):
        current_idx, current_island, current_owner = self.current_island_info()
        idx = current_idx if island_index is None else island_index
        island = current_island if island_index is None else self.world.islands[idx]
        owner = current_owner if island_index is None else self.island_owners.get(idx)
        if idx is None:
            self.add_toast("Adayı kurtarmak için karaya çıkmalısın!")
            return False

        my_id = self.my_player_id()
        if owner is not None:
            self.add_toast(f"{island.name} zaten kurtarıldı!")
            return False

        quest = next((q for q in self.quest_system.quests.values() if q.island_index == idx), None)
        if quest and quest.state != "ready":
            self.add_toast("Önce köylünün görevini alıp adadaki tehditleri yenmelisin!")
            return False

        cost = self.get_current_island_cost(False)

        if not self.can_afford(cost):
            missing = self.get_missing_resources(cost)
            self.add_toast(f"Kışlık kaynaklar yetersiz! Eksik: {', '.join(missing)}")
            screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
            screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 45
            self.floating_texts.append(FloatingText("Yetersiz Materyal!", (screen_x, screen_y), (255, 90, 90)))
            return False

        for item, amount in cost.items():
            self.inventory[item] -= amount

        self.island_owners[idx] = my_id
        island.owner = my_id
        if not (self.network and self.network.connected):
            self.capture_count += 1

        if self.network and self.network.connected:
            self.network.capture_island(idx)

        screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
        screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 50
        my_count = sum(1 for o in self.island_owners.values() if o == my_id)

        msg = f"{island.name} KURTARILDI! ({my_count}/{self.WINNING_COUNT})"
        self.floating_texts.append(FloatingText(f"{island.name} KURTARILDI!", (screen_x - 30, screen_y), (255, 230, 80), duration=2.5))

        self.add_toast(msg)

        if my_count >= self.WINNING_COUNT:
            self.winner = my_id

        return True

    def try_capture_island(self):
        """Compatibility alias for older input/tests; islands are rescued, never bought."""
        return self.try_rescue_island()

    def update_island_income(self, dt):
        if self.paused:
            return
        self.income_timer -= dt
        if self.income_timer <= 0:
            self.income_timer = 20.0
            my_id = self.my_player_id()
            my_islands = [self.world.islands[idx] for idx, o in self.island_owners.items() if o == my_id]
            if my_islands:
                gains = {}
                for isl in my_islands:
                    for res in isl.resources:
                        if res in ("Odun", "Tas", "Tahil", "Balik"):
                            gains[res] = gains.get(res, 0) + 1
                            self.inventory[res] = self.inventory.get(res, 0) + 1
                if gains:
                    gain_str = ", ".join(f"+{amt} {item}" for item, amt in gains.items())
                    self.add_toast(f"Ada Geliri: {gain_str}")
                    screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
                    screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 60
                    self.floating_texts.append(FloatingText(f"Ada Geliri: {gain_str}", (screen_x - 20, screen_y), (140, 240, 140)))

    def nearby_port(self):
        closest, closest_distance = None, float("inf")
        for port in self.ports:
            distance = math.hypot(self.player.x - (port.x + 0.5), self.player.y - (port.y + 0.5))
            if distance < closest_distance:
                closest_distance, closest = distance, port
        return closest, closest_distance

    def start_dash(self, direction=(0, -1)):
        if (self.dash_cooldown > 0 or self.is_sailing or self.map_open
                or self.dialogue.active or self.player_exhaust_timer > 0):
            return False
        dash_direction = pygame.Vector2(direction)
        if dash_direction.length_squared() <= .001:
            dash_direction.update(0, -1)
        dash_direction.normalize_ip()
        self.dash_direction = dash_direction
        self.dash_timer = .24
        self.dash_cooldown = .72
        self.dash_effect_timer = 0.0
        self.damage_cooldown = max(self.damage_cooldown, .30)
        self.facing = ("right" if dash_direction.x > 0 else "left") if abs(dash_direction.x) > abs(dash_direction.y) else (
            "down" if dash_direction.y > 0 else "up")
        for delay in (0.0, .035, .07):
            self.dash_effects.append({"x": self.player.x, "y": self.player.y,
                                      "angle": math.atan2(dash_direction.y, dash_direction.x),
                                      "life": .34 + delay, "max_life": .34 + delay})
        return True

    def update_dash_movement(self, dt):
        if self.dash_timer <= 0:
            return False
        step = min(dt, self.dash_timer)
        self.dash_timer = max(0.0, self.dash_timer - dt)
        speed = 15.5
        target_x = self.player.x + self.dash_direction.x * speed * step
        target_y = self.player.y + self.dash_direction.y * speed * step
        moved = False
        if can_stand(self.world, target_x, self.player.y, False):
            self.player.x = target_x
            moved = True
        if can_stand(self.world, self.player.x, target_y, False):
            self.player.y = target_y
            moved = True
        if not moved:
            self.dash_timer = 0.0

        self.dash_effect_timer -= dt
        while self.dash_effect_timer <= 0 and len(self.dash_effects) < 36:
            self.dash_effect_timer += .025
            self.dash_effects.append({"x": self.player.x, "y": self.player.y,
                                      "angle": math.atan2(self.dash_direction.y, self.dash_direction.x),
                                      "life": .32, "max_life": .32})
        return True

    def fire_arrow(self, mouse_pos):
        if self.arrow_cooldown > 0:
            return False
        target_x = (mouse_pos[0] + self.cam_x) / LOCAL_TILE_SIZE
        target_y = (mouse_pos[1] + self.cam_y) / LOCAL_TILE_SIZE
        dx, dy = target_x - self.player.x, target_y - self.player.y
        length = math.hypot(dx, dy)
        if length < .01:
            return False
        dx, dy = dx / length, dy / length
        self.arrows.append({"x": self.player.x, "y": self.player.y,
                            "vx": dx * 12.0, "vy": dy * 12.0, "life": 1.6})
        self.facing = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up")
        self.arrow_cooldown = .38
        return True

    def update_pvp_melee(self):
        if not (self.network and self.network.connected and self.combat.attacking):
            return
        attack = self.combat.attack_profile()
        if not (attack["active"][0] <= self.combat.timer <= attack["active"][1]):
            return
        hit_x, hit_y, hit_w, hit_h = self.combat.hitbox(self.player, self.facing)
        with self.network.lock:
            players = {pid: dict(data) for pid, data in self.network.other_players.items()}
        for pid, data in players.items():
            target_key = f"player:{pid}"
            if (target_key in self.combat.hit_targets or data.get("sailing", False)
                    or not (hit_x <= data.get("x", -999) <= hit_x + hit_w
                            and hit_y <= data.get("y", -999) <= hit_y + hit_h)):
                continue
            if self.network.pvp_attack(pid, self.combat.attack_kind):
                self.combat.hit_targets.add(target_key)
                self.pvp_hit_flashes[str(pid)] = .18
                self.combat.impact_pulse = .16

    def hit_remote_player_with_arrow(self, arrow):
        if not (self.network and self.network.connected):
            return False
        with self.network.lock:
            players = {pid: dict(data) for pid, data in self.network.other_players.items()}
        hit_radius = .9 if self.is_sailing else .58
        for pid, data in players.items():
            if bool(data.get("sailing", False)) != bool(self.is_sailing):
                continue
            if math.hypot(arrow["x"] - data.get("x", -999), arrow["y"] - data.get("y", -999)) < hit_radius:
                if self.network.pvp_attack(pid, "bow"):
                    arrow["life"] = 0
                    self.pvp_hit_flashes[str(pid)] = .18
                    return True
        return False

    def update_world_combat(self, dt):
        self.damage_cooldown = max(0.0, self.damage_cooldown - dt)
        self.arrow_cooldown = max(0.0, self.arrow_cooldown - dt)
        self.combat.update(dt, self.player, self.facing, self.quest_system.monsters,
                           self.handle_monster_defeated)
        lunge = self.combat.consume_lunge()
        if lunge:
            lunge_dx, lunge_dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0),
                                  "right": (1, 0)}.get(self.facing, (0, 1))
            target_x = self.player.x + lunge_dx * lunge
            target_y = self.player.y + lunge_dy * lunge
            if can_stand(self.world, target_x, target_y, False):
                self.player.update(target_x, target_y)
        self.update_pvp_melee()
        if self.execution is not None:
            return
        px, py = int(self.player.x), int(self.player.y)
        player_island = self.world.owners[py][px] if 0 <= px < COLS and 0 <= py < ROWS else -1
        attackers = self.enemy_ai.update(
            dt, self.player, self.quest_system.monsters, player_island,
            lambda x, y: can_stand(self.world, x, y, False))
        if attackers and self.damage_cooldown <= 0:
            strongest = max(attackers, key=lambda enemy: enemy.damage)
            self.health -= strongest.damage
            self.damage_cooldown = .62
            self.add_toast(f"{strongest.kind.title()} sana vurdu! -{strongest.damage} can",
                           color=(255, 115, 95))
        for arrow in self.arrows:
            arrow["x"] += arrow["vx"] * dt
            arrow["y"] += arrow["vy"] * dt
            arrow["life"] -= dt
            for enemy in self.quest_system.monsters:
                if enemy.alive and math.hypot(arrow["x"] - enemy.x, arrow["y"] - enemy.y) < .55:
                    enemy.health -= 2
                    enemy.hit_flash = .16
                    arrow["life"] = 0
                    if enemy.health <= 0:
                        enemy.alive = False
                        self.quest_system.monster_defeated(enemy)
                    break
            if arrow["life"] > 0:
                self.hit_remote_player_with_arrow(arrow)
        self.arrows = [arrow for arrow in self.arrows if arrow["life"] > 0]
        if self.health <= 0:
            self.health = self.max_health
            self.arrows.clear()
            self.add_toast("Bayıldın! Başka bir adada yeniden doğdun.", color=(255, 110, 90))
            self.respawn_player()

    def update_naval_combat(self, dt):
        self.damage_cooldown = max(0.0, self.damage_cooldown - dt)
        self.arrow_cooldown = max(0.0, self.arrow_cooldown - dt)
        hits = self.naval.update(dt, self.player, self.is_sailing,
                                 lambda x, y: can_stand(self.world, x, y, True))
        if hits and self.damage_cooldown <= 0:
            damage = min(4, hits * 2)
            self.health -= damage
            self.damage_cooldown = .75
            self.boat_speed *= .45
            self.add_toast(f"Korsan topu isabet etti! -{damage} can", color=(255, 95, 75))

        for arrow in self.arrows:
            arrow["x"] += arrow["vx"] * dt
            arrow["y"] += arrow["vy"] * dt
            arrow["life"] -= dt
            for ship in self.naval.ships:
                if (ship.alive and ship.kind == "pirate"
                        and math.hypot(arrow["x"] - ship.x, arrow["y"] - ship.y) < .85):
                    ship.health -= 2
                    ship.hit_flash = .16
                    arrow["life"] = 0
                    if ship.health <= 0:
                        ship.alive = False
                        self.add_resource(self.loot_rng.choice(("Odun", "Tas", "Balik")), 3)
                        self.add_toast("Korsan gemisi batırıldı!", color=(255, 210, 90))
                    break
            if arrow["life"] > 0:
                self.hit_remote_player_with_arrow(arrow)
        self.arrows = [arrow for arrow in self.arrows if arrow["life"] > 0]

        for ship in self.naval.ships:
            if (ship.alive and ship.kind == "pirate"
                    and math.hypot(self.player.x - ship.x, self.player.y - ship.y) < 1.0
                    and self.damage_cooldown <= 0):
                self.health -= 1
                self.damage_cooldown = .7
                self.boat_speed *= -.25
                self.add_toast("Korsan gemisi tekneye çarptı!", color=(255, 105, 85))
                break

        if self.health <= 0:
            self.health = self.max_health
            self.arrows.clear()
            self.is_sailing = False
            self.boat_speed = 0.0
            self.add_toast("Teknen battı! Başka bir adada uyandın.", color=(255, 100, 85))
            self.respawn_player()

    def trade_with_merchant_ship(self):
        merchant = self.naval.nearby_merchant(self.player)
        if merchant is None:
            return False
        if self.inventory.get("Balik", 0) < 2:
            self.add_toast("Tüccar: Takas için 2 Balık getir.", color=(130, 220, 245))
            return True
        self.inventory["Balik"] -= 2
        item = self.loot_rng.choice(("Odun", "Tas", "Tahil"))
        self.add_resource(item, 4)
        self.health = min(self.max_health, self.health + 2)
        self.add_toast(f"Deniz ticareti: 2 Balık → 4 {item}", color=(120, 235, 210))
        return True

    def update_wind_sailing(self, dt, mouse_pos):
        self.wind_timer += dt
        self.wind_angle += math.sin(self.wind_timer * .23) * dt * .08
        self.wind_strength = 0.85 + .35 * (0.5 + 0.5 * math.sin(self.wind_timer * .41))
        mx, my = mouse_pos
        self.sail_angle = math.atan2(my - GAME_HEIGHT / 2, mx - GAME_WIDTH / 2)
        capture = max(0.0, math.cos(self.wind_angle - self.sail_angle)) if self.sail_raised else 0.0
        self.boat_speed = min(8.0, self.boat_speed + capture * self.wind_strength * 22.0 * dt)

    def set_map_open(self, opened):
        self.map_open = opened
        self.moving = False
        self.held_direction_keys.clear()
        self.last_direction_tap = dict.fromkeys(self.last_direction_tap, -10.0)
        # Do not resume a queued dash when the chart is dismissed.
        self.dash_timer = 0.0
        self.leaves.clear()

    def ambient_leaves_enabled(self):
        return not (self.paused or self.map_open or self.inventory_open or self.trade_open
                    or self.dialogue.active or self.execution is not None
                    or self.fishing.active or self.fishing.zoom_level > 1.01
                    or self.grain_game.active or self.stone_game.active or self.wood_game.active
                    or (self.winner is not None and not self.victory_dismissed))

    def handle_event(self, event, logical_pos) -> str:
        # Victory / Defeat Modal Handling
        if self.winner is not None and not self.victory_dismissed:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                self.victory_dismissed = True
                return None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.victory_continue_rect.collidepoint(logical_pos):
                    self.victory_dismissed = True
                    return None
                elif self.victory_menu_rect.collidepoint(logical_pos):
                    return "MENU"
            return None

        if self.dialogue.active:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_e, pygame.K_RETURN, pygame.K_SPACE):
                self.dialogue.advance()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.dialogue.active = False
            return None

        # In-game pause modal
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

        # The chart owns input until closed; it never opens the pause menu.
        if self.map_open:
            if (event.type == pygame.KEYDOWN and event.key in (pygame.K_m, pygame.K_ESCAPE)
                    and not getattr(event, "repeat", False)):
                self.set_map_open(False)
            elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                  and self.map_ui.close_rect.collidepoint(logical_pos)):
                self.set_map_open(False)
            return None

        # Inventory Modal Handling
        if self.inventory_open:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_i, pygame.K_TAB):
                self.inventory_open = False
                return None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.inventory_close_rect.collidepoint(logical_pos):
                    self.inventory_open = False
                    return None
                elif self.conquer_action_rect.collidepoint(logical_pos):
                    self.try_capture_island()
                    return None
            return None

        # Trade Modal Handling
        if self.trade_open:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_t):
                    self.trade_open = False
                    return None
                elif event.key == pygame.K_RETURN:
                    self.submit_trade_proposal()
                    return None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.trade_close_rect.collidepoint(logical_pos):
                    self.trade_open = False
                    return None
                elif self.trade_send_btn.collidepoint(logical_pos):
                    self.submit_trade_proposal()
                    return None
                for action, val, rect in self.trade_action_rects:
                    if rect.collidepoint(logical_pos):
                        if action == 'select_partner':
                            self.trade_selected_partner = val
                        elif action == 'offer_plus':
                            have = self.inventory.get(val, 0)
                            if self.trade_offer.get(val, 0) < have:
                                self.trade_offer[val] = self.trade_offer.get(val, 0) + 1
                        elif action == 'offer_minus':
                            if self.trade_offer.get(val, 0) > 0:
                                self.trade_offer[val] -= 1
                        elif action == 'req_plus':
                            self.trade_request[val] = self.trade_request.get(val, 0) + 1
                        elif action == 'req_minus':
                            if self.trade_request.get(val, 0) > 0:
                                self.trade_request[val] -= 1
                        elif action == 'accept_trade':
                            if self.network and self.network.connected:
                                # Find trade to deduct requester items and add offer items
                                t = next((x for x in self.network.trades if x.get('id') == val), None)
                                if t and all(self.inventory.get(k, 0) >= v for k, v in t.get('request', {}).items()):
                                    for k, v in t.get('request', {}).items():
                                        self.inventory[k] -= v
                                    for k, v in t.get('offer', {}).items():
                                        self.inventory[k] = self.inventory.get(k, 0) + v
                                    self.processed_trades.add(val)
                                    self.network.accept_trade(val)
                                    self.add_toast("Ticaret kabul edildi! Kaynaklar takas edildi.", color=(120, 240, 130))
                        elif action == 'cancel_trade':
                            if self.network and self.network.connected:
                                self.network.cancel_trade(val)
                                self.add_toast("Ticaret teklifi iptal edildi.")
                        return None
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

        direction_keys = {
            pygame.K_w: ("up", (0, -1)), pygame.K_UP: ("up", (0, -1)),
            pygame.K_s: ("down", (0, 1)), pygame.K_DOWN: ("down", (0, 1)),
            pygame.K_a: ("left", (-1, 0)), pygame.K_LEFT: ("left", (-1, 0)),
            pygame.K_d: ("right", (1, 0)), pygame.K_RIGHT: ("right", (1, 0)),
        }
        if event.type == pygame.KEYUP and event.key in direction_keys:
            self.held_direction_keys.discard(event.key)

        if event.type == pygame.KEYDOWN:
            if (event.key in direction_keys and not getattr(event, "repeat", False)
                    and not self.map_open and not self.is_sailing):
                direction_name, _ = direction_keys[event.key]
                self.held_direction_keys.add(event.key)
                if self.game_time - self.last_direction_tap[direction_name] <= .28:
                    dash_x = dash_y = 0
                    for held_key in self.held_direction_keys:
                        _, (held_x, held_y) = direction_keys[held_key]
                        dash_x += held_x
                        dash_y += held_y
                    self.start_dash((dash_x, dash_y))
                    self.last_direction_tap[direction_name] = -10.0
                else:
                    self.last_direction_tap[direction_name] = self.game_time
            if self.is_sailing and not self.map_open:
                if event.key == pygame.K_a:
                    self.boat_speed += 0.65
                    self.turn_speed -= 2.0
                elif event.key == pygame.K_d:
                    self.boat_speed += 0.65
                    self.turn_speed += 2.0
                elif event.key == pygame.K_r:
                    self.sail_raised = not self.sail_raised
                    state = "açıldı" if self.sail_raised else "indirildi"
                    self.add_toast(f"Yelken {state}. [R]", color=(120, 220, 245))

            if event.key == pygame.K_m and not getattr(event, "repeat", False):
                self.set_map_open(True)
            elif event.key in (pygame.K_i, pygame.K_TAB) and not self.map_open:
                self.inventory_open = not self.inventory_open
                if self.inventory_open:
                    self.trade_open = False
            elif event.key == pygame.K_t and not self.map_open:
                self.trade_open = not self.trade_open
                if self.trade_open:
                    self.inventory_open = False
            elif event.key == pygame.K_c and not self.map_open and not self.is_sailing:
                self.try_capture_island()
            elif event.key == pygame.K_ESCAPE:
                if self.map_open:
                    self.map_open = False
                else:
                    self.paused = True
            elif event.key == pygame.K_e and not self.map_open and self.is_sailing:
                self.trade_with_merchant_ship()
            elif event.key == pygame.K_e and not self.map_open and not self.is_sailing:
                npc = self.quest_system.nearby_npc(self.player)
                port, distance = self.nearby_port()
                if npc:
                    self.quest_system.interact(npc, self.dialogue, self.grant_quest_reward,
                                               None, self.complete_quest_rescue)
                elif port and distance < 1.6:
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

            elif event.key in (pygame.K_j, pygame.K_SPACE) and not self.map_open and not self.is_sailing:
                if self.equipment.get("sword"):
                    self.combat.start_attack("dash" if self.dash_timer > 0 else "normal")
            elif event.key == pygame.K_k and not self.map_open and not self.is_sailing:
                if self.equipment.get("sword"):
                    self.combat.start_attack("crouch")

            elif event.key == pygame.K_f and not self.map_open:
                port, distance = self.nearby_port()
                if port and distance < 2.5:
                    self.is_sailing = not self.is_sailing
                    if self.is_sailing:
                        self.player.x = port.x + port.dx * 1.5 + 0.5
                        self.player.y = port.y + port.dy * 1.5 + 0.5
                        self.boat_speed = 0.0
                        self.turn_speed = 0.0
                        self.sail_raised = True
                    else:
                        self.player.x = port.spawn[0]
                        self.player.y = port.spawn[1]
                        self.sail_raised = True

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.map_button.collidepoint(logical_pos):
                self.set_map_open(not self.map_open)
            elif self.inventory_button.collidepoint(logical_pos) and not self.map_open:
                self.inventory_open = not self.inventory_open
                if self.inventory_open:
                    self.trade_open = False
            elif self.trade_button.collidepoint(logical_pos) and not self.map_open:
                self.trade_open = not self.trade_open
                if self.trade_open:
                    self.inventory_open = False
            elif any(rect.collidepoint(logical_pos) for _, rect in self.hud.items):
                return None
            elif not self.map_open and not self.is_sailing and self.hud_conquer_rect.collidepoint(logical_pos):
                self.try_capture_island()
            elif not self.map_open and self.equipment.get("bow"):
                self.fire_arrow(logical_pos)

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

    def update_characters(self, dt, speed=4.5):
        self.player_animation.update(dt, self.moving and not self.is_sailing and not self.paused,
                                     self.facing, speed)
        players = {}
        if self.network and self.network.connected:
            with self.network.lock:
                players = {pid: dict(player) for pid, player in self.network.other_players.items()}
        for pid in list(self.remote_animations):
            if pid not in players:
                del self.remote_animations[pid]
                self.remote_combats.pop(pid, None)
        for pid, player in players.items():
            animation = self.remote_animations.setdefault(pid, CharacterAnimator())
            x, y = player.get('x', 0), player.get('y', 0)
            speed = PLAYER_SPEED
            if 0 <= x < COLS and 0 <= y < ROWS:
                speed *= movement_multiplier(self.world, pygame.Vector2(x, y), False)
            animation.update(dt, player.get('moving', False) and not player.get('sailing', False),
                             player.get('facing', 'down'), speed)
            remote_combat = self.remote_combats.setdefault(pid, CombatSystem())
            attack_kind = player.get('attack_kind')
            if attack_kind in remote_combat.ATTACKS:
                remote_combat.state = 'attacking'
                remote_combat.attack_kind = attack_kind
                remote_combat.combo_step = max(1, player.get('combo_step', 1))
                remote_combat.timer = player.get('attack_timer', 0.0) * remote_combat.attack_profile()['duration']
            else:
                remote_combat.state = 'idle'
                remote_combat.attack_kind = None

    def update(self, dt: float, logical_mouse_pos: tuple):
        if not self.paused:
            self.game_time += max(0.0, dt)
        if self.paused:
            self.moving = False
        # Pump shared resources even while the pause modal is open.
        self.sync_resources(dt)
        self.net_timer += dt
        if self.net_timer >= 0.05 and self.network:
            attack_kind = self.combat.attack_kind if self.combat.attacking else None
            attack_progress = (self.combat.timer / self.combat.attack_profile()['duration']
                               if self.combat.attacking else 0.0)
            self.network.send_and_receive(self.player.x, self.player.y, self.facing,
                                          self.moving, self.is_sailing, self.boat_angle,
                                          self.sail_angle, self.sail_raised, attack_kind,
                                          min(1.0, attack_progress), self.combat.combo_step)
            self.net_timer = 0.0
            self.sync_resources(0)
        if (self.network and self.network.connected
                and getattr(self.network, 'spawn_revision', 0) > self.spawn_revision):
            with self.network.lock:
                if self.network.deaths > self.network_deaths:
                    self.add_toast(f"Oyuncu {self.network.last_hit_by} seni yendi; başka adada doğdun!",
                                   color=(255, 95, 90))
                self.network_deaths = self.network.deaths
                self.player.update(self.network.spawn)
                self.spawn_island = self.network.spawn_island
                self.spawn_revision = self.network.spawn_revision
                self.previous_pos = tuple(self.player)
                self.cam_x, self.cam_y = get_local_camera(self.player)
                self.health = self.max_health
                self.is_sailing = False
                self.sail_raised = True
        if (self.network and self.network.connected
                and getattr(self.network, 'combat_revision', 0) > self.network_combat_revision):
            with self.network.lock:
                old_health = self.health
                self.health = min(self.health, self.network.health)
                self.network_combat_revision = self.network.combat_revision
                attacker = self.network.last_hit_by
                if self.health < old_health:
                    self.damage_cooldown = max(self.damage_cooldown, .45)
                    self.add_toast(f"Oyuncu {attacker} sana vurdu! -{old_health - self.health} can",
                                   color=(255, 95, 90))
        if self.paused:
            self.update_characters(dt)
            return

        if self.player_exhaust_timer > 0:
            self.player_exhaust_timer -= dt
        self.dash_cooldown = max(0.0, self.dash_cooldown - dt)
        for effect in self.dash_effects:
            effect["life"] -= dt
        self.dash_effects = [effect for effect in self.dash_effects if effect["life"] > 0]
        self.pvp_hit_flashes = {pid: life - dt for pid, life in self.pvp_hit_flashes.items()
                                if life - dt > 0}
        if self.execution is not None:
            self.execution["timer"] += dt
            if self.execution["timer"] >= self.execution["duration"]:
                self.execution = None

        self.dialogue.update(dt)
        if not self.is_sailing and not self.map_open and not self.dialogue.active:
            self.update_world_combat(dt)
            self.naval.update(dt, self.player, False,
                              lambda x, y: can_stand(self.world, x, y, True))
        elif self.is_sailing and not self.map_open:
            self.update_naval_combat(dt)

        # Camera
        target_cam_x, target_cam_y = get_local_camera(self.player, self.fishing)
        self.cam_x += (target_cam_x - self.cam_x) * 4 * dt
        self.cam_y += (target_cam_y - self.cam_y) * 4 * dt

        # Player Movement
        any_minigame = (self.fishing.active or self.grain_game.active or self.stone_game.active
                        or self.wood_game.active or self.dialogue.active or self.execution is not None)
        if not self.map_open and not any_minigame:
            if self.is_sailing:
                self.update_wind_sailing(dt, logical_mouse_pos)
                drag = 0.995 if self.sail_raised else 0.985
                self.boat_speed *= drag ** (dt * 60.0)
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
                if self.update_dash_movement(dt):
                    pass
                elif self.player_exhaust_timer <= 0:
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
                if res is False:
                    self.add_toast("Odun kesme başarısız: süre doldu!", color=(255, 110, 90))
                elif isinstance(res, (int, float)) and not isinstance(res, bool) and res > 0:
                    self.player_exhaust_timer = res
            self.stone_game.update(dt)

        self.leaves.update(dt, self.player, (self.cam_x, self.cam_y),
                           enabled=self.ambient_leaves_enabled())

        dx = self.player.x - self.previous_pos[0]
        dy = self.player.y - self.previous_pos[1]
        self.moving = abs(dx) + abs(dy) > 0.0001
        if self.moving:
            self.facing = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up")
        self.previous_pos = (self.player.x, self.player.y)
        self.update_characters(dt, math.hypot(dx, dy) / max(dt, 1e-6))

        # Update Island Income, floating text & toasts
        self.update_island_income(dt)
        self.floating_texts = [ft for ft in self.floating_texts if ft.update(dt)]
        self.toasts = [t for t in self.toasts if t.update(dt)]

        # Sync island owners and victory status with multiplayer network
        if self.network and self.network.connected:
            with self.network.lock:
                for idx, o in self.network.island_owners.items():
                    if self.island_owners.get(idx) != o:
                        old_owner = self.island_owners.get(idx)
                        self.island_owners[idx] = o
                        if 0 <= idx < len(self.world.islands):
                            self.world.islands[idx].owner = o
                        if old_owner == self.my_player_id() and o != self.my_player_id():
                            self.add_toast(f"BİLGİ: {self.world.islands[idx].name} Oyuncu {o} tarafından kurtarıldı!", color=(130, 220, 150))
                if self.network.winner is not None and self.winner is None:
                    self.winner = self.network.winner
                self.capture_count = getattr(self.network, 'capture_count', len(self.island_owners))
            self.sync_trades_and_execute()

    def render(self, screen: pygame.Surface, logical_mouse_pos: tuple):
        camera_x, camera_y = round(self.cam_x), round(self.cam_y)
        if self.combat.impact_pulse > 0 and not self.is_sailing:
            shake_strength = (self.combat.impact_pulse / .16) * (7 if self.combat.combo_step >= 3 else 4)
            camera_x += round(math.sin(self.game_time * 173.0) * shake_strength)
            camera_y += round(math.cos(self.game_time * 211.0) * shake_strength * .65)
        screen.fill((32, 39, 41))

        if self.map_open:
            self.map_ui.draw_full(screen, logical_mouse_pos, self.player, self.network,
                                  self.island_owners, self.my_player_id())
            self.draw_victory_ui(screen, logical_mouse_pos)
            return
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
                "animation": self.player_animation,
                "combat": self.combat,
                "boat_angle": self.boat_angle,
                "sail_angle": self.sail_angle,
                "sail_raised": self.sail_raised,
                "health": self.health,
                "max_health": self.max_health,
                "player_id": self.my_player_id(),
            }]

            if self.network and self.network.connected:
                with self.network.lock:
                    for pid, pdata in self.network.other_players.items():
                        if pid not in self.remote_animations:
                            self.remote_animations[pid] = CharacterAnimator()
                            self.remote_animations[pid].update(0, pdata.get("moving", False), pdata.get("facing", "down"))
                        other_screen_pos = (round(pdata["x"] * LOCAL_TILE_SIZE) - camera_x, round(pdata["y"] * LOCAL_TILE_SIZE) - camera_y)
                        players_to_draw.append({
                            "y": pdata["y"],
                            "pos": other_screen_pos,
                            "moving": pdata.get("moving", False),
                            "facing": pdata.get("facing", "down"),
                            "color": (60, 100, 150),
                            "is_sailing": pdata.get("sailing", False),
                            "is_me": False,
                            "animation": self.remote_animations[pid],
                            "combat": self.remote_combats.get(pid),
                            "boat_angle": pdata.get("boat_angle", 0.0),
                            "sail_angle": pdata.get("sail_angle", 0.0),
                            "sail_raised": pdata.get("sail_raised", True),
                            "health": pdata.get("health", 8),
                            "max_health": pdata.get("max_health", 8),
                            "player_id": pid,
                        })

            # One foot-position sort for ALL tall objects, characters, and village flags.
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

            # Add island banners/flags at village centers
            for idx, island in enumerate(self.world.islands):
                if island.village:
                    fx, fy = island.village.center[0] - 1.5, island.village.center[1] + 0.5
                    if (camera_x - 60 <= fx * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 60
                            and camera_y - 60 <= fy * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 80):
                        objects.append((fy, "flag", (idx, fx, fy)))

            for npc in self.quest_system.npcs:
                objects.append((npc.y, "npc", npc))
            for monster in self.quest_system.monsters:
                if monster.alive and (camera_x - 80 <= monster.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 80
                                      and camera_y - 80 <= monster.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 80):
                    objects.append((monster.y, "monster", monster))
            for ship in self.naval.ships:
                if ship.alive and (camera_x - 100 <= ship.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 100
                                   and camera_y - 100 <= ship.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 100):
                    objects.append((ship.y, "sea_ship", ship))

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
                elif kind == "flag":
                    idx, fx, fy = obj
                    owner = self.island_owners.get(idx)
                    draw_island_flag(screen, round(fx * LOCAL_TILE_SIZE) - camera_x,
                                     round(fy * LOCAL_TILE_SIZE) - camera_y, owner, self.my_player_id())
                elif kind == "npc":
                    draw_villager(screen, obj, camera_x, camera_y)
                elif kind == "monster":
                    draw_monster(screen, obj, camera_x, camera_y)
                elif kind == "sea_ship":
                    draw_sea_ship(screen, obj, camera_x, camera_y, self.sailboat_hull, self.small_font)
                else:
                    p = obj
                    p["pos"] = tuple(round(v) for v in p["pos"])
                    draw_pos = p["pos"]
                    if (p["is_me"] and self.combat.attacking
                            and self.combat.attack_kind == "crouch"):
                        draw_pos = (draw_pos[0], draw_pos[1] + 7)
                    draw_player(screen, draw_pos, p["moving"], p["facing"], p["color"], p["is_sailing"],
                                p["boat_angle"], self.atlas, self.character_sheet, p["animation"],
                                self.sailboat_hull, p["sail_angle"], p["sail_raised"])
                    if not p["is_sailing"] and p.get("combat"):
                        draw_sword_attack(screen, draw_pos, p["facing"], p["combat"])
                    if not p["is_me"]:
                        if self.pvp_hit_flashes.get(str(p["player_id"]), 0) > 0:
                            pygame.draw.circle(screen, (255, 240, 155), p["pos"], 30, 4)
                        tag = self.small_font.render("Diger Oyuncu", True, (255, 255, 255))
                        screen.blit(tag, (p["pos"][0] - 25, p["pos"][1] - 55))
                        hp_width = round(42 * max(0, p["health"]) / max(1, p["max_health"]))
                        pygame.draw.rect(screen, (42, 20, 24), (p["pos"][0] - 21, p["pos"][1] - 63, 42, 5))
                        pygame.draw.rect(screen, (220, 65, 65),
                                         (p["pos"][0] - 21, p["pos"][1] - 63, hp_width, 5))

            draw_dash_effects(screen, self.dash_effects, camera_x, camera_y)
            draw_execution_effect(screen, self.execution, camera_x, camera_y, self.font)

            for arrow in self.arrows:
                ax = round(arrow["x"] * LOCAL_TILE_SIZE) - camera_x
                ay = round(arrow["y"] * LOCAL_TILE_SIZE) - camera_y
                angle = math.atan2(arrow["vy"], arrow["vx"])
                tail = (round(ax - math.cos(angle) * 16), round(ay - math.sin(angle) * 16))
                pygame.draw.line(screen, (235, 215, 165), tail, (ax, ay), 3)
                pygame.draw.circle(screen, (75, 62, 47), (ax, ay), 2)
            for ball in self.naval.cannonballs:
                bx = round(ball["x"] * LOCAL_TILE_SIZE) - camera_x
                by = round(ball["y"] * LOCAL_TILE_SIZE) - camera_y
                pygame.draw.circle(screen, (255, 125, 55), (bx, by), 7)
                pygame.draw.circle(screen, (255, 225, 125), (bx, by), 3)
                pygame.draw.circle(screen, (42, 35, 34), (bx, by), 7, 2)

            # ---------------------------------------------------------------
            # 8. ATMOSPHERIC PARTICLES & MINIGAMES UI
            # ---------------------------------------------------------------
            if self.ambient_leaves_enabled():
                self.leaves.draw(screen, camera_x, camera_y)
            self.fishing.draw_world(screen, camera_x, camera_y, self.player)

            if self.fishing.zoom_level > 1.01:
                zoom = self.fishing.zoom_level
                w, h = GAME_WIDTH, GAME_HEIGHT
                new_w, new_h = int(w / zoom), int(h / zoom)
                sub_rect = pygame.Rect((w - new_w) // 2, (h - new_h) // 2, new_w, new_h)
                zoomed_surface = pygame.transform.scale(screen.subsurface(sub_rect).copy(), (w, h))
                screen.blit(zoomed_surface, (0, 0))

            if self.execution is not None:
                progress = min(1.0, self.execution["timer"] / self.execution["duration"])
                cinematic = math.sin(progress * math.pi)
                zoom = 1.0 + cinematic * .42
                crop_w, crop_h = max(1, round(GAME_WIDTH / zoom)), max(1, round(GAME_HEIGHT / zoom))
                focus_x = round(self.execution["x"] * LOCAL_TILE_SIZE) - camera_x
                focus_y = round(self.execution["y"] * LOCAL_TILE_SIZE) - camera_y
                crop_x = max(0, min(GAME_WIDTH - crop_w, focus_x - crop_w // 2))
                crop_y = max(0, min(GAME_HEIGHT - crop_h, focus_y - crop_h // 2))
                crop = screen.subsurface((crop_x, crop_y, crop_w, crop_h)).copy()
                screen.blit(pygame.transform.smoothscale(crop, (GAME_WIDTH, GAME_HEIGHT)), (0, 0))
                bar_height = round(28 * cinematic)
                if bar_height:
                    pygame.draw.rect(screen, (10, 8, 14), (0, 0, GAME_WIDTH, bar_height))
                    pygame.draw.rect(screen, (10, 8, 14),
                                     (0, GAME_HEIGHT - bar_height, GAME_WIDTH, bar_height))

            self.fishing.draw_ui(screen, self.font)
            self.grain_game.draw_ui(screen, self.font, logical_mouse_pos)
            self.stone_game.draw_ui(screen, self.font)
            self.wood_game.draw_ui(screen, self.font)
            draw_dialogue_box(screen, self.dialogue, self.font, self.small_font)

            if self.player_exhaust_timer > 0:
                draw_text(screen, self.font, f"YORGUNLUK! ({self.player_exhaust_timer:.1f}s)",
                          (GAME_WIDTH // 2 - 70, GAME_HEIGHT // 2 - 50), (255, 50, 50))

        # Bottom status bar
        pygame.draw.rect(screen, (32, 39, 41), (0, GAME_HEIGHT - 30, GAME_WIDTH, 30))
        px, py = int(self.player.x), int(self.player.y)
        owner_idx = self.world.owners[py][px] if 0 <= px < COLS and 0 <= py < ROWS else -1
        current_island = self.world.islands[owner_idx] if owner_idx >= 0 else None
        if current_island:
            isl_owner = self.island_owners.get(owner_idx)
            if isl_owner == self.my_player_id():
                location = f"{current_island.name} [Senin Adan]"
            elif isl_owner is not None:
                location = f"{current_island.name} [Oyuncu {isl_owner}]"
            else:
                location = f"{current_island.name} [Sahipsiz]"
        else:
            location = "Deniz"

        net_status = "Tek Oyuncu (Cevrimdisi)"
        if self.network and self.network.connected:
            net_status = f"Cevrimici: {len(self.network.other_players) + 1} Oyuncu"

        info = f"{location} | {net_status}"
        port, distance = self.nearby_port()
        if port is not None and distance < 2.5:
            info += " | E: balik tut | F: gemiye bin/in"
        elif self.is_sailing:
            info += " | Fare: Yelken Açısı | R: Yelken İndir/Kaldır | A/D: Kürek/Manevra | Sol Tık: Yay"
        else:
            npc = self.quest_system.nearby_npc(self.player)
            if npc:
                info += f" | E: {npc.name} ile konuş"
            else:
                info += " | WASD: Yürü | Çift Yön: 8-Yön Dash | Dash+J: Dalga | J/BOŞLUK: Kılıç | K: Eğilme"

        draw_text(screen, self.small_font, info, (12, GAME_HEIGHT - 23), (229, 219, 193))

        # Combat/equipment and sailing telemetry.
        pygame.draw.rect(screen, (40, 22, 22), (14, 58, 180, 17), border_radius=4)
        pygame.draw.rect(screen, (190, 55, 52), (14, 58, round(180 * self.health / self.max_health), 17), border_radius=4)
        draw_text(screen, self.small_font, f"CAN {self.health}/{self.max_health}", (20, 58), (255, 238, 220))
        gear = f"Kılıç: {'✓' if self.equipment['sword'] else '—'}  Yay: {'✓' if self.equipment['bow'] else '—'}"
        if self.network and self.network.connected and getattr(self.network, 'pvp_supported', False):
            gear += f"  PvP K/D: {self.network.kills}/{self.network.deaths}"
        draw_text(screen, self.small_font, gear, (14, 79), (245, 218, 150))
        if not self.is_sailing:
            dash_ready = self.dash_cooldown <= 0
            dash_text = "DASH HAZIR [Çift Yön]" if dash_ready else f"DASH {self.dash_cooldown:.1f}s"
            draw_text(screen, self.small_font, dash_text, (14, 99),
                      (105, 235, 255) if dash_ready else (145, 155, 165))
        if self.is_sailing:
            wx, wy = GAME_WIDTH - 72, self.map_button.bottom + 46
            pygame.draw.circle(screen, (25, 30, 36), (wx, wy), 34)
            pygame.draw.circle(screen, (190, 205, 210), (wx, wy), 34, 2)
            wind_end = (round(wx + math.cos(self.wind_angle) * 27), round(wy + math.sin(self.wind_angle) * 27))
            sail_end = (round(wx + math.cos(self.sail_angle) * 22), round(wy + math.sin(self.sail_angle) * 22))
            pygame.draw.line(screen, (105, 205, 255), (wx, wy), wind_end, 4)
            pygame.draw.line(screen, (255, 210, 90) if self.sail_raised else (115, 115, 110),
                             (wx, wy), sail_end, 3)
            draw_text(screen, self.small_font, f"Rüzgâr {self.wind_strength:.1f}", (wx - 42, wy + 38), (220, 235, 240))
            sail_status = "YELKEN AÇIK" if self.sail_raised else "YELKEN İNDİ [R]"
            draw_text(screen, self.small_font, sail_status, (wx - 52, wy + 57),
                      (255, 220, 110) if self.sail_raised else (185, 190, 190))

        # Pixel resource strip and the always-visible world overview.
        if not self.map_open:
            self.map_ui.draw_mini(screen, logical_mouse_pos, self.player, self.network,
                                  self.island_owners, self.my_player_id(),
                                  (self.cam_x / LOCAL_TILE_SIZE, self.cam_y / LOCAL_TILE_SIZE,
                                   GAME_WIDTH / LOCAL_TILE_SIZE, GAME_HEIGHT / LOCAL_TILE_SIZE))
            my_count = sum(owner == self.my_player_id() for owner in self.island_owners.values())
            inf_pct = int(round((self.get_inflation_rate() - 1.0) * 100))
            self.hud.draw(screen, logical_mouse_pos, self.inventory, my_count, self.WINNING_COUNT, inf_pct)

            # Contextual Island Capture Prompt (Center Bottom)
            idx, island, owner = self.current_island_info()
            if idx is not None and not self.is_sailing:
                my_id = self.my_player_id()
                if owner != my_id:
                    is_enemy = False
                    cost = self.get_current_island_cost(False)
                    afford = self.can_afford(cost)
                    hov = self.hud_conquer_rect.collidepoint(logical_mouse_pos)
                    inf_pct = int(round((self.get_inflation_rate() - 1.0) * 100))
                    inf_str = f" [Enflasyon +%{inf_pct}]" if inf_pct > 0 else ""

                    if afford:
                        bar_bg = (120, 60, 28) if hov else (80, 38, 20)
                        bar_border = (255, 215, 60)
                        txt_col = (255, 240, 180)
                        lbl = f"🐺 {island.name} Kurtarma Erzağı [C] ({cost['Odun']}O {cost['Tas']}T {cost['Tahil']}H {cost['Balik']}B){inf_str}"
                    else:
                        bar_bg = (48, 25, 20)
                        bar_border = (120, 60, 50)
                        txt_col = (210, 140, 140)
                        lbl = f"🐺 {island.name} Kurtarma (Kışlık Kaynak Yetersiz){inf_str}"

                    pygame.draw.rect(screen, bar_bg, self.hud_conquer_rect, border_radius=6)
                    pygame.draw.rect(screen, bar_border, self.hud_conquer_rect, width=1, border_radius=6)
                    b_surf = self.small_font.render(lbl, True, txt_col)
                    screen.blit(b_surf, b_surf.get_rect(center=self.hud_conquer_rect.center))
                else:
                    badge_rect = pygame.Rect(GAME_WIDTH // 2 - 160, GAME_HEIGHT - 74, 320, 38)
                    pygame.draw.rect(screen, (25, 40, 20, 220), badge_rect, border_radius=6)
                    pygame.draw.rect(screen, (100, 200, 90), badge_rect, width=1, border_radius=6)
                    b_surf = self.small_font.render(f"✓ {island.name} Kurtarıldı (Köy Güvende)", True, (180, 240, 160))
                    screen.blit(b_surf, b_surf.get_rect(center=badge_rect.center))

        # Floating pickup texts
        for ft in self.floating_texts:
            ft.draw(screen, self.small_font)

        # Floating toast messages
        for i, t in enumerate(self.toasts):
            t.draw(screen, self.font, y_offset=i * 38)

        # Full Detailed Inventory Center Modal
        self.draw_inventory_ui(screen, logical_mouse_pos)

        # Player-to-Player Trade Center Modal
        self.draw_trade_ui(screen, logical_mouse_pos)

        # Victory or Defeat Modal
        self.draw_victory_ui(screen, logical_mouse_pos)

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

    def draw_inventory_ui(self, screen, logical_mouse_pos):
        if not self.inventory_open:
            return

        overlay = pygame.Surface((GAME_WIDTH, GAME_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 6, 4, 190))
        screen.blit(overlay, (0, 0))

        pw, ph = 740, 500
        px = (GAME_WIDTH - pw) // 2
        py = (GAME_HEIGHT - ph) // 2

        pygame.draw.rect(screen, (32, 20, 15), (px, py, pw, ph), border_radius=10)
        pygame.draw.rect(screen, (190, 145, 80), (px, py, pw, ph), width=2, border_radius=10)
        pygame.draw.rect(screen, (85, 55, 30), (px + 3, py + 3, pw - 6, ph - 6), width=1, border_radius=8)

        # Header
        header_rect = pygame.Rect(px + 4, py + 4, pw - 8, 38)
        pygame.draw.rect(screen, (52, 28, 20), header_rect, border_top_left_radius=8, border_top_right_radius=8)
        header_title = self.font.render("ENVANTER & ADA KURTARMA MERKEZİ", True, COLOR_TEXT_GOLD)
        screen.blit(header_title, (px + 18, py + 12))

        # Close Button
        self.inventory_close_rect = pygame.Rect(px + pw - 38, py + 7, 28, 26)
        close_hover = self.inventory_close_rect.collidepoint(logical_mouse_pos)
        pygame.draw.rect(screen, (130, 40, 30) if close_hover else (80, 28, 20), self.inventory_close_rect, border_radius=4)
        pygame.draw.rect(screen, (190, 145, 80), self.inventory_close_rect, width=1, border_radius=4)
        x_txt = self.font.render("X", True, (255, 235, 215))
        screen.blit(x_txt, x_txt.get_rect(center=self.inventory_close_rect.center))

        # Left Column: Material Inventory
        col1_x, col1_w = px + 18, 330
        col1_y = py + 52
        pygame.draw.rect(screen, (42, 26, 19), (col1_x, col1_y, col1_w, ph - 70), border_radius=6)
        pygame.draw.rect(screen, (140, 95, 50), (col1_x, col1_y, col1_w, ph - 70), width=1, border_radius=6)

        sec1_title = self.font.render("TOPLANAN KAYNAKLAR", True, (255, 220, 130))
        screen.blit(sec1_title, (col1_x + 14, col1_y + 12))

        materials_info = [
            ("Odun", "Ağaçlardan toplanır.", "Köyün kışlık yakacak ihtiyacı.", (235, 155, 75)),
            ("Tas", "Kayalardan cikarilir.", "Saglam yapilar ve savunma kaynagi.", (205, 215, 225)),
            ("Tahil", "Ekin tarlalarindan bicilir.", "Ada halkinin gida ihtiyaci.", (250, 215, 70)),
            ("Balik", "Iskelelerden tutulur.", "Deniz ticareti ve ozel erzak.", (110, 215, 255)),
        ]

        card_y = col1_y + 42
        for name, desc1, desc2, col in materials_info:
            card_rect = pygame.Rect(col1_x + 10, card_y, col1_w - 20, 84)
            pygame.draw.rect(screen, (30, 18, 14), card_rect, border_radius=5)
            pygame.draw.rect(screen, (85, 55, 30), card_rect, width=1, border_radius=5)

            pygame.draw.rect(screen, col, (card_rect.x + 8, card_rect.y + 10, 16, 16), border_radius=3)

            name_surf = self.font.render(name, True, col)
            count = self.inventory.get(name, 0)
            count_surf = self.font.render(f"Adet: {count}", True, (255, 245, 210))

            screen.blit(name_surf, (card_rect.x + 32, card_rect.y + 9))
            screen.blit(count_surf, (card_rect.right - count_surf.get_width() - 12, card_rect.y + 9))

            d1 = self.small_font.render(desc1, True, (200, 190, 175))
            d2 = self.small_font.render(desc2, True, (170, 160, 145))
            screen.blit(d1, (card_rect.x + 12, card_rect.y + 36))
            screen.blit(d2, (card_rect.x + 12, card_rect.y + 56))

            card_y += 94

        # Right Column: Conquest Status & Objectives
        col2_x, col2_w = px + 360, 360
        col2_y = py + 52
        pygame.draw.rect(screen, (42, 26, 19), (col2_x, col2_y, col2_w, ph - 70), border_radius=6)
        pygame.draw.rect(screen, (140, 95, 50), (col2_x, col2_y, col2_w, ph - 70), width=1, border_radius=6)

        sec2_title = self.font.render("ADALARI KIŞTAN KURTARMA", True, (255, 220, 130))
        screen.blit(sec2_title, (col2_x + 14, col2_y + 12))

        # Objective Box
        obj_rect = pygame.Rect(col2_x + 10, col2_y + 40, col2_w - 20, 90)
        pygame.draw.rect(screen, (30, 18, 14), obj_rect, border_radius=5)
        pygame.draw.rect(screen, (100, 70, 40), obj_rect, width=1, border_radius=5)

        my_id = self.my_player_id()
        my_count = sum(1 for o in self.island_owners.values() if o == my_id)

        obj_t1 = self.font.render("Zafer Hedefi: 6 Ada Fethi", True, (255, 215, 60))
        obj_t2 = self.small_font.render(f"Kurtardığın Ada: {my_count} / {self.WINNING_COUNT}", True, (235, 230, 215))
        screen.blit(obj_t1, (obj_rect.x + 12, obj_rect.y + 10))
        screen.blit(obj_t2, (obj_rect.x + 12, obj_rect.y + 34))

        # Progress Bar
        pbar_rect = pygame.Rect(obj_rect.x + 12, obj_rect.y + 60, obj_rect.width - 24, 16)
        pygame.draw.rect(screen, (18, 12, 10), pbar_rect, border_radius=4)
        pct = min(1.0, my_count / float(self.WINNING_COUNT))
        fill_w = int(pbar_rect.width * pct)
        if fill_w > 0:
            pygame.draw.rect(screen, (240, 180, 50), (pbar_rect.x, pbar_rect.y, fill_w, pbar_rect.height), border_radius=4)
        pygame.draw.rect(screen, (140, 100, 50), pbar_rect, width=1, border_radius=4)

        # Current Island Status Box
        isl_rect = pygame.Rect(col2_x + 10, col2_y + 140, col2_w - 20, 180)
        pygame.draw.rect(screen, (30, 18, 14), isl_rect, border_radius=5)
        pygame.draw.rect(screen, (100, 70, 40), isl_rect, width=1, border_radius=5)

        idx, island, owner = self.current_island_info()
        if idx is not None:
            isl_t1 = self.font.render(f"Konum: {island.name}", True, (255, 235, 160))
            screen.blit(isl_t1, (isl_rect.x + 12, isl_rect.y + 10))

            if owner == my_id:
                st_txt = "Durum: Kurtarıldı — Köylüler Kışa Hazır"
                st_col = (100, 225, 100)
            elif owner is not None:
                st_txt = f"Durum: Oyuncu {owner} Tarafından Kurtarıldı"
                st_col = (130, 210, 150)
            else:
                st_txt = "Durum: Tehdit Altında — Kışlık Erzak Bekleniyor"
                st_col = (200, 200, 200)

            isl_t2 = self.small_font.render(st_txt, True, st_col)
            screen.blit(isl_t2, (isl_rect.x + 12, isl_rect.y + 34))

            is_enemy = False
            cost = self.get_current_island_cost(False)
            inf_pct = int(round((self.get_inflation_rate() - 1.0) * 100))
            inf_tag = f" (+%{inf_pct} Enflasyon)" if inf_pct > 0 else ""
            cost_label = f"Köyün Kışlık Kaynak İhtiyacı{inf_tag}:"
            c_title = self.small_font.render(cost_label, True, (255, 215, 120))
            c_desc = self.small_font.render(f"{cost['Odun']} Odun, {cost['Tas']} Tas, {cost['Tahil']} Tahil, {cost['Balik']} Balik", True, (230, 220, 200))
            screen.blit(c_title, (isl_rect.x + 12, isl_rect.y + 60))
            screen.blit(c_desc, (isl_rect.x + 12, isl_rect.y + 80))

            if owner != my_id:
                self.conquer_action_rect = pygame.Rect(isl_rect.x + 20, isl_rect.y + 120, isl_rect.width - 40, 38)
                afford = self.can_afford(cost)
                btn_hov = self.conquer_action_rect.collidepoint(logical_mouse_pos)
                if afford:
                    btn_bg = (140, 65, 30) if btn_hov else (100, 45, 20)
                    btn_border = (255, 215, 60)
                    btn_text_col = (255, 240, 180)
                    btn_str = "KIŞLIK KAYNAKLARI TESLİM ET [C]"
                else:
                    btn_bg = (55, 35, 30)
                    btn_border = (90, 60, 50)
                    btn_text_col = (180, 120, 120)
                    btn_str = "YETERSIZ MATERYAL"

                pygame.draw.rect(screen, btn_bg, self.conquer_action_rect, border_radius=6)
                pygame.draw.rect(screen, btn_border, self.conquer_action_rect, width=1, border_radius=6)
                b_surf = self.font.render(btn_str, True, btn_text_col)
                screen.blit(b_surf, b_surf.get_rect(center=self.conquer_action_rect.center))
            else:
                own_msg = self.small_font.render("Bu ada kurtarıldı; köylüler güvenle üretim yapıyor.", True, (140, 220, 140))
                screen.blit(own_msg, (isl_rect.x + 12, isl_rect.y + 125))
        else:
            water_t = self.font.render("Denizdesin!", True, (120, 200, 240))
            water_d = self.small_font.render("Bir adaya yanaş, köylülerle konuş ve yerel tehdidi sona erdir.", True, (210, 210, 210))
            screen.blit(water_t, (isl_rect.x + 12, isl_rect.y + 30))
            screen.blit(water_d, (isl_rect.x + 12, isl_rect.y + 60))

        tip_text = self.small_font.render("İpucu: Kurtarılan adalar 20 saniyede bir dayanışma kaynağı sağlar!", True, (240, 200, 120))
        screen.blit(tip_text, (col2_x + 10, col2_y + 395))

    def draw_trade_ui(self, screen, logical_mouse_pos):
        if not self.trade_open:
            return

        overlay = pygame.Surface((GAME_WIDTH, GAME_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 8, 6, 200))
        screen.blit(overlay, (0, 0))

        pw, ph = 760, 520
        px = (GAME_WIDTH - pw) // 2
        py = (GAME_HEIGHT - ph) // 2

        pygame.draw.rect(screen, (28, 22, 18), (px, py, pw, ph), border_radius=10)
        pygame.draw.rect(screen, (120, 200, 130), (px, py, pw, ph), width=2, border_radius=10)
        pygame.draw.rect(screen, (50, 75, 50), (px + 3, py + 3, pw - 6, ph - 6), width=1, border_radius=8)

        # Header
        header_rect = pygame.Rect(px + 4, py + 4, pw - 8, 38)
        pygame.draw.rect(screen, (35, 52, 35), header_rect, border_top_left_radius=8, border_top_right_radius=8)
        header_title = self.font.render("OYUNCULAR ARASI TICARET PAZARI", True, (210, 255, 210))
        screen.blit(header_title, (px + 18, py + 12))

        # Close Button
        self.trade_close_rect = pygame.Rect(px + pw - 38, py + 7, 28, 26)
        close_hover = self.trade_close_rect.collidepoint(logical_mouse_pos)
        pygame.draw.rect(screen, (130, 40, 30) if close_hover else (80, 28, 20), self.trade_close_rect, border_radius=4)
        pygame.draw.rect(screen, (190, 145, 80), self.trade_close_rect, width=1, border_radius=4)
        x_txt = self.font.render("X", True, (255, 235, 215))
        screen.blit(x_txt, x_txt.get_rect(center=self.trade_close_rect.center))

        # Left Column: Send Trade Offer
        col1_x, col1_w = px + 18, 350
        col1_y = py + 50
        pygame.draw.rect(screen, (38, 30, 24), (col1_x, col1_y, col1_w, ph - 68), border_radius=6)
        pygame.draw.rect(screen, (110, 85, 55), (col1_x, col1_y, col1_w, ph - 68), width=1, border_radius=6)

        c1_title = self.font.render("YENI TEKLIF OLUSTUR", True, (255, 225, 140))
        screen.blit(c1_title, (col1_x + 14, col1_y + 10))

        # Available trade partners (other players)
        my_id = self.my_player_id()
        other_pids = []
        if self.network and self.network.connected:
            with self.network.lock:
                other_pids = sorted(list(self.network.other_players.keys()))

        self.trade_action_rects = []

        ptn_y = col1_y + 36
        ptn_lbl = self.small_font.render("Hedef Oyuncu:", True, (220, 215, 200))
        screen.blit(ptn_lbl, (col1_x + 14, ptn_y))

        # All players button
        all_btn = pygame.Rect(col1_x + 110, ptn_y - 2, 75, 22)
        is_all = (self.trade_selected_partner is None)
        pygame.draw.rect(screen, (60, 120, 70) if is_all else (45, 38, 30), all_btn, border_radius=4)
        pygame.draw.rect(screen, (120, 200, 130) if is_all else (80, 65, 50), all_btn, width=1, border_radius=4)
        all_txt = self.small_font.render("Herkes", True, (255, 255, 255) if is_all else (180, 175, 160))
        screen.blit(all_txt, all_txt.get_rect(center=all_btn.center))
        self.trade_action_rects.append(('select_partner', None, all_btn))

        bx = col1_x + 192
        for opid in other_pids[:3]:
            p_btn = pygame.Rect(bx, ptn_y - 2, 44, 22)
            is_sel = (self.trade_selected_partner == opid)
            pygame.draw.rect(screen, (60, 120, 70) if is_sel else (45, 38, 30), p_btn, border_radius=4)
            pygame.draw.rect(screen, (120, 200, 130) if is_sel else (80, 65, 50), p_btn, width=1, border_radius=4)
            p_txt = self.small_font.render(f"P{opid}", True, (255, 255, 255) if is_sel else (180, 175, 160))
            screen.blit(p_txt, p_txt.get_rect(center=p_btn.center))
            self.trade_action_rects.append(('select_partner', opid, p_btn))
            bx += 48

        # Giving (Offer) section
        res_list = [("Odun", RESOURCE_COLORS["Odun"]), ("Tas", RESOURCE_COLORS["Tas"]),
                    ("Tahil", RESOURCE_COLORS["Tahil"]), ("Balik", RESOURCE_COLORS["Balik"])]

        give_lbl = self.small_font.render("Verecegin (Cantan):", True, (130, 220, 140))
        screen.blit(give_lbl, (col1_x + 14, col1_y + 68))

        row_y = col1_y + 90
        for rname, rcol in res_list:
            have = self.inventory.get(rname, 0)
            offered = self.trade_offer.get(rname, 0)

            # Icon & Name
            pygame.draw.circle(screen, rcol, (col1_x + 22, row_y + 11), 5)
            r_txt = self.small_font.render(f"{rname} (var:{have})", True, (240, 235, 220))
            screen.blit(r_txt, (col1_x + 34, row_y + 3))

            # - button
            btn_minus = pygame.Rect(col1_x + 160, row_y, 24, 22)
            pygame.draw.rect(screen, (60, 40, 30), btn_minus, border_radius=3)
            pygame.draw.rect(screen, (110, 80, 50), btn_minus, width=1, border_radius=3)
            m_txt = self.font.render("-", True, (255, 255, 255))
            screen.blit(m_txt, m_txt.get_rect(center=btn_minus.center))
            self.trade_action_rects.append(('offer_minus', rname, btn_minus))

            # Value
            val_txt = self.font.render(str(offered), True, (255, 230, 120))
            screen.blit(val_txt, val_txt.get_rect(center=(col1_x + 205, row_y + 11)))

            # + button
            btn_plus = pygame.Rect(col1_x + 230, row_y, 24, 22)
            pygame.draw.rect(screen, (60, 40, 30), btn_plus, border_radius=3)
            pygame.draw.rect(screen, (110, 80, 50), btn_plus, width=1, border_radius=3)
            p_txt = self.font.render("+", True, (255, 255, 255))
            screen.blit(p_txt, p_txt.get_rect(center=btn_plus.center))
            self.trade_action_rects.append(('offer_plus', rname, btn_plus))

            row_y += 30

        # Request (Want) section
        want_lbl = self.small_font.render("Isteyecegin Kaynak:", True, (235, 180, 100))
        screen.blit(want_lbl, (col1_x + 14, row_y + 6))
        row_y += 28

        for rname, rcol in res_list:
            requested = self.trade_request.get(rname, 0)

            # Icon & Name
            pygame.draw.circle(screen, rcol, (col1_x + 22, row_y + 11), 5)
            r_txt = self.small_font.render(rname, True, (240, 235, 220))
            screen.blit(r_txt, (col1_x + 34, row_y + 3))

            # - button
            btn_minus = pygame.Rect(col1_x + 160, row_y, 24, 22)
            pygame.draw.rect(screen, (60, 40, 30), btn_minus, border_radius=3)
            pygame.draw.rect(screen, (110, 80, 50), btn_minus, width=1, border_radius=3)
            m_txt = self.font.render("-", True, (255, 255, 255))
            screen.blit(m_txt, m_txt.get_rect(center=btn_minus.center))
            self.trade_action_rects.append(('req_minus', rname, btn_minus))

            # Value
            val_txt = self.font.render(str(requested), True, (255, 230, 120))
            screen.blit(val_txt, val_txt.get_rect(center=(col1_x + 205, row_y + 11)))

            # + button
            btn_plus = pygame.Rect(col1_x + 230, row_y, 24, 22)
            pygame.draw.rect(screen, (60, 40, 30), btn_plus, border_radius=3)
            pygame.draw.rect(screen, (110, 80, 50), btn_plus, width=1, border_radius=3)
            p_txt = self.font.render("+", True, (255, 255, 255))
            screen.blit(p_txt, p_txt.get_rect(center=btn_plus.center))
            self.trade_action_rects.append(('req_plus', rname, btn_plus))

            row_y += 30

        # Send proposal button
        self.trade_send_btn = pygame.Rect(col1_x + 75, col1_y + ph - 118, 200, 36)
        can_send = any(v > 0 for v in self.trade_offer.values()) and any(v > 0 for v in self.trade_request.values())
        hov_send = self.trade_send_btn.collidepoint(logical_mouse_pos)
        pygame.draw.rect(screen, (50, 120, 60) if (can_send and hov_send) else ((35, 80, 40) if can_send else (40, 35, 30)),
                         self.trade_send_btn, border_radius=6)
        pygame.draw.rect(screen, (100, 210, 110) if can_send else (80, 65, 55), self.trade_send_btn, width=1, border_radius=6)
        s_txt = self.font.render("Teklifi Gonder [Enter]", True, (240, 255, 240) if can_send else (140, 130, 120))
        screen.blit(s_txt, s_txt.get_rect(center=self.trade_send_btn.center))

        # Right Column: Active & Incoming Offers
        col2_x, col2_w = px + 382, 360
        col2_y = py + 50
        pygame.draw.rect(screen, (38, 30, 24), (col2_x, col2_y, col2_w, ph - 68), border_radius=6)
        pygame.draw.rect(screen, (110, 85, 55), (col2_x, col2_y, col2_w, ph - 68), width=1, border_radius=6)

        c2_title = self.font.render("AKTIF VE GELEN TEKLIFLER", True, (255, 225, 140))
        screen.blit(c2_title, (col2_x + 14, col2_y + 10))

        trades = []
        if self.network and self.network.connected and hasattr(self.network, 'trades'):
            with self.network.lock:
                trades = list(self.network.trades)

        trade_card_y = col2_y + 38
        if not trades:
            empty_msg = self.small_font.render("Henuz aktif bir ticaret teklifi yok.", True, (180, 175, 160))
            empty_sub = self.small_font.render("Sol taraftan teklif olusturup diger", True, (150, 145, 135))
            empty_sub2 = self.small_font.render("oyuncularla kaynak takasi yapabilirsin!", True, (150, 145, 135))
            screen.blit(empty_msg, (col2_x + 16, trade_card_y + 10))
            screen.blit(empty_sub, (col2_x + 16, trade_card_y + 34))
            screen.blit(empty_sub2, (col2_x + 16, trade_card_y + 54))
        else:
            for t in trades[:3]:
                card_r = pygame.Rect(col2_x + 10, trade_card_y, col2_w - 20, 110)
                is_from_me = (t.get('from_pid') == my_id)
                status = t.get('status', 'pending')

                bg_col = (45, 34, 25)
                if status == 'accepted':
                    bg_col = (25, 45, 25)
                elif status == 'cancelled':
                    bg_col = (45, 25, 25)

                pygame.draw.rect(screen, bg_col, card_r, border_radius=6)
                pygame.draw.rect(screen, (100, 75, 50), card_r, width=1, border_radius=6)

                from_str = "Senin Teklifin" if is_from_me else f"Oyuncu {t.get('from_pid')} Teklifi"
                t_lbl = self.small_font.render(f"{from_str} [{status.upper()}]", True, (255, 220, 130))
                screen.blit(t_lbl, (card_r.x + 10, card_r.y + 8))

                give_items = ", ".join(f"{v} {k}" for k, v in t.get('offer', {}).items() if v > 0)
                req_items = ", ".join(f"{v} {k}" for k, v in t.get('request', {}).items() if v > 0)

                if is_from_me:
                    txt1 = self.small_font.render(f"Verecegin: {give_items}", True, (140, 230, 140))
                    txt2 = self.small_font.render(f"Istedigin: {req_items}", True, (240, 200, 120))
                else:
                    txt1 = self.small_font.render(f"Sana Verilen: {give_items}", True, (140, 230, 140))
                    txt2 = self.small_font.render(f"Senden Istenen: {req_items}", True, (240, 200, 120))

                screen.blit(txt1, (card_r.x + 10, card_r.y + 32))
                screen.blit(txt2, (card_r.x + 10, card_r.y + 54))

                if status == 'pending':
                    if is_from_me:
                        # Cancel button
                        c_btn = pygame.Rect(card_r.right - 90, card_r.bottom - 32, 80, 24)
                        pygame.draw.rect(screen, (100, 40, 30), c_btn, border_radius=4)
                        pygame.draw.rect(screen, (180, 80, 60), c_btn, width=1, border_radius=4)
                        c_txt = self.small_font.render("Iptal Et", True, (255, 230, 230))
                        screen.blit(c_txt, c_txt.get_rect(center=c_btn.center))
                        self.trade_action_rects.append(('cancel_trade', t.get('id'), c_btn))
                    else:
                        # Accept button
                        req_dict = t.get('request', {})
                        can_accept = all(self.inventory.get(k, 0) >= v for k, v in req_dict.items())
                        a_btn = pygame.Rect(card_r.right - 90, card_r.bottom - 32, 80, 24)
                        pygame.draw.rect(screen, (40, 110, 50) if can_accept else (50, 40, 35), a_btn, border_radius=4)
                        pygame.draw.rect(screen, (100, 200, 110) if can_accept else (80, 65, 55), a_btn, width=1, border_radius=4)
                        a_txt = self.small_font.render("Kabul Et" if can_accept else "Yetersiz", True, (255, 255, 255) if can_accept else (160, 140, 130))
                        screen.blit(a_txt, a_txt.get_rect(center=a_btn.center))
                        if can_accept:
                            self.trade_action_rects.append(('accept_trade', t.get('id'), a_btn))

                trade_card_y += 118

    def submit_trade_proposal(self):
        offer_clean = {k: v for k, v in self.trade_offer.items() if v > 0}
        req_clean = {k: v for k, v in self.trade_request.items() if v > 0}
        if not offer_clean or not req_clean:
            self.add_toast("Teklif icin hem verilecek hem istenecek kaynak secmelisin!")
            return False

        if not all(self.inventory.get(k, 0) >= v for k, v in offer_clean.items()):
            self.add_toast("Cantanizda teklif ettiginiz kadar kaynak yok!")
            return False

        if self.network and self.network.connected:
            self.network.propose_trade(self.trade_selected_partner, offer_clean, req_clean)
            self.add_toast("Ticaret teklifi gonderildi!")
            self.trade_offer = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
            self.trade_request = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
            return True
        else:
            self.add_toast("Ticaret icin cok oyunculu baglanti gerekiyor!")
            return False

    def sync_trades_and_execute(self):
        if not (self.network and self.network.connected and hasattr(self.network, 'trades')):
            return

        my_id = self.my_player_id()
        with self.network.lock:
            trades = list(self.network.trades)

        for t in trades:
            tid = t.get('id')
            if tid in self.processed_trades:
                continue

            if t.get('status') == 'accepted':
                # If I was the creator of the trade
                if t.get('from_pid') == my_id:
                    # Give offered, receive requested
                    for k, v in t.get('offer', {}).items():
                        self.inventory[k] = max(0, self.inventory.get(k, 0) - v)
                    for k, v in t.get('request', {}).items():
                        self.inventory[k] = self.inventory.get(k, 0) + v
                    self.processed_trades.add(tid)
                    self.add_toast(f"Ticaret Tamamlandi! Teklifin kabul edildi.", color=(120, 240, 130))

                # If I was the acceptor
                elif t.get('to_pid') == my_id or t.get('to_pid') is None:
                    # Only execute if this client triggered acceptance (detected via processed_trades or local accept)
                    pass

    def draw_victory_ui(self, screen, logical_mouse_pos):
        if self.winner is None or self.victory_dismissed:
            return

        overlay = pygame.Surface((GAME_WIDTH, GAME_HEIGHT), pygame.SRCALPHA)
        overlay.fill((8, 4, 2, 210))
        screen.blit(overlay, (0, 0))

        vw, vh = 580, 360
        vx = (GAME_WIDTH - vw) // 2
        vy = (GAME_HEIGHT - vh) // 2

        pygame.draw.rect(screen, (34, 18, 12), (vx, vy, vw, vh), border_radius=12)
        pygame.draw.rect(screen, (255, 215, 60), (vx, vy, vw, vh), width=2, border_radius=12)
        pygame.draw.rect(screen, (100, 60, 30), (vx + 3, vy + 3, vw - 6, vh - 6), width=1, border_radius=10)

        my_id = self.my_player_id()
        i_won = (self.winner == my_id)

        if i_won:
            t_col = (255, 225, 70)
            title = self.font.render("BÜYÜK ZAFER! 6 ADA KURTARILDI!", True, t_col)
            sub = self.small_font.render("Adalardaki tehditleri yenip köyleri kışa hazırladın!", True, (245, 235, 200))
        else:
            t_col = (240, 70, 70)
            title = self.font.render("OYUN BITTI!", True, t_col)
            sub = self.small_font.render(f"Oyuncu {self.winner} altı adayı kurtarıp köyleri kışa hazırladı!", True, (235, 220, 200))

        screen.blit(title, title.get_rect(center=(GAME_WIDTH // 2, vy + 40)))
        screen.blit(sub, sub.get_rect(center=(GAME_WIDTH // 2, vy + 75)))

        # Stats Box
        s_rect = pygame.Rect(vx + 40, vy + 110, vw - 80, 130)
        pygame.draw.rect(screen, (24, 12, 8), s_rect, border_radius=8)
        pygame.draw.rect(screen, (120, 80, 40), s_rect, width=1, border_radius=8)

        my_count = sum(1 for o in self.island_owners.values() if o == my_id)
        s1 = self.font.render(f"Fethedilen Adalarin: {my_count} / {self.WINNING_COUNT}", True, (255, 220, 100))
        s2 = self.small_font.render(f"Envanter: {self.inventory['Odun']} Odun | {self.inventory['Tas']} Tas | {self.inventory['Tahil']} Tahil | {self.inventory['Balik']} Balik", True, (230, 220, 200))
        s3 = self.small_font.render("Hukumranligin altindaki adalar baris ve bereket icinde yasiyor.", True, (180, 230, 160) if i_won else (200, 180, 160))

        screen.blit(s1, s1.get_rect(center=(GAME_WIDTH // 2, s_rect.y + 30)))
        screen.blit(s2, s2.get_rect(center=(GAME_WIDTH // 2, s_rect.y + 65)))
        screen.blit(s3, s3.get_rect(center=(GAME_WIDTH // 2, s_rect.y + 98)))

        # Buttons
        self.victory_continue_rect = pygame.Rect(vx + 60, vy + 280, 210, 44)
        self.victory_menu_rect = pygame.Rect(vx + 310, vy + 280, 210, 44)

        c_hov = self.victory_continue_rect.collidepoint(logical_mouse_pos)
        m_hov = self.victory_menu_rect.collidepoint(logical_mouse_pos)

        pygame.draw.rect(screen, (120, 60, 30) if c_hov else (85, 40, 20), self.victory_continue_rect, border_radius=6)
        pygame.draw.rect(screen, (255, 215, 60), self.victory_continue_rect, width=1, border_radius=6)
        c_txt = self.font.render("KESFE DEVAM ET", True, (255, 235, 180))
        screen.blit(c_txt, c_txt.get_rect(center=self.victory_continue_rect.center))

        pygame.draw.rect(screen, (120, 60, 30) if m_hov else (85, 40, 20), self.victory_menu_rect, border_radius=6)
        pygame.draw.rect(screen, (255, 215, 60), self.victory_menu_rect, width=1, border_radius=6)
        m_txt = self.font.render("ANA MENUYE DON", True, (255, 235, 180))
        screen.blit(m_txt, m_txt.get_rect(center=self.victory_menu_rect.center))


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
            spawn = self.network.spawn if connected and self.network.spawn else find_spawn(world)

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
        character_sheet = load_character_sheet(BASE_DIR)
        yield
        self.game_session = GameSession(data["world"], data["ports"], data["spawn"], tiles,
                                        data["network"], data["seed"], customization, atlas=self.atlas, character_sheet=character_sheet)
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
