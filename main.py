#!/usr/bin/env python3
"""
EDGE OF WINTER - Main Menu & Integrated Multiplayer Game Client
--------------------------------------------------------------
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

import sys
import math
import time
import random
import socket
import json
import queue
import threading
from dataclasses import replace
from enum import Enum

import pygame
import numpy as np

from modules.audio_manager import AudioManager
from modules.display import (VIEWPORT, desktop_size, enable_hidpi_awareness, fit_window_size,
                             logical_mouse_pos, window_size_options)
from modules.localization import (DEVELOPER_CREDIT, GAME_TITLE, RESOURCE_ACTIONS, TREANT_STORY,
                                  action_label, creature_name, format_amounts, item_name, tr,
                                  weapon_name)
from modules.save_game import load_save, save_seed, write_save
from modules.settings import (GameSettings, load_settings, random_seed_text,
                              save_settings, stable_seed, validate_endpoint)

from modules.paths import (ASSETS_DIR, CLOTHING_ASSET, GAME_LOGO_ASSET, HAIR_SKIN_ASSET, MENU_MUSIC_ASSET,
                           MAIN_MENU_BACKGROUND_ASSET, MENU_BUTTONS_ASSET,
                           MENU_CHARACTER_ASSET, OVERWORLD_TILESET_ASSET,
                           PLAYER_CHARACTER_DIR, PROJECT_ROOT,
                           SAILBOAT_HULL_ASSET, VILLAGER_ATLAS_ASSET,
                           require_asset)

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
MENU_WIDTH = 1024
MENU_HEIGHT = 576

# Gameplay is drawn to a logical view whose size follows the window's aspect
# ratio: 1200x780 is the minimum, wider windows add world columns at the same
# 780-pixel height (same tile scale), narrower ones add rows at 1200 width.
# GAME_WIDTH/GAME_HEIGHT are updated at runtime via ``set_game_view_size``.
BASE_GAME_WIDTH = 1200
BASE_GAME_HEIGHT = 780
GAME_WIDTH = BASE_GAME_WIDTH
GAME_HEIGHT = BASE_GAME_HEIGHT
# Beyond these aspect ratios (e.g. 32:9 or portrait) the view letterboxes.
MIN_GAME_ASPECT = 5 / 4
MAX_GAME_ASPECT = 2.4

DEFAULT_WIN_W = 1200
DEFAULT_WIN_H = 780
FPS = 60

BASE_DIR = PROJECT_ROOT
SAVE_FILE = BASE_DIR / "savegame.json"
AUTOSAVE_INTERVAL = 60.0


def load_local_save(world_seed=None):
    """Load the offline save for this world without making startup fragile."""
    return load_save(world_seed, SAVE_FILE)

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
DASH_COOLDOWN = 3.0
DASH_DURATION = .24
DASH_SPEED = 15.5

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
# Explicit Runtime Asset Paths
# ---------------------------------------------------------------------------
def find_tileset_file():
    """Compatibility helper returning the one verified overworld atlas."""
    return require_asset(OVERWORLD_TILESET_ASSET)


def remove_flat_background(surface, tolerance=22, min_hole_area=1000, hole_purity=.7):
    """Make an opaque artwork's flat backdrop transparent; keep real alpha as-is.

    The backdrop is every near-backdrop pixel connected to the image border,
    plus large enclosed regions of that exact colour (letter counters).  Small
    or textured dark regions inside the artwork, such as outlines, stay opaque.
    """
    alpha = pygame.surfarray.pixels_alpha(surface)
    already_transparent = int(alpha.min()) < 255
    del alpha
    if already_transparent:
        return surface
    w, h = surface.get_size()
    rgb = pygame.surfarray.array3d(surface).astype(np.int16)
    edges = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    backdrop = np.median(edges, axis=0)
    distance = np.abs(rgb - backdrop).max(axis=2)
    if np.mean(np.abs(edges - backdrop).max(axis=1) <= tolerance) < .9:
        return surface  # No uniform border: nothing safe to remove.

    near = pygame.Surface((w, h), pygame.SRCALPHA, 32)
    near_alpha = pygame.surfarray.pixels_alpha(near)
    near_alpha[...] = np.where(distance <= tolerance, 255, 0)
    del near_alpha
    border = pygame.mask.Mask((w, h))
    border.draw(pygame.mask.Mask((w, 1), fill=True), (0, 0))
    border.draw(pygame.mask.Mask((w, 1), fill=True), (0, h - 1))
    border.draw(pygame.mask.Mask((1, h), fill=True), (0, 0))
    border.draw(pygame.mask.Mask((1, h), fill=True), (w - 1, 0))
    background = pygame.mask.Mask((w, h))
    for component in pygame.mask.from_surface(near, 127).connected_components():
        if component.overlap_area(border, (0, 0)):
            background.draw(component, (0, 0))
        elif component.count() >= min_hole_area:
            pixels = pygame.surfarray.array_red(component.to_surface()) > 0
            if np.mean(distance[pixels] <= 4) >= hole_purity:
                background.draw(component, (0, 0))

    keyed = surface.copy()
    keyed_alpha = pygame.surfarray.pixels_alpha(keyed)
    keyed_alpha[pygame.surfarray.array_red(background.to_surface()) > 0] = 0
    del keyed_alpha
    return keyed


def load_required_character_sheet():
    """Load the canonical player art and make a missing path actionable."""
    sheet = load_character_sheet(PLAYER_CHARACTER_DIR)
    if sheet is None:
        raise FileNotFoundError(
            f"Required player character asset not found: {PLAYER_CHARACTER_DIR / 'manchar.jpeg'}"
        )
    return sheet


# ---------------------------------------------------------------------------
# Tile Atlas & Sprite Sheet Manager
# ---------------------------------------------------------------------------
from modules.terrain_render import TileAtlas, TerrainRenderer, prepare_terrain


# ---------------------------------------------------------------------------
# Multiplayer Networking Client
# ---------------------------------------------------------------------------
from modules.multiplayer import NetworkClient
from modules.game_ui import (InteractionHint, PixelHUD, PixelInteractionPrompt, WorldMapUI,
                             panel as draw_pixel_panel, label as draw_pixel_label,
                             pixel_bar, pixel_box, pixel_button, pixel_overlay, pixel_window)
from modules.autumn_leaves import AutumnLeaves
from modules.character_animation import CharacterAnimator, load_character_sheet
from modules.economy import INFLATION_PER_MINUTE, inflated_cost, inflation_multiplier
from modules.gameplay_systems import (AnimalSystem, CombatSystem, DialogueBox, EnemyAISystem,
                                      LootDrop, NavalEncounterSystem, QuestSystem)
from modules.pixel_sprites import (entity_sprite, item_sprite, preload_villager_sprites,
                                   villager_sprite, wizard_sprite)
from modules.progression import (FOODS, RECIPES, ProgressionSystem, TreantQuestProgress,
                                 TREANT_ACHIEVEMENT, TREANT_ACHIEVEMENT_DESCRIPTION,
                                 TREANT_ACHIEVEMENT_NAME, TREANT_QUEST_NAME, craft)
from modules.treant_boss import (BOSS_DAMAGED, ENCOUNTER_COMPLETED, PLAYER_HIT,
                                 BossPlayerState, BossState, EncounterResult, PlayerAttack,
                                 TreantBossEncounter, TreantConfig)


# ---------------------------------------------------------------------------
# World Generation & Data Structures (from main2.py)
# ---------------------------------------------------------------------------
# Shared by the server; generation and resource IDs have a single implementation.
from modules.worldgen import (
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
class PixelFont:
    """Aliased font wrapper: every render is crisp, pixel-edged text."""

    def __init__(self, size, name=None):
        self._font = pygame.font.Font(name, size)

    def render(self, text, antialias=False, color=(255, 255, 255), background=None):
        return self._font.render(text, False, color, background)

    def __getattr__(self, attr):
        return getattr(self._font, attr)


def wrap_text(font, text, width):
    """Greedy word wrap measured with the font that will draw the text."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.size(candidate)[0] > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def window_logical_mouse():
    """Current mouse position in logical game pixels (letterbox-aware)."""
    return logical_mouse_pos()


def draw_text(screen, font, text, position, color=(235, 240, 245), shadow=False):
    if shadow:
        # A 1px pixel shadow keeps HUD text legible over bright sand and shallows.
        x, y = position
        screen.blit(font.render(text, True, (18, 12, 10)), (x + 1, y + 1))
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
                sail_raised=True, hit_flash=0.0):
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
        if hit_flash <= 0:
            character_sheet.draw(screen, position, animation)
        else:
            x, y = round(position[0]), round(position[1])
            screen.blit(character_sheet.shadow, (x - 15, y - 4))
            frame = character_sheet.frames[animation.facing][animation.frame].copy()
            mask = pygame.mask.from_surface(frame)
            flash = mask.to_surface(setcolor=(255, 58, 48, 190), unsetcolor=(0, 0, 0, 0))
            frame.blit(flash, (0, 0))
            screen.blit(frame, (x - character_sheet.ANCHOR[0], y - character_sheet.ANCHOR[1]))
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

    if hit_flash > 0:
        mask = pygame.mask.from_surface(sprite)
        sprite.blit(mask.to_surface(setcolor=(255, 58, 48, 190), unsetcolor=(0, 0, 0, 0)), (0, 0))
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

    label = (tr("hud.merchant", key=pygame.key.name(GameSession.INTERACT_KEY).upper())
             if ship.kind == "merchant" else tr("hud.pirate"))
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
    role = getattr(npc, "profession", "villager")
    sprite = villager_sprite(role, getattr(npc, "facing", "down"),
                              int(getattr(npc, "walk_phase", 0.0)),
                              getattr(npc, "moving", False),
                              getattr(npc, "appearance_variant", 0))
    pygame.draw.ellipse(screen, (32, 24, 20, 95), (x - 17, y - 6, 34, 10))
    screen.blit(sprite, sprite.get_rect(midbottom=(x, y + 2)))
    if role == "merchant":
        pygame.draw.circle(screen, (255, 218, 82), (x + 17, y - 44), 3)


def draw_monster(screen, monster, camera_x, camera_y):
    x, y = round(monster.x * LOCAL_TILE_SIZE) - camera_x, round(monster.y * LOCAL_TILE_SIZE) - camera_y
    pygame.draw.ellipse(screen, (25, 22, 18, 105), (x - 20, y - 6, 40, 10))
    sprite = entity_sprite(monster.kind, monster.facing, int(monster.walk_phase), monster.hit_flash > 0)
    screen.blit(sprite, sprite.get_rect(midbottom=(x, y + 2)))
    bar_y = y - (60 if monster.kind not in ("wolf", "boar") else 49)
    pygame.draw.rect(screen, (45, 25, 24), (x - 16, bar_y, 32, 4))
    pygame.draw.rect(screen, (210, 70, 55), (x - 16, bar_y,
                                           round(32 * monster.health / monster.max_health), 4))
    if monster.state == "windup":
        charge = min(1.0, monster.attack_timer / max(.01, monster.attack_windup))
        radius = round(22 + charge * 8)
        pygame.draw.circle(screen, (255, 65 + round(charge * 90), 45), (x, y - 14), radius, 3)
        pygame.draw.arc(screen, (255, 225, 105), (x - 19, y - 48, 38, 38),
                        -math.pi / 2, -math.pi / 2 + math.tau * charge, 4)
    elif monster.state == "flank":
        pygame.draw.arc(screen, (245, 165, 65), (x - 22, y - 12, 44, 18), 0, math.pi, 2)


def draw_animal(screen, animal, camera_x, camera_y):
    x = round(animal.x * LOCAL_TILE_SIZE) - camera_x
    y = round(animal.y * LOCAL_TILE_SIZE) - camera_y
    pygame.draw.ellipse(screen, (29, 23, 18, 90), (x - 22, y - 6, 44, 10))
    sprite = entity_sprite(animal.kind, animal.facing, int(animal.walk_phase), animal.hit_flash > 0)
    screen.blit(sprite, sprite.get_rect(midbottom=(x, y + 2)))
    if animal.health < animal.max_health:
        pygame.draw.rect(screen, (45, 25, 24), (x - 16, y - 49, 32, 4))
        pygame.draw.rect(screen, (210, 70, 55),
                         (x - 16, y - 49, round(32 * max(0, animal.health) / animal.max_health), 4))


def draw_loot_drop(screen, drop, camera_x, camera_y, font):
    x = round(drop.x * LOCAL_TILE_SIZE) - camera_x
    y = round(drop.y * LOCAL_TILE_SIZE) - camera_y - 8 - round(math.sin(drop.phase) * 3)
    pygame.draw.ellipse(screen, (38, 24, 18), (x - 13, y + 9, 26, 8))
    sprite = item_sprite(drop.item)
    screen.blit(sprite, sprite.get_rect(center=(x, y)))
    if drop.count > 1:
        count = font.render(str(drop.count), True, (255, 237, 172))
        screen.blit(count, (x + 8, y + 5))


def draw_impact_particles(screen, particles, camera_x, camera_y):
    for particle in particles:
        x = round(particle["x"] * LOCAL_TILE_SIZE) - camera_x
        y = round(particle["y"] * LOCAL_TILE_SIZE) - camera_y
        size = 3 if particle["life"] > .12 else 2
        pygame.draw.rect(screen, particle["color"], (x - size // 2, y - size // 2, size, size))


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
        badge_text = tr("combat.wave_dash") if combat.attack_kind == "dash" else tr("combat.combo", combo=combo)
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
        label = font.render(tr("combat.finisher"), True, (255, 235, 135))
        shadow = font.render(tr("combat.finisher"), True, (40, 20, 25))
        rect = label.get_rect(center=(x, y - 92))
        screen.blit(shadow, rect.move(3, 3))
        screen.blit(label, rect)


# The dialogue panel keeps its original width on wide views instead of stretching.
DIALOGUE_PANEL_MAX_WIDTH = BASE_GAME_WIDTH - 110
DIALOGUE_TEXT_WIDTH = DIALOGUE_PANEL_MAX_WIDTH - 44


def game_view_size(surface_size):
    """Logical gameplay view for a drawable size, never stretching the world."""
    width, height = max(1, surface_size[0]), max(1, surface_size[1])
    aspect = max(MIN_GAME_ASPECT, min(MAX_GAME_ASPECT, width / height))
    if aspect >= BASE_GAME_WIDTH / BASE_GAME_HEIGHT:
        return round(BASE_GAME_HEIGHT * aspect), BASE_GAME_HEIGHT
    return BASE_GAME_WIDTH, round(BASE_GAME_WIDTH / aspect)


def set_game_view_size(size):
    """Adopt a new logical gameplay view; returns True when it changed."""
    global GAME_WIDTH, GAME_HEIGHT, DIALOGUE_TEXT_WIDTH
    size = (int(size[0]), int(size[1]))
    if size == (GAME_WIDTH, GAME_HEIGHT):
        return False
    GAME_WIDTH, GAME_HEIGHT = size
    DIALOGUE_TEXT_WIDTH = min(GAME_WIDTH - 110, DIALOGUE_PANEL_MAX_WIDTH) - 44
    return True
DIALOGUE_MAX_LINES = 3


def draw_dialogue_box(screen, dialogue, font, small_font):
    if not dialogue.active:
        return
    width = min(GAME_WIDTH - 110, DIALOGUE_PANEL_MAX_WIDTH)
    panel = pygame.Rect((GAME_WIDTH - width) // 2, GAME_HEIGHT - 205, width, 160)
    content = pixel_window(screen, panel, dialogue.speaker, font, accent=(212, 162, 86),
                           title_color=(255, 221, 135))
    lines = wrap_text(small_font, dialogue.visible_text, DIALOGUE_TEXT_WIDTH)
    for i, line in enumerate(lines[:DIALOGUE_MAX_LINES]):
        screen.blit(small_font.render(line, True, (244, 235, 213)), (content.x + 16, content.y + 10 + i * 24))
    hint = tr("dialogue.continue") if dialogue.page_complete else tr("dialogue.skip")
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
    pygame.draw.rect(screen, (30, 19, 17), arena_rect.inflate(8, 8), 4)
    pygame.draw.rect(screen, (212, 151, 76), arena_rect, 4)
    scale_x, scale_y = arena_rect.width / arena.WIDTH, arena_rect.height / arena.HEIGHT
    origin_x, origin_y = arena_rect.x, arena_rect.y
    for monster in arena.monsters:
        if monster.alive:
            px, py = monster.x * scale_x + origin_x, monster.y * scale_y + origin_y
            pygame.draw.ellipse(screen, (20, 16, 18), (px - 23, py - 6, 46, 11))
            wolf = entity_sprite("wolf", getattr(monster, "facing", "right"),
                                 int(getattr(monster, "walk_phase", 0)), monster.hit_flash > 0)
            screen.blit(wolf, wolf.get_rect(midbottom=(round(px), round(py + 2))))
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
    draw_player(screen, player_pos, False, arena.facing, character_sheet=character_sheet,
                animation=animator, hit_flash=arena.player_hit_flash)
    draw_sword_attack(screen, player_pos, arena.facing, arena.combat)
    title = font.render(tr("arena.title"), True, (255, 220, 140))
    screen.blit(title, (arena_rect.x + 18, arena_rect.y - 40))
    pixel_bar(screen, (arena_rect.right - 220, arena_rect.y - 35, 200, 18),
              arena.health / arena.max_health, (205, 65, 65), (55, 25, 28))
    info = small_font.render(tr("arena.controls"), True, (235, 222, 198))
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


def snapped_world_zoom(zoom):
    """Quantise a cinematic zoom so one world tile spans a whole number of pixels."""
    return max(LOCAL_TILE_SIZE, round(LOCAL_TILE_SIZE * zoom)) / LOCAL_TILE_SIZE


def magnify_world(screen, camera, zoom, origin):
    """Nearest-neighbour zoom of a finished world frame, sampled in world space.

    ``origin`` is the frame pixel shown at the top-left corner and ``camera``
    the integer camera the frame was drawn with. Resampling a screen-anchored
    crop at a fractional ratio made tiles 76 or 77 pixels wide depending on
    where they fell, so terrain slid and seamed whenever the camera moved.
    Here every tile maps to exactly the same pixel span and pattern.
    """
    tile = round(LOCAL_TILE_SIZE * snapped_world_zoom(zoom))
    if tile <= LOCAL_TILE_SIZE:
        return

    def source_indices(cam, start, length):
        offset = round((cam + start) * tile / LOCAL_TILE_SIZE)
        world = (np.arange(length) + offset) * LOCAL_TILE_SIZE // tile
        return np.clip(world - cam, 0, length - 1)

    width, height = screen.get_size()
    xs = source_indices(camera[0], origin[0], width)
    ys = source_indices(camera[1], origin[1], height)
    pixels = pygame.surfarray.array2d(screen)
    pygame.surfarray.blit_array(screen, pixels[xs[:, None], ys[None, :]])


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
ISLAND_INFLATION_PER_MINUTE = INFLATION_PER_MINUTE


def get_island_cost(is_enemy=False, inflation=1.0):
    base = ENEMY_ISLAND_COST if is_enemy else NEUTRAL_ISLAND_COST
    return inflated_cost(base, inflation)


RESOURCE_ICONS = {
    "Odun": "Odun",
    "Tas": "Tas",
    "Tahil": "Tahil",
    "Balik": "Balik",
}
SUPPLY_ITEMS = ("Odun", "Tas", "Tahil", "Balik")
TRADE_STATUS_KEYS = {"trade.status.pending", "trade.status.accepted", "trade.status.cancelled"}

RESOURCE_COLORS = {
    "Odun": (235, 155, 75),
    "Tas": (205, 215, 225),
    "Tahil": (250, 215, 70),
    "Balik": (110, 215, 255),
    "Çiğ Et": (214, 92, 79),
    "Pişmiş Et": (188, 105, 55),
    "Ekmek": (225, 173, 78),
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
        pw, ph = tw + 36, th + 16
        px = max(8, (GAME_WIDTH - pw) // 2)
        py = 56 + y_offset

        card = pygame.Surface((pw + 4, ph + 4), pygame.SRCALPHA)
        pixel_window(card, (0, 0, pw, ph), accent=(210, 155, 75))
        card.blit(surf, (18, 8))
        card.set_alpha(alpha)
        screen.blit(card, (px, py))


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
        self.message = tr("grain.start")

    def close(self):
        self.active   = False
        self._dragging = False

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_event(self, event, logical_mouse_pos=None):
        if not self.active:
            return
        pos = logical_mouse_pos if logical_mouse_pos else window_logical_mouse()

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
                self.message = tr("grain.follow")
            else:
                self.message = tr("grain.start_left")

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
            pos = logical_mouse_pos if logical_mouse_pos else window_logical_mouse()
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
            self.message = tr("grain.too_early")
        elif mean_dev < self._TOLERANCE_PERFECT:
            count = 3
            self.message = tr("grain.perfect")
        elif mean_dev < self._TOLERANCE_GOOD:
            count = 2
            self.message = tr("grain.good")
        elif mean_dev < self._TOLERANCE_POOR:
            count = 1
            self.message = tr("grain.poor")
        else:
            count = 0
            self.message = tr("grain.missed")

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
        pixel_window(screen, self._panel, accent=(140, 115, 55), alpha=215)

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
            pygame.draw.polygon(screen, (20, 20, 20), [(sx - 4, sy - 6), (sx + 6, sy), (sx - 4, sy + 6)])
            pygame.draw.circle(screen, (220, 80, 80), (ex, ey), 12)
            pygame.draw.circle(screen, (255, 255, 255), (ex, ey), 12, 2)

        # ── Progress trail ────────────────────────────────────────────────────
        if self._dragging and self._cursor_idx > 1:
            trail_pts = self._path_pts[:self._cursor_idx]
            if len(trail_pts) > 1:
                pygame.draw.lines(screen, (120, 240, 120), False, trail_pts, 3)

        # ── Scythe cursor ─────────────────────────────────────────────────────
        if self._dragging:
            pos = logical_mouse_pos if logical_mouse_pos else window_logical_mouse()
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
            pixel_bar(screen, (bar_x, bar_y, bar_w, 10), ratio, bar_col, (50, 48, 40), (140, 130, 100))
            accuracy = font.render(tr("grain.accuracy"), True, (210, 195, 140))
            screen.blit(accuracy, (bar_x - accuracy.get_width() - 10, bar_y - 2))

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
        self.on_impact = None
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
        self.message = tr("stone.start")
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
            self.message = tr("stone.timeout")
            self.close()
            return
        # Decay flash timers
        for t in self.targets:
            if t['flash_timer'] > 0:
                t['flash_timer'] = max(0.0, t['flash_timer'] - dt)

    def handle_event(self, event, logical_mouse_pos=None):
        if not self.active:
            return
        pos = logical_mouse_pos if logical_mouse_pos else window_logical_mouse()
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = False
            for t in self.targets:
                if not t['hit'] and t['rect'].collidepoint(pos):
                    t['hit'] = True
                    t['flash_timer'] = 0.25
                    hit = True
                    if callable(self.on_impact):
                        self.on_impact()
                    break

            # Smooth recoil: push cursor 50-90 logical px in a random direction.
            # The move is computed in game pixels and mapped back to the window,
            # so it stays inside the play area at any window size.
            angle = random.uniform(0, 2 * math.pi)
            dist = random.randint(50, 90)
            try:
                cx, cy = pos
                nx = int(cx + dist * math.cos(angle))
                ny = int(cy + dist * math.sin(angle))
                nx = max(10, min(GAME_WIDTH - 10, nx))
                ny = max(10, min(GAME_HEIGHT - 10, ny))
                pygame.mouse.set_pos(VIEWPORT.to_window((nx, ny)))
            except pygame.error:
                pass

            remaining = [t for t in self.targets if not t['hit']]
            if hit and len(remaining) == 0:
                self.node.harvest()
                if hasattr(self, 'on_harvest') and callable(self.on_harvest):
                    self.on_harvest(3)
                self.close()

    def draw_ui(self, screen, font, logical_mouse_pos=None):
        if not self.active:
            return

        # ── Dark overlay panel ────────────────────────────────────────────────
        panel_rect = pygame.Rect(GAME_WIDTH // 2 - 260, GAME_HEIGHT // 2 - 210, 520, 420)
        pixel_window(screen, panel_rect, accent=(120, 112, 98), alpha=210)

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
        pixel_bar(screen, (bar_x, bar_y, bar_w, bar_h), ratio, bar_color, (60, 55, 50), (110, 105, 95))
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
        mouse_pos = logical_mouse_pos if logical_mouse_pos else window_logical_mouse()
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


def wood_axe_sprite(level=1):
    s = pygame.Surface((46, 30), pygame.SRCALPHA)
    pygame.draw.polygon(s, (48, 38, 38),
                        [(13,12),(43,21),(45,26),(41,29),(11,18)])
    pygame.draw.line(s, (157,  94, 54), (15,16), (41,25), 4)
    pygame.draw.line(s, (222, 161, 91), (17,15), (41,23), 1)
    pygame.draw.polygon(s, (43, 47, 54),
                        [(0,3),(8,5),(19,9),(18,20),(7,23),(0,25)])
    blade_colors = ((127,155,158), (169,183,181), (197,174,104), (139,205,230))
    pygame.draw.polygon(s, blade_colors[max(0, min(3, level - 1))],
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
        self.axe_level = 1
        self.required_hits = 4
        self.impact = 1.0
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
        self.on_impact = None
        self.on_fall = None

    def open(self, node, axe_level=1, required_hits=None, impact=None):
        self.active   = True
        self.node     = node
        self.axe_level = max(1, min(4, int(axe_level)))
        self.required_hits = max(1, int(required_hits if required_hits is not None
                                         else 5 - self.axe_level))
        self.impact = max(1.0, float(impact if impact is not None
                                     else 1.0 + (self.axe_level - 1) * .3))
        self.axe = wood_axe_sprite(self.axe_level)
        self.variant  = int(node.x * 31 + node.y * 17) % 3
        self.hits     = 0
        self.phase    = 0.0
        self.timer    = 0.0
        self.state    = 'AIM'
        self.axe_y    = 79.0
        self.good_hit = False
        self.particles = []
        self.message  = tr("wood.start")
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
                if callable(self.on_impact):
                    self.on_impact()
                self.hits += 1
                self.message = tr("wood.hit")
                for _ in range(15 + self.axe_level * 5):
                    self.particles.append([
                        54.0, 79.0,
                        random.uniform(15, 65), random.uniform(-65, 10),
                        random.uniform(0.3, 0.7),
                    ])
            else:
                self.message = tr("wood.miss")
                self.time_remaining = max(0.0, self.time_remaining - self.MISS_PENALTY)

        elif self.state == 'IMPACT' and self.timer >= 0.3 + (self.axe_level - 1) * .025:
            self.state, self.timer = 'RETURN', 0.0

        elif self.state == 'RETURN' and self.timer >= 0.22:
            if self.hits >= self.required_hits:
                # ── Tree is felled ─────────────────────────────────────────
                self.state, self.timer = 'FALL', 0.0
                if callable(self.on_fall):
                    self.on_fall()
                self.message = tr("wood.felled")
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
                self.message = tr("wood.timeout")
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
        draw_text(screen, font, tr("wood.title"),
                  (panel.x + 28, panel.y + 23), (247, 206, 133))
        draw_text(screen, font, tr("wood.status", hits=self.hits, required=self.required_hits,
                                   level=self.axe_level),
                  (panel.x + 28, panel.y + 55), (210, 185, 147))
        draw_text(screen, font, tr("wood.time", seconds=self.time_remaining),
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
            shake = round(math.sin(self.timer * 70) * 2 * self.impact * (1 - min(1.0, self.timer / 0.3)))

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
            axe = self.axe
            if self.state == 'IMPACT' and self.good_hit:
                punch = 1.0 + .08 * (self.axe_level - 1) * max(0.0, 1.0 - self.timer / .25)
                if punch > 1.001:
                    axe = pygame.transform.scale(axe, (round(axe.get_width() * punch),
                                                        round(axe.get_height() * punch)))
            scene.blit(axe, (round(tx + 69 - offset), round(ty + self.axe_y - axe.get_height() / 2)))

        # Wood chip particles
        for x, y, vx, vy, life in self.particles:
            pygame.draw.rect(scene, (245, 188, 111),
                             (round(tx+x), round(ty+y), 2, 2))

        screen.blit(pygame.transform.scale(scene, (630, 396)),
                    (panel.x + 25, panel.y + 96))

        # ── Hit pips ──────────────────────────────────────────────────────────
        for i in range(self.required_hits):
            r = pygame.Rect(panel.x + 28 + i*47, panel.y + 510, 36, 9)
            pygame.draw.rect(screen,
                (233, 173, 93) if i < self.hits else (91, 78, 64), r)

        # ── Footer ────────────────────────────────────────────────────────────
        draw_text(screen, font, self.message,
                  (panel.x + 28, panel.y + 535), (248, 220, 171))
        draw_text(screen, font, tr("wood.controls"),
                  (panel.x + 28, panel.y + 567), (174, 171, 148))


class OpenWaterFishing:
    def __init__(self, seed):
        self.rng = random.Random(seed + 45677)
        self.active = False
        self.port = None
        self.fish_count = 0
        self.on_catch = None
        self.on_cast = None
        self.fishes = []
        self.active_fish = None
        self.fish_sprites = self._make_fish_sprites()
        self.rod_x, self.rod_y = 0.0, 0.0
        self.bobber_x, self.bobber_y = 0.0, 0.0
        self.line_length = 125.0
        self.reel_impulse = 0.0
        self.tension = 0.0
        self.progress = 0.0
        self.message = ""
        self.state = "waiting"
        self.wait_timer = 0.0
        self.escape_timer = 0.0
        self.zoom_level = 1.0
        self.target_zoom = 1.0

    @staticmethod
    def _make_fish_sprites():
        """Three deliberately different 9x6 fish silhouettes, scaled without blur."""
        palettes = (((54, 111, 132), (137, 205, 190), "fork"),
                    ((175, 91, 42), (244, 174, 72), "round"),
                    ((91, 82, 139), (199, 147, 184), "long"))
        sprites = []
        for dark, light, shape in palettes:
            fish = pygame.Surface((11, 7), pygame.SRCALPHA)
            if shape == "long":
                pygame.draw.polygon(fish, dark, [(0, 1), (3, 3), (0, 5), (6, 5), (10, 3), (6, 1)])
                pygame.draw.rect(fish, light, (4, 2, 4, 2))
            elif shape == "round":
                pygame.draw.polygon(fish, dark, [(0, 0), (3, 3), (0, 6), (6, 6), (10, 3), (6, 0)])
                pygame.draw.polygon(fish, light, [(3, 2), (7, 1), (9, 3), (7, 5), (3, 4)])
                pygame.draw.rect(fish, (110, 55, 33), (4, 0, 2, 1))
            else:
                pygame.draw.polygon(fish, dark, [(0, 1), (3, 3), (0, 6), (2, 5), (3, 4),
                                                  (7, 6), (10, 3), (7, 0), (3, 2)])
                pygame.draw.polygon(fish, light, [(3, 2), (7, 1), (9, 3), (7, 5), (3, 4)])
            pygame.draw.rect(fish, (26, 28, 31), (8, 2, 1, 1))
            sprite = pygame.transform.scale(fish, (22, 14))
            sprites.append((sprite, pygame.transform.flip(sprite, True, False)))
        return tuple(sprites)

    @property
    def fish_x(self):
        return self.fishes[self.active_fish]["x"] if self.active_fish is not None else -9999

    @property
    def fish_y(self):
        return self.fishes[self.active_fish]["y"] if self.active_fish is not None else -9999

    def open(self, port, player):
        self.active = True
        self.port = port
        self.rod_x = player.x * LOCAL_TILE_SIZE
        self.rod_y = player.y * LOCAL_TILE_SIZE - 10
        self.line_length = 125.0
        direction = pygame.Vector2(port.dx, port.dy)
        if direction.length_squared() == 0:
            direction.update(0, 1)
        self.bobber_x = self.rod_x + direction.x * self.line_length
        self.bobber_y = self.rod_y + direction.y * self.line_length
        self.fishes.clear()
        self.target_zoom = 1.6
        self.set_waiting(escaped=False)
        if callable(self.on_cast):
            self.on_cast()

    def close(self):
        self.active = False
        self.target_zoom = 1.0

    def set_waiting(self, escaped=False):
        self.state = "waiting"
        self.active_fish = None
        self.progress = 0.0
        self.tension = 0.0
        self.escape_timer = 0.0
        self.wait_timer = self.rng.uniform(1.5, 3.5)
        self.message = tr("fish.escaped") if escaped else tr("fish.waiting")

    def _water_point(self, world, radius=170):
        base_x = (self.port.x + self.port.dx * 3 + 0.5) * LOCAL_TILE_SIZE
        base_y = (self.port.y + self.port.dy * 3 + 0.5) * LOCAL_TILE_SIZE
        for _ in range(40):
            angle = self.rng.uniform(0, math.tau)
            distance = self.rng.uniform(38, radius)
            x, y = base_x + math.cos(angle) * distance, base_y + math.sin(angle) * distance
            gx, gy = int(x / LOCAL_TILE_SIZE), int(y / LOCAL_TILE_SIZE)
            if 0 <= gx < COLS and 0 <= gy < ROWS and world.heights[gy][gx] < SEA_LEVEL:
                return x, y
        return base_x, base_y

    def _spawn_school(self, world):
        while len(self.fishes) < 4:
            x, y = self._water_point(world)
            tx, ty = self._water_point(world)
            index = len(self.fishes)
            self.fishes.append({"x": x, "y": y, "tx": tx, "ty": ty,
                                "variant": index % 3, "heading": 1.0,
                                "decision": self.rng.uniform(.3, 1.1), "flee": 0.0,
                                "speed": self.rng.uniform(34, 50), "phase": self.rng.uniform(0, math.tau)})

    def spawn_fish(self, world):
        self._spawn_school(world)
        self.state = "fishing"
        self.active_fish = min(range(len(self.fishes)),
                               key=lambda index: math.hypot(self.fishes[index]["x"] - self.bobber_x,
                                                            self.fishes[index]["y"] - self.bobber_y))
        fish = self.fishes[self.active_fish]
        fish["tx"], fish["ty"] = self.bobber_x, self.bobber_y
        self.message = tr("fish.hooked")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e):
            self.close()
        elif event.type == pygame.MOUSEWHEEL:
            amount = max(-3, min(3, event.y))
            self.line_length = max(48.0, min(225.0, self.line_length - amount * 14.0))
            self.reel_impulse += amount
            if self.state == "fishing" and self.active_fish is not None:
                fish = self.fishes[self.active_fish]
                distance = math.hypot(fish["x"] - self.bobber_x, fish["y"] - self.bobber_y)
                if amount > 0 and distance < 34:
                    self.progress = min(1.0, self.progress + amount * .11)
                    self.tension = min(1.25, self.tension + amount * .12)
                elif amount < 0:
                    self.tension = max(0.0, self.tension + amount * .16)

    def _catch(self, world):
        caught = self.fishes[self.active_fish]
        caught["x"], caught["y"] = self._water_point(world)
        caught["tx"], caught["ty"] = self._water_point(world)
        self.fish_count += 1
        self.set_waiting(escaped=False)
        self.message = tr("fish.caught", count=self.fish_count)
        if callable(self.on_catch):
            self.on_catch(1)

    def update(self, dt, mouse_world_x, mouse_world_y, world):
        self.zoom_level += (self.target_zoom - self.zoom_level) * 4 * dt
        if not self.active: return
        dt = min(.06, max(0.0, dt))
        self._spawn_school(world)
        aim = pygame.Vector2(mouse_world_x - self.rod_x, mouse_world_y - self.rod_y)
        if aim.length_squared() < 1:
            aim.update(self.port.dx, self.port.dy)
        aim.normalize_ip()
        desired_x = self.rod_x + aim.x * self.line_length
        desired_y = self.rod_y + aim.y * self.line_length
        gx, gy = int(desired_x / LOCAL_TILE_SIZE), int(desired_y / LOCAL_TILE_SIZE)
        if 0 <= gx < COLS and 0 <= gy < ROWS and world.heights[gy][gx] < SEA_LEVEL:
            follow = min(1.0, dt * 7.5)
            self.bobber_x += (desired_x - self.bobber_x) * follow
            self.bobber_y += (desired_y - self.bobber_y) * follow
        self.tension = max(0.0, self.tension - dt * .18)
        self.reel_impulse *= .82 ** (dt * 60)

        if self.state == "waiting":
            self.wait_timer -= dt
            if self.wait_timer <= 0: self.spawn_fish(world)

        for index, fish in enumerate(self.fishes):
            fish["decision"] -= dt
            fish["phase"] += dt * 2.5
            hook_dx, hook_dy = fish["x"] - self.bobber_x, fish["y"] - self.bobber_y
            hook_distance = math.hypot(hook_dx, hook_dy)
            interested = self.state == "fishing" and index == self.active_fish
            if interested and self.tension < .82 and self.reel_impulse < 2.2:
                orbit = math.sin(fish["phase"]) * 13
                fish["tx"], fish["ty"] = self.bobber_x - aim.y * orbit, self.bobber_y + aim.x * orbit
            elif hook_distance < (52 if interested else 38) or self.tension > .9:
                away = pygame.Vector2(hook_dx, hook_dy)
                if away.length_squared() < 1:
                    away.update(self.rng.uniform(-1, 1), self.rng.uniform(-1, 1))
                away.normalize_ip()
                fish["tx"], fish["ty"] = fish["x"] + away.x * 115, fish["y"] + away.y * 115
                fish["flee"] = .8
            elif fish["decision"] <= 0:
                fish["tx"], fish["ty"] = self._water_point(world)
                fish["decision"] = self.rng.uniform(.7, 2.2)
            fish["flee"] = max(0.0, fish["flee"] - dt)
            dx, dy = fish["tx"] - fish["x"], fish["ty"] - fish["y"]
            distance = math.hypot(dx, dy)
            if distance > 1:
                speed = fish["speed"] * (2.0 if fish["flee"] > 0 else 1.0)
                nx, ny = fish["x"] + dx / distance * speed * dt, fish["y"] + dy / distance * speed * dt
                gx, gy = int(nx / LOCAL_TILE_SIZE), int(ny / LOCAL_TILE_SIZE)
                if 0 <= gx < COLS and 0 <= gy < ROWS and world.heights[gy][gx] < SEA_LEVEL:
                    fish["x"], fish["y"] = nx, ny
                    fish["heading"] = dx
                else:
                    fish["tx"], fish["ty"] = self._water_point(world)

        if self.state == "fishing" and self.active_fish is not None:
            fish = self.fishes[self.active_fish]
            distance = math.hypot(fish["x"] - self.bobber_x, fish["y"] - self.bobber_y)
            if distance < 22 and self.tension < .95:
                fish["x"] += (self.bobber_x - fish["x"]) * min(1, dt * 3)
                fish["y"] += (self.bobber_y - fish["y"]) * min(1, dt * 3)
                self.progress = min(1.0, self.progress + dt * .035)
            else:
                self.progress = max(0.0, self.progress - dt * (.06 + distance * .0015))
            escaping = distance > 100 or self.tension >= 1.0
            self.escape_timer = self.escape_timer + dt if escaping else max(0, self.escape_timer - dt * 2)
            if self.progress >= 1.0 and self.line_length <= 72:
                self._catch(world)
            elif self.escape_timer > .75:
                fish["flee"] = 1.4
                self.set_waiting(escaped=True)

    def draw_world(self, screen, camera_x, camera_y, player):
        if not self.active: return
        screen_bobber_x = int(self.bobber_x - camera_x)
        screen_bobber_y = int(self.bobber_y - camera_y)
        screen_player_x = int(player.x * LOCAL_TILE_SIZE - camera_x)
        screen_player_y = int(player.y * LOCAL_TILE_SIZE - camera_y)
        hand = pygame.Vector2(screen_player_x + 5, screen_player_y - 15)
        toward = pygame.Vector2(screen_bobber_x, screen_bobber_y) - hand
        if toward.length_squared() < 1:
            toward.update(0, -1)
        toward.normalize_ip()
        tip = hand + toward * 32 + pygame.Vector2(0, -10)
        butt = hand - toward * 7
        pygame.draw.line(screen, (43, 28, 22), butt, tip, 6)
        pygame.draw.line(screen, (137, 79, 38), butt, tip, 3)
        pygame.draw.line(screen, (232, 167, 78), hand + toward * 10, tip, 1)
        pygame.draw.line(screen, (229, 224, 201), tip, (screen_bobber_x, screen_bobber_y), 1)
        reel = (round(hand.x - toward.y * 5), round(hand.y + toward.x * 5))
        pygame.draw.circle(screen, (42, 31, 26), reel, 5)
        pygame.draw.circle(screen, (211, 156, 66), reel, 3, 1)
        for index, fish in enumerate(self.fishes):
            sprite = self.fish_sprites[fish["variant"]][0 if fish["heading"] >= 0 else 1]
            x, y = round(fish["x"] - camera_x), round(fish["y"] - camera_y + math.sin(fish["phase"]) * 2)
            screen.blit(sprite, sprite.get_rect(center=(x, y)))
            if index == self.active_fish and self.state == "fishing":
                pygame.draw.rect(screen, (245, 214, 116), (x - 2, y - 13, 4, 3))
        pygame.draw.rect(screen, (218, 82, 48), (screen_bobber_x - 2, screen_bobber_y - 4, 4, 5))
        pygame.draw.rect(screen, (244, 226, 165), (screen_bobber_x - 1, screen_bobber_y + 1, 2, 4))
        pygame.draw.line(screen, (190, 196, 190), (screen_bobber_x, screen_bobber_y + 4),
                         (screen_bobber_x + 3, screen_bobber_y + 9), 1)
        pygame.draw.line(screen, (190, 196, 190), (screen_bobber_x + 3, screen_bobber_y + 9),
                         (screen_bobber_x + 6, screen_bobber_y + 7), 1)

        bar_w, bar_h = 40, 6
        bar_x = screen_player_x - bar_w // 2
        bar_y = screen_player_y - 35
        pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
        if self.progress > 0:
            fill_w = int(bar_w * self.progress)
            pygame.draw.rect(screen, (100, 220, 100), (bar_x, bar_y, fill_w, bar_h))
        tension_w = int(bar_w * min(1, self.tension))
        pygame.draw.rect(screen, (45, 32, 25), (bar_x, bar_y + 8, bar_w, 3))
        pygame.draw.rect(screen, (235, 80, 55) if self.tension > .82 else (232, 174, 63),
                         (bar_x, bar_y + 8, tension_w, 3))

    def draw_ui(self, screen, font):
        if not self.active: return
        pixel_window(screen, (GAME_WIDTH // 2 - 300, GAME_HEIGHT - 110, 600, 72), accent=(186, 149, 91))
        draw_text(screen, font, self.message, (GAME_WIDTH // 2 - 280, GAME_HEIGHT - 94), (244, 218, 165))
        draw_text(screen, font, tr("fish.controls", length=int(self.line_length)),
                  (GAME_WIDTH // 2 - 280, GAME_HEIGHT - 68), (186, 212, 205))


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
    INTERACT_KEY = pygame.K_e
    EMBARK_KEY = pygame.K_f
    # Walking keys; double-tapping one of them is the Dash (Windstep) input.
    MOVE_KEYS = {
        pygame.K_w: ("up", (0, -1)), pygame.K_UP: ("up", (0, -1)),
        pygame.K_s: ("down", (0, 1)), pygame.K_DOWN: ("down", (0, 1)),
        pygame.K_a: ("left", (-1, 0)), pygame.K_LEFT: ("left", (-1, 0)),
        pygame.K_d: ("right", (1, 0)), pygame.K_RIGHT: ("right", (1, 0)),
    }
    SAGE_TALK_RADIUS = 1.8

    def __init__(self, world, ports, spawn, tiles, network, seed, customization, atlas=None,
                 character_sheet=None, audio=None, save_data=None):
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
        self.audio = audio
        self.audio_active = False
        self.atlas = atlas
        self.character_sheet = (character_sheet if character_sheet is not None
                                else load_required_character_sheet())
        hull = pygame.image.load(str(require_asset(SAILBOAT_HULL_ASSET))).convert_alpha()
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
        self.player_animation = CharacterAnimator()
        self.remote_animations = {}
        self.remote_combats = {}
        self.remote_combat_revisions = {}
        self.pvp_hit_flashes = {}
        self.terrain_renderer = TerrainRenderer(world, atlas) if atlas else None

        self.hud = PixelHUD()
        self.interaction_prompt = PixelInteractionPrompt()
        self.map_ui = WorldMapUI(world, tiles, GAME_WIDTH, GAME_HEIGHT)
        self.leaves = AutumnLeaves(seed, world, atlas, LOCAL_TILE_SIZE, (GAME_WIDTH, GAME_HEIGHT))
        self.fishing = OpenWaterFishing(seed)
        self.grain_game = GrainHarvesting(seed)
        self.stone_game = StoneMining()
        self.wood_game = WoodChopping()
        self.dialogue = DialogueBox()
        # Decode, clean, scale, and cache the nonuniform atlas during session
        # setup rather than hitching on the first visible villager.
        preload_villager_sprites()
        self.quest_system = QuestSystem(world)
        candidate_save = (dict(save_data) if isinstance(save_data, dict)
                          and not (network and network.connected) else {})
        self.local_save = (candidate_save if save_seed(candidate_save) in (None, world.seed)
                           else {})
        self.treant_progress = TreantQuestProgress.from_dict(self.local_save.get("treant_progress"))
        self.autosave_timer = AUTOSAVE_INTERVAL
        # Only the session the player actually entered autosaves (set by the app),
        # so preloaded or tool/test sessions never touch the real save file.
        self.autosave_enabled = False
        self.treant_encounter = TreantBossEncounter(
            BASE_DIR, TreantConfig(tile_size=LOCAL_TILE_SIZE)
        )
        # The session returns the player to the island automatically.
        self.treant_encounter.defeat_hint = tr("boss.returning")
        self.boss_active = False
        # True while the server owns the running encounter; losing the connection
        # then abandons the fight instead of continuing it locally.
        self.boss_online = False
        self.boss_return_position = tuple(world.boss_return or assigned_spawn)
        self.boss_attack_sequence = 0
        self.boss_attack_id = None
        self.boss_completion_pending = False
        self.boss_completion_result = None
        self.boss_completion_timer = 0.0
        self.portal_unlock_timer = 0.0
        self.portal_unlock_duration = 1.35
        self.achievement_popup = None
        self.achievement_popup_timer = 0.0
        self.treant_portal_sprite = self.treant_encounter.assets.props["portal"]
        self.treant_portal_locked = self.treant_portal_sprite.copy()
        shade = pygame.Surface(self.treant_portal_locked.get_size(), pygame.SRCALPHA)
        shade.fill((88, 70, 80, 255))
        self.treant_portal_locked.blit(shade, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.animal_system = AnimalSystem(world)
        self.combat = CombatSystem()
        self.enemy_ai = EnemyAISystem()
        self.naval = NavalEncounterSystem(
            world, seed, lambda x, y: can_stand(world, x, y, True))

        # Connect minigame harvest callbacks
        self.grain_game.on_harvest = lambda count=3: self.harvest_reward("Tahil", count)
        self.stone_game.on_harvest = lambda count=3: self.harvest_reward("Tas", count)
        self.wood_game.on_harvest = lambda count=4: self.harvest_reward("Odun", count)
        self.fishing.on_catch = lambda count=1: self.add_resource("Balik", count)
        self.fishing.on_cast = lambda: self._play_sfx(
            "throwing_fishing_rod", "interaction")
        self.stone_game.on_impact = lambda: self._play_sfx(
            "breaking_stone", "interaction", cooldown=0, max_instances=1,
            restart_if_busy=True)
        self.wood_game.on_impact = lambda: self._play_random_sfx(
            ("axe_chop_1", "axe_chop_2"), "interaction")
        self.wood_game.on_fall = lambda: self._play_sfx(
            "tree_falling", "interaction", max_instances=1)
        self.combat.on_attack = lambda _kind: self._play_random_sfx(
            ("sword_slice_1", "sword_slice_2"), "combat", restart_if_busy=True)

        # Inventory & Conquest Economy
        self.inventory = {
            "Odun": 8,
            "Tas": 6,
            "Tahil": 4,
            "Balik": 2,
            "Çiğ Et": 0,
            "Pişmiş Et": 0,
            "Ekmek": 0,
            "Ok": 10,
            "Kadim Anahtar": self.treant_progress.keys_held,
        }
        self.equipment = {"axe": True, "sword": DEBUG_STARTING_EQUIPMENT,
                          "bow": DEBUG_STARTING_EQUIPMENT}
        self.progression = ProgressionSystem()
        sword = self.progression.stats("sword")
        self.combat.configure_weapon(sword.damage_bonus, sword.range_multiplier,
                                     sword.attack_speed_multiplier)
        self.loot_rng = random.Random(seed + 44017)
        self.max_health = 8
        self.health = self.max_health
        self.max_energy = 100
        self.energy = self.max_energy
        self.damage_cooldown = 0.0
        self.player_hit_flash = 0.0
        self.player_knockback = pygame.Vector2()
        self.impact_particles = []
        self.loot_drops = []
        self.next_loot_id = 1
        self.processed_deaths = set()
        self.combat_xp = 0
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
        self.inventory_action_rects = []
        self.trade_button = self.hud.trade_button
        self.trade_open = False
        self.cooking_open = False
        self.cooking_close_rect = pygame.Rect(0, 0, 30, 30)
        self.cooking_action_rects = []
        self.cooking_cooldown = 0.0
        self.trade_close_rect = pygame.Rect(0, 0, 32, 32)
        self.trade_selected_partner = None
        self.trade_offer = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
        self.trade_request = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
        self.trade_send_btn = pygame.Rect(0, 0, 160, 36)
        self.trade_action_rects = []
        self.processed_trades = set()
        self.conquer_action_rect = pygame.Rect(0, 0, 220, 38)
        self.inventory_rescue_map_rect = pygame.Rect(600, 232, 340, 116)
        self.rescue_map_open = False
        self.game_time = 0.0
        self.last_direction_tap = {"up": -10.0, "down": -10.0, "left": -10.0, "right": -10.0}
        self.held_direction_keys = set()
        self.dash_timer = 0.0
        self.dash_cooldown = 0.0
        self.dash_power = 1.0
        self.dash_direction = pygame.Vector2(0, -1)
        self.dash_effect_timer = 0.0
        self.dash_effects = []
        # Dash (Windstep) is earned: the Wandering Sage teaches it after the
        # player's first liberated island.  Restored from the save below.
        self.dash_unlocked = False
        self.sage = None
        self.sage_particles = []
        self.ability_popup_timer = 0.0
        self.unlock_glow_timer = 0.0
        self.execution = None
        self.combat_rng = random.Random(seed + 99173)
        self.local_inflation = 1.0
        self.capture_count = (self.network.capture_count if self.network and hasattr(self.network, 'capture_count')
                              else len(self.island_owners))
        self._apply_local_save()

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
        self.font = PixelFont(24)
        self.small_font = PixelFont(21)
        self.tiny_font = PixelFont(18)

        # In-game pause modal state
        self.paused = False
        self.layout_view()
        self._last_boss_audio_state = None

    def layout_view(self):
        """Anchor view-dependent UI to the current logical view size.

        The gameplay view widens (or deepens) with the window's aspect ratio, so
        everything centred or right/bottom-anchored is recomputed here whenever
        the app changes ``GAME_WIDTH``/``GAME_HEIGHT``.  The world is untouched.
        """
        self.map_ui.resize(GAME_WIDTH, GAME_HEIGHT)
        self.world_map = self.map_ui.full_surface
        self.map_rect = self.map_ui.full_rect
        self.map_button = self.map_ui.minimap_rect
        self.leaves.viewport = (GAME_WIDTH, GAME_HEIGHT)
        self.hud_conquer_rect = pygame.Rect(GAME_WIDTH // 2 - 180, GAME_HEIGHT - 74, 360, 38)
        self.rescue_map_button = pygame.Rect(self.hud_conquer_rect.right + 8, self.hud_conquer_rect.y, 104, 38)
        self.rescue_map_rect = pygame.Rect(GAME_WIDTH // 2 - 180, self.hud_conquer_rect.y - 154, 360, 142)
        self.victory_continue_rect = pygame.Rect(GAME_WIDTH // 2 - 190, GAME_HEIGHT // 2 + 100, 180, 42)
        self.victory_menu_rect = pygame.Rect(GAME_WIDTH // 2 + 10, GAME_HEIGHT // 2 + 100, 180, 42)
        self.pause_resume_rect = pygame.Rect(GAME_WIDTH // 2 - 120, GAME_HEIGHT // 2 - 40, 240, 40)
        self.pause_menu_rect = pygame.Rect(GAME_WIDTH // 2 - 120, GAME_HEIGHT // 2 + 15, 240, 40)
        if hasattr(self, "cam_x") and not self.boss_active:
            # Re-clamp the camera to the new view so the world edge never shows.
            self.cam_x, self.cam_y = get_local_camera(self.player)

    # -----------------------------------------------------------------------
    # Offline save / restore (online progress is owned by the server)
    # -----------------------------------------------------------------------
    @staticmethod
    def _saved_count(value, limit=999_999):
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return max(0, min(limit, number))

    @staticmethod
    def _saved_float(value, low, high):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return max(low, min(high, number)) if math.isfinite(number) else None

    def _apply_local_save(self):
        """Restore offline progress; every field is validated independently."""
        save = self.local_save
        if not save:
            return
        section = lambda key: save.get(key) if isinstance(save.get(key), dict) else {}
        self.dash_unlocked = save.get("dash_unlocked") is True

        player = section("player")
        x = self._saved_float(player.get("x"), 0, COLS - 1)
        y = self._saved_float(player.get("y"), 0, ROWS - 1)
        if x is not None and y is not None and can_stand(self.world, x, y, False):
            self.player.update(x, y)
            index = self.world.owners[int(y)][int(x)]
            if 0 <= index < len(self.world.islands):
                self.spawn_island = index
        elif player.get("spawn") == "boss_portal" and self.world.boss_portal:
            self.player.update(self.world.boss_portal)
            self.spawn_island = self.world.boss_island_index

        for item, amount in section("inventory").items():
            amount = self._saved_count(amount)
            if isinstance(item, str) and amount is not None:
                self.inventory[item] = amount
        # The quest object is authoritative for keys; the inventory mirrors it.
        self.inventory["Kadim Anahtar"] = self.treant_progress.keys_held
        for weapon, owned in section("equipment").items():
            if weapon in self.equipment:
                self.equipment[weapon] = bool(owned)
        try:
            self.progression = ProgressionSystem(section("weapon_levels"))
        except (TypeError, ValueError):
            self.progression = ProgressionSystem()
        sword = self.progression.stats("sword")
        self.combat.configure_weapon(sword.damage_bonus, sword.range_multiplier,
                                     sword.attack_speed_multiplier)

        stats = section("stats")
        health = self._saved_count(stats.get("health"), self.max_health)
        self.health = health if health else self.max_health
        energy = self._saved_float(stats.get("energy"), 0, self.max_energy)
        self.energy = self.max_energy if energy is None else energy
        self.combat_xp = self._saved_count(stats.get("combat_xp")) or 0
        self.game_time = self._saved_float(stats.get("game_time"), 0, 10 ** 7) or 0.0

        rescued = save.get("rescued_islands")
        for index in rescued if isinstance(rescued, list) else ():
            if isinstance(index, int) and 0 <= index < len(self.world.islands):
                self.island_owners[index] = self.my_player_id()
                self.world.islands[index].owner = self.my_player_id()
        self.capture_count = len(self.island_owners)
        if self.capture_count >= self.WINNING_COUNT:
            self.winner = self.my_player_id()
            self.victory_dismissed = True  # Already celebrated in the saved run.

        for quest_id, state in section("quests").items():
            quest = self.quest_system.quests.get(quest_id)
            if quest is None or not isinstance(state, dict):
                continue
            if state.get("state") in ("available", "active", "ready", "completed"):
                quest.state = state["state"]
            progress = self._saved_count(state.get("progress"), quest.required)
            if progress is not None:
                quest.progress = progress
        defeated = save.get("defeated_monsters")
        defeated = {str(value) for value in defeated} if isinstance(defeated, list) else set()
        for monster in self.quest_system.monsters:
            if monster.id in defeated:
                monster.alive = False
                self.processed_deaths.add(monster.id)
        print(f"[SAVE] Restored offline progress ({len(self.island_owners)} rescued islands, "
              f"{self.treant_progress.keys_held} keys).")

    def save_snapshot(self):
        """The JSON-serializable offline progress of this session."""
        if self.boss_active:
            x, y = self.boss_return_position
        elif self.is_sailing or not can_stand(self.world, self.player.x, self.player.y, False):
            # Never strand a loaded player at sea: keep the last saved land position.
            previous = self.local_save.get("player")
            x, y = ((previous.get("x"), previous.get("y")) if isinstance(previous, dict)
                    else (None, None))
        else:
            x, y = self.player.x, self.player.y
        player = ({"x": round(float(x), 3), "y": round(float(y), 3)}
                  if x is not None and y is not None else {})
        my_id = self.my_player_id()
        return {
            "world_seed": int(self.world.seed),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "player": player,
            "inventory": {item: int(amount) for item, amount in self.inventory.items()},
            "equipment": {weapon: bool(owned) for weapon, owned in self.equipment.items()},
            "weapon_levels": dict(self.progression.levels),
            "stats": {"health": int(self.health), "energy": round(float(self.energy), 2),
                      "combat_xp": int(self.combat_xp), "game_time": round(self.game_time, 2)},
            "rescued_islands": sorted(int(index) for index, owner in self.island_owners.items()
                                      if owner == my_id),
            "quests": {quest.id: {"state": quest.state, "progress": quest.progress}
                       for quest in self.quest_system.quests.values()
                       if quest.state != "available" or quest.progress},
            "defeated_monsters": sorted(monster.id for monster in self.quest_system.monsters
                                        if not monster.alive),
            "treant_progress": self.treant_progress.to_dict(),
            "dash_unlocked": bool(self.dash_unlocked),
        }

    def save_progress(self, reason="manual"):
        """Write offline progress; online sessions are saved by the server."""
        if self.network and self.network.connected:
            return False
        try:
            snapshot = self.save_snapshot()
            write_save(snapshot, SAVE_FILE)
        except (OSError, TypeError, ValueError) as exc:
            print(f"[SAVE] Could not save progress ({reason}): {exc}")
            return False
        self.local_save = snapshot
        self.autosave_timer = AUTOSAVE_INTERVAL
        return True

    def request_autosave(self, delay=1.0):
        """Save shortly after a milestone (rescue, key, boss result)."""
        self.autosave_timer = min(self.autosave_timer, delay)

    def _tick_autosave(self, dt):
        if not self.autosave_enabled:
            return
        self.autosave_timer -= max(0.0, dt)
        if self.autosave_timer <= 0:
            if not self.save_progress("autosave"):
                self.autosave_timer = AUTOSAVE_INTERVAL

    # -----------------------------------------------------------------------
    # The Wandering Sage and the Windstep (Dash) unlock
    # -----------------------------------------------------------------------
    def liberated_island_count(self):
        """Islands owned by this player (server-confirmed when online)."""
        my_id = self.my_player_id()
        owners = self.island_owners
        if self.network and self.network.connected:
            # A local rescue is optimistic until the server's ownership confirms it.
            with self.network.lock:
                owners = dict(self.network.island_owners)
        return sum(1 for owner in owners.values() if owner == my_id)

    def dash_binding_label(self):
        order = ("up", "left", "down", "right")
        letters = [self.key_label(key) for key, (direction, _) in
                   sorted(self.MOVE_KEYS.items(), key=lambda item: order.index(item[1][0]))
                   if len(pygame.key.name(key)) == 1]
        return tr("ability.binding", keys="/".join(letters))

    def sage_nearby(self):
        sage = self.sage
        return (sage is not None and sage["leaving"] is None and sage["age"] >= .6
                and not self.is_sailing and not self.boss_active
                and math.hypot(self.player.x - sage["x"], self.player.y - sage["y"]) <= self.SAGE_TALK_RADIUS)

    def _sage_may_appear(self):
        return not (self.boss_active or self.is_sailing or self.paused or self.map_open
                    or self.dialogue.active or self.execution is not None or self.fishing.active
                    or self.grain_game.active or self.stone_game.active or self.wood_game.active
                    or self.cooking_open or (self.winner is not None and not self.victory_dismissed))

    def _sage_spot(self):
        """A walkable spot beside the player, preferring the direction they face."""
        fx, fy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0),
                  "right": (1, 0)}.get(self.facing, (0, 1))
        base = math.atan2(fy, fx)
        for radius in (2.0, 2.6, 1.6, 3.2):
            for step in range(12):
                angle = base + ((step + 1) // 2) * (1 if step % 2 else -1) * math.pi / 6
                x = self.player.x + math.cos(angle) * radius
                y = self.player.y + math.sin(angle) * radius
                if (can_stand(self.world, x, y, False)
                        and (int(x), int(y)) not in self.world.buildings):
                    return x, y
        return None

    def _sage_burst(self, x, y, count, palette=((150, 190, 255), (215, 235, 255), (190, 150, 255))):
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(.6, 2.2)
            life = random.uniform(.45, 1.0)
            self.sage_particles.append([x + math.cos(angle) * .2, y - random.uniform(.2, 1.2),
                                        math.cos(angle) * speed, math.sin(angle) * speed - .6,
                                        life, life, random.choice(palette)])

    def _place_sage(self):
        spot = self._sage_spot()
        if spot is None:
            return False
        if self.sage is None:
            self.sage = {"x": spot[0], "y": spot[1], "age": 0.0, "leaving": None}
        else:
            self.sage.update(x=spot[0], y=spot[1], age=0.0)
        self._sage_burst(spot[0], spot[1], 28)
        return True

    def update_sage(self, dt):
        """Bring the Sage after the first liberation until Windstep is learned.

        The check is state-based rather than a one-shot event, so quitting
        mid-encounter or loading an older save never strands the unlock.
        """
        self.ability_popup_timer = max(0.0, self.ability_popup_timer - dt)
        self.unlock_glow_timer = max(0.0, self.unlock_glow_timer - dt)
        for particle in self.sage_particles:
            particle[0] += particle[2] * dt
            particle[1] += particle[3] * dt
            particle[3] -= .9 * dt
            particle[4] -= dt
        self.sage_particles = [particle for particle in self.sage_particles if particle[4] > 0]

        sage = self.sage
        if sage is None:
            if (not self.dash_unlocked and self.liberated_island_count() > 0
                    and self._sage_may_appear() and self._place_sage()):
                self.add_toast(tr("sage.arrives"), color=(196, 206, 255))
            return
        sage["age"] += dt
        if random.random() < dt * 7:  # Motes drifting off the staff crystal.
            self.sage_particles.append([sage["x"] + .45 + random.uniform(-.1, .1), sage["y"] - 1.25,
                                        random.uniform(-.25, .25), random.uniform(-.7, -.3),
                                        .9, .9, random.choice(((150, 225, 255), (220, 240, 255)))])
        if sage["leaving"] is not None:
            sage["leaving"] -= dt
            if sage["leaving"] <= 0:
                self.sage = None
        elif self.dash_unlocked:
            sage["leaving"] = 1.2
        elif (math.hypot(self.player.x - sage["x"], self.player.y - sage["y"]) > 18
              and self._sage_may_appear()):
            # The Sage follows a hero who wandered off instead of waiting forever.
            self._place_sage()

    def talk_to_sage(self):
        pages = [tr("sage.line1"), tr("sage.line2"), tr("sage.line3"), tr("sage.line4"),
                 tr("sage.line5"), tr("sage.line6"),
                 tr("sage.line7", binding=self.dash_binding_label())]
        # Closing the dialogue early leaves the Sage waiting; only the last page unlocks.
        self.dialogue.open(tr("sage.name"), pages, self.unlock_dash)
        return True

    def unlock_dash(self):
        """Permanently grant Windstep; repeated calls never grant it twice."""
        if self.dash_unlocked:
            return False
        self.dash_unlocked = True
        self.dash_cooldown = 0.0
        self.ability_popup_timer = 6.0
        self.unlock_glow_timer = 1.4
        self._sage_burst(self.player.x, self.player.y, 36,
                         ((140, 215, 255), (235, 250, 255), (110, 180, 255)))
        if self.sage is not None:
            self.sage["leaving"] = 1.2
            self._sage_burst(self.sage["x"], self.sage["y"], 24)
        self.add_toast(tr("ability.toast", binding=self.dash_binding_label()), color=(170, 225, 255))
        self.request_autosave()
        return True

    def draw_sage(self, screen, camera_x, camera_y):
        sage = self.sage
        x = round(sage["x"] * LOCAL_TILE_SIZE) - camera_x
        y = round(sage["y"] * LOCAL_TILE_SIZE) - camera_y
        if sage["leaving"] is not None:
            alpha = max(0.0, sage["leaving"] / 1.2)
        else:
            alpha = min(1.0, sage["age"] / .8)
        pulse = .5 + .5 * math.sin(sage["age"] * 3.2)
        glow = pygame.Surface((96, 40), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (120, 160, 255, round((40 + 30 * pulse) * alpha)), glow.get_rect())
        pygame.draw.ellipse(glow, (190, 215, 255, round(45 * alpha)), glow.get_rect().inflate(-36, -16))
        screen.blit(glow, glow.get_rect(center=(x, y)))
        if sage["age"] < .8 and sage["leaving"] is None:
            # Arrival: a ring of light that widens as the Sage materializes.
            ring = round(14 + sage["age"] * 50)
            pygame.draw.ellipse(screen, (205, 225, 255), (x - ring, y - ring // 3, ring * 2, ring * 2 // 3), 2)
        sprite = wizard_sprite(int(sage["age"] * 2.5) % 2)
        if alpha < 1.0:
            sprite = sprite.copy()
            sprite.set_alpha(round(255 * alpha))
        screen.blit(sprite, sprite.get_rect(midbottom=(x, y + 3)))

    def draw_sage_effects(self, screen, camera_x, camera_y):
        for px, py, _vx, _vy, life, max_life, color in self.sage_particles:
            sx = round(px * LOCAL_TILE_SIZE) - camera_x
            sy = round(py * LOCAL_TILE_SIZE) - camera_y
            size = 3 if life > max_life * .5 else 2
            pygame.draw.rect(screen, color, (sx - size // 2, sy - size // 2, size, size))
        if self.unlock_glow_timer > 0:
            progress = 1.0 - self.unlock_glow_timer / 1.4
            px = round(self.player.x * LOCAL_TILE_SIZE) - camera_x
            py = round(self.player.y * LOCAL_TILE_SIZE) - camera_y - 26
            radius = round(20 + progress * 46)
            glow = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            center = (radius + 2, radius + 2)
            pygame.draw.circle(glow, (130, 200, 255, round(90 * (1 - progress))), center, radius)
            pygame.draw.circle(glow, (240, 250, 255, round(220 * (1 - progress))), center, radius, 3)
            screen.blit(glow, glow.get_rect(center=(px, py)))

    @staticmethod
    def _windstep_icon(size=40):
        icon = pygame.Surface((20, 20), pygame.SRCALPHA)
        for offset, color in ((0, (95, 170, 255)), (5, (170, 225, 255)), (10, (245, 252, 255))):
            pygame.draw.polygon(icon, (25, 35, 60), [(offset, 3), (offset + 6, 10), (offset, 17),
                                                     (offset + 3, 17), (offset + 9, 10), (offset + 3, 3)])
            pygame.draw.polygon(icon, color, [(offset + 1, 5), (offset + 5, 10), (offset + 1, 15),
                                              (offset + 3, 15), (offset + 7, 10), (offset + 3, 5)])
        return pygame.transform.scale(icon, (size, size))

    def draw_ability_popup(self, screen):
        if self.ability_popup_timer <= 0:
            return
        width, height = 470, 128
        card = pygame.Surface((width + 4, height + 4), pygame.SRCALPHA)  # + window shadow
        content = pixel_window(card, (0, 0, width, height), tr("ability.unlocked"), self.font,
                               accent=(120, 190, 255), title_color=(215, 238, 255))
        elapsed = 6.0 - self.ability_popup_timer
        pulse = .5 + .5 * math.sin(elapsed * 6)
        icon_center = (content.x + 34, content.y + content.height // 2)
        halo = pygame.Surface((76, 76), pygame.SRCALPHA)
        pygame.draw.circle(halo, (130, 200, 255, round(60 + 70 * pulse)), (38, 38), 30 + round(5 * pulse))
        pygame.draw.circle(halo, (235, 248, 255, round(140 * pulse)), (38, 38), 30 + round(5 * pulse), 2)
        card.blit(halo, halo.get_rect(center=icon_center))
        icon = self._windstep_icon()
        card.blit(icon, icon.get_rect(center=icon_center))
        draw_text(card, self.font, tr("ability.windstep"), (content.x + 76, content.y + 10),
                  (190, 230, 255), shadow=True)
        draw_text(card, self.small_font, self.dash_binding_label(), (content.x + 76, content.y + 44),
                  (236, 222, 190))
        # Slide in from above, then fade out over the last half second.
        slide = min(1.0, elapsed / .35)
        card.set_alpha(round(255 * min(1.0, self.ability_popup_timer / .5)))
        screen.blit(card, ((GAME_WIDTH - width) // 2, round(-height + (height + 92) * slide)))

    def _play_sfx(self, name, category="interaction", **kwargs):
        if self.audio is not None:
            return self.audio.play_sfx(name, category, **kwargs)
        return False

    def _play_random_sfx(self, names, category="interaction", **kwargs):
        if self.audio is not None:
            return self.audio.play_random_sfx(names, category, **kwargs)
        return None

    def activate_audio(self):
        self.audio_active = True
        if self.audio is not None:
            self.audio.activate_gameplay()
            self._update_audio(0.0)

    def deactivate_audio(self):
        self.audio_active = False
        if self.audio is not None:
            self.audio.deactivate_gameplay()

    def _surface_footstep(self):
        tx, ty = int(self.player.x), int(self.player.y)
        if not (0 <= ty < len(self.world.heights)
                and 0 <= tx < len(self.world.heights[ty])):
            return None
        height = self.world.heights[ty][tx]
        if (tx, ty) in self.world.roads or (tx, ty) in self.world.buildings:
            return "walking_on_dirt"
        if SAND_LEVEL <= height < MOUNTAIN_LEVEL:
            return "walking_on_grass"
        if height >= SEA_LEVEL:
            return "walking_on_dirt"
        return None

    def _creature_audio_entities(self):
        for animal in self.animal_system.animals:
            yield animal.id, animal.kind, animal.x, animal.y, animal.alive
        for monster in self.quest_system.monsters:
            if monster.kind == "wolf":
                kind = "wolf"
            elif monster.kind == "pirate":
                kind = "pirate"
            else:
                kind = "monster"
            yield monster.id, kind, monster.x, monster.y, monster.alive
        for ship in self.naval.ships:
            if ship.kind == "pirate":
                yield ship.id, "pirate", ship.x, ship.y, ship.alive

    def _update_boss_audio(self):
        if self.audio is None or not self.boss_active:
            self._last_boss_audio_state = None
            return
        state = self.treant_encounter.state
        if state == self._last_boss_audio_state:
            return
        self._last_boss_audio_state = state
        if state == BossState.ARM_WINDUP:
            self.audio.play_sfx("platanus_slash", "boss", max_instances=1)
        elif state == BossState.ARM_EXTEND:
            self.audio.play_sfx("platanus_arm_grow", "boss", max_instances=1)
        elif state == BossState.EARTHQUAKE:
            self.audio.play_sfx("platanus_landing", "boss", max_instances=1)

    def _update_audio(self, dt):
        if self.audio is None or not self.audio_active:
            return
        if self.boss_active and (self.boss_completion_pending
                                 or self.treant_encounter.get_result() != EncounterResult.IN_PROGRESS):
            # The encounter is decided: the boss track fades out under the result
            # banner, and the overworld theme returns once the player is back.
            self.audio.stop_music(900)
        else:
            self.audio.switch_music("boss_1" if self.boss_active else "main_theme", 1000)

        movement_name = None
        if not self.paused and self.moving:
            if self.is_sailing and abs(self.boat_speed) > .08:
                movement_name = "boat_paddle"
            elif not self.is_sailing and self.dash_timer <= 0:
                movement_name = self._surface_footstep()
        current_movement = self.audio.active_loop("movement")
        if movement_name:
            self.audio.start_loop(movement_name, "movement", fade_ms=120)
        elif current_movement:
            self.audio.stop_loop(current_movement, 120)

        # "fishing" is the authoritative hooked-fish state.  Keep the long
        # recording alive through that struggle and stop it on catch/escape/close.
        reeling = (not self.paused and self.fishing.active
                   and self.fishing.state == "fishing")
        if reeling:
            self.audio.start_loop("fishing", "fishing", fade_ms=100)
        else:
            self.audio.stop_loop("fishing", 80)

        self._update_boss_audio()
        if not self.paused and not self.boss_active:
            self.audio.update_creatures(dt, self._creature_audio_entities(), self.player)
        self.audio.update(dt)

    def my_player_id(self):
        if self.network and self.network.connected and self.network.id is not None:
            return self.network.id
        return 0

    def add_resource(self, item, count):
        self.inventory[item] = self.inventory.get(item, 0) + count
        display_name = item_name(item)
        screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
        screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 45
        color = RESOURCE_COLORS.get(item, (255, 235, 120))
        self.floating_texts.append(FloatingText(f"+{count} {display_name}", (screen_x, screen_y), color))
        self.add_toast(tr("toast.gathered", count=count, item=display_name))

    @property
    def combat_level(self):
        # Levels deliberately grow slowly; XP is granted only by confirmed damage.
        return 1 + int(math.sqrt(max(0, self.combat_xp) / 12.0))

    def award_combat_xp(self, amount, target_kind="enemy"):
        amount = max(0, int(amount))
        if not amount:
            return
        self.combat_xp += amount
        color = (255, 218, 92) if target_kind not in ("sheep", "cow") else (205, 225, 150)
        sx = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
        sy = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 58
        self.floating_texts.append(FloatingText(tr("combat.xp", amount=amount), (sx, sy), color, 1.1))

    def spawn_impact(self, x, y, count=6):
        for index in range(count):
            angle = self.combat_rng.random() * math.tau
            speed = self.combat_rng.uniform(.7, 2.0)
            self.impact_particles.append({
                "x": x, "y": y - .25,
                "vx": math.cos(angle) * speed, "vy": math.sin(angle) * speed - .8,
                "life": self.combat_rng.uniform(.16, .28),
                "color": ((255, 232, 143), (244, 142, 64), (255, 250, 220))[index % 3],
            })

    def spawn_loot(self, x, y, item, count=1):
        drop = LootDrop(f"loot:{self.seed}:{self.next_loot_id}", x, y, item, count,
                        phase=self.combat_rng.random() * math.tau)
        self.next_loot_id += 1
        self.loot_drops.append(drop)
        return drop

    def enemy_loot(self, monster):
        tables = {
            "wolf": (("Çiğ Et", 1, .55), ("Tahil", 1, .18)),
            "boar": (("Çiğ Et", 2, .72), ("Tas", 1, .12)),
            "pirate": (("Balik", 2, .50), ("Odun", 2, .42), ("Tas", 1, .24)),
            "bandit": (("Odun", 2, .52), ("Tahil", 2, .35), ("Tas", 1, .22)),
            "thief": (("Tahil", 2, .48), ("Balik", 1, .30), ("Tas", 1, .18)),
        }
        made = 0
        for item, count, chance in tables.get(monster.kind, (("Odun", 1, .4),)):
            if self.loot_rng.random() < chance and made < 2:
                self.spawn_loot(monster.x + made * .18, monster.y, item, count)
                made += 1
        if made == 0 and self.loot_rng.random() < .35:
            self.spawn_loot(monster.x, monster.y, "Odun", 1)

    def handle_animal_defeated(self, animal):
        if animal.id in self.processed_deaths:
            return
        self.processed_deaths.add(animal.id)
        minimum, maximum = ((2, 4) if animal.kind == "cow" else (1, 2))
        amount = self.loot_rng.randint(minimum, maximum)
        self.spawn_loot(animal.x, animal.y, "Çiğ Et", amount)
        self.add_toast(tr("toast.hunted", creature=creature_name(animal.kind), count=amount),
                       color=(235, 173, 113))

    def nearby_campfire(self, radius=1.8):
        fires = [(x, y) for kind, x, y in self.world.village_props if kind == "campfire"
                 and math.hypot(self.player.x - x, self.player.y - y) <= radius]
        return min(fires, key=lambda p: math.hypot(self.player.x - p[0], self.player.y - p[1]),
                   default=None)

    def nearby_resource_node(self, radius=1.5):
        """Return the nearest node accepted by the existing E interaction."""
        return min(
            (node for node in self.world.nodes if node.active
             and math.hypot(self.player.x - node.x, self.player.y - node.y) < radius),
            key=lambda node: math.hypot(self.player.x - node.x, self.player.y - node.y),
            default=None,
        )

    @staticmethod
    def key_label(key):
        return pygame.key.name(key).upper()

    def interaction_hint(self):
        """Select the single prompt using the same priority as ``handle_event``."""
        blocked = (self.boss_active or self.paused or self.map_open or self.inventory_open
                   or self.trade_open or self.cooking_open or self.dialogue.active
                   or self.execution is not None or self.fishing.active
                   or self.fishing.zoom_level > 1.01 or self.grain_game.active
                   or self.stone_game.active or self.wood_game.active
                   or (self.winner is not None and not self.victory_dismissed))
        if blocked:
            return None

        interact = self.key_label(self.INTERACT_KEY)
        embark = self.key_label(self.EMBARK_KEY)
        port, port_distance = self.nearby_port()
        if self.is_sailing:
            merchant = self.naval.nearby_merchant(self.player)
            if merchant is not None:
                return InteractionHint(interact, action_label("trade"), (merchant.x, merchant.y - .9), "merchant")
            if port is not None and port_distance < 2.5:
                return InteractionHint(embark, action_label("disembark"),
                                       (port.x + .5, port.y + .1), "port")
            return None

        if self.sage_nearby():
            return InteractionHint(interact, action_label("talk"),
                                   (self.sage["x"], self.sage["y"] - 1.55), "sage")

        if self.near_treant_portal():
            if self.portal_unlock_timer > 0:
                return None
            px, py = self.world.boss_portal
            if self.treant_progress.boss_defeated:
                action = action_label("inspect")
            elif self.treant_progress.portal_unlocked:
                action = action_label("enter")
            elif self.treant_progress.keys_held >= 3:
                action = action_label("unseal")
            else:
                action = action_label("seals", held=self.treant_progress.keys_held)
            return InteractionHint(interact, action, (px, py - 1.65), "portal")

        campfire = self.nearby_campfire()
        if campfire is not None:
            return InteractionHint(interact, action_label("cook"),
                                   (campfire[0], campfire[1] - .7), "campfire")

        npc = self.quest_system.nearby_npc(self.player)
        if npc is not None:
            return InteractionHint(interact, action_label("talk"), (npc.x, npc.y - 1.0), "npc")

        if port is not None and port_distance < 1.6:
            return InteractionHint(interact, action_label("fish"),
                                   (port.x + .5, port.y + .1), "port")

        node = self.nearby_resource_node()
        if node is not None:
            offsets = {"Odun": 1.8, "Tas": .8, "Tahil": .9}
            return InteractionHint(interact, action_label(RESOURCE_ACTIONS.get(node.type, "collect")),
                                   (node.x, node.y - offsets.get(node.type, .8)),
                                   f"resource:{node.type}")

        if port is not None and port_distance < 2.5:
            return InteractionHint(embark, action_label("embark"),
                                   (port.x + .5, port.y + .1), "port")
        return None

    def draw_interaction_prompt(self, screen, camera_x, camera_y):
        hint = self.interaction_hint()
        if hint is None:
            return None
        return self.interaction_prompt.draw(
            screen, hint, (camera_x, camera_y), LOCAL_TILE_SIZE
        )

    def cook_recipe(self, recipe):
        if self.cooking_cooldown > 0 or self.nearby_campfire(2.1) is None:
            return False
        recipes = {
            "meat": ({"Çiğ Et": 1}, "Pişmiş Et", 1),
            "bread": ({"Tahil": 2}, "Ekmek", 1),
        }
        if recipe not in recipes:
            return False
        ingredients, output, amount = recipes[recipe]
        if not self.can_afford(ingredients):
            missing = ", ".join(self.get_missing_resources(ingredients))
            self.add_toast(tr("toast.cook_missing", missing=missing), color=(255, 125, 95))
            self.cooking_cooldown = .18
            return False
        for item, needed in ingredients.items():
            self.inventory[item] -= needed
        self.inventory[output] = self.inventory.get(output, 0) + amount
        self.cooking_cooldown = .22
        self.add_toast(tr("toast.cooked", amount=amount, item=item_name(output)), color=(255, 205, 105))
        # Recipes resolve immediately in the existing mechanic, so this is a
        # success-bound one-shot rather than an invented cooking duration.
        self._play_sfx("cooking", "interaction", max_instances=1)
        return True

    def consume_food(self, item):
        food = FOODS.get(item)
        needs_health = self.health < self.max_health
        needs_energy = self.energy < self.max_energy
        if food is None or self.inventory.get(item, 0) <= 0 or not (needs_health or needs_energy):
            return False
        self.inventory[item] -= 1
        healed = min(food.health, self.max_health - self.health)
        energized = min(food.energy, self.max_energy - self.energy)
        self.health += healed
        self.energy += energized
        gains = []
        if healed:
            gains.append(tr("toast.health_gain", amount=healed))
        if energized:
            gains.append(tr("toast.energy_gain", amount=energized))
        self.add_toast(tr("toast.ate", item=item_name(item), gains=", ".join(gains)), color=(125, 235, 145))
        self._play_sfx("eating", "interaction", max_instances=1, restart_if_busy=True)
        return True

    def quick_eat(self):
        """Eat the strongest useful carried food from the H shortcut."""
        choices = sorted(FOODS, key=lambda name: (FOODS[name].health, FOODS[name].energy),
                         reverse=True)
        for item in choices:
            if self.consume_food(item):
                return True
        self.add_toast(tr("toast.no_food"), color=(190, 175, 145))
        return False

    def craft_inventory_recipe(self, recipe_key):
        recipe = RECIPES.get(recipe_key)
        if recipe is None:
            return False
        amount = craft(recipe_key, self.inventory)
        if not amount:
            missing = self.get_missing_resources(recipe.ingredients)
            self.add_toast(tr("toast.craft_missing", missing=", ".join(missing)), color=(255, 125, 95))
            return False
        self.add_toast(tr("toast.crafted", amount=amount, item=item_name(recipe.output)), color=(125, 220, 245))
        return True

    def upgrade_weapon(self, weapon):
        cost = self.progression.next_cost(weapon) if weapon in self.progression.levels else None
        if cost is None:
            self.add_toast(tr("toast.weapon_max"), color=(245, 210, 110))
            return False
        if not self.progression.upgrade(weapon, self.inventory):
            self.add_toast(tr("toast.upgrade_missing", missing=", ".join(self.get_missing_resources(cost))),
                           color=(255, 125, 95))
            return False
        if weapon == "sword":
            stats = self.progression.stats("sword")
            self.combat.configure_weapon(stats.damage_bonus, stats.range_multiplier,
                                         stats.attack_speed_multiplier)
        self.add_toast(tr("toast.upgraded", weapon=weapon_name(weapon), level=self.progression.levels[weapon]),
                       color=(255, 220, 90))
        return True

    def harvest_reward(self, item, count):
        self.add_resource(item, count)
        # Production mode starts without gear; gathering then has a rare 4% drop.
        missing = [name for name, owned in self.equipment.items() if not owned]
        if missing and self.loot_rng.random() < 0.04:
            item = self.loot_rng.choice(missing)
            self.equipment[item] = True
            self.add_toast(tr("toast.rare_loot", item=weapon_name(item)), color=(255, 220, 90))

    def add_toast(self, message, color=(255, 235, 160)):
        self.toasts.append(ToastNotification(message, color=color))
        if len(self.toasts) > 3:
            self.toasts.pop(0)

    def handle_monster_defeated(self, monster):
        if monster.id in self.processed_deaths:
            return
        self.processed_deaths.add(monster.id)
        self.quest_system.monster_defeated(monster)
        self.enemy_loot(monster)
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

    def handle_entity_defeated(self, entity):
        if entity.kind in ("sheep", "cow"):
            self.handle_animal_defeated(entity)
        else:
            self.handle_monster_defeated(entity)

    def update_tree_sword_hits(self):
        if not self.combat.attacking:
            return
        attack = self.combat.attack_profile()
        if not (attack["active"][0] <= self.combat.timer <= attack["active"][1]):
            return
        hit_x, hit_y, hit_w, hit_h = self.combat.hitbox(self.player, self.facing)
        for node in self.world.nodes:
            key = f"tree:{node.id}"
            if (node.type != "Odun" or not node.active or key in self.combat.hit_targets
                    or not (hit_x <= node.x <= hit_x + hit_w and hit_y <= node.y <= hit_y + hit_h)):
                continue
            self.combat.hit_targets.add(key)
            self.leaves.burst(node, 10)
            self.spawn_impact(node.x, node.y - .55, 4)
            self.combat.impact_pulse = max(self.combat.impact_pulse, .10)

    def update_world_effects(self, dt):
        if self.network and self.network.connected and getattr(self.network, 'animal_authority', False):
            for animal in self.animal_system.animals:
                animal.hit_flash = max(0.0, animal.hit_flash - dt)
        for particle in self.impact_particles:
            particle["life"] -= dt
            particle["x"] += particle["vx"] * dt
            particle["y"] += particle["vy"] * dt
            particle["vy"] += 5.0 * dt
        self.impact_particles = [p for p in self.impact_particles if p["life"] > 0]
        for drop in self.loot_drops:
            drop.life -= dt
            drop.phase += dt * 4.0
        picked = []
        for drop in self.loot_drops:
            if drop.life > 0 and math.hypot(self.player.x - drop.x, self.player.y - drop.y) <= .72:
                if drop.authoritative and self.network and self.network.connected:
                    self.network.pickup(drop.id)
                else:
                    self.add_resource(drop.item, drop.count)
                    picked.append(drop.id)
        self.loot_drops = [drop for drop in self.loot_drops
                           if drop.life > 0 and drop.id not in picked]

    def apply_player_knockback(self, dt):
        if self.player_knockback.length_squared() <= .002:
            self.player_knockback.update(0, 0)
            return
        next_x = self.player.x + self.player_knockback.x * dt
        next_y = self.player.y + self.player_knockback.y * dt
        if can_stand(self.world, next_x, self.player.y, False):
            self.player.x = next_x
        else:
            self.player_knockback.x = 0
        if can_stand(self.world, self.player.x, next_y, False):
            self.player.y = next_y
        else:
            self.player_knockback.y = 0
        self.player_knockback *= max(0.0, 1.0 - 9.0 * dt)

    def grant_quest_reward(self, reward):
        for item, amount in reward.items():
            self.inventory[item] = self.inventory.get(item, 0) + amount
        reward_text = format_amounts(reward, sign="+")
        self.add_toast(tr("toast.quest_complete", reward=reward_text), color=(130, 245, 145))

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
                missing.append(f"{amount - have} {item_name(item)}")
        return missing

    def get_inflation_rate(self):
        if self.network and self.network.connected and hasattr(self.network, 'inflation'):
            return self.network.inflation
        return inflation_multiplier(self.game_time)

    def get_current_island_cost(self, is_enemy=False):
        return get_island_cost(is_enemy, self.get_inflation_rate())

    def award_ancient_key(self, village_id):
        """Award one quest key for one genuinely completed village rescue."""
        step = self.treant_progress.record_village_rescue(village_id)
        if step is None:
            return False
        self.inventory["Kadim Anahtar"] = self.treant_progress.keys_held
        speaker, pages = TREANT_STORY[step]
        self.dialogue.open(speaker, pages)
        self.add_toast(tr("toast.key_found", held=self.treant_progress.keys_held),
                       color=(255, 208, 82))
        self.request_autosave()
        return True

    def near_treant_portal(self, radius=1.75):
        if self.is_sailing or not self.world.boss_portal:
            return False
        index, _, _ = self.current_island_info()
        px, py = self.world.boss_portal
        return (index == self.world.boss_island_index
                and math.hypot(self.player.x - px, self.player.y - py) <= radius)

    def interact_treant_portal(self):
        """Unlock or enter the encounter; proximity alone never teleports."""
        progress = self.treant_progress
        if progress.boss_defeated:
            self.add_toast(tr("toast.curse_broken"), color=(190, 220, 160))
            return False
        if not progress.portal_unlocked:
            if progress.keys_held < 3:
                self.add_toast(tr("toast.seals_missing", held=progress.keys_held),
                               color=(225, 158, 105))
                return False
            if (self.network and self.network.connected
                    and getattr(self.network, 'treant_progress_supported', False)):
                if self.network.unlock_treant_portal():
                    self.add_toast(tr("toast.seals_verifying"), color=(255, 180, 65))
                    return True
                return False
            if not progress.unlock_portal():
                return False
            self.inventory["Kadim Anahtar"] = 0
            self.portal_unlock_timer = self.portal_unlock_duration
            self.add_toast(tr("toast.portal_opening"), color=(255, 180, 65))
            self.request_autosave()
            return True
        if self.portal_unlock_timer > 0 or self.boss_active:
            return False
        return self.enter_treant_boss()

    def boss_player_state(self):
        vectors = {"up": (0.0, -1.0), "down": (0.0, 1.0),
                   "left": (-1.0, 0.0), "right": (1.0, 0.0)}
        return BossPlayerState(
            player_id=str(self.my_player_id()), x=self.player.x, y=self.player.y,
            health=self.health, max_health=self.max_health,
            facing=vectors.get(self.facing, (0.0, 1.0)),
            invulnerable=self.damage_cooldown > 0,
        )

    def enter_treant_boss(self):
        """Switch this GameSession into its encounter substate on the same window."""
        if self.boss_active or self.treant_progress.boss_defeated:
            return False
        if self.network and self.network.connected:
            if not getattr(self.network, 'treant_boss_authority', False):
                self.add_toast(tr("toast.no_boss_authority"), color=(245, 150, 105))
                return False
            if self.network.enter_treant_boss():
                self.add_toast(tr("toast.boss_verifying"), color=(255, 180, 65))
                return True
            return False
        self.boss_return_position = tuple(self.world.boss_return or self.player)
        spawn = self.treant_encounter.start(self.boss_player_state())
        self.player.update(spawn)
        self.previous_pos = tuple(spawn)
        self.boss_active = True
        self.boss_online = False
        self.boss_completion_pending = False
        self.boss_completion_result = None
        self.boss_completion_timer = 0.0
        self.boss_attack_id = None
        self.combat.state = "idle"
        self.combat.queued_kind = None
        self.player_knockback.update(0, 0)
        self.damage_cooldown = max(self.damage_cooldown, .5)
        self.paused = self.map_open = self.inventory_open = self.trade_open = False
        self.dialogue.active = False
        return True

    def leave_treant_boss(self, result, reason=None):
        """Restore the preserved overworld session after victory, defeat or retreat.

        ``reason`` is ``"retreat"`` or ``"connection_lost"`` for aborted fights.
        """
        if not self.boss_active:
            return
        victory = result == EncounterResult.VICTORY
        self.boss_active = False
        self.boss_online = False
        self.boss_completion_pending = False
        self.boss_completion_result = None
        self.boss_completion_timer = 0.0
        self.treant_encounter.cleanup()
        self.player.update(self.boss_return_position)
        self.previous_pos = tuple(self.player)
        self.cam_x, self.cam_y = get_local_camera(self.player)
        self.combat.state = "idle"
        self.combat.queued_kind = None
        self.player_knockback.update(0, 0)
        self.damage_cooldown = .7
        self.request_autosave()
        if victory:
            first = self.treant_progress.complete_boss()
            self.health = max(1, self.health)
            if first:
                self.achievement_popup = (TREANT_ACHIEVEMENT_NAME, TREANT_ACHIEVEMENT_DESCRIPTION)
                self.achievement_popup_timer = 7.0
                self.add_toast(tr("achievement.toast", name=TREANT_ACHIEVEMENT_NAME), color=(255, 216, 92))
        else:
            self.health = self.max_health
            message = {"retreat": "toast.boss_retreat",
                       "connection_lost": "toast.boss_connection_lost"}.get(reason, "toast.boss_repelled")
            self.add_toast(tr(message),
                           color=(245, 130, 105))

    def update_treant_boss(self, dt):
        """Host-authoritative adapter around the modular encounter API."""
        online_authority = bool(
            self.network and self.network.connected
            and getattr(self.network, 'treant_boss_authority', False)
        )
        if self.boss_online and not online_authority:
            self.leave_treant_boss(EncounterResult.DEFEAT, "connection_lost")
            return
        self.damage_cooldown = max(0.0, self.damage_cooldown - dt)
        self.player_hit_flash = max(0.0, self.player_hit_flash - dt)
        if self.boss_completion_pending:
            # Keep the encounter on the existing window long enough for its result
            # overlay and terminal particles to be visible before restoring the
            # preserved overworld session.
            self.treant_encounter.update(dt, self.boss_player_state())
            self.treant_encounter.consume_events()
            self.boss_completion_timer = max(0.0, self.boss_completion_timer - dt)
            self.moving = False
            self.update_characters(dt, 0.0)
            if self.boss_completion_timer <= 0:
                self.leave_treant_boss(self.boss_completion_result)
            return
        old = (self.player.x, self.player.y)
        keys = pygame.key.get_pressed()
        direction = pygame.Vector2(
            int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT]),
            int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]),
        )
        if direction.length_squared() and not self.dialogue.active:
            direction = direction.normalize()
            desired = (self.player.x + direction.x * PLAYER_SPEED * dt,
                       self.player.y + direction.y * PLAYER_SPEED * dt)
            self.player.update(self.treant_encounter.constrain_motion(old, desired))
            self.facing = ("right" if direction.x > 0 else "left") if abs(direction.x) > abs(direction.y) else ("down" if direction.y > 0 else "up")

        # Reuse the normal sword timing, damage, range and animation.  The boss
        # accepts a unique swing id only once, so one visual attack cannot double-hit.
        was_attacking = self.combat.attacking
        previous_attack_timer = self.combat.timer
        self.combat.update(dt, self.player, self.facing, [], lambda _target: None)
        if (self.combat.attacking
                and (not was_attacking or self.combat.timer < previous_attack_timer)):
            self.boss_attack_sequence += 1
            self.boss_attack_id = f"main:{self.my_player_id()}:{self.boss_attack_sequence}"
        if self.combat.attacking:
            profile = self.combat.attack_profile()
            if profile["active"][0] <= self.combat.timer <= profile["active"][1]:
                if self.boss_attack_id is None:
                    self.boss_attack_sequence += 1
                    self.boss_attack_id = f"main:{self.my_player_id()}:{self.boss_attack_sequence}"
                x, y, width, height = self.combat.hitbox(self.player, self.facing)
                if online_authority:
                    accepted = False
                    if "treant-requested" not in self.combat.hit_targets:
                        accepted = self.network.attack_treant_boss(
                            self.boss_attack_id, self.combat.attack_kind,
                            self.combat.combo_step, self.progression.levels["sword"],
                        )
                        self.combat.hit_targets.add("treant-requested")
                else:
                    accepted = self.treant_encounter.register_player_attack(PlayerAttack(
                        self.boss_attack_id, str(self.my_player_id()), x, y, width, height,
                        profile["damage"], 0.0,
                    ))
                if accepted:
                    if not online_authority:
                        self.combat.hit_targets.add("treant")
                        self.combat.hit_stop = .045
                        self.combat.impact_pulse = .16
        else:
            self.boss_attack_id = None

        lunge = self.combat.consume_lunge()
        if lunge:
            dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0),
                      "right": (1, 0)}.get(self.facing, (0, 1))
            self.player.update(self.treant_encounter.constrain_motion(
                tuple(self.player), (self.player.x + dx * lunge, self.player.y + dy * lunge)))

        if online_authority:
            self.treant_encounter.update_replica(dt)
            self.net_timer += dt
            if self.net_timer >= .05:
                attack_kind = self.combat.attack_kind if self.combat.attacking else None
                attack_progress = (self.combat.timer / self.combat.attack_profile()['duration']
                                   if self.combat.attacking else 0.0)
                self.network.send_and_receive(
                    self.player.x, self.player.y, self.facing, self.moving, False,
                    self.boat_angle, self.sail_angle, self.sail_raised, attack_kind,
                    min(1.0, attack_progress), self.combat.combo_step,
                )
                self.net_timer = 0.0
                self.sync_treant_network_progress()
            dx, dy = self.player.x - old[0], self.player.y - old[1]
            self.moving = abs(dx) + abs(dy) > .0001
            self.previous_pos = tuple(self.player)
            self.update_characters(dt, math.hypot(dx, dy) / max(dt, 1e-6))
            return

        self.treant_encounter.update(dt, self.boss_player_state())
        completion = None
        for emitted in self.treant_encounter.consume_events():
            if emitted.type == PLAYER_HIT and self.damage_cooldown <= 0:
                self.health = max(0, self.health - emitted.data.get("damage", 0))
                self.damage_cooldown = float(emitted.data.get("invulnerability", .7))
                self.player_hit_flash = .18
                self.player_knockback.update(emitted.data.get("knockback", (0, 0)))
            elif emitted.type == BOSS_DAMAGED:
                self.award_combat_xp(max(1, round(emitted.data.get("damage", 1))), "treant")
            elif emitted.type == ENCOUNTER_COMPLETED:
                completion = EncounterResult(emitted.data["result"])

        if self.player_knockback.length_squared() > .002:
            desired = (self.player.x + self.player_knockback.x * dt,
                       self.player.y + self.player_knockback.y * dt)
            self.player.update(self.treant_encounter.constrain_motion(tuple(self.player), desired))
            self.player_knockback *= max(0.0, 1.0 - 9.0 * dt)

        dx, dy = self.player.x - old[0], self.player.y - old[1]
        self.moving = abs(dx) + abs(dy) > .0001
        self.previous_pos = tuple(self.player)
        self.update_characters(dt, math.hypot(dx, dy) / max(dt, 1e-6))
        if self.health <= 0 and completion is None:
            # Supplying zero health makes the encounter emit its validated defeat.
            self.treant_encounter.update(0, self.boss_player_state())
            for emitted in self.treant_encounter.consume_events():
                if emitted.type == ENCOUNTER_COMPLETED:
                    completion = EncounterResult(emitted.data["result"])
        if completion is not None:
            self.boss_completion_pending = True
            self.boss_completion_result = completion
            self.boss_completion_timer = 1.8 if completion == EncounterResult.VICTORY else 1.0

    def sync_treant_network_progress(self):
        """Apply only server-confirmed online rescue and portal progression."""
        if not (self.network and self.network.connected
                and getattr(self.network, 'treant_progress_supported', False)):
            return
        state = getattr(self.network, 'treant_progress', {}) or {}
        server_ids = [int(value) for value in state.get('rescued_villages', ())]
        for village_id in server_ids:
            if village_id not in self.treant_progress.rescued_village_ids:
                self.award_ancient_key(village_id)
        server_unlocked = bool(state.get('portal_unlocked', False))
        if server_unlocked and not self.treant_progress.portal_unlocked:
            self.treant_progress.portal_unlocked = True
            self.treant_progress.keys_held = 0
            self.inventory["Kadim Anahtar"] = 0
            self.portal_unlock_timer = self.portal_unlock_duration
            self.add_toast(tr("toast.server_portal"), color=(255, 190, 70))
        elif not server_unlocked:
            server_keys = max(0, min(3, int(state.get('ancient_keys', 0))))
            self.treant_progress.keys_held = server_keys
            self.inventory["Kadim Anahtar"] = server_keys

        server_boss_active = bool(state.get('boss_active', False))
        boss_snapshot = state.get('boss')
        if server_boss_active:
            if not self.boss_active:
                self.boss_return_position = tuple(self.world.boss_return or self.player)
                spawn = self.treant_encounter.start(self.boss_player_state())
                self.player.update(spawn)
                self.previous_pos = tuple(spawn)
                self.boss_active = True
                self.boss_online = True
                self.boss_completion_pending = False
                self.boss_completion_result = None
                self.boss_completion_timer = 0.0
                self.boss_attack_id = None
                self.combat.state = "idle"
                self.combat.queued_kind = None
                self.player_knockback.update(0, 0)
                self.paused = self.map_open = self.inventory_open = self.trade_open = False
                self.dialogue.active = False
            if isinstance(boss_snapshot, dict):
                self.treant_encounter.apply_state_snapshot(boss_snapshot)
            position = state.get('player_position')
            if isinstance(position, (list, tuple)) and len(position) == 2:
                self.player.update(float(position[0]), float(position[1]))
                self.previous_pos = tuple(self.player)
            server_health = max(0, min(self.max_health, float(state.get('health', self.health))))
            if server_health < self.health:
                self.player_hit_flash = .18
                self.damage_cooldown = max(self.damage_cooldown, .42)
            self.health = server_health
            self.combat_xp = max(self.combat_xp, int(getattr(self.network, 'combat_xp', self.combat_xp)))
            return

        if (self.boss_active and self.network and self.network.connected
                and getattr(self.network, 'treant_boss_authority', False)):
            result_value = state.get('boss_result', EncounterResult.DEFEAT.value)
            try:
                result = EncounterResult(result_value)
            except ValueError:
                result = EncounterResult.DEFEAT
            if result == EncounterResult.IN_PROGRESS:
                result = EncounterResult.DEFEAT
            self.leave_treant_boss(result)
        elif bool(state.get('boss_defeated', False)) and not self.treant_progress.boss_defeated:
            first = self.treant_progress.complete_boss()
            if first:
                self.achievement_popup = (TREANT_ACHIEVEMENT_NAME, TREANT_ACHIEVEMENT_DESCRIPTION)
                self.achievement_popup_timer = 7.0
                self.add_toast(tr("achievement.toast", name=TREANT_ACHIEVEMENT_NAME), color=(255, 216, 92))

    def try_rescue_island(self, island_index=None):
        current_idx, current_island, current_owner = self.current_island_info()
        idx = current_idx if island_index is None else island_index
        island = current_island if island_index is None else self.world.islands[idx]
        owner = current_owner if island_index is None else self.island_owners.get(idx)
        if idx is None:
            self.add_toast(tr("toast.must_land"))
            return False

        my_id = self.my_player_id()
        if owner is not None:
            self.add_toast(tr("toast.already_rescued", name=island.name))
            return False

        quest = next((q for q in self.quest_system.quests.values() if q.island_index == idx), None)
        if quest and quest.state != "ready":
            self.add_toast(tr("toast.quest_first"))
            return False

        cost = self.get_current_island_cost(False)

        if not self.can_afford(cost):
            missing = self.get_missing_resources(cost)
            self.add_toast(tr("toast.supplies_missing", missing=", ".join(missing)))
            screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
            screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 45
            self.floating_texts.append(FloatingText(tr("toast.insufficient"), (screen_x, screen_y), (255, 90, 90)))
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

        msg = tr("toast.rescued", name=island.name, count=my_count, target=self.WINNING_COUNT)
        self.floating_texts.append(FloatingText(tr("toast.rescued_short", name=island.name),
                                                (screen_x - 30, screen_y), (255, 230, 80), duration=2.5))

        self.add_toast(msg)

        # Only islands with generated villages qualify, and the progress object
        # independently de-duplicates their stable island IDs.
        if island.village is not None and not (self.network and self.network.connected):
            self.award_ancient_key(idx)

        if my_count >= self.WINNING_COUNT:
            self.winner = my_id

        self.request_autosave()
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
                    gain_str = format_amounts(gains, sign="+")
                    self.add_toast(tr("toast.income", gains=gain_str))
                    screen_x = round(self.player.x * LOCAL_TILE_SIZE) - round(self.cam_x)
                    screen_y = round(self.player.y * LOCAL_TILE_SIZE) - round(self.cam_y) - 60
                    self.floating_texts.append(FloatingText(tr("toast.income", gains=gain_str), (screen_x - 20, screen_y), (140, 240, 140)))

    def nearby_port(self):
        closest, closest_distance = None, float("inf")
        for port in self.ports:
            distance = math.hypot(self.player.x - (port.x + 0.5), self.player.y - (port.y + 0.5))
            if distance < closest_distance:
                closest_distance, closest = distance, port
        return closest, closest_distance

    def start_dash(self, direction=(0, -1)):
        if not self.dash_unlocked:
            return False
        if (self.dash_timer > 0 or self.is_sailing or self.map_open
                or self.dialogue.active or self.player_exhaust_timer > 0):
            return False
        charge = self.dash_charge_ratio
        if charge <= .05:
            return False
        dash_direction = pygame.Vector2(direction)
        if dash_direction.length_squared() <= .001:
            dash_direction.update(0, -1)
        dash_direction.normalize_ip()
        self.dash_direction = dash_direction
        self.dash_power = charge
        self.dash_timer = DASH_DURATION * charge
        self.dash_cooldown = DASH_COOLDOWN
        self.energy = max(0, self.energy - round(12 * charge))
        self.dash_effect_timer = 0.0
        self.damage_cooldown = max(self.damage_cooldown, .12 + .18 * charge)
        self.facing = ("right" if dash_direction.x > 0 else "left") if abs(dash_direction.x) > abs(dash_direction.y) else (
            "down" if dash_direction.y > 0 else "up")
        for index in range(1 + round(2 * charge)):
            delay = index * .035
            self.dash_effects.append({"x": self.player.x, "y": self.player.y,
                                      "angle": math.atan2(dash_direction.y, dash_direction.x),
                                      "life": .34 + delay, "max_life": .34 + delay})
        return True

    @property
    def dash_charge_ratio(self):
        return max(0.0, min(1.0, 1.0 - self.dash_cooldown / DASH_COOLDOWN))

    def update_dash_movement(self, dt):
        if self.dash_timer <= 0:
            return False
        step = min(dt, self.dash_timer)
        self.dash_timer = max(0.0, self.dash_timer - dt)
        speed = DASH_SPEED * (.65 + .35 * self.dash_power)
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
        if self.inventory.get("Ok", 0) <= 0:
            self.add_toast(tr("toast.no_arrows"),
                           color=(255, 135, 105))
            return False
        target_x = (mouse_pos[0] + self.cam_x) / LOCAL_TILE_SIZE
        target_y = (mouse_pos[1] + self.cam_y) / LOCAL_TILE_SIZE
        dx, dy = target_x - self.player.x, target_y - self.player.y
        length = math.hypot(dx, dy)
        if length < .01:
            return False
        dx, dy = dx / length, dy / length
        stats = self.progression.stats("bow")
        self.inventory["Ok"] -= 1
        self.arrows.append({"x": self.player.x, "y": self.player.y,
                            "vx": dx * 12.0, "vy": dy * 12.0,
                            "life": 1.6 * stats.range_multiplier,
                            "damage": 2 + stats.damage_bonus,
                            "weapon_level": stats.level})
        self.facing = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up")
        self.arrow_cooldown = .38 / stats.attack_speed_multiplier
        self._play_sfx("bow_and_arrow", "combat", max_instances=2, restart_if_busy=True)
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
                    or data.get("boss_active", False)
                    or not (hit_x <= data.get("x", -999) <= hit_x + hit_w
                            and hit_y <= data.get("y", -999) <= hit_y + hit_h)):
                continue
            if self.network.pvp_attack(pid, self.combat.attack_kind,
                                       self.progression.levels["sword"]):
                self.combat.hit_targets.add(target_key)

    def update_network_animal_melee(self):
        if not (self.network and self.network.connected
                and getattr(self.network, 'animal_authority', False) and self.combat.attacking):
            return
        attack = self.combat.attack_profile()
        if not (attack["active"][0] <= self.combat.timer <= attack["active"][1]):
            return
        x, y, w, h = self.combat.hitbox(self.player, self.facing)
        for animal in self.animal_system.animals:
            target_key = f"animal:{animal.id}"
            if (not animal.alive or target_key in self.combat.hit_targets
                    or not (x <= animal.x <= x + w and y <= animal.y <= y + h)):
                continue
            if self.network.entity_attack(animal.id, self.combat.attack_kind,
                                          self.progression.levels["sword"]):
                self.combat.hit_targets.add(target_key)

    def hit_remote_player_with_arrow(self, arrow):
        if not (self.network and self.network.connected):
            return False
        with self.network.lock:
            players = {pid: dict(data) for pid, data in self.network.other_players.items()}
        hit_radius = .9 if self.is_sailing else .58
        for pid, data in players.items():
            if (data.get("boss_active", False)
                    or bool(data.get("sailing", False)) != bool(self.is_sailing)):
                continue
            if math.hypot(arrow["x"] - data.get("x", -999), arrow["y"] - data.get("y", -999)) < hit_radius:
                if self.network.pvp_attack(pid, "bow", arrow.get("weapon_level", 1)):
                    arrow["life"] = 0
                    return True
        return False

    def update_world_combat(self, dt):
        self.damage_cooldown = max(0.0, self.damage_cooldown - dt)
        self.arrow_cooldown = max(0.0, self.arrow_cooldown - dt)
        animals_authoritative = bool(self.network and self.network.connected
                                     and getattr(self.network, 'animal_authority', False))
        targets = self.quest_system.monsters + ([] if animals_authoritative else self.animal_system.animals)
        hits = self.combat.update(dt, self.player, self.facing, targets,
                                  self.handle_entity_defeated,
                                  lambda x, y, entity: (
                                      self.animal_system.suitable_step(
                                          entity, x, y, lambda px, py: can_stand(self.world, px, py, False))
                                      if entity.kind in ("sheep", "cow")
                                      else can_stand(self.world, x, y, False)))
        for target, damage, defeated in hits:
            self.spawn_impact(target.x, target.y, 8 if defeated else 5)
            self.award_combat_xp(1 if target.kind in ("sheep", "cow") else max(1, damage), target.kind)
            if target.kind in ("sheep", "cow") and target.alive:
                self.animal_system.flee(target, self.player.x, self.player.y)
        self.update_tree_sword_hits()
        self.update_network_animal_melee()
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
            self.player_hit_flash = .16
            push = pygame.Vector2(self.player.x - strongest.x, self.player.y - strongest.y)
            if push.length_squared() > .001:
                self.player_knockback = push.normalize() * 5.2
            self.spawn_impact(self.player.x, self.player.y, 5)
            self.add_toast(tr("toast.creature_hit", creature=creature_name(strongest.kind),
                              damage=strongest.damage),
                           color=(255, 115, 95))
            # Gathering windows lock movement; an attack interrupts them so the
            # player can fight back instead of standing helpless.
            for activity in (self.wood_game, self.stone_game, self.grain_game):
                if activity.active and getattr(activity, "state", None) != "FALL":
                    activity.close()
        for arrow in self.arrows:
            arrow["x"] += arrow["vx"] * dt
            arrow["y"] += arrow["vy"] * dt
            arrow["life"] -= dt
            for enemy in self.quest_system.monsters:
                if enemy.alive and math.hypot(arrow["x"] - enemy.x, arrow["y"] - enemy.y) < .55:
                    damage = arrow.get("damage", 2)
                    enemy.health -= damage
                    enemy.hit_flash = .16
                    arrow["life"] = 0
                    self.spawn_impact(enemy.x, enemy.y, 5)
                    self.award_combat_xp(damage, enemy.kind)
                    if enemy.health <= 0:
                        enemy.alive = False
                        if not enemy.death_handled:
                            enemy.death_handled = True
                            self.handle_monster_defeated(enemy)
                    break
            if arrow["life"] > 0 and not animals_authoritative:
                for animal in self.animal_system.animals:
                    if animal.alive and math.hypot(arrow["x"] - animal.x, arrow["y"] - animal.y) < .62:
                        damage = arrow.get("damage", 2)
                        animal.health -= damage
                        animal.hit_flash = .16
                        arrow["life"] = 0
                        self.spawn_impact(animal.x, animal.y, 5)
                        self.award_combat_xp(1, animal.kind)
                        if animal.health <= 0:
                            animal.alive = False
                            if not animal.death_handled:
                                animal.death_handled = True
                                self.handle_animal_defeated(animal)
                        else:
                            self.animal_system.flee(animal, self.player.x, self.player.y)
                        break
            elif arrow["life"] > 0 and animals_authoritative:
                for animal in self.animal_system.animals:
                    if animal.alive and math.hypot(arrow["x"] - animal.x, arrow["y"] - animal.y) < .62:
                        if self.network.entity_attack(animal.id, "bow", arrow.get("weapon_level", 1)):
                            arrow["life"] = 0
                        break
            if arrow["life"] > 0:
                self.hit_remote_player_with_arrow(arrow)
        self.arrows = [arrow for arrow in self.arrows if arrow["life"] > 0]
        if self.health <= 0:
            self.health = self.max_health
            self.arrows.clear()
            self.add_toast(tr("toast.fainted"), color=(255, 110, 90))
            self.respawn_player()
        if not animals_authoritative:
            self.animal_system.update(dt, self.player,
                                      lambda x, y: can_stand(self.world, x, y, False))
        self.apply_player_knockback(dt)

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
            self.add_toast(tr("toast.cannonball", damage=damage), color=(255, 95, 75))

        for arrow in self.arrows:
            arrow["x"] += arrow["vx"] * dt
            arrow["y"] += arrow["vy"] * dt
            arrow["life"] -= dt
            for ship in self.naval.ships:
                if (ship.alive and ship.kind == "pirate"
                        and math.hypot(arrow["x"] - ship.x, arrow["y"] - ship.y) < .85):
                    ship.health -= arrow.get("damage", 2)
                    ship.hit_flash = .16
                    arrow["life"] = 0
                    if ship.health <= 0:
                        ship.alive = False
                        self.add_resource(self.loot_rng.choice(("Odun", "Tas", "Balik")), 3)
                        self.add_toast(tr("toast.pirate_sunk"), color=(255, 210, 90))
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
                self.add_toast(tr("toast.pirate_ram"), color=(255, 105, 85))
                break

        if self.health <= 0:
            self.health = self.max_health
            self.arrows.clear()
            self.is_sailing = False
            self.boat_speed = 0.0
            self.add_toast(tr("toast.boat_sunk"), color=(255, 100, 85))
            self.respawn_player()

    def trade_with_merchant_ship(self):
        merchant = self.naval.nearby_merchant(self.player)
        if merchant is None:
            return False
        if self.inventory.get("Balik", 0) < 2:
            self.add_toast(tr("toast.merchant_need"), color=(130, 220, 245))
            return True
        self.inventory["Balik"] -= 2
        item = self.loot_rng.choice(("Odun", "Tas", "Tahil"))
        self.add_resource(item, 4)
        self.health = min(self.max_health, self.health + 2)
        self.add_toast(tr("toast.sea_trade", item=item_name(item)), color=(120, 235, 210))
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
        if opened:
            self.map_ui.focus("full", self.player)
            self.rescue_map_open = False
            self.map_ui.stop_drag("rescue")
        else:
            self.map_ui.stop_drag("full")
        self.moving = False
        self.held_direction_keys.clear()
        self.last_direction_tap = dict.fromkeys(self.last_direction_tap, -10.0)
        # Do not resume a queued dash when the chart is dismissed.
        self.dash_timer = 0.0
        self.leaves.clear()

    def ambient_leaves_enabled(self):
        return not (self.paused or self.map_open or self.inventory_open or self.trade_open
                    or self.cooking_open
                    or self.dialogue.active or self.execution is not None
                    or self.fishing.active or self.fishing.zoom_level > 1.01
                    or self.grain_game.active or self.stone_game.active or self.wood_game.active
                    or (self.winner is not None and not self.victory_dismissed))

    def handle_event(self, event, logical_pos) -> str:
        if self.boss_active:
            self.treant_encounter.handle_event(event)
            if self.boss_completion_pending:
                # The outcome is already authoritative. Do not let a late Escape
                # turn the visible victory/defeat transition into a different result.
                return None
            direction_keys = {
                pygame.K_w: "up", pygame.K_UP: "up", pygame.K_s: "down", pygame.K_DOWN: "down",
                pygame.K_a: "left", pygame.K_LEFT: "left", pygame.K_d: "right", pygame.K_RIGHT: "right",
            }
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if (self.network and self.network.connected
                            and getattr(self.network, 'treant_boss_authority', False)):
                        self.network.retreat_treant_boss()
                    else:
                        self.leave_treant_boss(EncounterResult.DEFEAT, "retreat")
                elif event.key in (pygame.K_j, pygame.K_SPACE) and self.equipment.get("sword"):
                    self.combat.start_attack("normal")
                elif event.key == pygame.K_k and self.equipment.get("sword"):
                    self.combat.start_attack("crouch")
                elif (event.key in direction_keys and not getattr(event, "repeat", False)
                      and self.dash_unlocked):
                    direction_name = direction_keys[event.key]
                    if self.game_time - self.last_direction_tap[direction_name] <= .28:
                        self.combat.start_attack("dash", self.dash_power)
                        self.last_direction_tap[direction_name] = -10.0
                    else:
                        self.last_direction_tap[direction_name] = self.game_time
            return None

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

        # Food is intentionally usable from gameplay and every non-paused modal.
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_h
                and not getattr(event, "repeat", False) and not self.paused):
            self.quick_eat()
            return None

        if self.dialogue.active:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_e, pygame.K_RETURN, pygame.K_SPACE):
                self.dialogue.advance()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.dialogue.active = False
            return None

        if self.cooking_open:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e):
                self.cooking_open = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.cooking_close_rect.collidepoint(logical_pos):
                    self.cooking_open = False
                else:
                    for action, value, rect in self.cooking_action_rects:
                        if rect.collidepoint(logical_pos):
                            if action == "cook":
                                self.cook_recipe(value)
                            elif action == "eat":
                                self.consume_food(value)
                            break
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
            else:
                self.map_ui.handle_event(event, logical_pos, "full", self.map_ui.full_rect)
            return None

        # Inventory Modal Handling
        if self.inventory_open:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_i, pygame.K_TAB):
                self.inventory_open = False
                self.map_ui.stop_drag("rescue")
                return None
            elif self.map_ui.handle_event(event, logical_pos, "rescue", self.inventory_rescue_map_rect):
                return None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.inventory_close_rect.collidepoint(logical_pos):
                    self.inventory_open = False
                    self.map_ui.stop_drag("rescue")
                    return None
                for action, value, rect in self.inventory_action_rects:
                    if rect.collidepoint(logical_pos):
                        if action == "eat":
                            self.consume_food(value)
                        elif action == "craft":
                            self.craft_inventory_recipe(value)
                        elif action == "upgrade":
                            self.upgrade_weapon(value)
                        return None
                if self.conquer_action_rect.collidepoint(logical_pos):
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
                                    self.add_toast(tr("toast.trade_accepted"), color=(120, 240, 130))
                        elif action == 'cancel_trade':
                            if self.network and self.network.connected:
                                self.network.cancel_trade(val)
                                self.add_toast(tr("toast.trade_cancelled"))
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

        if self.rescue_map_open and self.map_ui.handle_event(
                event, logical_pos, "rescue", self.rescue_map_rect):
            return None
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rescue_map_button.collidepoint(logical_pos)
                and self.current_island_info()[0] is not None and not self.is_sailing):
            self.rescue_map_open = not self.rescue_map_open
            if self.rescue_map_open:
                self.map_ui.focus("rescue", self.player)
            else:
                self.map_ui.stop_drag("rescue")
            return None

        direction_keys = self.MOVE_KEYS
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
                    self.add_toast(tr("toast.sail_raised") if self.sail_raised else tr("toast.sail_lowered"),
                                   color=(120, 220, 245))

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
            elif event.key == self.INTERACT_KEY and not self.map_open and self.is_sailing:
                self.trade_with_merchant_ship()
            elif event.key == self.INTERACT_KEY and not self.map_open and not self.is_sailing:
                npc = self.quest_system.nearby_npc(self.player)
                port, distance = self.nearby_port()
                campfire = self.nearby_campfire()
                if self.sage_nearby():
                    self.talk_to_sage()
                elif self.near_treant_portal():
                    self.interact_treant_portal()
                elif campfire:
                    self.cooking_open = True
                    self.inventory_open = False
                    self.trade_open = False
                elif npc:
                    self.quest_system.interact(npc, self.dialogue, self.grant_quest_reward,
                                               None, self.complete_quest_rescue)
                elif port and distance < 1.6:
                    self.fishing.open(port, self.player)
                    self.port_trigger_ready = False
                else:
                    node = self.nearby_resource_node()
                    if node is not None:
                        if node.type == "Odun":
                            axe = self.progression.stats("axe")
                            self.wood_game.open(node, axe.level, axe.required_hits, axe.impact)
                        elif node.type == "Tas": self.stone_game.open(node)
                        elif node.type == "Tahil": self.grain_game.open(node)

            elif event.key in (pygame.K_j, pygame.K_SPACE) and not self.map_open and not self.is_sailing:
                if self.equipment.get("sword"):
                    is_dash = self.dash_timer > 0
                    self.combat.start_attack("dash" if is_dash else "normal",
                                             self.dash_power if is_dash else 1.0)
            elif event.key == pygame.K_k and not self.map_open and not self.is_sailing:
                if self.equipment.get("sword"):
                    self.combat.start_attack("crouch")

            elif event.key == self.EMBARK_KEY and not self.map_open:
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

    def sync_authoritative_animals(self):
        if not (self.network and self.network.connected
                and getattr(self.network, 'animal_authority', False)):
            return
        with self.network.lock:
            snapshots = {uid: dict(data) for uid, data in self.network.animals.items()}
            world_loot = {uid: dict(data) for uid, data in self.network.world_loot.items()}
            pickup_events = list(self.network.pickup_events)
            self.network.pickup_events.clear()
        by_id = {animal.id: animal for animal in self.animal_system.animals}
        for uid, data in snapshots.items():
            animal = by_id.get(uid)
            if animal is None:
                continue
            old_health, old_alive = animal.health, animal.alive
            animal.x = float(data.get('x', animal.x))
            animal.y = float(data.get('y', animal.y))
            animal.health = int(data.get('health', animal.health))
            animal.max_health = int(data.get('max_health', animal.max_health))
            animal.alive = bool(data.get('alive', animal.alive))
            animal.facing = data.get('facing', animal.facing)
            animal.walk_phase = float(data.get('walk_phase', animal.walk_phase))
            if animal.health < old_health:
                animal.hit_flash = .16
                self.spawn_impact(animal.x, animal.y, 7 if not animal.alive else 5)
            if old_alive and not animal.alive:
                animal.death_handled = True

        # Server-owned animal meat coexists with local enemy drops.
        local_drops = [drop for drop in self.loot_drops if not drop.authoritative]
        existing = {drop.id: drop for drop in self.loot_drops if drop.authoritative}
        synced = []
        for uid, data in world_loot.items():
            drop = existing.get(uid)
            if drop is None:
                drop = LootDrop(uid, float(data['x']), float(data['y']), data['item'],
                                int(data.get('count', 1)), phase=self.combat_rng.random() * math.tau,
                                authoritative=True)
            else:
                drop.x, drop.y = float(data['x']), float(data['y'])
                drop.count = int(data.get('count', drop.count))
            synced.append(drop)
        self.loot_drops = local_drops + synced
        for event in pickup_events:
            item, count = event.get('item'), event.get('count', 0)
            if isinstance(item, str) and isinstance(count, int) and count > 0:
                self.add_resource(item, count)

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
                self.remote_combat_revisions.pop(pid, None)
        for pid, player in players.items():
            animation = self.remote_animations.setdefault(pid, CharacterAnimator())
            x, y = player.get('x', 0), player.get('y', 0)
            speed = PLAYER_SPEED
            if 0 <= x < COLS and 0 <= y < ROWS:
                speed *= movement_multiplier(self.world, pygame.Vector2(x, y), False)
            animation.update(dt, player.get('moving', False) and not player.get('sailing', False),
                             player.get('facing', 'down'), speed)
            remote_combat = self.remote_combats.setdefault(pid, CombatSystem())
            revision = player.get('damage_revision', 0)
            old_revision = self.remote_combat_revisions.get(pid, revision)
            if revision > old_revision:
                self.pvp_hit_flashes[str(pid)] = .18
            self.remote_combat_revisions[pid] = revision
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
        self._tick_autosave(dt)
        self.update_sage(dt)
        self.portal_unlock_timer = max(0.0, self.portal_unlock_timer - dt)
        self.achievement_popup_timer = max(0.0, self.achievement_popup_timer - dt)
        if self.achievement_popup_timer <= 0:
            self.achievement_popup = None
        if self.boss_active:
            self.update_treant_boss(dt)
            self._update_audio(dt)
            self.floating_texts = [ft for ft in self.floating_texts if ft.update(dt)]
            self.toasts = [toast for toast in self.toasts if toast.update(dt)]
            return
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
            self.sync_treant_network_progress()
            if self.boss_active:
                self._update_audio(dt)
                self.floating_texts = [ft for ft in self.floating_texts if ft.update(dt)]
                self.toasts = [toast for toast in self.toasts if toast.update(dt)]
                return
        self.sync_authoritative_animals()
        if (self.network and self.network.connected
                and getattr(self.network, 'spawn_revision', 0) > self.spawn_revision):
            with self.network.lock:
                if self.network.deaths > self.network_deaths:
                    self.add_toast(tr("toast.player_defeated_you", pid=self.network.last_hit_by),
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
                self.combat_xp = max(self.combat_xp, getattr(self.network, 'combat_xp', 0))
                self.network_combat_revision = self.network.combat_revision
                attacker = self.network.last_hit_by
                if self.health < old_health:
                    authoritative = getattr(self.network, 'authoritative_position', None)
                    if authoritative:
                        self.player.update(authoritative)
                    self.damage_cooldown = max(self.damage_cooldown, .45)
                    self.player_hit_flash = .16
                    self.add_toast(tr("toast.player_hit_you", pid=attacker, damage=old_health - self.health),
                                   color=(255, 95, 90))
        if self.paused:
            self.update_characters(dt)
            self._update_audio(dt)
            return

        if self.player_exhaust_timer > 0:
            self.player_exhaust_timer -= dt
        self.dash_cooldown = max(0.0, self.dash_cooldown - dt)
        self.energy = min(self.max_energy, self.energy + 7.0 * dt)
        self.cooking_cooldown = max(0.0, self.cooking_cooldown - dt)
        self.player_hit_flash = max(0.0, self.player_hit_flash - dt)
        self.update_world_effects(dt)
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
        self.quest_system.update_npc_animations(dt)
        if not self.is_sailing and not self.map_open and not self.dialogue.active and not self.cooking_open:
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
                        or self.wood_game.active or self.dialogue.active or self.cooking_open
                        or self.execution is not None)
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
            zoom = snapped_world_zoom(self.fishing.zoom_level)
            if zoom > 1.0:
                # Same zoom the renderer shows, so the bobber aims where the cursor is.
                cx, cy = GAME_WIDTH / 2, GAME_HEIGHT / 2
                real_mx = cx + (mx - cx) / zoom
                real_my = cy + (my - cy) / zoom

            self.fishing.update(dt, real_mx + self.cam_x, real_my + self.cam_y, self.world)
            self.grain_game.update(dt, logical_mouse_pos)
            if self.wood_game.active:
                res = self.wood_game.update(dt)
                if res is False:
                    self.add_toast(tr("toast.wood_failed"), color=(255, 110, 90))
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
                            self.add_toast(tr("toast.island_taken", name=self.world.islands[idx].name, pid=o),
                                           color=(130, 220, 150))
                if self.network.winner is not None and self.winner is None:
                    self.winner = self.network.winner
                self.capture_count = getattr(self.network, 'capture_count', len(self.island_owners))
            self.sync_trades_and_execute()

        self._update_audio(dt)

    def render(self, screen: pygame.Surface, logical_mouse_pos: tuple):
        if self.boss_active:
            def draw_boss_player(target, camera):
                pos = (round(self.player.x * LOCAL_TILE_SIZE - camera[0]),
                       round(self.player.y * LOCAL_TILE_SIZE - camera[1]))
                draw_player(target, pos, self.moving, self.facing, None, False, 0.0,
                            self.atlas, self.character_sheet, self.player_animation,
                            self.sailboat_hull, 0.0, True, self.player_hit_flash)

            def draw_boss_effects(target, camera):
                pos = (round(self.player.x * LOCAL_TILE_SIZE - camera[0]),
                       round(self.player.y * LOCAL_TILE_SIZE - camera[1]))
                draw_sword_attack(target, pos, self.facing, self.combat)

            self.treant_encounter.render(
                screen, None, (self.player.y, draw_boss_player), draw_boss_effects
            )
            self.hud.draw_health(screen, self.health, self.max_health)
            draw_text(screen, self.small_font, tr("hud.boss_controls"),
                      (12, GAME_HEIGHT - 26), (238, 224, 193))
            self.draw_treant_tracker(screen)
            for i, toast in enumerate(self.toasts):
                toast.draw(screen, self.font, y_offset=i * 38)
            self.draw_achievement_popup(screen)
            return

        camera_x, camera_y = round(self.cam_x), round(self.cam_y)
        if self.combat.impact_pulse > 0 and not self.is_sailing:
            shake_strength = (self.combat.impact_pulse / .16) * (3 if self.combat.combo_step >= 3 else 2)
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
                        if pdata.get("boss_active", False):
                            continue
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
                if (camera_x - 80 <= npc.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 80
                        and camera_y - 80 <= npc.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 80):
                    objects.append((npc.y, "npc", npc))
            for monster in self.quest_system.monsters:
                if monster.alive and (camera_x - 80 <= monster.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 80
                                      and camera_y - 80 <= monster.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 80):
                    objects.append((monster.y, "monster", monster))
            for animal in self.animal_system.animals:
                if animal.alive and (camera_x - 80 <= animal.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 80
                                     and camera_y - 80 <= animal.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 80):
                    objects.append((animal.y, "animal", animal))
            for drop in self.loot_drops:
                if (camera_x - 50 <= drop.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 50
                        and camera_y - 50 <= drop.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 50):
                    objects.append((drop.y, "loot", drop))
            for ship in self.naval.ships:
                if ship.alive and (camera_x - 100 <= ship.x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 100
                                   and camera_y - 100 <= ship.y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 100):
                    objects.append((ship.y, "sea_ship", ship))
            if self.world.boss_portal:
                portal_x, portal_y = self.world.boss_portal
                if (camera_x - 180 <= portal_x * LOCAL_TILE_SIZE <= camera_x + GAME_WIDTH + 180
                        and camera_y - 180 <= portal_y * LOCAL_TILE_SIZE <= camera_y + GAME_HEIGHT + 180):
                    objects.append((portal_y, "treant_portal", (portal_x, portal_y)))

            if self.sage is not None:
                objects.append((self.sage["y"], "sage", self.sage))
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
                elif kind == "sage":
                    self.draw_sage(screen, camera_x, camera_y)
                elif kind == "monster":
                    draw_monster(screen, obj, camera_x, camera_y)
                elif kind == "animal":
                    draw_animal(screen, obj, camera_x, camera_y)
                elif kind == "loot":
                    draw_loot_drop(screen, obj, camera_x, camera_y, self.small_font)
                elif kind == "sea_ship":
                    draw_sea_ship(screen, obj, camera_x, camera_y, self.sailboat_hull, self.small_font)
                elif kind == "treant_portal":
                    portal_x, portal_y = obj
                    sprite = (self.treant_portal_sprite if self.treant_progress.portal_unlocked
                              else self.treant_portal_locked)
                    sx = round(portal_x * LOCAL_TILE_SIZE) - camera_x
                    sy = round(portal_y * LOCAL_TILE_SIZE) - camera_y
                    screen.blit(sprite, sprite.get_rect(midbottom=(sx, sy + 5)))
                    rune_count = (3 if self.treant_progress.portal_unlocked
                                  else self.treant_progress.keys_held)
                    if self.portal_unlock_timer > 0:
                        rune_count = 3
                    for rune in range(rune_count):
                        angle = self.game_time * 1.8 + rune * math.tau / 3
                        point = (round(sx + math.cos(angle) * 43),
                                 round(sy - 18 + math.sin(angle) * 17))
                        pulse = 2 + round(2 * (math.sin(self.game_time * 6 + rune) + 1) / 2)
                        pygame.draw.circle(screen, (255, 196, 66), point, 5 + pulse)
                        pygame.draw.circle(screen, (255, 244, 165), point, 2)
                else:
                    p = obj
                    p["pos"] = tuple(round(v) for v in p["pos"])
                    draw_pos = p["pos"]
                    if (p["is_me"] and self.combat.attacking
                            and self.combat.attack_kind == "crouch"):
                        draw_pos = (draw_pos[0], draw_pos[1] + 7)
                    draw_player(screen, draw_pos, p["moving"], p["facing"], p["color"], p["is_sailing"],
                                p["boat_angle"], self.atlas, self.character_sheet, p["animation"],
                                self.sailboat_hull, p["sail_angle"], p["sail_raised"],
                                self.player_hit_flash if p["is_me"] else self.pvp_hit_flashes.get(str(p["player_id"]), 0))
                    if not p["is_sailing"] and p.get("combat"):
                        draw_sword_attack(screen, draw_pos, p["facing"], p["combat"])
                    if not p["is_me"]:
                        if self.pvp_hit_flashes.get(str(p["player_id"]), 0) > 0:
                            pygame.draw.circle(screen, (255, 240, 155), p["pos"], 30, 4)
                        tag = self.small_font.render(tr("hud.other_player", pid=p["player_id"]), True, (255, 255, 255))
                        screen.blit(tag, tag.get_rect(midbottom=(p["pos"][0], p["pos"][1] - 42)))
                        hp_width = round(42 * max(0, p["health"]) / max(1, p["max_health"]))
                        pygame.draw.rect(screen, (42, 20, 24), (p["pos"][0] - 21, p["pos"][1] - 63, 42, 5))
                        pygame.draw.rect(screen, (220, 65, 65),
                                         (p["pos"][0] - 21, p["pos"][1] - 63, hp_width, 5))

            draw_dash_effects(screen, self.dash_effects, camera_x, camera_y)
            self.draw_sage_effects(screen, camera_x, camera_y)
            draw_impact_particles(screen, self.impact_particles, camera_x, camera_y)
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
            self.draw_interaction_prompt(screen, camera_x, camera_y)

            zoom = snapped_world_zoom(self.fishing.zoom_level)
            if zoom > 1.0:
                magnify_world(screen, (camera_x, camera_y), zoom,
                              (GAME_WIDTH / 2 * (1 - 1 / zoom), GAME_HEIGHT / 2 * (1 - 1 / zoom)))

            if self.execution is not None:
                progress = min(1.0, self.execution["timer"] / self.execution["duration"])
                cinematic = math.sin(progress * math.pi)
                zoom = snapped_world_zoom(1.0 + cinematic * .42)
                crop_w, crop_h = GAME_WIDTH / zoom, GAME_HEIGHT / zoom
                focus_x = round(self.execution["x"] * LOCAL_TILE_SIZE) - camera_x
                focus_y = round(self.execution["y"] * LOCAL_TILE_SIZE) - camera_y
                crop_x = max(0, min(GAME_WIDTH - crop_w, focus_x - crop_w / 2))
                crop_y = max(0, min(GAME_HEIGHT - crop_h, focus_y - crop_h / 2))
                magnify_world(screen, (camera_x, camera_y), zoom, (crop_x, crop_y))
                bar_height = round(28 * cinematic)
                if bar_height:
                    pygame.draw.rect(screen, (10, 8, 14), (0, 0, GAME_WIDTH, bar_height))
                    pygame.draw.rect(screen, (10, 8, 14),
                                     (0, GAME_HEIGHT - bar_height, GAME_WIDTH, bar_height))

        # Bottom status bar
        pygame.draw.rect(screen, (32, 39, 41), (0, GAME_HEIGHT - 30, GAME_WIDTH, 30))
        px, py = int(self.player.x), int(self.player.y)
        owner_idx = self.world.owners[py][px] if 0 <= px < COLS and 0 <= py < ROWS else -1
        current_island = self.world.islands[owner_idx] if owner_idx >= 0 else None
        if current_island:
            isl_owner = self.island_owners.get(owner_idx)
            if isl_owner == self.my_player_id():
                location = tr("hud.your_island", name=current_island.name)
            elif isl_owner is not None:
                location = tr("hud.player_island", name=current_island.name, owner=isl_owner)
            else:
                location = tr("hud.unclaimed", name=current_island.name)
        else:
            location = tr("hud.sea")

        net_status = tr("hud.offline")
        if self.network and self.network.connected:
            net_status = tr("hud.online", count=len(self.network.other_players) + 1)

        interact = self.key_label(self.INTERACT_KEY)
        info = f"{location} | {net_status} | {tr('hud.quick_eat')}"
        port, distance = self.nearby_port()
        if port is not None and distance < 2.5:
            info += " | " + tr("hud.port_controls", interact=interact,
                               embark=self.key_label(self.EMBARK_KEY))
        elif self.is_sailing:
            info += " | " + tr("hud.sail_controls")
        else:
            npc = self.quest_system.nearby_npc(self.player)
            if self.near_treant_portal():
                if self.treant_progress.portal_unlocked:
                    info += " | " + tr("hud.portal_enter", interact=interact)
                else:
                    info += " | " + tr("hud.portal_locked", interact=interact,
                                       held=self.treant_progress.keys_held)
            elif self.nearby_campfire():
                info += " | " + tr("hud.campfire", interact=interact)
            elif npc:
                info += " | " + tr("hud.talk_to", interact=interact, name=npc.name)
            else:
                info += " | " + (tr("hud.walk_controls") if self.dash_unlocked
                                 else tr("hud.walk_controls_no_dash"))

        draw_text(screen, self.small_font, info, (12, GAME_HEIGHT - 23), (229, 219, 193))

        # Five pixel hearts map the existing health scale into half-heart units.
        self.hud.draw_health(screen, self.health, self.max_health)
        energy_rect = pygame.Rect(14, 89, 150, 7)
        pixel_bar(screen, energy_rect, self.energy / self.max_energy, (74, 197, 166),
                  (24, 31, 34), (174, 226, 201))
        levels = self.progression.levels
        gear = tr("hud.gear", axe=levels['axe'], sword=levels['sword'], bow=levels['bow'],
                  arrows=self.inventory.get('Ok', 0), level=self.combat_level, xp=self.combat_xp)
        if self.network and self.network.connected and getattr(self.network, 'pvp_supported', False):
            gear += tr("hud.pvp", kills=self.network.kills, deaths=self.network.deaths)
        draw_text(screen, self.small_font, gear, (14, 98), (245, 218, 150), shadow=True)
        if not self.is_sailing and not self.dash_unlocked:
            draw_text(screen, self.small_font, tr("hud.dash_locked"), (18, 121), (150, 140, 128),
                      shadow=True)
        elif not self.is_sailing:
            charge = self.dash_charge_ratio
            dash_bar = pygame.Rect(14, 120, 210, 13)
            if self.unlock_glow_timer > 0:
                flash = round(4 + 6 * self.unlock_glow_timer / 1.4)
                pygame.draw.rect(screen, (225, 245, 255), dash_bar.inflate(flash, flash), 2)
            pixel_bar(screen, dash_bar, charge, (68, 205, 235) if charge < 1 else (110, 245, 255),
                      (23, 29, 36), (150, 206, 218))
            dash_text = (tr("hud.dash_ready") if charge >= 1
                         else tr("hud.dash_charging", pct=round(charge * 100)))
            draw_text(screen, self.small_font, dash_text, (dash_bar.x + 4, dash_bar.bottom + 2),
                      (105, 235, 255) if charge >= 1 else (174, 196, 204), shadow=True)
        if self.is_sailing:
            wx, wy = GAME_WIDTH - 72, self.map_button.bottom + 46
            pygame.draw.circle(screen, (25, 30, 36), (wx, wy), 34)
            pygame.draw.circle(screen, (190, 205, 210), (wx, wy), 34, 2)
            wind_end = (round(wx + math.cos(self.wind_angle) * 27), round(wy + math.sin(self.wind_angle) * 27))
            sail_end = (round(wx + math.cos(self.sail_angle) * 22), round(wy + math.sin(self.sail_angle) * 22))
            pygame.draw.line(screen, (105, 205, 255), (wx, wy), wind_end, 4)
            pygame.draw.line(screen, (255, 210, 90) if self.sail_raised else (115, 115, 110),
                             (wx, wy), sail_end, 3)
            draw_text(screen, self.small_font, tr("hud.wind", strength=self.wind_strength), (wx - 42, wy + 38), (220, 235, 240))
            sail_status = tr("hud.sail_raised") if self.sail_raised else tr("hud.sail_lowered")
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
            if idx is None:
                self.rescue_map_open = False
                self.map_ui.stop_drag("rescue")
            if (idx is not None and not self.is_sailing and not self.fishing.active
                    and not self.grain_game.active and not self.stone_game.active
                    and not self.wood_game.active and not self.dialogue.active and not self.cooking_open):
                my_id = self.my_player_id()
                if owner != my_id:
                    is_enemy = False
                    cost = self.get_current_island_cost(False)
                    afford = self.can_afford(cost)
                    hov = self.hud_conquer_rect.collidepoint(logical_mouse_pos)
                    inf_pct = int(round((self.get_inflation_rate() - 1.0) * 100))
                    inf_str = tr("hud.inflation_tag", pct=inf_pct) if inf_pct > 0 else ""

                    if afford:
                        compact = " ".join(f"{cost[item]}{item_name(item)[0]}" for item in SUPPLY_ITEMS)
                        lbl = tr("hud.rescue_ready", name=island.name, cost=compact, inflation=inf_str)
                    else:
                        lbl = tr("hud.rescue_short", name=island.name, inflation=inf_str)
                    # Long island names shrink, then shorten, to stay inside the bar.
                    limit = self.hud_conquer_rect.width - 16
                    font = self.small_font if self.small_font.size(lbl)[0] <= limit else self.tiny_font
                    while font.size(lbl)[0] > limit and len(lbl) > 4:
                        lbl = lbl[:-4] + "..."
                    pixel_button(screen, self.hud_conquer_rect, lbl, font, hov, afford, "wood",
                                 (255, 240, 180) if afford else (210, 140, 140))
                else:
                    badge_rect = pygame.Rect(GAME_WIDTH // 2 - 160, GAME_HEIGHT - 74, 320, 38)
                    pixel_box(screen, badge_rect, (25, 40, 20), (100, 200, 90))
                    b_surf = self.small_font.render(tr("hud.rescued", name=island.name), True, (180, 240, 160))
                    screen.blit(b_surf, b_surf.get_rect(center=badge_rect.center))

                # The lower rescue chart is optional, leaving the delivery action intact.
                draw_pixel_panel(screen, self.rescue_map_button,
                                 self.rescue_map_button.collidepoint(logical_mouse_pos))
                draw_pixel_label(screen, tr("hud.map"), (self.rescue_map_button.x + 12,
                                                     self.rescue_map_button.y + 8), scale=1,
                                 color=(245, 207, 128))
                if self.rescue_map_open:
                    self.map_ui.draw_rescue(screen, self.rescue_map_rect, self.player, self.network,
                                            self.island_owners, self.my_player_id())

        # Floating pickup texts
        for ft in self.floating_texts:
            ft.draw(screen, self.small_font)

        # Floating toast messages
        for i, t in enumerate(self.toasts):
            t.draw(screen, self.font, y_offset=i * 38)

        self.draw_treant_tracker(screen)
        self.draw_achievement_popup(screen)
        self.draw_ability_popup(screen)

        # Activity windows (minigames, dialogue) sit above the HUD and quest tracker.
        if not self.map_open:
            self.fishing.draw_ui(screen, self.font)
            self.grain_game.draw_ui(screen, self.font, logical_mouse_pos)
            self.stone_game.draw_ui(screen, self.font, logical_mouse_pos)
            self.wood_game.draw_ui(screen, self.font)
            draw_dialogue_box(screen, self.dialogue, self.font, self.small_font)
            if self.player_exhaust_timer > 0:
                draw_text(screen, self.font, tr("hud.exhausted", seconds=self.player_exhaust_timer),
                          (GAME_WIDTH // 2 - 70, GAME_HEIGHT // 2 - 50), (255, 50, 50), shadow=True)

        # Full Detailed Inventory Center Modal
        self.draw_inventory_ui(screen, logical_mouse_pos)

        # Player-to-Player Trade Center Modal
        self.draw_trade_ui(screen, logical_mouse_pos)

        # Compact campfire recipe modal is drawn above the HUD and world.
        self.draw_cooking_ui(screen, logical_mouse_pos)

        # Victory or Defeat Modal
        self.draw_victory_ui(screen, logical_mouse_pos)

        # In-Game Pause Modal
        if self.paused:
            pixel_overlay(screen, alpha=180)
            mw, mh = 360, 220
            mx = (GAME_WIDTH - mw) // 2
            my = (GAME_HEIGHT - mh) // 2
            pixel_window(screen, (mx, my, mw, mh), tr("pause.title"), self.font,
                         accent=COLOR_BORDER_OUTER, title_color=COLOR_TEXT_GOLD)
            pixel_button(screen, self.pause_resume_rect, tr("pause.resume"), self.font,
                         self.pause_resume_rect.collidepoint(logical_mouse_pos), text_color=(255, 230, 160))
            pixel_button(screen, self.pause_menu_rect, tr("pause.menu"), self.font,
                         self.pause_menu_rect.collidepoint(logical_mouse_pos), text_color=(255, 230, 160))

    def draw_treant_tracker(self, screen):
        if not self.treant_progress.quest_active:
            return
        progress = self.treant_progress
        held = 3 if progress.portal_unlocked else progress.keys_held
        if progress.boss_defeated:
            goal, color = tr("quest.complete"), (170, 230, 150)
        elif progress.portal_unlocked:
            goal, color = tr("quest.goal_boss"), (255, 190, 120)
        elif progress.keys_held >= 3:
            goal, color = tr("quest.goal_portal"), (255, 190, 120)
        else:
            goal, color = tr("quest.goal_keys"), (232, 194, 155)
        width = max(280, self.small_font.size(goal)[0] + 34)
        panel = pygame.Rect(12, 154, width, 86)
        content = pixel_window(screen, panel, TREANT_QUEST_NAME.upper(), self.small_font,
                               accent=(171, 103, 43), header=22, alpha=220)
        draw_text(screen, self.small_font, tr("quest.keys", held=held),
                  (content.x + 8, content.y + 4), (255, 218, 125))
        draw_text(screen, self.small_font, goal, (content.x + 8, content.y + 24), color)

    def draw_achievement_popup(self, screen):
        if not self.achievement_popup or self.achievement_popup_timer <= 0:
            return
        name, description = self.achievement_popup
        panel = pygame.Rect(GAME_WIDTH - 440, 18, 418, 100)
        content = pixel_window(screen, panel, tr("achievement.unlocked", name=name), self.font,
                               accent=(237, 177, 62), title_color=(255, 220, 110))
        for index, line in enumerate(wrap_text(self.small_font, description, content.width - 24)[:2]):
            draw_text(screen, self.small_font, line,
                      (content.x + 12, content.y + 8 + index * 20), (236, 220, 187))

    def draw_cooking_ui(self, screen, logical_mouse_pos):
        if not self.cooking_open:
            return
        pixel_overlay(screen, (18, 9, 5), 160)
        panel_rect = pygame.Rect(GAME_WIDTH // 2 - 250, GAME_HEIGHT // 2 - 180, 500, 360)
        pixel_window(screen, panel_rect, tr("cook.title"), self.font, accent=(218, 147, 63),
                     title_color=(255, 220, 128))
        self.cooking_close_rect = pygame.Rect(panel_rect.right - 40, panel_rect.y + 10, 26, 24)
        pixel_button(screen, self.cooking_close_rect, "X", self.font,
                     self.cooking_close_rect.collidepoint(logical_mouse_pos), tone="red")

        recipes = (
            ("meat", item_name("Pişmiş Et"), f"1 {item_name('Çiğ Et')}", "Çiğ Et", 1, "Pişmiş Et"),
            ("bread", tr("cook.village_bread"), f"2 {item_name('Tahil')}", "Tahil", 2, "Ekmek"),
        )
        self.cooking_action_rects = []
        for row, (key, name, requirement, ingredient, needed, output) in enumerate(recipes):
            card = pygame.Rect(panel_rect.x + 24, panel_rect.y + 62 + row * 104, panel_rect.width - 48, 90)
            pixel_box(screen, card, (31, 18, 13), (126, 80, 42))
            screen.blit(item_sprite(ingredient), (card.x + 14, card.y + 23))
            arrow = card.x + 50, card.y + 39
            pygame.draw.polygon(screen, (238, 181, 82),
                                [(arrow[0], arrow[1] - 4), (arrow[0] + 12, arrow[1] - 4), (arrow[0] + 12, arrow[1] - 9),
                                 (arrow[0] + 21, arrow[1]), (arrow[0] + 12, arrow[1] + 9),
                                 (arrow[0] + 12, arrow[1] + 4), (arrow[0], arrow[1] + 4)])
            screen.blit(item_sprite(output), (card.x + 78, card.y + 23))
            screen.blit(self.font.render(name, True, (255, 224, 150)), (card.x + 116, card.y + 12))
            have = self.inventory.get(ingredient, 0)
            enough = have >= needed
            req = self.small_font.render(tr("cook.requires", requirement=requirement, have=have), True,
                                         (180, 232, 150) if enough else (245, 125, 105))
            screen.blit(req, (card.x + 116, card.y + 42))
            button = pygame.Rect(card.right - 104, card.y + 24, 88, 38)
            pixel_button(screen, button, tr("cook.button"), self.small_font,
                         button.collidepoint(logical_mouse_pos), enough)
            self.cooking_action_rects.append(("cook", key, button))

        food_y = panel_rect.bottom - 76
        pygame.draw.line(screen, (114, 70, 38), (panel_rect.x + 24, food_y - 8),
                         (panel_rect.right - 24, food_y - 8), 2)
        x = panel_rect.x + 30
        for row, (item, heal) in enumerate((("Pişmiş Et", 2), ("Ekmek", 1))):
            y = food_y + row * 32
            screen.blit(item_sprite(item, 1), (x, y + 6))
            count = self.inventory.get(item, 0)
            label = self.small_font.render(tr("cook.food_line", name=item_name(item), count=count, heal=heal),
                                           True, (235, 218, 183))
            screen.blit(label, (x + 22, y + 6))
            eat = pygame.Rect(panel_rect.right - 94, y, 64, 28)
            usable = bool(count) and (self.health < self.max_health or self.energy < self.max_energy)
            pixel_button(screen, eat, tr("eat.button"), self.small_font,
                         eat.collidepoint(logical_mouse_pos), usable, "green")
            self.cooking_action_rects.append(("eat", item, eat))

    def draw_inventory_ui(self, screen, logical_mouse_pos):
        if not self.inventory_open:
            return

        pixel_overlay(screen, alpha=190)
        pw, ph = 1040, 620
        px = (GAME_WIDTH - pw) // 2
        py = (GAME_HEIGHT - ph) // 2
        pixel_window(screen, (px, py, pw, ph), tr("inventory.title"), self.font,
                     accent=(190, 145, 80), title_color=COLOR_TEXT_GOLD, header=36)

        self.inventory_close_rect = pygame.Rect(px + pw - 40, py + 9, 28, 26)
        pixel_button(screen, self.inventory_close_rect, "X", self.font,
                     self.inventory_close_rect.collidepoint(logical_mouse_pos), tone="red")

        self.inventory_action_rects = []

        # Left Column: all carried items, including food and ammunition.
        col1_x, col1_w = px + 18, 292
        col1_y = py + 52
        pixel_box(screen, (col1_x, col1_y, col1_w, ph - 70), (42, 26, 19), (140, 95, 50))
        screen.blit(self.font.render(tr("inventory.items"), True, (255, 220, 130)), (col1_x + 14, col1_y + 12))

        food = FOODS
        materials_info = [
            ("Odun", tr("inventory.material"), (235, 155, 75)),
            ("Tas", tr("inventory.material"), (205, 215, 225)),
            ("Tahil", tr("inventory.provisions"), (250, 215, 70)),
            ("Balik", tr("inventory.provisions"), (110, 215, 255)),
            ("Pişmiş Et", tr("inventory.food_stats", health=food["Pişmiş Et"].health,
                             energy=food["Pişmiş Et"].energy), (218, 132, 77)),
            ("Ekmek", tr("inventory.food_stats", health=food["Ekmek"].health,
                         energy=food["Ekmek"].energy), (231, 182, 91)),
            ("Ok", tr("inventory.ammo"), (174, 205, 210)),
        ]

        card_y = col1_y + 42
        for name, description, col in materials_info:
            card_rect = pygame.Rect(col1_x + 10, card_y, col1_w - 20, 60)
            pixel_box(screen, card_rect, (30, 18, 14), (85, 55, 30))

            icon = item_sprite(name)
            screen.blit(icon, icon.get_rect(center=(card_rect.x + 24, card_rect.centery)))

            name_surf = self.font.render(item_name(name), True, col)
            count = self.inventory.get(name, 0)
            count_surf = self.font.render(f"x{count}", True, (255, 245, 210))

            screen.blit(name_surf, (card_rect.x + 43, card_rect.y + 8))
            count_x = card_rect.right - count_surf.get_width() - 10
            screen.blit(count_surf, (count_x, card_rect.y + 8))

            desc = self.small_font.render(description, True, (184, 176, 160))
            screen.blit(desc, (card_rect.x + 43, card_rect.y + 34))
            if name in FOODS:
                eat = pygame.Rect(card_rect.right - 56, card_rect.y + 30, 46, 24)
                usable = count > 0 and (self.health < self.max_health or self.energy < self.max_energy)
                pixel_button(screen, eat, tr("eat.button"), self.small_font,
                             eat.collidepoint(logical_mouse_pos), usable, "green")
                self.inventory_action_rects.append(("eat", name, eat))

            card_y += 68

        hint = self.small_font.render(tr("inventory.quick_eat"), True, (155, 215, 150))
        screen.blit(hint, (col1_x + 12, col1_y + ph - 94))

        # Middle Column: inventory crafting and weapon upgrades.
        col_mid_x, col_mid_w = px + 320, 332
        pixel_box(screen, (col_mid_x, col1_y, col_mid_w, ph - 70), (42, 26, 19), (140, 95, 50))
        screen.blit(self.font.render(tr("craft.title"), True, (255, 220, 130)),
                    (col_mid_x + 14, col1_y + 12))

        recipe = RECIPES["arrows"]
        craft_card = pygame.Rect(col_mid_x + 10, col1_y + 44, col_mid_w - 20, 90)
        pixel_box(screen, craft_card, (30, 18, 14), (103, 78, 47))
        screen.blit(item_sprite("Ok"), (craft_card.x + 12, craft_card.y + 14))
        screen.blit(self.font.render(tr("craft.arrows", amount=recipe.amount), True, (210, 235, 225)),
                    (craft_card.x + 48, craft_card.y + 10))
        ingredients = format_amounts(recipe.ingredients, " + ")
        enough = self.can_afford(recipe.ingredients)
        screen.blit(self.small_font.render(ingredients, True, (176, 220, 160) if enough else (240, 130, 105)),
                    (craft_card.x + 48, craft_card.y + 38))
        craft_btn = pygame.Rect(craft_card.right - 100, craft_card.y + 52, 88, 28)
        pixel_button(screen, craft_btn, tr("craft.button"), self.small_font,
                     craft_btn.collidepoint(logical_mouse_pos), enough, "green")
        self.inventory_action_rects.append(("craft", "arrows", craft_btn))

        weapon_notes = {"axe": tr("weapon.axe_note"), "sword": tr("weapon.combat_note"),
                        "bow": tr("weapon.combat_note")}
        for row, weapon in enumerate(("axe", "sword", "bow")):
            y = col1_y + 148 + row * 112
            card = pygame.Rect(col_mid_x + 10, y, col_mid_w - 20, 100)
            pixel_box(screen, card, (30, 18, 14), (103, 78, 47))
            level = self.progression.levels[weapon]
            stats = self.progression.stats(weapon)
            screen.blit(self.font.render(tr("weapon.level", name=weapon_name(weapon), level=level),
                                         True, (255, 220, 135)), (card.x + 12, card.y + 10))
            detail = (tr("weapon.hits", hits=stats.required_hits) if weapon == "axe"
                      else tr("weapon.stats", damage=stats.damage_bonus, range=stats.range_multiplier))
            screen.blit(self.small_font.render(detail, True, (190, 205, 188)), (card.x + 12, card.y + 37))
            screen.blit(self.small_font.render(weapon_notes[weapon], True, (155, 145, 132)),
                        (card.x + 12, card.y + 61))
            cost = self.progression.next_cost(weapon)
            button = pygame.Rect(card.right - 104, card.y + 55, 94, 32)
            can_upgrade = cost is not None and self.can_afford(cost)
            label = tr("weapon.max") if cost is None else tr("weapon.upgrade")
            pixel_button(screen, button, label, self.small_font,
                         button.collidepoint(logical_mouse_pos), can_upgrade)
            if cost is not None:
                screen.blit(self.small_font.render(format_amounts(cost, " / "), True, (210, 174, 125)),
                            (card.x + 12, card.bottom - 20))
            self.inventory_action_rects.append(("upgrade", weapon, button))

        # Right Column: Conquest Status & Objectives
        col2_x, col2_w = px + 662, 360
        col2_y = py + 52
        pixel_box(screen, (col2_x, col2_y, col2_w, ph - 70), (42, 26, 19), (140, 95, 50))
        screen.blit(self.font.render(tr("rescue.title"), True, (255, 220, 130)), (col2_x + 14, col2_y + 12))

        # Interactive rescue chart: wheel zoom and left-button drag use the same
        # navigation model as the full map, while the delivery action stays below.
        self.inventory_rescue_map_rect = pygame.Rect(col2_x + 10, col2_y + 40, col2_w - 20, 116)
        self.map_ui.draw_rescue(screen, self.inventory_rescue_map_rect, self.player, self.network,
                                self.island_owners, self.my_player_id())

        # Objective Box
        obj_rect = pygame.Rect(col2_x + 10, col2_y + 164, col2_w - 20, 74)
        pixel_box(screen, obj_rect, (30, 18, 14), (100, 70, 40))

        my_id = self.my_player_id()
        my_count = sum(1 for o in self.island_owners.values() if o == my_id)

        obj_t1 = self.font.render(tr("rescue.goal"), True, (255, 215, 60))
        obj_t2 = self.small_font.render(tr("rescue.progress", count=my_count, target=self.WINNING_COUNT),
                                        True, (235, 230, 215))
        screen.blit(obj_t1, (obj_rect.x + 12, obj_rect.y + 10))
        screen.blit(obj_t2, (obj_rect.x + 12, obj_rect.y + 32))
        pixel_bar(screen, (obj_rect.x + 12, obj_rect.y + 54, obj_rect.width - 24, 12),
                  my_count / float(self.WINNING_COUNT), (240, 180, 50), (18, 12, 10))

        # Current Island Status Box
        isl_rect = pygame.Rect(col2_x + 10, col2_y + 246, col2_w - 20, 164)
        pixel_box(screen, isl_rect, (30, 18, 14), (100, 70, 40))

        idx, island, owner = self.current_island_info()
        if idx is not None:
            isl_t1 = self.font.render(tr("rescue.location", name=island.name), True, (255, 235, 160))
            screen.blit(isl_t1, (isl_rect.x + 12, isl_rect.y + 10))

            if owner == my_id:
                st_txt, st_col = tr("rescue.status_mine"), (100, 225, 100)
            elif owner is not None:
                st_txt, st_col = tr("rescue.status_other", owner=owner), (130, 210, 150)
            else:
                st_txt, st_col = tr("rescue.status_threat"), (200, 200, 200)
            screen.blit(self.small_font.render(st_txt, True, st_col), (isl_rect.x + 12, isl_rect.y + 34))

            cost = self.get_current_island_cost(False)
            inf_pct = int(round((self.get_inflation_rate() - 1.0) * 100))
            inf_tag = tr("rescue.inflation", pct=inf_pct) if inf_pct > 0 else ""
            c_title = self.small_font.render(tr("rescue.needs", inflation=inf_tag), True, (255, 215, 120))
            c_desc = self.small_font.render(format_amounts({item: cost[item] for item in SUPPLY_ITEMS}),
                                            True, (230, 220, 200))
            screen.blit(c_title, (isl_rect.x + 12, isl_rect.y + 60))
            screen.blit(c_desc, (isl_rect.x + 12, isl_rect.y + 80))

            if owner != my_id:
                self.conquer_action_rect = pygame.Rect(isl_rect.x + 20, isl_rect.y + 112, isl_rect.width - 40, 38)
                afford = self.can_afford(cost)
                btn_str = tr("rescue.deliver") if afford else tr("rescue.insufficient")
                pixel_button(screen, self.conquer_action_rect, btn_str, self.font,
                             self.conquer_action_rect.collidepoint(logical_mouse_pos), afford,
                             text_color=(255, 240, 180) if afford else (180, 120, 120))
            else:
                own_msg = self.small_font.render(tr("rescue.owned"), True, (140, 220, 140))
                screen.blit(own_msg, (isl_rect.x + 12, isl_rect.y + 115))
        else:
            water_t = self.font.render(tr("rescue.at_sea"), True, (120, 200, 240))
            screen.blit(water_t, (isl_rect.x + 12, isl_rect.y + 30))
            for index, line in enumerate(wrap_text(self.small_font, tr("rescue.at_sea_hint"),
                                                   isl_rect.width - 24)[:3]):
                screen.blit(self.small_font.render(line, True, (210, 210, 210)),
                            (isl_rect.x + 12, isl_rect.y + 60 + index * 20))

        tip_text = self.small_font.render(tr("rescue.map_hint"), True, (240, 200, 120))
        screen.blit(tip_text, (col2_x + 10, col2_y + 418))

    def draw_trade_ui(self, screen, logical_mouse_pos):
        if not self.trade_open:
            return

        pixel_overlay(screen, (10, 8, 6), 200)
        pw, ph = 760, 520
        px = (GAME_WIDTH - pw) // 2
        py = (GAME_HEIGHT - ph) // 2
        pixel_window(screen, (px, py, pw, ph), tr("trade.title"), self.font,
                     accent=(120, 200, 130), title_color=(210, 255, 210), header=36)

        self.trade_close_rect = pygame.Rect(px + pw - 40, py + 9, 28, 26)
        pixel_button(screen, self.trade_close_rect, "X", self.font,
                     self.trade_close_rect.collidepoint(logical_mouse_pos), tone="red")

        # Left Column: Send Trade Offer
        col1_x, col1_w = px + 18, 350
        col1_y = py + 50
        pixel_box(screen, (col1_x, col1_y, col1_w, ph - 68), (38, 30, 24), (110, 85, 55))
        screen.blit(self.font.render(tr("trade.new_offer"), True, (255, 225, 140)), (col1_x + 14, col1_y + 10))

        # Available trade partners (other players)
        my_id = self.my_player_id()
        other_pids = []
        if self.network and self.network.connected:
            with self.network.lock:
                other_pids = sorted(list(self.network.other_players.keys()))

        self.trade_action_rects = []

        ptn_y = col1_y + 36
        ptn_lbl = self.small_font.render(tr("trade.partner"), True, (220, 215, 200))
        screen.blit(ptn_lbl, (col1_x + 14, ptn_y))

        # All players button
        all_btn = pygame.Rect(col1_x + 110, ptn_y - 2, 75, 22)
        is_all = (self.trade_selected_partner is None)
        pixel_button(screen, all_btn, tr("trade.everyone"), self.small_font,
                     all_btn.collidepoint(logical_mouse_pos), True, "green" if is_all else "wood",
                     (255, 255, 255) if is_all else (200, 190, 170))
        self.trade_action_rects.append(('select_partner', None, all_btn))

        bx = col1_x + 192
        for opid in other_pids[:3]:
            p_btn = pygame.Rect(bx, ptn_y - 2, 44, 22)
            is_sel = (self.trade_selected_partner == opid)
            pixel_button(screen, p_btn, f"P{opid}", self.small_font,
                         p_btn.collidepoint(logical_mouse_pos), True, "green" if is_sel else "wood",
                         (255, 255, 255) if is_sel else (200, 190, 170))
            self.trade_action_rects.append(('select_partner', opid, p_btn))
            bx += 48

        def stepper(row_y, resource, value, minus_action, plus_action):
            btn_minus = pygame.Rect(col1_x + 160, row_y, 24, 22)
            pixel_button(screen, btn_minus, "-", self.font, btn_minus.collidepoint(logical_mouse_pos))
            self.trade_action_rects.append((minus_action, resource, btn_minus))
            val_txt = self.font.render(str(value), True, (255, 230, 120))
            screen.blit(val_txt, val_txt.get_rect(center=(col1_x + 205, row_y + 11)))
            btn_plus = pygame.Rect(col1_x + 230, row_y, 24, 22)
            pixel_button(screen, btn_plus, "+", self.font, btn_plus.collidepoint(logical_mouse_pos))
            self.trade_action_rects.append((plus_action, resource, btn_plus))

        # Giving (Offer) section
        res_list = [(name, RESOURCE_COLORS[name]) for name in SUPPLY_ITEMS]
        give_lbl = self.small_font.render(tr("trade.give"), True, (130, 220, 140))
        screen.blit(give_lbl, (col1_x + 14, col1_y + 68))

        row_y = col1_y + 90
        for rname, rcol in res_list:
            have = self.inventory.get(rname, 0)
            pygame.draw.rect(screen, rcol, (col1_x + 18, row_y + 7, 8, 8))
            r_txt = self.small_font.render(tr("trade.have", name=item_name(rname), count=have), True, (240, 235, 220))
            screen.blit(r_txt, (col1_x + 34, row_y + 3))
            stepper(row_y, rname, self.trade_offer.get(rname, 0), 'offer_minus', 'offer_plus')
            row_y += 30

        # Request (Want) section
        want_lbl = self.small_font.render(tr("trade.want"), True, (235, 180, 100))
        screen.blit(want_lbl, (col1_x + 14, row_y + 6))
        row_y += 28

        for rname, rcol in res_list:
            pygame.draw.rect(screen, rcol, (col1_x + 18, row_y + 7, 8, 8))
            r_txt = self.small_font.render(item_name(rname), True, (240, 235, 220))
            screen.blit(r_txt, (col1_x + 34, row_y + 3))
            stepper(row_y, rname, self.trade_request.get(rname, 0), 'req_minus', 'req_plus')
            row_y += 30

        # Send proposal button
        self.trade_send_btn = pygame.Rect(col1_x + 75, col1_y + ph - 118, 200, 36)
        can_send = any(v > 0 for v in self.trade_offer.values()) and any(v > 0 for v in self.trade_request.values())
        pixel_button(screen, self.trade_send_btn, tr("trade.send"), self.font,
                     self.trade_send_btn.collidepoint(logical_mouse_pos), can_send, "green")

        # Right Column: Active & Incoming Offers
        col2_x, col2_w = px + 382, 360
        col2_y = py + 50
        pixel_box(screen, (col2_x, col2_y, col2_w, ph - 68), (38, 30, 24), (110, 85, 55))
        screen.blit(self.font.render(tr("trade.active"), True, (255, 225, 140)), (col2_x + 14, col2_y + 10))

        trades = []
        if self.network and self.network.connected and hasattr(self.network, 'trades'):
            with self.network.lock:
                trades = list(self.network.trades)

        trade_card_y = col2_y + 38
        if not trades:
            screen.blit(self.small_font.render(tr("trade.empty"), True, (180, 175, 160)),
                        (col2_x + 16, trade_card_y + 10))
            screen.blit(self.small_font.render(tr("trade.empty_hint1"), True, (150, 145, 135)),
                        (col2_x + 16, trade_card_y + 34))
            screen.blit(self.small_font.render(tr("trade.empty_hint2"), True, (150, 145, 135)),
                        (col2_x + 16, trade_card_y + 54))
        else:
            for t in trades[:3]:
                card_r = pygame.Rect(col2_x + 10, trade_card_y, col2_w - 20, 110)
                is_from_me = (t.get('from_pid') == my_id)
                status = t.get('status', 'pending')
                bg_col = {'accepted': (25, 45, 25), 'cancelled': (45, 25, 25)}.get(status, (45, 34, 25))
                pixel_box(screen, card_r, bg_col, (100, 75, 50))

                from_str = tr("trade.yours") if is_from_me else tr("trade.from", pid=t.get('from_pid'))
                status_key = f"trade.status.{status}"
                status_text = tr(status_key) if status_key in TRADE_STATUS_KEYS else str(status).upper()
                t_lbl = self.small_font.render(f"{from_str} [{status_text}]", True, (255, 220, 130))
                screen.blit(t_lbl, (card_r.x + 10, card_r.y + 8))

                give_items = format_amounts({k: v for k, v in t.get('offer', {}).items() if v > 0})
                req_items = format_amounts({k: v for k, v in t.get('request', {}).items() if v > 0})

                if is_from_me:
                    txt1 = self.small_font.render(tr("trade.you_give", items=give_items), True, (140, 230, 140))
                    txt2 = self.small_font.render(tr("trade.you_want", items=req_items), True, (240, 200, 120))
                else:
                    txt1 = self.small_font.render(tr("trade.they_give", items=give_items), True, (140, 230, 140))
                    txt2 = self.small_font.render(tr("trade.they_want", items=req_items), True, (240, 200, 120))

                screen.blit(txt1, (card_r.x + 10, card_r.y + 32))
                screen.blit(txt2, (card_r.x + 10, card_r.y + 54))

                if status == 'pending':
                    button = pygame.Rect(card_r.right - 100, card_r.bottom - 32, 90, 24)
                    if is_from_me:
                        pixel_button(screen, button, tr("trade.cancel"), self.small_font,
                                     button.collidepoint(logical_mouse_pos), True, "red")
                        self.trade_action_rects.append(('cancel_trade', t.get('id'), button))
                    else:
                        req_dict = t.get('request', {})
                        can_accept = all(self.inventory.get(k, 0) >= v for k, v in req_dict.items())
                        pixel_button(screen, button, tr("trade.accept") if can_accept else tr("trade.insufficient"),
                                     self.small_font, button.collidepoint(logical_mouse_pos), can_accept, "green")
                        if can_accept:
                            self.trade_action_rects.append(('accept_trade', t.get('id'), button))

                trade_card_y += 118

    def submit_trade_proposal(self):
        offer_clean = {k: v for k, v in self.trade_offer.items() if v > 0}
        req_clean = {k: v for k, v in self.trade_request.items() if v > 0}
        if not offer_clean or not req_clean:
            self.add_toast(tr("toast.trade_select"))
            return False

        if not all(self.inventory.get(k, 0) >= v for k, v in offer_clean.items()):
            self.add_toast(tr("toast.trade_lacking"))
            return False

        if self.network and self.network.connected:
            self.network.propose_trade(self.trade_selected_partner, offer_clean, req_clean)
            self.add_toast(tr("toast.trade_sent"))
            self.trade_offer = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
            self.trade_request = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
            return True
        else:
            self.add_toast(tr("toast.trade_offline"))
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
                    self.add_toast(tr("toast.trade_complete"), color=(120, 240, 130))

                # If I was the acceptor
                elif t.get('to_pid') == my_id or t.get('to_pid') is None:
                    # Only execute if this client triggered acceptance (detected via processed_trades or local accept)
                    pass

    def draw_victory_ui(self, screen, logical_mouse_pos):
        if self.winner is None or self.victory_dismissed:
            return

        pixel_overlay(screen, (8, 4, 2), 210)
        vw, vh = 600, 360
        vx = (GAME_WIDTH - vw) // 2
        vy = (GAME_HEIGHT - vh) // 2

        my_id = self.my_player_id()
        i_won = (self.winner == my_id)
        if i_won:
            t_col = (255, 225, 70)
            title_text, sub_text = tr("victory.title"), tr("victory.sub")
        else:
            t_col = (240, 70, 70)
            title_text, sub_text = tr("defeat.title"), tr("defeat.sub", winner=self.winner)
        pixel_window(screen, (vx, vy, vw, vh), accent=(255, 215, 60) if i_won else (196, 82, 60))

        title = self.font.render(title_text, True, t_col)
        sub = self.small_font.render(sub_text, True, (245, 235, 200))
        screen.blit(title, title.get_rect(center=(GAME_WIDTH // 2, vy + 40)))
        screen.blit(sub, sub.get_rect(center=(GAME_WIDTH // 2, vy + 75)))

        # Stats Box
        s_rect = pygame.Rect(vx + 30, vy + 110, vw - 60, 130)
        pixel_box(screen, s_rect, (24, 12, 8), (120, 80, 40))

        my_count = sum(1 for o in self.island_owners.values() if o == my_id)
        s1 = self.font.render(tr("victory.islands", count=my_count, target=self.WINNING_COUNT), True, (255, 220, 100))
        inventory = format_amounts({item: self.inventory.get(item, 0) for item in SUPPLY_ITEMS}, " | ")
        s2 = self.small_font.render(tr("victory.inventory", items=inventory), True, (230, 220, 200))
        s3 = self.small_font.render(tr("victory.flavor"), True, (180, 230, 160) if i_won else (200, 180, 160))

        screen.blit(s1, s1.get_rect(center=(GAME_WIDTH // 2, s_rect.y + 30)))
        screen.blit(s2, s2.get_rect(center=(GAME_WIDTH // 2, s_rect.y + 65)))
        screen.blit(s3, s3.get_rect(center=(GAME_WIDTH // 2, s_rect.y + 98)))

        # Buttons
        self.victory_continue_rect = pygame.Rect(vx + 70, vy + 280, 210, 44)
        self.victory_menu_rect = pygame.Rect(vx + 320, vy + 280, 210, 44)
        pixel_button(screen, self.victory_continue_rect, tr("victory.continue"), self.font,
                     self.victory_continue_rect.collidepoint(logical_mouse_pos), text_color=(255, 235, 180))
        pixel_button(screen, self.victory_menu_rect, tr("victory.menu"), self.font,
                     self.victory_menu_rect.collidepoint(logical_mouse_pos), text_color=(255, 235, 180))


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
    def __init__(self, host='127.0.0.1', port=5555, audio=None, world_seed=42):
        self.host = host
        self.port = port
        self.status = PreloadStatus.NOT_STARTED
        self.progress = 0.0
        self.status_text = tr("preload.not_started")
        self.data_queue = queue.Queue()
        self.worker_thread = None
        self.configured_seed = int(world_seed)
        self.network = NetworkClient(host=self.host, port=self.port, offline_seed=self.configured_seed)
        self.game_session = None
        self.atlas = None
        self.finalizer = None
        self.audio = audio
        self.cancelled = False

    def cancel(self):
        """Abandon this preload (settings changed); a late connection is closed."""
        self.cancelled = True
        self.network.close()

    def start(self):
        self.status = PreloadStatus.LOADING
        self.status_text = tr("preload.preparing")
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def _worker(self):
        try:
            self.progress = 0.05
            self.status_text = tr("preload.network")

            connected = self.network.try_connect(timeout=0.6)
            if self.cancelled:
                self.network.close()
                return
            # Online play always uses the server's seed, so every client builds the
            # same shared world; offline play uses the configured seed.
            seed = self.network.seed

            self.status_text = tr("preload.terrain")
            self.progress = 0.10

            def on_progress(p):
                self.progress = 0.10 + p * 0.70

            world = make_world(seed, on_progress)

            self.status_text = tr("preload.ports")
            self.progress = 0.82
            ports = generate_ports(world)

            self.status_text = tr("preload.spawn")
            self.progress = 0.88
            spawn = self.network.spawn if connected and self.network.spawn else find_spawn(world)

            self.status_text = tr("preload.tiles")
            self.progress = 0.94
            tile_bytes = compute_tile_pixels(world)
            prepare_terrain(world)

            self.progress = 0.99
            self.status_text = tr("preload.finalizing")
            if self.cancelled:
                self.network.close()
                return

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
            self.status_text = tr("preload.error", error=e)

    def _finalize(self, data, customization):
        tiles = pygame.image.frombuffer(data["tile_bytes"], (COLS, ROWS), "RGB").convert()
        try:
            self.atlas = TileAtlas(find_tileset_file(), deferred=True)
            yield from self.atlas.build_steps
        except Exception as exc:
            print(f"[WARNING] Could not load TileAtlas: {exc}")
            self.atlas = None
        character_sheet = load_required_character_sheet()
        yield
        self.game_session = GameSession(data["world"], data["ports"], data["spawn"], tiles,
                                        data["network"], data["seed"], customization,
                                        atlas=self.atlas, character_sheet=character_sheet,
                                        audio=self.audio, save_data=load_local_save(data["world"].seed))
        if self.game_session.terrain_renderer:
            yield from self.game_session.terrain_renderer.warm_view(
                self.game_session.cam_x, self.game_session.cam_y, GAME_WIDTH, GAME_HEIGHT)
        self.status = PreloadStatus.READY
        self.progress = 1.0
        self.status_text = tr("preload.ready")

    def poll(self, customization) -> bool:
        if self.status == PreloadStatus.READY:
            return True
        if self.finalizer is None and not self.data_queue.empty():
            self.status_text = tr("preload.artwork")
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
                self.status_text = tr("preload.error", error=exc)
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
    # True once the player has entered the world, so quitting saves progress.
    session_started = False

    def __init__(self):
        enable_hidpi_awareness()
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption(GAME_TITLE)

        # Logical surfaces for menu and game; the viewport scales them to the window.
        self.menu_surface = pygame.Surface((MENU_WIDTH, MENU_HEIGHT))
        self.game_surface = pygame.Surface((GAME_WIDTH, GAME_HEIGHT))
        # Settings/credits are drawn here so they also cover the full-resolution logo.
        self.menu_overlay = pygame.Surface((MENU_WIDTH, MENU_HEIGHT), pygame.SRCALPHA)

        # State management: "MENU" or "GAME"
        self.state = "MENU"
        self.show_customize = False
        self.show_settings = False
        self.show_credits = False
        self.settings = load_settings()
        self.settings_draft = {}
        self.settings_focus = None
        self.settings_error = ""
        self.settings_notice = ""
        # (validated GameSettings, warning lines) while the confirmation is open.
        self.settings_pending = None

        # Display scaling / letterboxing variables
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.is_fullscreen = False
        self.apply_display(self.settings)
        self.clock = pygame.time.Clock()
        self.audio = AudioManager(BASE_DIR / "music", menu_music=MENU_MUSIC_ASSET)
        self.audio.set_category_volume("music", self.settings.music_volume / 100)
        self.is_running = True

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
        self.preloader = BackgroundPreloader(
            self.settings.server_address, self.settings.server_port, self.audio,
            stable_seed(self.settings.world_seed))
        self.preloader.start()
        self.audio.play_menu_music()

    # -----------------------------------------------------------------------
    # Asset Loading & Slicing
    # -----------------------------------------------------------------------
    def load_menu_assets(self):
        print("Loading menu assets...")

        # 1. Background
        bg_path = require_asset(MAIN_MENU_BACKGROUND_ASSET)
        bg_raw = pygame.image.load(str(bg_path)).convert()
        self.bg_surface = pygame.transform.scale(bg_raw, (MENU_WIDTH, MENU_HEIGHT))

        # 2. Base Character
        char_path = require_asset(MENU_CHARACTER_ASSET)
        char_raw = pygame.image.load(str(char_path)).convert_alpha()
        f0_rect = pygame.Rect(92, 36, 238, 483)
        self.char_orig = char_raw.subsurface(f0_rect).copy()

        char_h = 190
        char_scale = char_h / self.char_orig.get_height()
        char_w = round(self.char_orig.get_width() * char_scale)
        self.char_scaled = pygame.transform.scale(self.char_orig, (char_w, char_h))
        self.char_pos = (430 - char_w // 2, 370 - char_h)

        # 3. Wooden Menu Asset
        menu_path = require_asset(MENU_BUTTONS_ASSET)
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
        hair_path = require_asset(HAIR_SKIN_ASSET)
        self.hair_sheet = pygame.image.load(str(hair_path)).convert_alpha()

        # 5. Cloth Sheet
        cloth_path = require_asset(CLOTHING_ASSET)
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

        self.load_logo()
        print("Menu assets loaded successfully!")

    # Sky band above the character preview (y >= 180) and left of the wooden
    # sign (x >= 722).  While the customization panel (x >= 476, y >= 68) is
    # open the logo shrinks into the compact top-left box instead.
    LOGO_BOX = pygame.Rect(28, 10, 660, 150)
    LOGO_BOX_COMPACT = pygame.Rect(16, 6, 448, 164)

    def load_logo(self):
        """Load the optional title artwork; the text title remains as fallback."""
        self.logo = None
        self.logo_rect = None
        self._logo_rects = {}
        self._logo_cache = (None, None)
        if not GAME_LOGO_ASSET.is_file():
            print(f"[MENU] Logo not found at {GAME_LOGO_ASSET}; using the text title.")
            return
        try:
            logo = pygame.image.load(str(GAME_LOGO_ASSET)).convert_alpha()
            logo = remove_flat_background(logo)
            # Trim transparent margins so the artwork, not its canvas, fills the box.
            bounds = logo.get_bounding_rect(min_alpha=8)
            if bounds.width < 8 or bounds.height < 8:
                raise ValueError("logo is empty after removing its background")
            logo = self._logo_with_backing(logo.subsurface(bounds).copy())
        except (pygame.error, OSError, ValueError) as exc:
            print(f"[MENU] Could not load logo {GAME_LOGO_ASSET.name}: {exc}; using the text title.")
            return
        for compact, box in ((False, self.LOGO_BOX), (True, self.LOGO_BOX_COMPACT)):
            fit = min(box.width / logo.get_width(), box.height / logo.get_height())
            size = (max(1, round(logo.get_width() * fit)), max(1, round(logo.get_height() * fit)))
            rect = pygame.Rect((0, 0), size)
            rect.midtop = (box.centerx, box.top)
            self._logo_rects[compact] = rect
        self.logo = logo
        self.logo_rect = self._logo_rects[False]

    @staticmethod
    def _logo_with_backing(logo, radius=9, shadow=(6, 12)):
        """Add a dark outline and drop shadow so the title reads over the busy backdrop."""
        size = radius * 2 + 1
        disc = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(disc, (255, 255, 255), (radius, radius), radius)
        # Convolving with a disc dilates the silhouette by ``radius`` on every side.
        halo = pygame.mask.from_surface(logo, 64).convolve(pygame.mask.from_surface(disc))
        sx, sy = shadow
        canvas = pygame.Surface((halo.get_size()[0] + sx, halo.get_size()[1] + sy), pygame.SRCALPHA)
        canvas.blit(halo.to_surface(setcolor=(12, 7, 5, 105), unsetcolor=(0, 0, 0, 0)), (sx, sy))
        canvas.blit(halo.to_surface(setcolor=(24, 14, 10, 185), unsetcolor=(0, 0, 0, 0)), (0, 0))
        canvas.blit(logo, (radius, radius))
        return canvas

    def draw_menu_backdrop(self):
        """Fill any area around the 16:9 menu with a dimmed extension of its scene."""
        size = self.window.get_size()
        if (self.target_w, self.target_h) == size:
            return
        cached = getattr(self, "_menu_backdrop", None)
        if cached is None or cached[0] != size:
            cover = max(size[0] / MENU_WIDTH, size[1] / MENU_HEIGHT)
            scaled = pygame.transform.smoothscale(
                self.bg_surface, (math.ceil(MENU_WIDTH * cover), math.ceil(MENU_HEIGHT * cover)))
            backdrop = pygame.Surface(size)
            backdrop.blit(scaled, scaled.get_rect(center=(size[0] // 2, size[1] // 2)))
            backdrop.fill((92, 80, 76), special_flags=pygame.BLEND_RGB_MULT)
            self._menu_backdrop = cached = (size, backdrop)
        self.window.blit(cached[1], (0, 0))

    def draw_logo(self):
        """Blit the logo at window resolution with its aspect ratio preserved.

        Downscaling the high-resolution artwork uses area filtering (nearest
        neighbour would drop whole art pixels and shimmer); enlarging stays
        nearest neighbour so pixels remain sharp squares.
        """
        if self.logo is None:
            return
        self.logo_rect = self._logo_rects[bool(self.show_customize)]
        size = (max(1, round(self.logo_rect.width * self.scale)),
                max(1, round(self.logo_rect.height * self.scale)))
        if self._logo_cache[0] != size:
            shrinking = size[0] < self.logo.get_width()
            scaler = pygame.transform.smoothscale if shrinking else pygame.transform.scale
            self._logo_cache = (size, scaler(self.logo, size))
        self.window.blit(self._logo_cache[1], (self.offset_x + round(self.logo_rect.x * self.scale),
                                               self.offset_y + round(self.logo_rect.y * self.scale)))

    # -----------------------------------------------------------------------
    # Coordinate Conversion & Window Letterboxing
    # -----------------------------------------------------------------------
    def update_letterbox(self):
        try:
            window_size = pygame.display.get_window_size()
        except pygame.error:
            window_size = None
        surface_size = self.window.get_size()
        # Gameplay adopts the display's aspect ratio (more world on wide screens)
        # instead of letterboxing a fixed 1200x780 image.
        if set_game_view_size(game_view_size(surface_size)):
            self.game_surface = pygame.Surface((GAME_WIDTH, GAME_HEIGHT))
            preloader = getattr(self, "preloader", None)
            if preloader is not None and preloader.game_session is not None:
                preloader.game_session.layout_view()
        logical = (GAME_WIDTH, GAME_HEIGHT) if self.state == "GAME" else (MENU_WIDTH, MENU_HEIGHT)
        VIEWPORT.update(surface_size, logical, self.settings.pixel_perfect, window_size)
        self.scale = VIEWPORT.scale
        self.target_w, self.target_h = VIEWPORT.target_size
        self.offset_x, self.offset_y = VIEWPORT.offset

    def window_to_logical(self, pos: tuple) -> tuple:
        return VIEWPORT.to_logical(pos)

    def apply_display(self, settings):
        """Open the window in the configured mode; fullscreen uses the desktop resolution."""
        self.is_fullscreen = settings.display_mode == "fullscreen"
        if self.is_fullscreen:
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            size = fit_window_size((settings.window_width, settings.window_height), desktop_size())
            self.window = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.update_letterbox()

    def toggle_fullscreen(self):
        mode = "windowed" if self.is_fullscreen else "fullscreen"
        self.settings = replace(self.settings, display_mode=mode)
        self.apply_display(self.settings)
        try:
            save_settings(self.settings)
        except OSError as exc:
            print(f"[SETTINGS] Could not save display mode: {exc}")

    SETTINGS_FIELDS = ("world_seed", "server_address", "server_port")

    def settings_layout(self):
        mx, my = (MENU_WIDTH - 540) // 2, (MENU_HEIGHT - 500) // 2
        cx, cy = (MENU_WIDTH - 440) // 2, (MENU_HEIGHT - 210) // 2
        row = lambda index: my + 48 + index * 38
        return {
            "panel": pygame.Rect(mx, my, 540, 500),
            "world_seed": pygame.Rect(mx + 200, row(0), 220, 28),
            "random": pygame.Rect(mx + 428, row(0), 84, 28),
            "server_address": pygame.Rect(mx + 200, row(1), 312, 28),
            "server_port": pygame.Rect(mx + 200, row(2), 110, 28),
            "display": pygame.Rect(mx + 200, row(3), 220, 28),
            "size_prev": pygame.Rect(mx + 200, row(4), 32, 28),
            "size_value": pygame.Rect(mx + 236, row(4), 148, 28),
            "size_next": pygame.Rect(mx + 388, row(4), 32, 28),
            "scaling": pygame.Rect(mx + 200, row(5), 220, 28),
            "volume_down": pygame.Rect(mx + 200, row(6), 32, 28),
            "volume_value": pygame.Rect(mx + 236, row(6), 148, 28),
            "volume_up": pygame.Rect(mx + 388, row(6), 32, 28),
            "apply": pygame.Rect(mx + 125, my + 432, 130, 32),
            "cancel": pygame.Rect(mx + 285, my + 432, 130, 32),
            "confirm_panel": pygame.Rect(cx, cy, 440, 210),
            "confirm_yes": pygame.Rect(cx + 70, cy + 160, 130, 32),
            "confirm_no": pygame.Rect(cx + 240, cy + 160, 130, 32),
        }

    def open_settings(self):
        self.show_settings = True
        self.settings_draft = {"world_seed": self.settings.world_seed,
                               "server_address": self.settings.server_address,
                               "server_port": str(self.settings.server_port),
                               "display_mode": self.settings.display_mode,
                               "window_size": (self.settings.window_width, self.settings.window_height),
                               "pixel_perfect": self.settings.pixel_perfect,
                               "music_volume": self.settings.music_volume}
        self.settings_focus = None
        self.settings_error = ""
        self.settings_notice = ""
        self.settings_pending = None

    def close_settings(self):
        self.show_settings = False
        self.settings_focus = None
        self.settings_pending = None

    def _apply_settings(self):
        """Validate the draft; regenerate only after an explicit confirmation."""
        try:
            host, port = validate_endpoint(self.settings_draft["server_address"],
                                           self.settings_draft["server_port"])
            seed_text = self.settings_draft["world_seed"].strip()
            stable_seed(seed_text)
        except ValueError as exc:
            self.settings_error, self.settings_notice = str(exc), ""
            return
        draft = self.settings_draft
        width, height = draft.get("window_size", (self.settings.window_width, self.settings.window_height))
        new = GameSettings(seed_text, host, port,
                           draft.get("display_mode", self.settings.display_mode), width, height,
                           draft.get("pixel_perfect", self.settings.pixel_perfect),
                           draft.get("music_volume", self.settings.music_volume)).validated()
        seed_changed = seed_text != self.settings.world_seed
        server_changed = (host, port) != (self.settings.server_address, self.settings.server_port)
        if not (seed_changed or server_changed):
            if self._presentation(new) == self._presentation(self.settings):
                self.close_settings()
                return
            # Display and volume changes never touch the world: apply right away.
            try:
                save_settings(new)
            except OSError as exc:
                self.settings_error, self.settings_notice = tr("settings.save_failed", error=exc), ""
                return
            self._apply_presentation(new)
            self.settings_error, self.settings_notice = "", tr("settings.display_applied")
            return
        session = self.preloader.game_session
        if session is not None and session.boss_active:
            self.settings_error, self.settings_notice = tr("settings.busy"), ""
            return
        connected = self.preloader.network.connected
        if session is None and not connected:
            # Nothing has been played yet: no world or connection would be lost.
            self._commit_settings(new)
            return
        lines = []
        if seed_changed:
            lines.append(tr("settings.confirm_regen"))
        if server_changed:
            lines.append(tr("settings.confirm_reconnect"))
        if connected:
            lines.append(tr("settings.confirm_disconnect"))
        if session is not None:
            lines.append(tr("settings.confirm_progress"))
        self.settings_error = ""
        self.settings_pending = (new, lines)

    @staticmethod
    def _presentation(settings):
        return (settings.display_mode, settings.window_width, settings.window_height,
                settings.pixel_perfect, settings.music_volume)

    def _apply_presentation(self, new):
        """Apply display/volume differences from the current settings, then adopt ``new``."""
        old = self.settings
        self.settings = new
        if self.audio is not None and new.music_volume != old.music_volume:
            self.audio.set_category_volume("music", new.music_volume / 100)
        if self._presentation(new)[:4] != self._presentation(old)[:4]:
            self.apply_display(new)

    def _commit_settings(self, new):
        try:
            save_settings(new)
        except OSError as exc:
            self.settings_error, self.settings_notice = tr("settings.save_failed", error=exc), ""
            self.settings_pending = None
            return
        if self.preloader.game_session is not None:
            # Offline progress is kept per world seed, so switching worlds is safe.
            self.save_game_progress("settings")
            self.preloader.game_session.deactivate_audio()
        self.session_started = False
        self.preloader.cancel()
        self._apply_presentation(new)
        self.preloader = BackgroundPreloader(new.server_address, new.server_port, self.audio,
                                             stable_seed(new.world_seed))
        self.preloader.start()
        self.settings_pending = None
        self.settings_error = ""
        self.settings_notice = tr("settings.saved")

    def _settings_key(self, event):
        if self.settings_pending is not None:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                self._commit_settings(self.settings_pending[0])
            elif event.key in (pygame.K_ESCAPE, pygame.K_n):
                self.settings_pending = None
            return
        if event.key == pygame.K_ESCAPE:
            self.close_settings()
            return
        order = self.SETTINGS_FIELDS
        if event.key == pygame.K_TAB:
            current = order.index(self.settings_focus) if self.settings_focus in order else -1
            step = -1 if event.mod & pygame.KMOD_SHIFT else 1
            self.settings_focus = order[(current + step) % len(order)]
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._apply_settings()
            return
        if not self.settings_focus:
            return
        value = self.settings_draft[self.settings_focus]
        if event.key == pygame.K_BACKSPACE:
            self.settings_draft[self.settings_focus] = value[:-1]
        elif event.key == pygame.K_a and event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META):
            self.settings_draft[self.settings_focus] = ""
        elif event.unicode and event.unicode.isprintable() and len(value) < 80:
            if self.settings_focus != "server_port" or event.unicode.isdigit():
                self.settings_draft[self.settings_focus] = value + event.unicode
        self.settings_error = ""

    def _settings_click(self, lx, ly):
        layout = self.settings_layout()
        if self.settings_pending is not None:
            if layout["confirm_yes"].collidepoint(lx, ly):
                self._commit_settings(self.settings_pending[0])
            elif layout["confirm_no"].collidepoint(lx, ly):
                self.settings_pending = None
            return
        for name in self.SETTINGS_FIELDS:
            if layout[name].collidepoint(lx, ly):
                self.settings_focus = name
                return
        draft = self.settings_draft
        if layout["random"].collidepoint(lx, ly):
            draft["world_seed"] = random_seed_text()
            self.settings_error = ""
        elif layout["display"].collidepoint(lx, ly):
            draft["display_mode"] = "windowed" if draft["display_mode"] == "fullscreen" else "fullscreen"
        elif layout["size_prev"].collidepoint(lx, ly) or layout["size_next"].collidepoint(lx, ly):
            sizes = window_size_options(desktop_size(), draft["window_size"])
            index = sizes.index(tuple(draft["window_size"]))
            step = 1 if layout["size_next"].collidepoint(lx, ly) else -1
            draft["window_size"] = sizes[(index + step) % len(sizes)]
        elif layout["scaling"].collidepoint(lx, ly):
            draft["pixel_perfect"] = not draft["pixel_perfect"]
        elif layout["volume_down"].collidepoint(lx, ly):
            draft["music_volume"] = max(0, draft["music_volume"] - 10)
        elif layout["volume_up"].collidepoint(lx, ly):
            draft["music_volume"] = min(100, draft["music_volume"] + 10)
        elif layout["apply"].collidepoint(lx, ly):
            self._apply_settings()
        elif layout["cancel"].collidepoint(lx, ly):
            self.close_settings()
        elif not layout["panel"].collidepoint(lx, ly):
            self.settings_focus = None

    # -----------------------------------------------------------------------
    # Event Handling
    # -----------------------------------------------------------------------
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.is_running = False
                return

            elif event.type in (pygame.VIDEORESIZE, pygame.WINDOWSIZECHANGED):
                self.window = pygame.display.get_surface()
                self.update_letterbox()

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                self.toggle_fullscreen()

            if self.state == "GAME" and self.preloader.game_session:
                pointer = event.pos if hasattr(event, "pos") else pygame.mouse.get_pos()
                lx, ly = self.window_to_logical(pointer)
                action = self.preloader.game_session.handle_event(event, (lx, ly))
                if action == "MENU":
                    self.preloader.game_session.save_progress("menu")
                    self.preloader.game_session.deactivate_audio()
                    self.state = "MENU"
                    self.update_letterbox()
                    self.audio.play_menu_music()

            elif self.state == "MENU":
                if event.type == pygame.KEYDOWN:
                    if self.show_settings:
                        self._settings_key(event)
                        continue
                    if event.key == pygame.K_ESCAPE:
                        if self.show_settings:
                            self.show_settings = False
                        elif self.show_credits:
                            self.show_credits = False
                        elif self.show_customize:
                            self.show_customize = False
                        elif self.preloader.game_session:
                            self.state = "GAME"
                            self.session_started = True
                            self.preloader.game_session.autosave_enabled = True
                            self.preloader.game_session.activate_audio()
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
            self._settings_click(lx, ly)
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
                self.session_started = True
                self.preloader.game_session.autosave_enabled = True
                self.preloader.game_session.activate_audio()
                self.show_customize = False
                self.show_settings = False
                self.show_credits = False
                self.update_letterbox()
            else:
                print(f"[MENU] Start Game clicked, but world is still preparing ({self.preloader.progress:.0%})...")
        elif action_name == "Customize":
            self.show_customize = not self.show_customize
        elif action_name == "Settings":
            self.open_settings()
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
        if self.logo is None:
            self.font_renderer.draw_text_centered(self.menu_surface, GAME_TITLE,
                                                  (MENU_WIDTH // 2, 32), font_type="large",
                                                  color=COLOR_TEXT_GOLD)

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
                self.font_renderer.draw_text_centered(self.menu_surface, tr("menu.start_hint"), hint_rect.center,
                                                     font_type="small", color=(255, 235, 140))

    def _menu_window(self, rect, title=None):
        """Square-cornered menu panel matching the in-game pixel windows."""
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.menu_surface, COLOR_TEXT_SHADOW, rect.move(3, 3))
        pygame.draw.rect(self.menu_surface, (28, 16, 12), rect)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, rect, 2)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_INNER, rect.inflate(-6, -6), 1)
        for x in (rect.left + 3, rect.right - 5):
            for y in (rect.top + 3, rect.bottom - 5):
                pygame.draw.rect(self.menu_surface, COLOR_TEXT_GOLD, (x, y, 2, 2))
        if title:
            header = pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, 28)
            pygame.draw.rect(self.menu_surface, COLOR_PANEL_HEADER, header)
            pygame.draw.line(self.menu_surface, COLOR_BORDER_OUTER, header.bottomleft,
                             (header.right - 1, header.bottom), 1)
            self.font_renderer.draw_text_centered(self.menu_surface, title, header.center,
                                                  font_type="title", color=COLOR_TEXT_GOLD)

    def _menu_button(self, rect, text, hovered=False, enabled=True, font_type="small"):
        rect = pygame.Rect(rect)
        fill = ((96, 50, 28) if hovered else (70, 35, 22)) if enabled else (48, 34, 28)
        pygame.draw.rect(self.menu_surface, COLOR_TEXT_SHADOW, rect.move(2, 2))
        pygame.draw.rect(self.menu_surface, fill, rect)
        pygame.draw.rect(self.menu_surface, COLOR_TEXT_GOLD if hovered and enabled else COLOR_BORDER_OUTER,
                         rect, 2)
        pygame.draw.line(self.menu_surface, (150, 92, 50), (rect.x + 2, rect.y + 2),
                         (rect.right - 3, rect.y + 2))
        self.font_renderer.draw_text_centered(self.menu_surface, text, rect.center, font_type=font_type,
                                              color=COLOR_TEXT_GOLD if enabled else COLOR_TEXT_MUTED)

    def _menu_dim(self, alpha=165):
        dim = pygame.Surface((MENU_WIDTH, MENU_HEIGHT), pygame.SRCALPHA)
        dim.fill((10, 5, 4, alpha))
        self.menu_surface.blit(dim, (0, 0))

    def render_preload_status_badge(self):
        badge_x = 24
        badge_y = MENU_HEIGHT - 38

        if self.preloader.status == PreloadStatus.READY:
            badge_rect = pygame.Rect(badge_x, badge_y, 160, 24)
            pygame.draw.rect(self.menu_surface, (26, 36, 22), badge_rect)
            pygame.draw.rect(self.menu_surface, (100, 180, 90), badge_rect, 2)
            self.font_renderer.draw_text_centered(self.menu_surface, tr("menu.world_ready"), badge_rect.center,
                                                  font_type="small", color=(180, 240, 160))
        elif self.preloader.status == PreloadStatus.LOADING:
            badge_rect = pygame.Rect(badge_x, badge_y, 220, 26)
            pygame.draw.rect(self.menu_surface, (40, 24, 16), badge_rect)
            pygame.draw.rect(self.menu_surface, (190, 110, 40), badge_rect, 2)

            pct = int(self.preloader.progress * 100)
            self.font_renderer.draw_text(self.menu_surface, tr("menu.world_loading", pct=pct),
                                         (badge_x + 8, badge_y + 4), font_type="small", color=COLOR_TEXT_GOLD)

            bar_w, bar_h = 204, 4
            bar_x, bar_y = badge_x + 8, badge_y + 18
            pygame.draw.rect(self.menu_surface, (20, 12, 8), (bar_x, bar_y, bar_w, bar_h))
            fill_w = int(bar_w * self.preloader.progress)
            if fill_w > 0:
                pygame.draw.rect(self.menu_surface, (225, 130, 45), (bar_x, bar_y, fill_w, bar_h))
        elif self.preloader.status == PreloadStatus.ERROR:
            badge_rect = pygame.Rect(badge_x, badge_y, 200, 24)
            pygame.draw.rect(self.menu_surface, (50, 16, 16), badge_rect)
            pygame.draw.rect(self.menu_surface, (220, 60, 60), badge_rect, 2)
            self.font_renderer.draw_text_centered(self.menu_surface, tr("menu.load_error"), badge_rect.center,
                                                  font_type="small", color=(255, 120, 120))

    def render_customization_panel(self):
        if not self.show_customize: return

        px, py = self.panel_rect.x, self.panel_rect.y
        panel_surf = pygame.Surface(self.panel_rect.size, pygame.SRCALPHA)
        panel_surf.fill(COLOR_PANEL_BG)
        self.menu_surface.blit(panel_surf, (px, py))
        pygame.draw.rect(self.menu_surface, COLOR_PANEL_HEADER, (px + 3, py + 3, self.panel_rect.width - 6, 26))
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, self.panel_rect, 2)
        pygame.draw.rect(self.menu_surface, COLOR_BORDER_INNER, self.panel_rect.inflate(-4, -4), 1)
        pygame.draw.line(self.menu_surface, COLOR_BORDER_OUTER, (px, py + 30), (self.panel_rect.right - 1, py + 30), 1)

        self.font_renderer.draw_text(self.menu_surface, tr("menu.customize_title"), (px + 10, py + 8),
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
        if not self.show_settings:
            return
        self._menu_dim(180)
        layout = self.settings_layout()
        panel = layout["panel"]
        mouse = self.window_to_logical(pygame.mouse.get_pos())
        modal_open = self.settings_pending is not None
        self._menu_window(panel, tr("settings.title"))

        labels = ((tr("settings.world_seed"), "world_seed"), (tr("settings.server_address"), "server_address"),
                  (tr("settings.port"), "server_port"))
        for label_text, name in labels:
            rect = layout[name]
            self.font_renderer.draw_text(self.menu_surface, label_text + ":", (panel.x + 24, rect.y + 7),
                                         font_type="small", color=COLOR_TEXT_WARM)
            focused = self.settings_focus == name
            pygame.draw.rect(self.menu_surface, (72, 42, 25) if focused else (43, 25, 18), rect)
            pygame.draw.rect(self.menu_surface, COLOR_TEXT_GOLD if focused else COLOR_BORDER_OUTER, rect, 2)
            shown = self.settings_draft[name]
            # Keep the caret visible for long entries by showing the tail.
            while shown and self.font_renderer.font_small.size(shown + "|")[0] > rect.width - 14:
                shown = shown[1:]
            if focused and int(self.time_elapsed * 2) % 2 == 0:
                shown += "|"
            self.font_renderer.draw_text(self.menu_surface, shown, (rect.x + 7, rect.y + 7),
                                         font_type="small", color=COLOR_TEXT_GOLD)
        draft = self.settings_draft
        rows = (("display", "settings.display_label"), ("size_value", "settings.window_size"),
                ("scaling", "settings.scaling"), ("volume_value", "settings.music_volume"))
        for name, key in rows:
            self.font_renderer.draw_text(self.menu_surface, tr(key) + ":", (panel.x + 24, layout[name].y + 7),
                                         font_type="small", color=COLOR_TEXT_WARM)
        width, height = draft["window_size"]
        values = {
            "random": tr("settings.random"),
            "display": tr("settings.fullscreen") if draft["display_mode"] == "fullscreen" else tr("settings.windowed"),
            "size_prev": "<", "size_next": ">", "volume_down": "-", "volume_up": "+",
            "scaling": tr("settings.pixel_perfect") if draft["pixel_perfect"] else tr("settings.fit"),
        }
        for name, text in values.items():
            self._menu_button(layout[name], text, not modal_open and layout[name].collidepoint(mouse))
        for name, text in (("size_value", f"{width} x {height}"), ("volume_value", f"{draft['music_volume']}%")):
            rect = layout[name]
            pygame.draw.rect(self.menu_surface, (43, 25, 18), rect)
            pygame.draw.rect(self.menu_surface, COLOR_BORDER_OUTER, rect, 2)
            self.font_renderer.draw_text_centered(self.menu_surface, text, rect.center,
                                                  font_type="small", color=COLOR_TEXT_GOLD)
        if draft["display_mode"] == "fullscreen":
            self.font_renderer.draw_text(self.menu_surface, tr("settings.size_note"),
                                         (layout["size_next"].right + 10, layout["size_value"].y + 7),
                                         font_type="small", color=COLOR_TEXT_MUTED)
        if self.audio is not None and self.audio.MENU_MUSIC not in self.audio.paths:
            self.font_renderer.draw_text(self.menu_surface, tr("settings.menu_music_missing"),
                                         (layout["volume_up"].right + 10, layout["volume_value"].y + 7),
                                         font_type="small", color=COLOR_TEXT_MUTED)

        net = self.preloader.network
        session = self.preloader.game_session
        active_seed = session.seed if session is not None else "-"
        status = (tr("settings.online", host=net.host, port=net.port) if net.connected
                  else tr("settings.offline"))
        info_y = panel.y + 318
        self.font_renderer.draw_text(self.menu_surface,
                                     tr("settings.status", configured=stable_seed(self.settings.world_seed),
                                        active=active_seed, status=status),
                                     (panel.x + 24, info_y), font_type="small", color=COLOR_TEXT_MUTED)
        if (not net.connected and net.error_msg and self.preloader.status == PreloadStatus.READY):
            failed = tr("settings.connection_failed", host=net.host, port=net.port, error=net.error_msg[:48])
            for index, line in enumerate(self._wrap_menu_text(failed, panel.width - 48)[:2]):
                self.font_renderer.draw_text(self.menu_surface, line, (panel.x + 24, info_y + 20 + index * 16),
                                             font_type="small", color=(220, 150, 80))
        message, color = ((self.settings_error, (255, 150, 100)) if self.settings_error
                          else (self.settings_notice, (170, 230, 150)))
        if message:
            for index, line in enumerate(self._wrap_menu_text(message, panel.width - 48)[:2]):
                self.font_renderer.draw_text_centered(self.menu_surface, line,
                                                      (panel.centerx, panel.y + 386 + index * 16),
                                                      font_type="small", color=color)
        self._menu_button(layout["apply"], tr("settings.apply"),
                          not modal_open and layout["apply"].collidepoint(mouse), font_type="med")
        self._menu_button(layout["cancel"], tr("settings.cancel"),
                          not modal_open and layout["cancel"].collidepoint(mouse), font_type="med")
        self.font_renderer.draw_text_centered(self.menu_surface, tr("settings.tab_hint"),
                                              (panel.centerx, panel.bottom - 14), font_type="small",
                                              color=COLOR_TEXT_MUTED)
        if modal_open:
            self._render_settings_confirm(layout, mouse)

    def _wrap_menu_text(self, text, width):
        return wrap_text(self.font_renderer.font_small, text, width)

    def _render_settings_confirm(self, layout, mouse):
        self._menu_dim(120)
        box = layout["confirm_panel"]
        self._menu_window(box, tr("settings.confirm_title"))
        y = box.y + 50
        for line in self.settings_pending[1]:
            for wrapped in self._wrap_menu_text(line, box.width - 40):
                self.font_renderer.draw_text(self.menu_surface, wrapped, (box.x + 20, y),
                                             font_type="small", color=COLOR_TEXT_WARM)
                y += 18
        self._menu_button(layout["confirm_yes"], tr("settings.confirm"),
                          layout["confirm_yes"].collidepoint(mouse), font_type="med")
        self._menu_button(layout["confirm_no"], tr("settings.cancel"),
                          layout["confirm_no"].collidepoint(mouse), font_type="med")

    def render_credits_modal(self):
        if not self.show_credits: return

        self._menu_dim()
        mw, mh = 460, 280
        mx = (MENU_WIDTH - mw) // 2
        my = (MENU_HEIGHT - mh) // 2
        self._menu_window((mx, my, mw, mh), tr("menu.credits"))

        lines = [
            (GAME_TITLE, "title", COLOR_TEXT_GOLD),
            (tr("menu.developed_by"), "small", COLOR_TEXT_WARM),
            (DEVELOPER_CREDIT, "med", COLOR_TEXT_GOLD),
            ("", "small", COLOR_TEXT_MUTED),
            (tr("credits.art"), "small", COLOR_TEXT_WARM),
            (tr("credits.engine"), "small", COLOR_TEXT_WARM),
            (tr("credits.network"), "small", COLOR_TEXT_MUTED),
            (tr("credits.world"), "small", COLOR_TEXT_MUTED),
        ]

        curr_y = my + 50
        for text, ftype, col in lines:
            if text:
                self.font_renderer.draw_text_centered(self.menu_surface, text, (MENU_WIDTH // 2, curr_y),
                                                      font_type=ftype, color=col)
            curr_y += 20

        back_btn = pygame.Rect(MENU_WIDTH // 2 - 60, my + 225, 120, 32)
        mouse = self.window_to_logical(pygame.mouse.get_pos())
        self._menu_button(back_btn, tr("menu.back"), back_btn.collidepoint(mouse), font_type="med")

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

            self.draw_menu_backdrop()
            self.window.blit(pygame.transform.scale(self.menu_surface, (self.target_w, self.target_h)),
                             (self.offset_x, self.offset_y))
            self.draw_logo()
            if self.show_settings or self.show_credits:
                # Modal windows go on a transparent layer above the logo.
                base, self.menu_surface = self.menu_surface, self.menu_overlay
                self.menu_overlay.fill((0, 0, 0, 0))
                try:
                    self.render_settings_modal()
                    self.render_credits_modal()
                finally:
                    self.menu_surface = base
                self.window.blit(pygame.transform.scale(self.menu_overlay, (self.target_w, self.target_h)),
                                 (self.offset_x, self.offset_y))

        elif self.state == "GAME" and self.preloader.game_session:
            # Render full gameplay with Fall Tile Set sprites onto game_surface
            self.preloader.game_session.render(self.game_surface, (lx, ly))
            self.window.fill(COLOR_BG_DARK)
            self.window.blit(pygame.transform.scale(self.game_surface, (self.target_w, self.target_h)),
                             (self.offset_x, self.offset_y))

        pygame.display.flip()

    def run(self):
        print(f"Starting {GAME_TITLE} application loop...")
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
            else:
                self.audio.update(dt)

            # 4. Handle events & render
            self.handle_events()
            self.render()

        # Clean shutdown
        self.shutdown()
        sys.exit(0)

    def save_game_progress(self, reason):
        session = self.preloader.game_session
        if self.session_started and session is not None:
            session.save_progress(reason)

    def shutdown(self):
        self.save_game_progress("quit")
        self.remember_window_size()
        if self.preloader.network:
            self.preloader.network.close()
        self.audio.stop_all()
        pygame.quit()

    def remember_window_size(self):
        """Persist a window the player resized by dragging (windowed mode only)."""
        if self.is_fullscreen:
            return
        width, height = self.window.get_size()
        if (width, height) == (self.settings.window_width, self.settings.window_height):
            return
        self.settings = replace(self.settings, window_width=width, window_height=height)
        try:
            save_settings(self.settings)
        except (OSError, ValueError) as exc:
            print(f"[SETTINGS] Could not save window size: {exc}")


# ---------------------------------------------------------------------------
# Program Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = AutumnGameApp()
    try:
        app.run()
    except KeyboardInterrupt:
        app.shutdown()
        print("\n[GAME] Stopped.")
