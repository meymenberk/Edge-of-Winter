#!/usr/bin/env python3
"""Reusable, import-safe Treant boss encounter and a small standalone demo.

The reusable code in this file never initializes pygame, creates a display, polls
global input, imports ``main.py``, or starts networking.  The host supplies compact
player snapshots and player attacks, then consumes structured encounter events.

World coordinates are expressed in tiles and positions are foot anchors, matching
the current game.  Rendering converts them with ``config.tile_size`` (48 by
default).  Importing this module has no side effects beyond defining Python names.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union
import copy
import json
import math
import os
import random

import pygame
import numpy as np

from .localization import tr
from .paths import PLATANUS_ASSET_DIR, PROJECT_ROOT


__all__ = [
    "BOSS_STARTED", "BOSS_PHASE_CHANGED", "BOSS_ATTACK_STARTED", "PLAYER_HIT",
    "BOSS_DAMAGED", "BOSS_DEFEATED", "PLAYER_DEFEATED", "ENCOUNTER_COMPLETED",
    "BossState", "EncounterResult", "BossPlayerState", "PlayerAttack",
    "EncounterEvent", "TreantConfig", "TreantBossEncounter",
    "BOSS_NAME", "BOSS_ASSET_RELATIVE_DIR", "resolve_boss_assets_dir",
    "TREANT_RENDER_DEBUG", "run_demo",
]


TREANT_RENDER_DEBUG = os.environ.get("TREANT_RENDER_DEBUG", "").strip().lower() in {
    "1", "true", "yes", "on",
}


BOSS_NAME = "PLATANUS"
BOSS_NAME_UPPER = "PLATANUS"
BOSS_ASSET_RELATIVE_DIR = Path("assets") / "bosses" / "platanus"


def resolve_boss_assets_dir(base: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the canonical PLATANUS atlas directory without using cwd.

    ``base`` remains backwards compatible with the original public API: callers
    may pass either the project/module directory or a directory containing the
    two atlas files directly.  When both layouts are present, the dedicated
    folder always wins so a stale loose copy can never be selected silently.
    """
    if base is None:
        return PLATANUS_ASSET_DIR
    else:
        supplied_path = Path(base).expanduser()
        supplied = (supplied_path if supplied_path.is_absolute()
                    else PROJECT_ROOT / supplied_path).resolve()
    dedicated = supplied / BOSS_ASSET_RELATIVE_DIR
    if dedicated.is_dir():
        return dedicated
    return supplied


def _strip_rects(edges: Sequence[int], top: int, bottom: int) -> tuple[tuple[int, int, int, int], ...]:
    return tuple((left, top, right - left, bottom - top)
                 for left, right in zip(edges, edges[1:]))


_idle_cuts = (0, 104, 198, 283, 368, 462, 557, 656, 765)
_walk_cuts = (765, 874, 960, 1048, 1139, 1238, 1335, 1422, 1536)
_roar_cuts = (0, 93, 180, 269, 358, 450, 542, 641)
_hurt_cuts = (641, 741, 832, 923)
_death_cuts = (923, 1010, 1089, 1167, 1245, 1327, 1403, 1468, 1536)
_jump_cuts = (0, 99, 195, 303, 413, 501, 575, 650)
_impact_cuts = (650, 750, 846, 959, 1074, 1188, 1305, 1419, 1536)
_arm_cuts = (0, 88, 183, 277, 380, 495, 609, 723, 826, 907, 987, 1073, 1170)
_root_cuts = (1170, 1225, 1263, 1302, 1344, 1389, 1435, 1478, 1536)
_spin_cuts = (0, 137, 253, 389, 535, 689, 853, 996, 1152, 1320, 1419, 1475, 1536)
_leaf_cuts = (0, 95, 183, 258, 354, 530, 629, 723, 815, 903, 1060, 1340, 1536)

_r_roar = _strip_rects(_roar_cuts, 218, 334)
_r_hurt = _strip_rects(_hurt_cuts, 218, 334)
_r_jump = _strip_rects(_jump_cuts, 387, 512)

# Hand-measured against the real 1536x1024 sheet. Section headings end above
# these rectangles and frame numbers begin below them.
BOSS_ANIMATION_RECTS = {
    "idle": _strip_rects(_idle_cuts, 38, 160),
    "walk": _strip_rects(_walk_cuts, 38, 160),
    "roar": (_r_roar[0], _r_roar[1], _r_roar[2], _r_roar[3], _r_roar[3], _r_roar[4], _r_roar[5], _r_roar[6]),
    "hurt": (_r_hurt[0], _r_hurt[1], _r_hurt[1], _r_hurt[2]),
    "death": _strip_rects(_death_cuts, 218, 334),
    "jump": (_r_jump[0], _r_jump[1], _r_jump[2], _r_jump[2], _r_jump[3], _r_jump[4], _r_jump[5], _r_jump[6]),
    "impact": _strip_rects(_impact_cuts, 387, 512),
    "arm": _strip_rects(_arm_cuts, 566, 665),
    "root": _strip_rects(_root_cuts, 566, 665),
    "spin": _strip_rects(_spin_cuts, 716, 818),
    "leaf_storm": _strip_rects(_leaf_cuts, 868, 1004),
}

# Verified interiors avoid the atlas' rounded white tile corners. These are
# actual material samples, not a guessed grid.
BOSS_TILE_RECTS = (
    (31, 49, 110, 104), (161, 49, 105, 104), (286, 49, 111, 104),
    (416, 49, 99, 104), (535, 49, 105, 104), (660, 49, 103, 104),
    (782, 49, 99, 104),
)

# Mixed-size props from the real 1448x1086 atlas. Crops are hand-fitted to verified
# illustrations, excluding headings, divider lines, and neighboring frames.
BOSS_PROP_RECTS = {
    "tree": (16, 429, 230, 223),
    "tree_birch": (248, 447, 131, 200),
    "dead_tree": (380, 414, 174, 235),
    "stump": (585, 461, 202, 183),
    "mushrooms": (783, 449, 142, 183),
    "root_hazard": (1097, 467, 157, 169),
    "ruin": (421, 701, 216, 335),
    "portal": (23, 701, 394, 347),
    "ritual_platform": (681, 658, 744, 402),
    "cliff": (23, 215, 120, 162),
}

# Public event names are strings on purpose: they serialize cleanly and do not
# force a future server to know about Python Enum encoding.
BOSS_STARTED = "BOSS_STARTED"
BOSS_PHASE_CHANGED = "BOSS_PHASE_CHANGED"
BOSS_ATTACK_STARTED = "BOSS_ATTACK_STARTED"
PLAYER_HIT = "PLAYER_HIT"
BOSS_DAMAGED = "BOSS_DAMAGED"
BOSS_DEFEATED = "BOSS_DEFEATED"
PLAYER_DEFEATED = "PLAYER_DEFEATED"
ENCOUNTER_COMPLETED = "ENCOUNTER_COMPLETED"


class BossState(str, Enum):
    INTRO = "INTRO"
    IDLE = "IDLE"
    APPROACH = "APPROACH"
    ARM_WINDUP = "ARM_WINDUP"
    ARM_EXTEND = "ARM_EXTEND"
    ARM_RECOVERY = "ARM_RECOVERY"
    PHASE_TRANSITION = "PHASE_TRANSITION"
    JUMP_WINDUP = "JUMP_WINDUP"
    JUMP_ASCEND = "JUMP_ASCEND"
    JUMP_DESCEND = "JUMP_DESCEND"
    EARTHQUAKE = "EARTHQUAKE"
    EARTHQUAKE_RECOVERY = "EARTHQUAKE_RECOVERY"
    HURT = "HURT"
    DYING = "DYING"
    DEFEATED = "DEFEATED"


class EncounterResult(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    VICTORY = "VICTORY"
    DEFEAT = "DEFEAT"


@dataclass(frozen=True)
class BossPlayerState:
    """One host-owned player snapshot.

    ``x``/``y`` are the feet in tile-space. ``width``/``height`` are logical
    collision dimensions, not decorative sprite dimensions. The encounter never
    mutates this object or keeps a second authoritative health value.
    """

    player_id: str
    x: float
    y: float
    width: float = 0.36
    height: float = 0.72
    health: float = 8.0
    max_health: float = 8.0
    facing: tuple[float, float] = (0.0, 1.0)
    invulnerable: bool = False

    @property
    def hitbox(self) -> "FloatRect":
        return FloatRect(self.x - self.width / 2, self.y - self.height,
                         self.width, self.height)


@dataclass(frozen=True)
class PlayerAttack:
    """A host-validated sword/ability hitbox submitted once per swing.

    Reusing an ``attack_id`` is harmless: the encounter accepts it at most once.
    ``x``/``y`` are the top-left of an axis-aligned world-space rectangle.
    """

    attack_id: str
    player_id: str
    x: float
    y: float
    width: float
    height: float
    damage: float = 1.0
    knockback: float = 0.0

    @property
    def hitbox(self) -> "FloatRect":
        return FloatRect(self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class EncounterEvent:
    type: str
    time: float
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "time": self.time, "data": dict(self.data)}


@dataclass(frozen=True)
class FloatRect:
    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float: return self.x
    @property
    def right(self) -> float: return self.x + self.width
    @property
    def top(self) -> float: return self.y
    @property
    def bottom(self) -> float: return self.y + self.height
    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    def intersects(self, other: "FloatRect") -> bool:
        return (self.left < other.right and self.right > other.left and
                self.top < other.bottom and self.bottom > other.top)


@dataclass
class TreantConfig:
    tile_size: int = 48
    arena_width: int = 22
    arena_height: int = 16
    max_health: float = 120.0
    boss_speed: float = 1.75
    # Phase two is faster still, but stays well below the player's 4.5 tiles/s.
    phase_two_speed_multiplier: float = 1.15
    # The phase-two jump travels up to this far toward its locked landing mark.
    leap_range: float = 2.2
    boss_width: float = 1.15
    boss_height: float = 1.55
    arm_damage: float = 2.0
    earthquake_damage: float = 3.0
    arm_range: float = 4.4
    arm_width: float = 1.05
    earthquake_radius: float = 3.15
    trigger_radius: float = 4.25
    seed: int = 731_991
    auto_start: bool = False
    debug_hitboxes: bool = False

    def __post_init__(self) -> None:
        if self.tile_size < 8:
            raise ValueError("tile_size must be at least 8")
        if self.arena_width < 14 or self.arena_height < 12:
            raise ValueError("arena must be at least 14x12 tiles")
        if self.max_health <= 0:
            raise ValueError("max_health must be positive")


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple[int, int, int]
    kind: str = "dust"


class AnimationController:
    """Delta-time animation with state-specific frame rates and no anchor drift."""

    DURATIONS = {
        "idle": 0.18, "walk": 0.13, "arm": 0.09, "jump": 0.11,
        "impact": 0.08, "hurt": 0.10, "roar": 0.12, "death": 0.14,
    }

    def __init__(self, animations: Mapping[str, Sequence[pygame.Surface]]) -> None:
        self.animations = animations
        self.name = "idle"
        self.frame_index = 0
        self.elapsed = 0.0
        self.finished = False

    @property
    def frame(self) -> pygame.Surface:
        frames = self.animations.get(self.name) or self.animations["idle"]
        return frames[min(self.frame_index, len(frames) - 1)]

    def play(self, name: str, restart: bool = False) -> None:
        if name not in self.animations:
            name = "idle"
        if name != self.name or restart:
            self.name, self.frame_index, self.elapsed, self.finished = name, 0, 0.0, False

    def update(self, dt: float, loop: bool = True) -> None:
        frames = self.animations.get(self.name) or self.animations["idle"]
        if len(frames) <= 1 or self.finished:
            return
        self.elapsed += max(0.0, dt)
        duration = self.DURATIONS.get(self.name, 0.12)
        while self.elapsed >= duration:
            self.elapsed -= duration
            self.frame_index += 1
            if self.frame_index >= len(frames):
                if loop:
                    self.frame_index = 0
                else:
                    self.frame_index = len(frames) - 1
                    self.finished = True
                    break


class TreantAssets:
    """Loads the two verified production atlases and caches every derived surface.

    Normal execution is strict: absent, resized, or malformed art raises a useful
    error instead of silently substituting placeholders. Generated sprites exist
    only behind the explicit ``allow_test_assets`` switch for isolated tests.
    """

    SECTION_ORDER = (
        "idle", "walk", "roar", "hurt", "death", "jump", "impact",
        "arm", "root", "spin", "leaf_storm", "misc",
    )

    def __init__(self, assets_dir: Path, tile_size: int,
                 animation_rects: Optional[Mapping[str, Sequence[tuple[int, int, int, int]]]] = None,
                 allow_test_assets: bool = False) -> None:
        self.assets_dir = Path(assets_dir).expanduser().resolve()
        self.tile_size = tile_size
        self.anim_path = self.assets_dir / "bossanim.png"
        self.tile_path = self.assets_dir / "bosstile.png"
        self.missing_assets: list[str] = []
        self.allow_test_assets = bool(allow_test_assets)
        self.source_rects: dict[str, list[pygame.Rect]] = {}
        self.tile_source_rects: list[pygame.Rect] = []
        self.prop_source_rects: dict[str, pygame.Rect] = {}
        self.animations = self._load_boss(animation_rects)
        if not hasattr(self, "arm_segment"):
            # Explicit test-art mode only; production parts are cropped from the
            # real ARM EXTEND strip in _load_boss.
            self.arm_segment = pygame.transform.scale(self.animations["arm"][2], (34, 24))
            self.arm_claw = pygame.transform.scale(self.animations["arm"][3], (34, 38))
        self.terrain_tiles, self.props = self._load_tiles()
        if not hasattr(self, "terrain_sources"):
            self.terrain_sources = [pygame.transform.scale(tile, (24, 24))
                                    for tile in self.terrain_tiles]
        self.arm_direction_cache: dict[int, tuple[pygame.Surface, pygame.Surface]] = {}
        self.shadow = pygame.Surface((92, 28), pygame.SRCALPHA)
        pygame.draw.ellipse(self.shadow, (24, 11, 17, 105), self.shadow.get_rect())

    @staticmethod
    def _load_surface(path: Path) -> pygame.Surface:
        surface = pygame.image.load(str(path))
        if surface.get_masks()[3] == 0:
            alpha_surface = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            alpha_surface.blit(surface, (0, 0))
            surface = alpha_surface
        if pygame.display.get_surface() is not None:
            return surface.convert_alpha()
        return surface.copy()

    @staticmethod
    def _background_key(raw: pygame.Surface) -> tuple[int, int, int]:
        w, h = raw.get_size()
        samples = [raw.get_at((x, y))[:3] for x, y in
                   ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        return max(set(samples), key=samples.count)

    @classmethod
    def _remove_flat_background(cls, raw: pygame.Surface, name: str = "") -> pygame.Surface:
        result = pygame.Surface(raw.get_size(), pygame.SRCALPHA)
        result.blit(raw, (0, 0))
        w, h = result.get_size()

        # Remove known labels and divider lines
        if name == "ritual_platform":
            result.fill((0, 0, 0, 0), (0, 0, w, 35))
        elif name == "dead_tree":
            result.fill((0, 0, 0, 0), (0, 0, w, 6))
        elif name == "mushrooms":
            result.fill((0, 0, 0, 0), (124, 0, w - 124, h))

        rgb = pygame.surfarray.array3d(result)
        alpha = pygame.surfarray.pixels_alpha(result)

        # Ivory, white, and gray paper backgrounds in bosstile.png
        paper = (rgb.min(axis=2) > 190) & (rgb.max(axis=2) - rgb.min(axis=2) < 36)
        paper |= (rgb.min(axis=2) > 230)
        paper |= (rgb.min(axis=2) > 175) & (rgb.max(axis=2) - rgb.min(axis=2) < 22)
        alpha[paper] = 0
        del alpha

        mask = pygame.mask.from_surface(result, 12)
        components = mask.connected_components(8)
        if not components:
            return result
        components.sort(key=lambda c: c.count(), reverse=True)
        primary = components[0]

        keep_mask = pygame.Mask((w, h))
        keep_mask.draw(primary, (0, 0))
        for comp in components[1:]:
            rect = comp.get_bounding_rects()[0]
            touches_edge = (rect.left <= 0 or rect.right >= w or rect.top <= 0 or rect.bottom >= h)
            if touches_edge and comp.count() < primary.count() * 0.12:
                continue
            keep_mask.draw(comp, (0, 0))

        alpha_mask = keep_mask.to_surface(
            setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0)
        )
        result.blit(alpha_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        a = pygame.surfarray.pixels_alpha(result)
        rgb = pygame.surfarray.pixels3d(result)
        rgb[a == 0] = [0, 0, 0]
        del a, rgb
        return result

    @classmethod
    def _discover_rects(cls, raw: pygame.Surface) -> dict[str, list[pygame.Rect]]:
        """Legacy diagnostic helper; production loading uses measured rectangles."""
        cleaned = cls._remove_flat_background(raw)
        mask = pygame.mask.from_surface(cleaned, 24)
        sw, sh = raw.get_size()
        components = [r for r in mask.get_bounding_rects()
                      if r.width >= max(10, sw // 100)
                      and r.height >= max(14, sh // 55)
                      and r.width * r.height >= sw * sh * 0.00016]
        if not components:
            return {}
        median_h = sorted(r.height for r in components)[len(components) // 2]
        components = [r for r in components if r.height >= max(14, median_h * 0.42)]
        components.sort(key=lambda r: (r.centery, r.left))
        rows: list[list[pygame.Rect]] = []
        for rect in components:
            row = next((group for group in rows
                        if abs(sum(r.centery for r in group) / len(group) - rect.centery)
                        <= max(rect.height, sum(r.height for r in group) / len(group)) * 0.48), None)
            if row is None:
                rows.append([rect])
            else:
                row.append(rect)
        rows = [sorted(group, key=lambda r: r.left) for group in rows if group]
        rows.sort(key=lambda group: min(r.top for r in group))
        result: dict[str, list[pygame.Rect]] = {}
        for name, row in zip(cls.SECTION_ORDER, rows):
            top_limit = max(0, min(r.top for r in row) - int(median_h * .18))
            bottom_limit = min(sh, max(r.bottom for r in row) + int(median_h * .12))
            expanded = []
            for index, rect in enumerate(row):
                left_bound = 0 if index == 0 else (row[index - 1].right + rect.left) // 2
                right_bound = sw if index + 1 == len(row) else (rect.right + row[index + 1].left) // 2
                pad = int(rect.height * .20)
                crop = pygame.Rect(max(left_bound, rect.left - pad), top_limit,
                                   min(right_bound, rect.right + pad) - max(left_bound, rect.left - pad),
                                   bottom_limit - top_limit)
                expanded.append(crop)
            result[name] = expanded
        return result

    @staticmethod
    def _prepare_boss_sheet(raw: pygame.Surface) -> pygame.Surface:
        """Clean boss animation atlas alpha without distorting colors or outlines."""
        result = raw.copy()
        w, h = result.get_size()
        # Zero out non-sprite text/header bands in bossanim.png
        bands = ((0, 38), (160, 218), (334, 387), (512, 566), (665, 716), (818, 868), (1004, 1024))
        for y0, y1 in bands:
            result.fill((0, 0, 0, 0), (0, y0, w, y1 - y0))

        alpha = pygame.surfarray.pixels_alpha(result)
        rgb = pygame.surfarray.pixels3d(result)
        # Background haze in bossanim.png has alpha <= 28.
        # Preserve dark outlines (alpha > 28) without altering original RGB!
        a = alpha.astype(np.float32)
        new_a = np.where(a <= 28.0, 0.0, np.minimum(255.0, (a - 28.0) * 255.0 / 42.0)).astype(np.uint8)
        alpha[:] = new_a
        # Zero out RGB where alpha is 0 to prevent scaling/rotation halos
        rgb[new_a == 0] = [0, 0, 0]
        del alpha, rgb
        return result

    @staticmethod
    def _remove_neighbor_fragments(sprite: pygame.Surface) -> pygame.Surface:
        """Drop adjacent-frame slivers from tightly packed illustrated strips."""
        result = sprite.copy()
        mask = pygame.mask.from_surface(result, 20)
        components = mask.connected_components(8)
        if len(components) <= 1:
            return result
        w, h = result.get_size()
        cx = w / 2.0
        primary = max(components, key=lambda comp: (
            comp.count() - abs(comp.centroid()[0] - cx) * 3.5
        ))
        keep_mask = pygame.Mask((w, h))
        keep_mask.draw(primary, (0, 0))
        for component in components:
            if component is primary:
                continue
            rects = component.get_bounding_rects()
            if not rects:
                continue
            rect = rects[0]
            touches_edge = (rect.left <= 0 or rect.right >= w or rect.top <= 0 or rect.bottom >= h)
            if touches_edge and component.count() < primary.count() * 0.35:
                continue
            keep_mask.draw(component, (0, 0))
        mask_surf = keep_mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
        result.blit(mask_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        a = pygame.surfarray.pixels_alpha(result)
        rgb = pygame.surfarray.pixels3d(result)
        rgb[a == 0] = [0, 0, 0]
        del a, rgb
        return result

    @classmethod
    def _fit_frame(cls, sprite: pygame.Surface,
                   size: tuple[int, int] = (154, 112)) -> pygame.Surface:
        sprite = cls._remove_neighbor_fragments(sprite)
        bounds = sprite.get_bounding_rect(min_alpha=12)
        if bounds.width <= 0 or bounds.height <= 0:
            return pygame.Surface(size, pygame.SRCALPHA)
        scale = min(.82, (size[0] - 4) / max(1, sprite.get_width()), (size[1] - 4) / max(1, sprite.get_height()))
        target = (max(1, round(sprite.get_width() * scale)),
                  max(1, round(sprite.get_height() * scale)))
        art = pygame.transform.scale(sprite, target)
        canvas = pygame.Surface(size, pygame.SRCALPHA)
        canvas.blit(art, art.get_rect(midbottom=(size[0] // 2, size[1] - 1)))
        a = pygame.surfarray.pixels_alpha(canvas)
        rgb = pygame.surfarray.pixels3d(canvas)
        rgb[a == 0] = [0, 0, 0]
        del a, rgb
        return canvas

    def _load_boss(self, explicit: Optional[Mapping[str, Sequence[tuple[int, int, int, int]]]]) -> dict[str, list[pygame.Surface]]:
        if not self.anim_path.exists():
            self.missing_assets.append(self.anim_path.name)
            if self.allow_test_assets:
                return self._placeholder_boss()
            raise FileNotFoundError(f"Required Treant animation atlas not found: {self.anim_path}")
        raw = self._load_surface(self.anim_path)
        if raw.get_size() != (1536, 1024):
            raise ValueError(f"bossanim.png must be the verified 1536x1024 atlas; got {raw.get_size()}")
        cleaned = self._prepare_boss_sheet(raw)
        # Treat caller rectangles as overrides. This preserves compatibility with
        # integrations that only customize one sequence while all other sequences
        # continue to use the measured production-atlas rectangles.
        layouts = {key: [pygame.Rect(r) for r in rects]
                   for key, rects in BOSS_ANIMATION_RECTS.items()}
        if explicit:
            layouts.update({key: [pygame.Rect(r) for r in rects]
                            for key, rects in explicit.items()})
        expected = {"idle": 8, "walk": 8, "roar": 8, "hurt": 4, "death": 8,
                    "jump": 8, "impact": 8, "arm": 12, "root": 8,
                    "spin": 12, "leaf_storm": 12}
        frames: dict[str, list[pygame.Surface]] = {}
        for name, count in expected.items():
            valid = [r.clip(cleaned.get_rect()) for r in layouts.get(name, ())]
            valid = [r for r in valid if r.width > 2 and r.height > 2]
            if len(valid) != count:
                raise ValueError(f"bossanim.png: {name} requires {count} verified frames; found {len(valid)}")
            self.source_rects[name] = valid
            frames[name] = [self._fit_frame(cleaned.subsurface(rect).copy()) for rect in valid]
        # Directional reach is assembled from real wooden pixels rather than a
        # vector line. These two clean pieces come from ARM EXTEND frame 5.
        self.arm_segment = self._fit_art_part(
            cleaned.subsurface((528, 580, 36, 24)).copy(), (36, 24)
        )
        self.arm_claw = self._fit_art_part(
            cleaned.subsurface((570, 568, 28, 36)).copy(), (32, 40)
        )
        return frames

    @staticmethod
    def _fit_art_part(sprite: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
        bounds = sprite.get_bounding_rect(min_alpha=12)
        if bounds.width <= 0 or bounds.height <= 0:
            raise ValueError("bossanim.png: an ARM EXTEND composite part is empty")
        sprite = sprite.subsurface(bounds).copy()
        scale = min(size[0] / sprite.get_width(), size[1] / sprite.get_height())
        art = pygame.transform.scale(
            sprite, (max(1, round(sprite.get_width() * scale)),
                     max(1, round(sprite.get_height() * scale)))
        )
        padded_size = (size[0] + 8, size[1] + 8)
        result = pygame.Surface(padded_size, pygame.SRCALPHA)
        result.blit(art, art.get_rect(center=result.get_rect().center))
        a = pygame.surfarray.pixels_alpha(result)
        rgb = pygame.surfarray.pixels3d(result)
        rgb[a == 0] = [0, 0, 0]
        del a, rgb
        return result

    @staticmethod
    def _placeholder_boss() -> dict[str, list[pygame.Surface]]:
        result: dict[str, list[pygame.Surface]] = {}
        for name in ("idle", "walk", "roar", "hurt", "death", "jump", "impact", "arm"):
            count = 6 if name in ("arm", "jump", "death") else 4
            frames = []
            for i in range(count):
                s = pygame.Surface((88, 106), pygame.SRCALPHA)
                if name == "death":
                    squash = max(.15, 1 - i / (count - 1))
                    body = pygame.Rect(24, 46 + round(45 * (1 - squash)), 40, round(49 * squash))
                else:
                    bob = -2 if name in ("walk", "jump") and i % 2 else 0
                    body = pygame.Rect(25, 43 + bob, 38, 51)
                pygame.draw.ellipse(s, (49, 25, 20), body.inflate(6, 5))
                pygame.draw.ellipse(s, (108, 50, 24), body)
                pygame.draw.rect(s, (78, 37, 24), (31, body.bottom - 5, 8, 10))
                pygame.draw.rect(s, (78, 37, 24), (50, body.bottom - 5, 8, 10))
                if name != "death" or i < count - 1:
                    pygame.draw.line(s, (65, 31, 22), (35, 47), (18, 17), 6)
                    pygame.draw.line(s, (65, 31, 22), (53, 47), (71, 14), 6)
                    pygame.draw.line(s, (65, 31, 22), (20, 22), (10, 15), 4)
                    pygame.draw.line(s, (65, 31, 22), (68, 20), (80, 11), 4)
                    for lx, ly, c in ((15, 12, (224, 81, 24)), (75, 10, (238, 116, 25)),
                                      (28, 26, (174, 48, 22)), (65, 28, (245, 145, 28))):
                        pygame.draw.circle(s, c, (lx, ly), 7)
                    pygame.draw.circle(s, (255, 182, 52), (36, 60), 3)
                    pygame.draw.circle(s, (255, 182, 52), (52, 60), 3)
                    pygame.draw.arc(s, (27, 14, 16), (33, 63, 22, 15), 0.15, math.pi - .15, 3)
                    arm_len = 14
                    if name == "arm": arm_len += round(31 * i / max(1, count - 1))
                    pygame.draw.line(s, (83, 39, 23), (27, 62), (27 - arm_len, 70), 9)
                    pygame.draw.line(s, (83, 39, 23), (61, 62), (74, 70), 9)
                frames.append(s)
            result[name] = frames
        return result

    def _load_tiles(self) -> tuple[list[pygame.Surface], dict[str, pygame.Surface]]:
        if not self.tile_path.exists():
            self.missing_assets.append(self.tile_path.name)
            if self.allow_test_assets:
                palette = self._sample_autumn_palette(None)
                tree = self._make_tree()
                stone = self._make_stone()
                ruin = self._make_ruin()
                platform = pygame.Surface((570, 307), pygame.SRCALPHA)
                pygame.draw.ellipse(platform, (91, 61, 48), (55, 90, 460, 180))
                pygame.draw.ellipse(platform, (205, 99, 30), (95, 112, 380, 138), 5)
                portal = self._make_portal()
                props = {
                    "portal": portal,
                    "tree": tree, "tree_birch": tree, "dead_tree": tree, "stump": stone,
                    "mushrooms": stone, "root_hazard": ruin, "stone": stone,
                    "ruin": ruin, "cliff": stone, "ritual_platform": platform,
                }
                return [self._make_ground_tile(i, palette) for i in range(8)], props
            raise FileNotFoundError(f"Required Treant terrain atlas not found: {self.tile_path}")
        raw = self._load_surface(self.tile_path)
        if raw.get_size() != (1448, 1086):
            raise ValueError(f"bosstile.png must be the verified 1448x1086 atlas; got {raw.get_size()}")
        self.tile_source_rects = [pygame.Rect(rect) for rect in BOSS_TILE_RECTS]
        self.terrain_sources = [pygame.transform.scale(raw.subsurface(rect).copy(), (24, 24))
                                for rect in self.tile_source_rects]
        tiles = [pygame.transform.scale(source, (self.tile_size, self.tile_size))
                 for source in self.terrain_sources]
        sizes = {
            "tree": (156, 156), "tree_birch": (94, 150), "dead_tree": (118, 158),
            "stump": (130, 136), "mushrooms": (90, 132), "root_hazard": (104, 142),
            "ruin": (116, 190), "portal": (246, 226),
            "ritual_platform": (570, 307), "cliff": (86, 112),
        }
        props: dict[str, pygame.Surface] = {}
        for name, rect_value in BOSS_PROP_RECTS.items():
            rect = pygame.Rect(rect_value)
            self.prop_source_rects[name] = rect
            crop = self._remove_flat_background(raw.subsurface(rect).copy(), name)
            if name == "ritual_platform":
                # Clear title text, margins, and section divider rules outside dais art.
                crop.fill((0, 0, 0, 0), (0, 0, crop.get_width(), 34))
                crop.fill((0, 0, 0, 0), (0, 0, 240, 62))
                crop.fill((0, 0, 0, 0), (420, 0, crop.get_width() - 420, 62))
            elif name == "dead_tree":
                # Remove the section rule and slivers of its left neighbor.
                crop.fill((0, 0, 0, 0), (0, 0, crop.get_width(), 8))
                crop.fill((0, 0, 0, 0), (0, 0, 3, crop.get_height()))
            elif name == "mushrooms":
                # The presentation layout clips unrelated neighboring art into the
                # narrow margins around this otherwise self-contained cluster.
                crop.fill((0, 0, 0, 0), (0, 0, 1, crop.get_height()))
                crop.fill((0, 0, 0, 0), (127, 0, crop.get_width() - 127,
                                         crop.get_height()))
            if crop.get_bounding_rect(min_alpha=12).width <= 0:
                raise ValueError(f"bosstile.png: verified {name!r} crop contains no visible artwork")
            props[name] = self._fit_prop(crop, sizes[name])
        # Small generic stones use the lower part of the monolith art rather than
        # generated geometry; all normal arena visuals now originate in bosstile.
        props["stone"] = pygame.transform.scale(props["ruin"], (48, 78))
        return tiles, props

    @staticmethod
    def _fit_prop(sprite: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
        bounds = sprite.get_bounding_rect(min_alpha=12)
        if bounds.width <= 0 or bounds.height <= 0:
            return pygame.Surface(size, pygame.SRCALPHA)
        sprite = sprite.subsurface(bounds).copy()
        scale = min((size[0] - 4) / sprite.get_width(), (size[1] - 4) / sprite.get_height())
        target = (max(1, round(sprite.get_width() * scale)),
                  max(1, round(sprite.get_height() * scale)))
        art = pygame.transform.scale(sprite, target)
        canvas = pygame.Surface(size, pygame.SRCALPHA)
        canvas.blit(art, art.get_rect(midbottom=(size[0] // 2, size[1] - 2)))
        a = pygame.surfarray.pixels_alpha(canvas)
        rgb = pygame.surfarray.pixels3d(canvas)
        rgb[a == 0] = [0, 0, 0]
        del a, rgb
        return canvas

    def _extract_prop_art(self, raw: pygame.Surface) -> dict[str, pygame.Surface]:
        """Legacy diagnostic helper; production props use measured rectangles."""
        cleaned = self._remove_flat_background(raw)
        sw, sh = cleaned.get_size()
        mask = pygame.mask.from_surface(cleaned, 24)
        candidates = [r for r in mask.get_bounding_rects()
                      if r.width >= max(16, sw // 90)
                      and r.height >= max(18, sh // 70)
                      and r.width * r.height >= sw * sh * .00022
                      and max(r.width, r.height) >= min(sw, sh) * .09
                      and r.width < sw * .38 and r.height < sh * .42]
        if not candidates:
            return {}

        measured: list[tuple[pygame.Rect, dict[str, float]]] = []
        for rect in candidates:
            counts = {"orange": 0, "green": 0, "purple": 0, "cyan": 0,
                      "gray": 0, "brown": 0, "bright": 0, "total": 0}
            step = max(1, min(rect.width, rect.height) // 14)
            for y in range(rect.top, rect.bottom, step):
                for x in range(rect.left, rect.right, step):
                    color = cleaned.get_at((x, y))
                    if color.a < 32:
                        continue
                    r, g, b = color[:3]
                    counts["total"] += 1
                    counts["orange"] += r > 120 and r > g * 1.25 and g > b * .75
                    counts["green"] += g > r * .80 and g > b * 1.15 and g > 55
                    counts["purple"] += b > g * 1.12 and r > g * 1.06 and max(r, b) > 100
                    counts["cyan"] += b > r * 1.08 and g > r * 1.08 and max(g, b) > 110
                    counts["gray"] += max(r, g, b) - min(r, g, b) < 38 and 45 < r < 210
                    counts["brown"] += r > g * 1.10 and g >= b * .85 and 45 < r < 190
                    counts["bright"] += max(r, g, b) > 210 and max(r, g, b) - min(r, g, b) > 60
            total = max(1, counts.pop("total"))
            measured.append((rect, {key: value / total for key, value in counts.items()}))

        aspect_score = lambda rect: 1.0 - min(1.0, abs(math.log(max(.08, rect.width / rect.height))))
        scorers = {
            "portal": lambda rect, c: (9 * c["purple"] + 6 * c["cyan"]
                                        + 2.5 * c["bright"] + 1.6 * aspect_score(rect)),
            "tree": lambda rect, c: (5 * c["orange"] + 3 * c["green"]
                                      + min(1.5, rect.height / max(1, rect.width))),
            "stone": lambda rect, c: 7 * c["gray"] + 1.4 * aspect_score(rect),
            "ruin": lambda rect, c: 4.5 * c["gray"] + 3 * c["brown"] + .7 * aspect_score(rect),
        }
        eligible = {
            "portal": lambda c: c["purple"] + c["cyan"] + c["bright"] > .035,
            "tree": lambda c: c["orange"] + c["green"] > .14,
            "stone": lambda c: c["gray"] > .16,
            "ruin": lambda c: c["gray"] + c["brown"] > .22,
        }
        sizes = {"portal": (92, 94), "tree": (100, 134), "stone": (48, 42), "ruin": (70, 74)}
        used: set[tuple[int, int, int, int]] = set()
        result: dict[str, pygame.Surface] = {}
        # Magic portal is most distinctive; choose it before shared gray/brown props.
        for name in ("portal", "tree", "stone", "ruin"):
            ranked = sorted(((scorers[name](rect, colors), rect) for rect, colors in measured
                             if eligible[name](colors) and tuple(rect) not in used), reverse=True,
                            key=lambda item: item[0])
            if not ranked:
                continue
            rect = ranked[0][1]
            used.add(tuple(rect))
            self.prop_source_rects[name] = rect
            result[name] = self._fit_prop(cleaned.subsurface(rect).copy(), sizes[name])
        return result

    def _extract_ground_tiles(self, raw: Optional[pygame.Surface]) -> list[pygame.Surface]:
        """Legacy diagnostic helper; production tiles use measured rectangles."""
        if raw is None:
            return []
        w, h = raw.get_size()
        cell = max(18, min(48, min(w, h) // 20))
        step = max(9, cell // 2)
        candidates: list[tuple[float, pygame.Rect]] = []
        for top in range(0, h - cell + 1, step):
            for left in range(0, w - cell + 1, step):
                colors = []
                white = dark = 0
                for sy in range(6):
                    for sx in range(6):
                        c = raw.get_at((left + (sx * cell + cell // 2) // 6,
                                        top + (sy * cell + cell // 2) // 6))
                        if c.a < 32: continue
                        rgb = c[:3]
                        colors.append(rgb)
                        white += min(rgb) > 224 and max(rgb) - min(rgb) < 28
                        dark += max(rgb) < 38
                if len(colors) < 28 or white > 3 or dark > 14:
                    continue
                means = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                if not (means[0] > means[1] * 1.05 and means[1] >= means[2] * .85
                        and 48 < sum(means) / 3 < 205):
                    continue
                variance = sum(sum((c[i] - means[i]) ** 2 for i in range(3)) for c in colors) / len(colors)
                autumn = (means[0] - means[2]) + .35 * (means[0] - means[1])
                score = autumn - variance / 145 - white * 40
                candidates.append((score, pygame.Rect(left, top, cell, cell)))
        chosen: list[pygame.Rect] = []
        for _, rect in sorted(candidates, key=lambda item: item[0], reverse=True):
            if all(math.hypot(rect.centerx - old.centerx, rect.centery - old.centery) > cell * 1.4
                   for old in chosen):
                chosen.append(rect)
            if len(chosen) == 8: break
        self.tile_source_rects = chosen
        return [pygame.transform.scale(raw.subsurface(rect).copy(),
                                       (self.tile_size, self.tile_size)) for rect in chosen]

    @staticmethod
    def _sample_autumn_palette(raw: Optional[pygame.Surface]) -> tuple[tuple[int, int, int], ...]:
        if raw is None:
            return ((121, 63, 31), (145, 75, 29), (171, 91, 31), (91, 48, 32))
        w, h = raw.get_size()
        colors = []
        for gy in range(2, 7):
            for gx in range(2, 9):
                c = raw.get_at((gx * w // 10, gy * h // 9))[:3]
                if c[0] > c[2] and c[0] > 45 and max(c) - min(c) > 18:
                    colors.append(c)
        if len(colors) < 4:
            return ((121, 63, 31), (145, 75, 29), (171, 91, 31), (91, 48, 32))
        return tuple(colors[:4])

    def _make_ground_tile(self, variant: int, palette: Sequence[tuple[int, int, int]]) -> pygame.Surface:
        size = self.tile_size
        s = pygame.Surface((size, size))
        base = palette[variant % len(palette)]
        s.fill(base)
        rng = random.Random(914 + variant)
        for _ in range(24):
            x, y = rng.randrange(size), rng.randrange(size)
            delta = rng.choice((-18, -10, 10, 16))
            c = tuple(max(0, min(255, channel + delta)) for channel in base)
            s.fill(c, (x, y, rng.choice((2, 3, 5)), rng.choice((1, 2))))
        return s

    @staticmethod
    def _make_portal() -> pygame.Surface:
        s = pygame.Surface((92, 94), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (48, 22, 40), (10, 6, 72, 82), 10)
        pygame.draw.ellipse(s, (125, 48, 39), (14, 10, 64, 75), 6)
        pygame.draw.ellipse(s, (241, 118, 30, 180), (25, 23, 42, 55))
        pygame.draw.ellipse(s, (255, 197, 74, 210), (33, 29, 26, 44), 3)
        return s

    @staticmethod
    def _make_tree() -> pygame.Surface:
        s = pygame.Surface((100, 134), pygame.SRCALPHA)
        pygame.draw.rect(s, (72, 39, 27), (43, 67, 16, 59))
        for x, y, r, c in ((49, 43, 38, (151, 47, 24)), (30, 47, 25, (211, 73, 20)),
                           (70, 50, 27, (235, 119, 24)), (48, 24, 25, (181, 55, 20))):
            pygame.draw.circle(s, c, (x, y), r)
        return s

    @staticmethod
    def _make_stone() -> pygame.Surface:
        s = pygame.Surface((48, 42), pygame.SRCALPHA)
        pygame.draw.polygon(s, (66, 55, 53), [(5, 34), (11, 9), (34, 3), (44, 31), (37, 39), (12, 39)])
        pygame.draw.polygon(s, (111, 91, 76), [(11, 9), (34, 3), (28, 19), (8, 25)])
        return s

    @staticmethod
    def _make_ruin() -> pygame.Surface:
        s = pygame.Surface((70, 74), pygame.SRCALPHA)
        for x, y, w, h in ((4, 50, 62, 13), (10, 16, 13, 39), (47, 9, 13, 46), (7, 8, 19, 12), (43, 2, 21, 13)):
            pygame.draw.rect(s, (83, 68, 62), (x, y, w, h))
            pygame.draw.line(s, (133, 101, 68), (x + 2, y + 2), (x + w - 3, y + 2), 2)
        return s


class TreantBossEncounter:
    """Standalone encounter logic with an event-based host boundary.

    ``update`` accepts one player snapshot or a sequence. Boss damage is submitted
    explicitly with ``register_player_attack``. Boss attacks emit ``PLAYER_HIT``;
    the host validates/applies that damage and supplies updated health next frame.
    """

    # Tiles between the entrance sprite's foot (stair bottom) and its arch base.
    PORTAL_ARCH_DEPTH = 2.35

    def __init__(self, assets_dir: Optional[Union[str, Path]] = None,
                 config: Optional[TreantConfig] = None,
                 animation_rects: Optional[Mapping[str, Sequence[tuple[int, int, int, int]]]] = None,
                 allow_test_assets: bool = False) -> None:
        self.config = config or TreantConfig()
        self.assets_dir = resolve_boss_assets_dir(assets_dir)
        self.assets = TreantAssets(self.assets_dir, self.config.tile_size, animation_rects,
                                   allow_test_assets=allow_test_assets)
        self.animation = AnimationController(self.assets.animations)
        self.rng = random.Random(self.config.seed)
        self.portal_spawn = (self.config.arena_width / 2, self.config.arena_height - 2.15)
        self.ritual_center = (self.config.arena_width / 2, self.config.arena_height * .46)
        self.boss_spawn = (self.ritual_center[0], self.ritual_center[1] - .25)
        self._arena_surface = self._build_arena_surface()
        # Shown under the defeat banner; hosts that return the player
        # automatically replace the standalone demo's restart prompt.
        self.defeat_hint = tr("boss.restart")
        self._render_debug_frame = 0
        self._render_debug_records: list[dict[str, Any]] = []
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        self.state = BossState.INTRO
        self.result = EncounterResult.IN_PROGRESS
        self.phase = 1
        self.health = self.config.max_health
        self.boss_x, self.boss_y = self.boss_spawn
        self.visual_jump_height = 0.0
        self.state_time = 0.0
        self.total_time = 0.0
        self.idle_duration = 0.40
        self.cooldown = 0.0
        self.earthquake_cooldown = 0.0
        self.started = False
        self.arrival_time = 0.0
        self._events: deque[EncounterEvent] = deque()
        self._seen_player_attacks: set[str] = set()
        self._hit_players_by_attack: dict[str, set[str]] = {}
        self._attack_serial = 0
        self._current_attack_id: Optional[str] = None
        self._target_id: Optional[str] = None
        self._locked_direction = pygame.Vector2(0, 1)
        self._jump_center = pygame.Vector2(self.boss_x, self.boss_y)
        self._jump_start = pygame.Vector2(self.boss_x, self.boss_y)
        self._approach_mode = "chase"
        self._strafe_sign = 1
        self._last_attack = ""
        self._phase_transition_done = False
        self._boss_defeat_emitted = False
        self._completion_emitted = False
        self._defeated_players: set[str] = set()
        self._hurt_return_state = BossState.IDLE
        self._hurt_duration = 0.0
        self.particles: list[Particle] = []
        self.camera_shake = 0.0
        self.shockwave_progress = 0.0
        self.animation.play("idle", restart=True)

    @property
    def boss_hitbox(self) -> FloatRect:
        return FloatRect(self.boss_x - self.config.boss_width / 2,
                         self.boss_y - self.config.boss_height,
                         self.config.boss_width, self.config.boss_height)

    def start(self, player_state: Union[BossPlayerState, Sequence[BossPlayerState]]) -> tuple[float, float]:
        """Prepare portal arrival and return the documented player spawn point."""
        self._reset_runtime()
        if self.config.auto_start:
            self._begin_battle()
        return self.portal_spawn

    def cleanup(self) -> None:
        """Release transient encounter state; cached Pygame surfaces remain reusable."""
        self.particles.clear()
        self._events.clear()
        self._seen_player_attacks.clear()
        self._hit_players_by_attack.clear()

    def forfeit(self) -> None:
        """End an active encounter as a defeat (retreat/disconnect authority hook)."""
        self._finish_defeat()

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Optional hook reserved for encounter UI; currently consumes no input."""
        return False

    @staticmethod
    def _players(value: Union[BossPlayerState, Sequence[BossPlayerState]]) -> list[BossPlayerState]:
        if isinstance(value, BossPlayerState):
            return [value]
        return list(value)

    def _emit(self, event_type: str, **data: Any) -> None:
        self._events.append(EncounterEvent(event_type, round(self.total_time, 6), data))

    def consume_events(self) -> list[EncounterEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    def get_result(self) -> EncounterResult:
        return self.result

    def get_state_snapshot(self) -> dict[str, Any]:
        """Plain authoritative state suitable for network snapshots."""
        return {
            "version": 1, "state": self.state.value, "result": self.result.value,
            "phase": self.phase, "health": self.health,
            "max_health": self.config.max_health, "boss_x": self.boss_x,
            "boss_y": self.boss_y, "state_time": self.state_time,
            "total_time": self.total_time, "arrival_time": self.arrival_time,
            "started": self.started,
            "attack_id": self._current_attack_id,
            "attack_direction": tuple(self._locked_direction),
            "jump_center": tuple(self._jump_center),
            "visual_jump_height": self.visual_jump_height,
            "shockwave_progress": self.shockwave_progress,
            "camera_shake": self.camera_shake,
        }

    def apply_state_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        """Apply a trusted authority snapshot to a render-only replica."""
        if int(snapshot.get("version", 0)) != 1:
            raise ValueError("unsupported PLATANUS snapshot version")
        state = BossState(snapshot["state"])
        if state != self.state:
            self._enter_state(state)
        self.result = EncounterResult(snapshot.get("result", EncounterResult.IN_PROGRESS.value))
        self.phase = max(1, min(2, int(snapshot.get("phase", self.phase))))
        self.health = max(0.0, min(self.config.max_health, float(snapshot.get("health", self.health))))
        self.boss_x = float(snapshot.get("boss_x", self.boss_x))
        self.boss_y = float(snapshot.get("boss_y", self.boss_y))
        self.state_time = max(0.0, float(snapshot.get("state_time", self.state_time)))
        self.total_time = max(0.0, float(snapshot.get("total_time", self.total_time)))
        self.arrival_time = max(0.0, float(snapshot.get("arrival_time", self.arrival_time)))
        self.started = bool(snapshot.get("started", state != BossState.INTRO))
        self._current_attack_id = snapshot.get("attack_id")
        direction = snapshot.get("attack_direction", (0.0, 1.0))
        center = snapshot.get("jump_center", (self.boss_x, self.boss_y))
        if isinstance(direction, (list, tuple)) and len(direction) == 2:
            self._locked_direction.update(float(direction[0]), float(direction[1]))
        if isinstance(center, (list, tuple)) and len(center) == 2:
            self._jump_center.update(float(center[0]), float(center[1]))
        self.visual_jump_height = max(0.0, float(snapshot.get("visual_jump_height", 0.0)))
        self.shockwave_progress = max(0.0, min(1.0, float(snapshot.get("shockwave_progress", 0.0))))
        self.camera_shake = max(0.0, float(snapshot.get("camera_shake", 0.0)))

    def update_replica(self, dt: float) -> None:
        """Advance only visual timing between authoritative network snapshots."""
        dt = min(.05, max(0.0, float(dt)))
        self.total_time += dt
        self.arrival_time += dt
        self.state_time += dt
        self.camera_shake = max(0.0, self.camera_shake - dt)
        self._update_particles(dt)
        looping = self.state not in (BossState.DYING, BossState.PHASE_TRANSITION)
        self.animation.update(dt, loop=looping)

    def register_player_attack(self, attack: PlayerAttack) -> bool:
        """Validate and apply one unique host-submitted hit to authoritative boss HP."""
        if attack.attack_id in self._seen_player_attacks:
            return False
        if (not self.started or self.result != EncounterResult.IN_PROGRESS
                or self.state in (BossState.PHASE_TRANSITION, BossState.DYING, BossState.DEFEATED)
                or attack.damage <= 0 or not attack.hitbox.intersects(self.boss_hitbox)):
            return False
        self._seen_player_attacks.add(attack.attack_id)
        old = self.health
        self.health = max(0.0, self.health - float(attack.damage))
        actual = old - self.health
        self._emit(BOSS_DAMAGED, player_id=str(attack.player_id), attack_id=attack.attack_id,
                   damage=actual, health=self.health, max_health=self.config.max_health)
        self._burst(self.boss_x, self.boss_y - .7, 6, "hit")
        if self.health <= 0:
            self._enter_state(BossState.DYING)
        elif self.phase == 1 and self.health <= self.config.max_health * .5:
            self.phase = 2
            self._phase_transition_done = True
            self._current_attack_id = None
            self._enter_state(BossState.PHASE_TRANSITION)
            self._emit(BOSS_PHASE_CHANGED, phase=2, health=self.health)
            self._burst(self.boss_x, self.boss_y - .65, 22, "magic")
        else:
            # Very short hit reaction never invalidates an already active boss hit.
            return_state = self.state
            if self.state in (BossState.IDLE, BossState.APPROACH):
                self._hurt_return_state = return_state
                self._enter_state(BossState.HURT)
        return True

    def can_stand(self, x: float, y: float, half_width: float = .18) -> bool:
        """Finite island collision used by both host adapters and the demo."""
        cx, cy = self.config.arena_width / 2, self.config.arena_height / 2 + .15
        rx, ry = self.config.arena_width / 2 - 0.85 - half_width, self.config.arena_height / 2 - 0.75 - half_width
        if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 > 1.0:
            return False
        # Trees/ruins are readable blockers; the center and portal lane stay open.
        for bx, by, bw, bh in self._blockers():
            if bx - half_width < x < bx + bw + half_width and by - half_width < y < by + bh + half_width:
                return False
        return True

    def constrain_motion(self, old: tuple[float, float], desired: tuple[float, float],
                         half_width: float = .18) -> tuple[float, float]:
        """Axis-separated arena collision helper with anti-tunneling and smooth sliding."""
        total_dx = desired[0] - old[0]
        total_dy = desired[1] - old[1]
        dist = math.hypot(total_dx, total_dy)
        max_step = half_width * 0.75
        steps = max(1, math.ceil(dist / max_step)) if dist > 0 else 1
        step_dx = total_dx / steps
        step_dy = total_dy / steps
        cur_x, cur_y = old
        for _ in range(steps):
            next_x = cur_x + step_dx
            if self.can_stand(next_x, cur_y, half_width):
                cur_x = next_x
            next_y = cur_y + step_dy
            if self.can_stand(cur_x, next_y, half_width):
                cur_y = next_y
        return cur_x, cur_y

    def update(self, dt: float, player_state: Union[BossPlayerState, Sequence[BossPlayerState]]) -> None:
        dt = min(.05, max(0.0, float(dt)))
        players = self._players(player_state)
        self.total_time += dt
        self.arrival_time += dt
        self.cooldown = max(0.0, self.cooldown - dt)
        self.earthquake_cooldown = max(0.0, self.earthquake_cooldown - dt)
        self.camera_shake = max(0.0, self.camera_shake - dt)
        self._update_particles(dt)
        self._detect_player_defeat(players)
        if self.result != EncounterResult.IN_PROGRESS:
            self._update_terminal(dt)
            return
        live = [p for p in players if p.health > 0]
        if not live:
            self._finish_defeat()
            return
        target = min(live, key=lambda p: (p.x - self.boss_x) ** 2 + (p.y - self.boss_y) ** 2)
        if not self.started:
            self.animation.play("idle")
            self.animation.update(dt)
            if self.config.auto_start or math.hypot(target.x - self.ritual_center[0], target.y - self.ritual_center[1]) <= self.config.trigger_radius:
                self._begin_battle()
            return
        self.state_time += dt
        self._update_state(dt, target, live)
        looping = self.state not in (BossState.DYING, BossState.PHASE_TRANSITION)
        self.animation.update(dt, loop=looping)

    def _detect_player_defeat(self, players: Sequence[BossPlayerState]) -> None:
        for player in players:
            if player.health <= 0 and player.player_id not in self._defeated_players:
                self._defeated_players.add(player.player_id)
                self._emit(PLAYER_DEFEATED, player_id=player.player_id)

    def _finish_defeat(self) -> None:
        if self.result != EncounterResult.IN_PROGRESS:
            return
        self.result = EncounterResult.DEFEAT
        self._current_attack_id = None
        if not self._completion_emitted:
            self._completion_emitted = True
            self._emit(ENCOUNTER_COMPLETED, result=self.result.value)

    def _update_terminal(self, dt: float) -> None:
        if self.state == BossState.DYING:
            self.state_time += dt
            self.animation.update(dt, loop=False)

    def _begin_battle(self) -> None:
        if self.started:
            return
        self.started = True
        self._enter_state(BossState.IDLE)
        self._emit(BOSS_STARTED, boss_name=BOSS_NAME, health=self.health,
                   max_health=self.config.max_health, phase=self.phase)

    def _enter_state(self, state: BossState) -> None:
        self.state, self.state_time = state, 0.0
        names = {
            BossState.INTRO: "idle", BossState.IDLE: "idle", BossState.APPROACH: "walk",
            BossState.ARM_WINDUP: "arm", BossState.ARM_EXTEND: "arm", BossState.ARM_RECOVERY: "arm",
            BossState.PHASE_TRANSITION: "roar", BossState.JUMP_WINDUP: "jump",
            BossState.JUMP_ASCEND: "jump", BossState.JUMP_DESCEND: "jump",
            BossState.EARTHQUAKE: "impact", BossState.EARTHQUAKE_RECOVERY: "idle",
            BossState.HURT: "hurt", BossState.DYING: "death", BossState.DEFEATED: "death",
        }
        self.animation.play(names[state], restart=True)
        if state == BossState.DYING:
            self._current_attack_id = None

    def _new_attack(self, kind: str, target: BossPlayerState) -> None:
        self._attack_serial += 1
        self._current_attack_id = f"treant:{self._attack_serial}"
        self._target_id = target.player_id
        self._hit_players_by_attack[self._current_attack_id] = set()
        direction = pygame.Vector2(target.x - self.boss_x, target.y - self.boss_y)
        if direction.length_squared() < .0001: direction.update(0, 1)
        self._locked_direction = direction.normalize()
        self._last_attack = kind
        self._emit(BOSS_ATTACK_STARTED, attack_id=self._current_attack_id, attack=kind,
                   target_player_id=target.player_id,
                   direction=(round(self._locked_direction.x, 5), round(self._locked_direction.y, 5)))

    # Distances (tiles) that shape PLATANUS's footwork.  The arm reaches 4.4
    # tiles, so attacking from 3.1 leaves a readable lane on either side.
    ATTACK_DISTANCE = 3.1
    CHASE_DISTANCE = 3.45
    PRESSURE_DISTANCE = 2.25
    CROWDED_DISTANCE = 1.15

    def _move_speed(self) -> float:
        multiplier = self.config.phase_two_speed_multiplier if self.phase == 2 else 1.0
        return self.config.boss_speed * multiplier

    def _step(self, direction: pygame.Vector2, distance: float) -> bool:
        """Move with axis sliding; veer around blockers instead of stalling on them."""
        if distance <= 0 or direction.length_squared() < 1e-6:
            return False
        base = direction.normalize()
        for angle in (0, 35 * self._strafe_sign, -35 * self._strafe_sign,
                      70 * self._strafe_sign, -70 * self._strafe_sign):
            step = base.rotate(angle) * distance
            moved = False
            # A zero-length axis component is not progress; only real travel counts.
            if abs(step.x) > 1e-6 and self.can_stand(self.boss_x + step.x, self.boss_y, .65):
                self.boss_x += step.x
                moved = True
            if abs(step.y) > 1e-6 and self.can_stand(self.boss_x, self.boss_y + step.y, .65):
                self.boss_y += step.y
                moved = True
            if moved:
                return True
        # Fully boxed in: try circling the other way next time.
        self._strafe_sign *= -1
        return False

    def _approach(self, mode: str) -> None:
        self._approach_mode = mode
        self._enter_state(BossState.APPROACH)

    def _leap_target(self, target: BossPlayerState) -> pygame.Vector2:
        """Landing mark between PLATANUS and the target, never on top of them."""
        start = pygame.Vector2(self._jump_start)
        offset = pygame.Vector2(target.x - start.x, target.y - start.y)
        travel = min(self.config.leap_range, max(0.0, offset.length() - 1.1))
        if travel <= .05:
            return start
        offset.scale_to_length(travel)
        for fraction in (1.0, .75, .5, .25):
            point = start + offset * fraction
            if self.can_stand(point.x, point.y, .65):
                return point
        return start

    def _start_attack(self, target: BossPlayerState) -> None:
        use_quake = (self.phase == 2 and self.earthquake_cooldown <= 0
                     and self._last_attack != "earthquake"
                     and self.rng.random() < .46)
        self._new_attack("earthquake" if use_quake else "arm", target)
        if use_quake:
            self._jump_start.update(self.boss_x, self.boss_y)
            self._jump_center.update(self._leap_target(target))
            self._enter_state(BossState.JUMP_WINDUP)
        else:
            self._enter_state(BossState.ARM_WINDUP)

    def _resume_after_attack(self, distance: float) -> None:
        """Flow straight back into the chase when the target has run off."""
        self._current_attack_id = None
        if distance > self.CHASE_DISTANCE:
            self._approach("chase")
        else:
            self._enter_state(BossState.IDLE)

    def _update_state(self, dt: float, target: BossPlayerState,
                      players: Sequence[BossPlayerState]) -> None:
        distance = math.hypot(target.x - self.boss_x, target.y - self.boss_y)
        to_target = pygame.Vector2(target.x - self.boss_x, target.y - self.boss_y)
        if self.state == BossState.IDLE:
            if self.state_time >= self.idle_duration:
                if distance < self.CROWDED_DISTANCE and self.cooldown > .25:
                    # Step back out of the player's face so the next arm has a lane.
                    self._approach("retreat")
                elif distance > self.CHASE_DISTANCE:
                    self._approach("chase")
                elif self.cooldown > 0 and distance > self.PRESSURE_DISTANCE:
                    # Use recovery time to regain pressure instead of freezing.
                    self._approach("chase")
                elif self.cooldown <= 0:
                    self._start_attack(target)
                elif self.cooldown > .35:
                    # Circle the player while recovering rather than standing still.
                    self._approach("strafe")
        elif self.state == BossState.APPROACH:
            speed = self._move_speed()
            if self._approach_mode == "retreat":
                if distance >= self.PRESSURE_DISTANCE - .25 or self.state_time > .45:
                    self._enter_state(BossState.IDLE)
                    self.idle_duration = .08
                else:
                    self._step(-to_target, speed * .85 * dt)
            elif self._approach_mode == "strafe":
                if self.cooldown <= 0 or distance > self.CHASE_DISTANCE or self.state_time > .7:
                    self._enter_state(BossState.IDLE)
                    self.idle_duration = .05
                elif to_target.length_squared() > .001:
                    # Orbit while holding roughly the pressure distance.
                    orbit = to_target.normalize().rotate(90 * self._strafe_sign)
                    orbit += to_target.normalize() * ((distance - 2.0) * .6)
                    if not self._step(orbit, speed * .6 * dt):
                        self._strafe_sign *= -1
            else:
                if self.cooldown <= 0 and distance <= self.ATTACK_DISTANCE:
                    # Go straight from the chase into the telegraphed attack.
                    self._start_attack(target)
                elif self.cooldown > 0 and distance <= 2.65:
                    self._enter_state(BossState.IDLE)
                    self.idle_duration = .08 if self.phase == 2 else .12
                elif self.state_time > 2.2:
                    self._enter_state(BossState.IDLE)
                    self.idle_duration = .10
                elif to_target.length_squared() > .001:
                    self._step(to_target, speed * dt)
        elif self.state == BossState.ARM_WINDUP:
            # Track early, lock at 0.34 s, then leave a readable fixed warning.
            if self.state_time < .34:
                vec = pygame.Vector2(target.x - self.boss_x, target.y - self.boss_y)
                if vec.length_squared() > .001: self._locked_direction = vec.normalize()
            if self.state_time >= .72:
                self._enter_state(BossState.ARM_EXTEND)
        elif self.state == BossState.ARM_EXTEND:
            # Damage begins only when the real/composited arm has visually reached
            # its target. The collision length is the same visible fraction.
            if .17 <= self.state_time <= .29:
                self._resolve_arm_hits(players, self._arm_extension_fraction())
            if self.state_time >= .38:
                self._enter_state(BossState.ARM_RECOVERY)
        elif self.state == BossState.ARM_RECOVERY:
            if self.state_time >= (.42 if self.phase == 1 else .34):
                self.cooldown = .80 if self.phase == 1 else .64
                self.idle_duration = .26 if self.phase == 1 else .18
                self._resume_after_attack(distance)
        elif self.state == BossState.PHASE_TRANSITION:
            if self.state_time >= 1.35:
                self.cooldown = .45
                self.earthquake_cooldown = .25
                self.idle_duration = .45
                self._enter_state(BossState.IDLE)
        elif self.state == BossState.JUMP_WINDUP:
            # The landing mark follows the target briefly, then locks so the
            # flashing ring gives over a second of warning before impact.
            if self.state_time < .5:
                self._jump_center.update(self._leap_target(target))
            if self.state_time >= .82:
                self._enter_state(BossState.JUMP_ASCEND)
        elif self.state == BossState.JUMP_ASCEND:
            p = min(1.0, self.state_time / .48)
            # The source frames already contain vertical pose travel. This modest
            # world-independent offset completes the lift without a double jump.
            self.visual_jump_height = math.sin(p * math.pi / 2) * .55
            self.boss_x, self.boss_y = self._jump_start.lerp(self._jump_center, p * .5)
            if p >= 1.0: self._enter_state(BossState.JUMP_DESCEND)
        elif self.state == BossState.JUMP_DESCEND:
            p = min(1.0, self.state_time / .40)
            self.visual_jump_height = math.cos(p * math.pi / 2) * .55
            self.boss_x, self.boss_y = self._jump_start.lerp(self._jump_center, .5 + p * .5)
            if p >= 1.0:
                self.visual_jump_height = 0.0
                self._enter_state(BossState.EARTHQUAKE)
                self._resolve_earthquake_hits(players)
                self._burst(self.boss_x, self.boss_y, 28, "debris")
                self.camera_shake = .34
        elif self.state == BossState.EARTHQUAKE:
            self.shockwave_progress = min(1.0, self.state_time / .46)
            if self.state_time >= .52:
                self._enter_state(BossState.EARTHQUAKE_RECOVERY)
        elif self.state == BossState.EARTHQUAKE_RECOVERY:
            if self.state_time >= .66:
                self.cooldown = 1.0
                self.earthquake_cooldown = 4.4
                self.idle_duration = .24
                self.shockwave_progress = 0.0
                self._resume_after_attack(distance)
        elif self.state == BossState.HURT:
            if self.state_time >= .16:
                self._enter_state(self._hurt_return_state)
        elif self.state == BossState.DYING:
            if self.state_time >= 1.65:
                self._enter_state(BossState.DEFEATED)
                self.result = EncounterResult.VICTORY
                self._burst(self.boss_x, self.boss_y - .5, 38, "leaf")
                if not self._boss_defeat_emitted:
                    self._boss_defeat_emitted = True
                    self._emit(BOSS_DEFEATED, boss_name=BOSS_NAME)
                if not self._completion_emitted:
                    self._completion_emitted = True
                    self._emit(ENCOUNTER_COMPLETED, result=self.result.value)

    def _arm_extension_fraction(self) -> float:
        if self.state == BossState.ARM_EXTEND:
            progress = min(1.0, self.state_time / .18)
            return progress * progress * (3.0 - 2.0 * progress)
        if self.state == BossState.ARM_RECOVERY:
            progress = min(1.0, self.state_time / .46)
            return 1.0 - progress * progress * (3.0 - 2.0 * progress)
        return 0.0

    def _arm_origin(self) -> pygame.Vector2:
        return pygame.Vector2(self.boss_x, self.boss_y - .78)

    def _resolve_arm_hits(self, players: Sequence[BossPlayerState],
                          extension: float = 1.0) -> None:
        if self._current_attack_id is None: return
        hit = self._hit_players_by_attack[self._current_attack_id]
        start = self._arm_origin()
        visible_reach = self.config.arm_range * max(0.0, min(1.0, extension))
        for player in players:
            if player.player_id in hit or player.invulnerable: continue
            center = pygame.Vector2(*player.hitbox.center)
            rel = center - start
            along = rel.dot(self._locked_direction)
            across = abs(rel.cross(self._locked_direction))
            extra = math.hypot(player.width, player.height) * .5
            if -.15 <= along <= visible_reach and across <= self.config.arm_width / 2 + extra:
                hit.add(player.player_id)
                knock = self._locked_direction * 5.2
                self._emit(PLAYER_HIT, player_id=player.player_id, attack_id=self._current_attack_id,
                           attack="arm", damage=self.config.arm_damage,
                           knockback=(knock.x, knock.y), invulnerability=0.70)

    def _resolve_earthquake_hits(self, players: Sequence[BossPlayerState]) -> None:
        if self._current_attack_id is None: return
        hit = self._hit_players_by_attack[self._current_attack_id]
        for player in players:
            if player.player_id in hit or player.invulnerable: continue
            nearest_x = max(player.hitbox.left, min(self._jump_center.x, player.hitbox.right))
            nearest_y = max(player.hitbox.top, min(self._jump_center.y, player.hitbox.bottom))
            dx, dy = nearest_x - self._jump_center.x, nearest_y - self._jump_center.y
            if dx * dx + dy * dy <= self.config.earthquake_radius ** 2:
                hit.add(player.player_id)
                push = pygame.Vector2(player.x - self._jump_center.x, player.y - self._jump_center.y)
                if push.length_squared() < .001: push.update(0, 1)
                push.scale_to_length(6.2)
                self._emit(PLAYER_HIT, player_id=player.player_id, attack_id=self._current_attack_id,
                           attack="earthquake", damage=self.config.earthquake_damage,
                           knockback=(push.x, push.y), invulnerability=0.85)

    def _burst(self, x: float, y: float, count: int, kind: str) -> None:
        colors = {
            "hit": ((255, 225, 120), (245, 120, 48), (255, 248, 205)),
            "magic": ((255, 174, 40), (229, 74, 28), (255, 220, 80)),
            "debris": ((106, 72, 49), (162, 102, 52), (218, 142, 55)),
            "leaf": ((235, 77, 22), (255, 151, 30), (166, 48, 27)),
        }[kind]
        for index in range(count):
            angle = self.rng.random() * math.tau
            speed = self.rng.uniform(.7, 3.1)
            life = self.rng.uniform(.35, .85)
            self.particles.append(Particle(x, y, math.cos(angle) * speed,
                                           math.sin(angle) * speed - self.rng.uniform(.3, 1.3),
                                           life, life, colors[index % len(colors)], kind))

    def _update_particles(self, dt: float) -> None:
        for p in self.particles:
            p.life -= dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += (3.8 if p.kind != "magic" else .4) * dt
            p.vx *= max(0.0, 1 - 1.5 * dt)
        self.particles[:] = [p for p in self.particles if p.life > 0]

    def _blockers(self) -> tuple[tuple[float, float, float, float], ...]:
        w, h = self.config.arena_width, self.config.arena_height
        return (
            # 4 arena trees (canopy walkable, trunk base solid)
            (2.4 - 0.35, 4.1 - 0.5, 0.7, 0.5),
            (w - 2.5 - 0.3, 4.0 - 0.45, 0.6, 0.45),
            (2.6 - 0.35, h - 4.0 - 0.5, 0.7, 0.5),
            (w - 2.5 - 0.35, h - 4.2 - 0.5, 0.7, 0.5),
            # Cliff wall / monolith rock
            (4.4 - 0.6, 2.7 - 0.6, 1.2, 0.6),
            # Ancient ruin / stone pillar
            (w - 4.2 - 0.55, 3.2 - 0.7, 1.1, 0.7),
            # Mushroom cluster
            (3.7 - 0.45, 8.7 - 0.45, 0.9, 0.45),
            # Solid stump
            (w - 3.7 - 0.55, 8.8 - 0.55, 1.1, 0.55),
            # Root hazard
            (2.9 - 0.5, 6.7 - 0.5, 1.0, 0.5),
            # Portal left and right stone pillars (lane between remains open)
            (w / 2 - 1.9, self.portal_spawn[1] - 0.4, 0.7, 0.6),
            (w / 2 + 1.2, self.portal_spawn[1] - 0.4, 0.7, 0.6),
        )

    def _quilt_material(self, source_indices: Sequence[int], width: int, height: int,
                        seed_offset: int) -> np.ndarray:
        """Build one continuous opaque material at the game's 24px art scale.

        Patches cross every logical tile boundary, mirroring terrain_render.py's
        quilted-material strategy. The result is cached in the arena surface and
        never rebuilt or masked during frame rendering.
        """
        sources = [pygame.surfarray.array3d(self.assets.terrain_sources[index])
                   for index in source_indices]
        xx, yy = np.meshgrid(np.arange(width), np.arange(height), indexing="ij")
        material = sources[0][xx % 24, yy % 24].copy()
        rng = np.random.default_rng(self.config.seed + seed_offset)
        px, py = np.meshgrid(np.arange(18), np.arange(18), indexing="ij")
        distance = (px - 8.5) ** 2 + (py - 8.5) ** 2
        for pass_index in range(2):
            for left in range(-9, width, 13):
                for top in range(-9, height, 13):
                    source = sources[int(rng.integers(0, len(sources)))]
                    sx, sy = (int(value) for value in rng.integers(0, 24, size=2))
                    mask = distance < (58 + rng.integers(-17, 18, size=(18, 18)))
                    x0, y0 = max(0, left), max(0, top)
                    x1, y1 = min(width, left + 18), min(height, top + 18)
                    if x0 >= x1 or y0 >= y1:
                        continue
                    lx0, ly0 = x0 - left, y0 - top
                    lx1, ly1 = lx0 + x1 - x0, ly0 + y1 - y0
                    local_x, local_y = px[lx0:lx1, ly0:ly1], py[lx0:lx1, ly0:ly1]
                    patch = source[(sx + local_x) % 24, (sy + local_y) % 24]
                    local_mask = mask[lx0:lx1, ly0:ly1]
                    target = material[x0:x1, y0:y1]
                    target[local_mask] = patch[local_mask]
        return material

    def _build_arena_surface(self) -> pygame.Surface:
        ts, w, h = self.config.tile_size, self.config.arena_width, self.config.arena_height
        # Compose at the main terrain renderer's 24px art scale, then perform one
        # nearest-neighbor enlargement. No independently scaled 48px squares remain.
        art = 24
        low_w, low_h = w * art, h * art
        # This layer is opaque terrain, so give it an explicit RGB pixel format.
        # On macOS a default-depth Surface inherits the RGBA display masks.  The
        # later ritual-platform blit then copies the prop's transparent padding
        # into that alpha-capable destination: exactly 570 * 307 alpha-zero pixels
        # before other art overlaps it.  The window compositor presents the
        # surviving parts of that rectangular alpha hole as black.
        surface = pygame.Surface((low_w, low_h), depth=24)
        pixels = pygame.surfarray.pixels3d(surface)
        xx, yy = np.meshgrid(np.arange(low_w), np.arange(low_h), indexing="ij")
        void_wave = ((xx * 17 + yy * 29 + (xx // 9) * 7) % 23).astype(np.uint8)
        pixels[:, :, 0] = 12 + void_wave // 7
        pixels[:, :, 1] = 20 + void_wave // 4
        pixels[:, :, 2] = 28 + void_wave // 3

        base = self._quilt_material((0, 3), low_w, low_h, 11)
        leaves = self._quilt_material((1, 0), low_w, low_h, 29)
        roots = self._quilt_material((2, 4), low_w, low_h, 47)
        rock = self._quilt_material((5, 6), low_w, low_h, 71)
        cx, cy = w / 2, h / 2 + .15
        rx, ry = w / 2 - .75, h / 2 - .65
        tile_x, tile_y = (xx + .5) / art, (yy + .5) / art
        ellipse = ((tile_x - cx) / rx) ** 2 + ((tile_y - cy) / ry) ** 2
        breakup = (.018 * np.sin(xx * .071) + .014 * np.sin(yy * .097) +
                   .012 * np.sin((xx + yy) * .043))
        inside = ellipse <= 1.0 + breakup
        field = (np.sin(xx * .025 + 1.7) + np.sin(yy * .031 - .8) +
                 np.sin((xx - yy) * .018 + 2.4))
        root_mask = inside & ((ellipse > .69 + field * .035) |
                              ((field > 1.82) & (ellipse > .34)))
        leaf_mask = inside & ~root_mask & (field > .42) & (ellipse > .18)
        rock_field = np.sin(xx * .019 - 2.1) + np.sin(yy * .023 + .4)
        rock_mask = inside & (ellipse > .80) & (rock_field > .55)

        pixels[inside] = base[inside]
        pixels[leaf_mask] = leaves[leaf_mask]
        pixels[root_mask] = roots[root_mask]
        pixels[rock_mask] = rock[rock_mask]

        # A ragged real-texture path joins the portal and ritual steps without
        # producing square tile boundaries.
        path_top = (self.ritual_center[1] + 2.0) * art
        path_bottom = (self.portal_spawn[1] + .25) * art
        path_half = art * (.72 + .10 * np.sin(yy * .12))
        path = (inside & (yy >= path_top) & (yy <= path_bottom) &
                (np.abs(xx - cx * art) <= path_half))
        pixels[path] = rock[path]

        # Two hard pixel rings integrate the finite island with the dark void.
        eroded = inside.copy()
        for _ in range(3):
            eroded &= (np.roll(eroded, 1, 0) & np.roll(eroded, -1, 0) &
                       np.roll(eroded, 1, 1) & np.roll(eroded, -1, 1))
        rim = inside & ~eroded
        rim_color = rock[rim].astype(np.uint16)
        pixels[rim] = np.clip(rim_color * np.array((.56, .48, .44)), 0, 255).astype(np.uint8)
        del pixels

        surface = pygame.transform.scale(surface, (w * ts, h * ts))
        # The real ritual centerpiece is cached into the terrain layer so actors
        # and attack effects render naturally above it.
        pc = (round(self.ritual_center[0] * ts), round(self.ritual_center[1] * ts))
        platform = self.assets.props["ritual_platform"]
        surface.blit(platform, platform.get_rect(midtop=(pc[0], pc[1] - 153)))
        return surface

    def _camera_offset(self, surface: pygame.Surface, camera: Any) -> tuple[float, float]:
        if camera is None:
            world_w = self.config.arena_width * self.config.tile_size
            world_h = self.config.arena_height * self.config.tile_size
            return (world_w - surface.get_width()) / 2, (world_h - surface.get_height()) / 2
        if isinstance(camera, (tuple, list)) and len(camera) >= 2:
            return float(camera[0]), float(camera[1])
        if hasattr(camera, "x") and hasattr(camera, "y"):
            return float(camera.x), float(camera.y)
        raise TypeError("camera must be None, a (pixel_x, pixel_y) pair, or have x/y attributes")

    def _to_screen(self, x: float, y: float, camera: tuple[float, float]) -> tuple[int, int]:
        return round(x * self.config.tile_size - camera[0]), round(y * self.config.tile_size - camera[1])

    def render(self, surface: pygame.Surface, camera: Any = None,
               external_entity: Optional[tuple[float, Any]] = None,
               external_effects: Optional[Any] = None) -> None:
        """Draw into a host surface, optionally depth-sorting a host-owned player.

        The optional callbacks keep player movement, health and combat owned by the
        main game while allowing the arena's foreground gate to occlude the player
        correctly.  Existing two-argument integrations remain fully compatible.
        """
        self._render_scene(surface, camera, external_entity, external_effects)

    def _render_scene(self, surface: pygame.Surface, camera: Any = None,
                      external_entity: Optional[tuple[float, Any]] = None,
                      external_effects: Optional[Any] = None) -> None:
        """Internal layered renderer; the demo injects its real player here."""
        cam = self._camera_offset(surface, camera)
        shake_x = shake_y = 0
        if self.camera_shake > 0:
            magnitude = max(1, round(5 * self.camera_shake / .34))
            # Render-only deterministic shake; never alters world coordinates.
            tick = int(self.total_time * 60)
            shake_x = ((tick * 7) % (magnitude * 2 + 1)) - magnitude
            shake_y = ((tick * 11) % (magnitude * 2 + 1)) - magnitude
        draw_cam = (cam[0] - shake_x, cam[1] - shake_y)
        # The native macOS display surface can carry an alpha channel.  Make the
        # encounter framebuffer explicitly opaque before any alpha-blended art.
        # The mean of the arena's dithered void, so wide views show no seam.
        surface.fill((13, 25, 32, 255))
        surface.blit(self._arena_surface, (-round(draw_cam[0]), -round(draw_cam[1])))
        self._draw_arrival(surface, draw_cam)
        self._draw_telegraphs(surface, draw_cam)
        self._draw_depth_sorted_entities(surface, draw_cam, external_entity,
                                         external_effects)
        self._draw_particles(surface, draw_cam)
        # An effects-only integration has no entity depth to attach to. Keep that
        # uncommon private-call behavior, while the normal player adapter renders
        # its sprite and attack effects together at the player's foot depth.
        if external_effects is not None and external_entity is None:
            external_effects(surface, draw_cam)
        if self.started or self.state in (BossState.DYING, BossState.DEFEATED):
            self._draw_boss_bar(surface)
        if self.result != EncounterResult.IN_PROGRESS:
            self._draw_result_overlay(surface)
        if TREANT_RENDER_DEBUG:
            self._capture_render_debug_stages(
                surface, draw_cam, external_entity, external_effects
            )

    def _prop_entries(self) -> list[tuple[float, str, float, float]]:
        """Return render depth/name/anchor entries for arena decorations."""
        w, h = self.config.arena_width, self.config.arena_height
        # The gate sprite's foot is the bottom of its front stairs, but the arch
        # itself stands ~2.35 tiles further back.  Sorting by the arch keeps actors
        # on the stairs (including the arrival point) in front of the gate, while
        # actors walking north through it still pass behind the arch.
        gate_foot = self.portal_spawn[1] + .2
        return [
            (gate_foot - self.PORTAL_ARCH_DEPTH, "portal", self.portal_spawn[0], gate_foot),
            (4.1, "tree", 2.4, 4.1), (4.0, "tree_birch", w - 2.5, 4.0),
            (h - 4.0, "dead_tree", 2.6, h - 4.0),
            (h - 4.2, "tree", w - 2.5, h - 4.2),
            (2.7, "cliff", 4.4, 2.7), (3.2, "ruin", w - 4.2, 3.2),
            (8.7, "mushrooms", 3.7, 8.7), (8.8, "stump", w - 3.7, 8.8),
            (6.7, "root_hazard", 2.9, 6.7),
        ]

    def _draw_debug_props(self, surface: pygame.Surface,
                          cam: tuple[float, float], names: set[str]) -> None:
        for _, name, x, y in sorted(self._prop_entries()):
            if name not in names:
                continue
            sprite = self.assets.props[name]
            sx, sy = self._to_screen(x, y, cam)
            surface.blit(sprite, sprite.get_rect(midbottom=(sx, sy)))

    @staticmethod
    def _debug_surface_metrics(surface: pygame.Surface) -> dict[str, Any]:
        alpha = pygame.surfarray.array_alpha(surface)
        rgb = pygame.surfarray.array3d(surface)
        visible = alpha > 0
        opaque_dark = visible & (alpha >= 250) & (rgb.max(axis=2) <= 12)
        bounds = surface.get_bounding_rect(min_alpha=1)
        return {
            "size": list(surface.get_size()),
            "bounds": [bounds.x, bounds.y, bounds.width, bounds.height],
            "visible_pixels": int(np.count_nonzero(visible)),
            "transparent_pixels": int(np.count_nonzero(~visible)),
            "opaque_dark_pixels": int(np.count_nonzero(opaque_dark)),
        }

    def _capture_render_debug_stages(
        self, final_surface: pygame.Surface, cam: tuple[float, float],
        external_entity: Optional[tuple[float, Any]], external_effects: Optional[Any],
    ) -> None:
        """Save bounded, opt-in render stages from the real display pipeline."""
        frame_number = self._render_debug_frame
        self._render_debug_frame += 1
        # Eight samples cover several animation ticks without producing hundreds
        # of megabytes during an ordinary interactive diagnostic run.
        if frame_number % 4 or frame_number // 4 >= 8:
            return
        debug_dir = self.assets_dir / "validation" / "treant_render_stages"
        debug_dir.mkdir(parents=True, exist_ok=True)
        prefix = (f"{frame_number:03d}_{self.state.value.lower()}_"
                  f"{self.animation.name}_{self.animation.frame_index}")

        # Diagnostic screenshots are opaque scene images, not RGBA layers.  An
        # explicit RGB format also makes their PNGs display identically to the
        # actual window instead of exposing platform window-alpha metadata.
        terrain = pygame.Surface(final_surface.get_size(), depth=24)
        terrain.fill((12, 17, 25))
        terrain.blit(self._arena_surface, (-round(cam[0]), -round(cam[1])))
        portal = terrain.copy()
        self._draw_debug_props(portal, cam, {"portal"})
        decorations = portal.copy()
        self._draw_debug_props(
            decorations, cam,
            {name for _, name, _, _ in self._prop_entries() if name != "portal"},
        )

        player_layer = pygame.Surface(final_surface.get_size(), pygame.SRCALPHA)
        if external_entity is not None:
            external_entity[1](player_layer, cam)
        player = terrain.copy()
        player.blit(player_layer, (0, 0))

        boss_layer = pygame.Surface(final_surface.get_size(), pygame.SRCALPHA)
        self._draw_boss(boss_layer, cam)
        boss = terrain.copy()
        boss.blit(boss_layer, (0, 0))

        effects_layer = pygame.Surface(final_surface.get_size(), pygame.SRCALPHA)
        self._draw_telegraphs(effects_layer, cam)
        if self.state in (BossState.ARM_EXTEND, BossState.ARM_RECOVERY):
            self._draw_arm_extension(effects_layer, cam)
        if external_effects is not None:
            external_effects(effects_layer, cam)
        effects = terrain.copy()
        effects.blit(effects_layer, (0, 0))

        stages = {
            "01_terrain": terrain,
            "02_portal": portal,
            "03_decorations": decorations,
            "04_player": player,
            "05_boss": boss,
            "06_attack_effects": effects,
            "07_final": final_surface.copy(),
        }
        for stage_name, stage_surface in stages.items():
            pygame.image.save(stage_surface, debug_dir / f"{prefix}_{stage_name}.png")
        record = {
            "frame": frame_number,
            "state": self.state.value,
            "animation": self.animation.name,
            "animation_frame": self.animation.frame_index,
            "stages": {
                stage_name: self._debug_surface_metrics(stage_surface)
                for stage_name, stage_surface in stages.items()
            },
            "player_layer": self._debug_surface_metrics(player_layer),
            "boss_layer": self._debug_surface_metrics(boss_layer),
            "effects_layer": self._debug_surface_metrics(effects_layer),
        }
        self._render_debug_records.append(record)
        (debug_dir / "alpha_report.json").write_text(
            json.dumps(self._render_debug_records, indent=2), encoding="utf-8"
        )

    def _draw_depth_sorted_entities(self, surface: pygame.Surface,
                                    cam: tuple[float, float],
                                    external_entity: Optional[tuple[float, Any]],
                                    external_effects: Optional[Any] = None) -> None:
        # The entrance is one alpha-preserving sprite at its physical foot depth.
        # Drawing a complete back copy plus a rectangularly erased front copy
        # double-composited antialiased pixels and made occlusion depend on an
        # oversized crop. A single depth-sorted silhouette naturally appears in
        # front of actors behind the gate and behind actors who have passed it.
        entries: list[tuple[float, str, Any]] = [
            (depth, "prop", (name, x, y))
            for depth, name, x, y in self._prop_entries()
        ]
        entries.append((self.boss_y, "boss", None))
        if external_entity is not None:
            entries.append((float(external_entity[0]), "external", external_entity[1]))
        for _, kind, value in sorted(entries, key=lambda entry: entry[0]):
            if kind == "boss":
                self._draw_boss(surface, cam)
            elif kind == "external":
                value(surface, cam)
                if external_effects is not None:
                    external_effects(surface, cam)
            else:
                name, x, y = value
                sprite = self.assets.props[name]
                sx, sy = self._to_screen(x, y, cam)
                if (-sprite.get_width() < sx < surface.get_width() + sprite.get_width()
                        and -sprite.get_height() < sy < surface.get_height() + sprite.get_height()):
                    surface.blit(sprite, sprite.get_rect(midbottom=(sx, sy)))

    def _draw_arrival(self, surface: pygame.Surface, cam: tuple[float, float]) -> None:
        if self.arrival_time > 1.3: return
        x, y = self._to_screen(*self.portal_spawn, cam)
        p = self.arrival_time / 1.3
        radius = round(9 + p * 35)
        alpha = round(210 * (1 - p))
        glow = pygame.Surface((radius * 2 + 8, radius + 12), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (255, 153, 38, alpha), glow.get_rect(), max(2, radius // 7))
        surface.blit(glow, glow.get_rect(center=(x, y - 5)))

    def _draw_telegraphs(self, surface: pygame.Surface, cam: tuple[float, float]) -> None:
        ts = self.config.tile_size
        if self.state == BossState.ARM_WINDUP:
            origin = self._arm_origin()
            start = self._to_screen(origin.x, origin.y, cam)
            end = (round(start[0] + self._locked_direction.x * self.config.arm_range * ts),
                   round(start[1] + self._locked_direction.y * self.config.arm_range * ts))
            warning = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            pulse = 105 + round(55 * math.sin(self.total_time * 12))
            pygame.draw.line(warning, (255, 115, 35, pulse), start, end,
                             max(3, round(self.config.arm_width * ts)), )
            pygame.draw.line(warning, (255, 220, 90, 210), start, end, 2)
            surface.blit(warning, (0, 0))
        if self.state in (BossState.JUMP_WINDUP, BossState.JUMP_ASCEND, BossState.JUMP_DESCEND):
            center = self._to_screen(*self._jump_center, cam)
            rx = round(self.config.earthquake_radius * ts)
            ry = max(12, round(rx * .52))
            box = pygame.Rect(center[0] - rx, center[1] - ry, rx * 2, ry * 2)
            color = (255, 107, 34) if int(self.total_time * 8) % 2 else (255, 193, 65)
            pygame.draw.ellipse(surface, color, box, 4)
        if self.state == BossState.EARTHQUAKE:
            center = self._to_screen(*self._jump_center, cam)
            radius = round(self.config.earthquake_radius * ts * self.shockwave_progress)
            ellipse = pygame.Rect(center[0] - radius, center[1] - radius // 2,
                                  radius * 2, max(2, radius))
            pygame.draw.ellipse(surface, (255, 170, 50), ellipse, 7)
            pygame.draw.ellipse(surface, (97, 47, 29), ellipse.inflate(-14, -7), 3)
        if self.state in (BossState.EARTHQUAKE, BossState.EARTHQUAKE_RECOVERY):
            center = pygame.Vector2(self._to_screen(*self._jump_center, cam))
            # Eight deterministic cracks keep the impact readable without touching
            # simulation RNG or creating additional full-size effect surfaces.
            for index in range(8):
                angle = index * math.tau / 8 + .17
                direction = pygame.Vector2(math.cos(angle), math.sin(angle) * .52)
                side = pygame.Vector2(-direction.y, direction.x)
                start = center + direction * (24 + index % 2 * 7)
                bend = start + direction * (28 + index % 3 * 6) + side * (5 if index % 2 else -5)
                end = center + direction * (79 + index % 3 * 11)
                pygame.draw.line(surface, (62, 31, 25), start, bend, 4)
                pygame.draw.line(surface, (104, 48, 25), bend, end, 3)

    def _state_animation_frame(self) -> pygame.Surface:
        def timed(name: str, start: int, end: int, duration: float) -> pygame.Surface:
            frames = self.assets.animations[name]
            progress = min(1.0, self.state_time / max(.001, duration))
            index = start + min(end - start, int(progress * (end - start + 1)))
            return frames[index]

        if self.state == BossState.ARM_WINDUP:
            return timed("arm", 0, 2, .72)
        if self.state == BossState.ARM_EXTEND:
            return timed("arm", 3, 8, .38)
        if self.state == BossState.ARM_RECOVERY:
            # Frame 11 is the separate root-contact burst, not a boss pose.
            frames = self.assets.animations["arm"]
            progress = min(1.0, self.state_time / .55)
            return frames[9 if progress < .34 else 10 if progress < .68 else 0]
        if self.state == BossState.JUMP_WINDUP:
            return timed("jump", 0, 1, .82)
        if self.state == BossState.JUMP_ASCEND:
            return timed("jump", 2, 4, .48)
        if self.state == BossState.JUMP_DESCEND:
            return timed("jump", 5, 7, .40)
        if self.state == BossState.EARTHQUAKE:
            return timed("impact", 0, 7, .52)
        if self.state == BossState.HURT:
            return timed("hurt", 0, 3, .16)
        return self.animation.frame

    def _draw_arm_extension(self, surface: pygame.Surface, cam: tuple[float, float]) -> None:
        extension = self._arm_extension_fraction()
        if extension <= .01:
            return
        origin = self._arm_origin()
        start = pygame.Vector2(self._to_screen(origin.x, origin.y, cam))
        length = self.config.arm_range * self.config.tile_size * extension
        end = start + self._locked_direction * length
        angle = math.atan2(self._locked_direction.y, self._locked_direction.x)
        sector = int(round(angle / (math.pi / 8))) % 16
        cached = self.assets.arm_direction_cache.get(sector)
        if cached is None:
            degrees = -sector * 22.5
            seg_rot = pygame.transform.rotate(self.assets.arm_segment, degrees)
            claw_rot = pygame.transform.rotate(self.assets.arm_claw, degrees)
            for surf in (seg_rot, claw_rot):
                a = pygame.surfarray.pixels_alpha(surf)
                rgb = pygame.surfarray.pixels3d(surf)
                rgb[a == 0] = [0, 0, 0]
                del a, rgb
            cached = (seg_rot, claw_rot)
            self.assets.arm_direction_cache[sector] = cached
        segment, claw = cached
        # Overlap real wood pieces so their transparent tapered ends form one
        # organic branch instead of a geometric line or stretched rectangle.
        spacing = 22
        for distance in range(16, max(17, round(length) - 12), spacing):
            point = start + self._locked_direction * min(distance, length - 8)
            surface.blit(segment, segment.get_rect(center=(round(point.x), round(point.y))))
        surface.blit(claw, claw.get_rect(center=(round(end.x), round(end.y))))
        if (self.state == BossState.ARM_EXTEND
                and .17 <= self.state_time <= .29):
            impact = self.assets.animations["arm"][11]
            surface.blit(impact, impact.get_rect(midbottom=(round(end.x), round(end.y + 20))))

    def _draw_boss(self, surface: pygame.Surface, cam: tuple[float, float]) -> None:
        bx, by = self._to_screen(self.boss_x, self.boss_y, cam)
        jump_px = round(self.visual_jump_height * self.config.tile_size)
        shadow_scale = max(.45, 1 - self.visual_jump_height * .18)
        shadow = pygame.transform.scale(self.assets.shadow,
                                        (max(1, round(self.assets.shadow.get_width() * shadow_scale)),
                                         max(1, round(self.assets.shadow.get_height() * shadow_scale))))
        surface.blit(shadow, shadow.get_rect(center=(bx, by - 5)))
        arm_in_front = (self._locked_direction.y >= -0.25)
        if not arm_in_front:
            self._draw_arm_extension(surface, cam)
        frame = self._state_animation_frame()
        # ARM EXTEND is authored toward screen-right; mirror only for leftward use.
        # Other upright states retain the original walking orientation rule.
        arm_state = self.state in (BossState.ARM_WINDUP, BossState.ARM_EXTEND,
                                   BossState.ARM_RECOVERY)
        if ((arm_state and self._locked_direction.x < -.12)
                or (not arm_state and self._locked_direction.x > .12)):
            frame = pygame.transform.flip(frame, True, False)
        if self.state == BossState.HURT and int(self.state_time * 45) % 2 == 0:
            flash = frame.copy()
            mask = pygame.mask.from_surface(flash)
            flash.blit(mask.to_surface(setcolor=(255, 96, 54, 185), unsetcolor=(0, 0, 0, 0)), (0, 0))
            frame = flash
        surface.blit(frame, frame.get_rect(midbottom=(bx, by - jump_px)))
        if arm_in_front:
            self._draw_arm_extension(surface, cam)
        if self.config.debug_hitboxes:
            rect = self.boss_hitbox
            sx, sy = self._to_screen(rect.x, rect.y, cam)
            pygame.draw.rect(surface, (70, 255, 130), (sx, sy, round(rect.width * self.config.tile_size), round(rect.height * self.config.tile_size)), 1)

    def _draw_particles(self, surface: pygame.Surface, cam: tuple[float, float]) -> None:
        for p in self.particles:
            x, y = self._to_screen(p.x, p.y, cam)
            alpha = max(0, min(255, round(255 * p.life / p.max_life)))
            size = 5 if p.kind in ("leaf", "debris") else 3
            dot = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            if p.kind == "leaf":
                pygame.draw.polygon(dot, (*p.color, alpha), [(0, size), (size, 0), (size * 2 - 1, size), (size, size * 2 - 1)])
            else:
                pygame.draw.circle(dot, (*p.color, alpha), (size, size), size)
            surface.blit(dot, (x - size, y - size))

    def _draw_boss_bar(self, surface: pygame.Surface) -> None:
        width = min(620, surface.get_width() - 80)
        x, y = (surface.get_width() - width) // 2, 42
        font = pygame.font.Font(None, 25)
        small = pygame.font.Font(None, 18)
        title = font.render(BOSS_NAME_UPPER, True, (255, 220, 139))
        surface.blit(title, title.get_rect(center=(surface.get_width() // 2, y - 17)))
        outer = pygame.Rect(x - 5, y - 5, width + 10, 30)
        pygame.draw.rect(surface, (42, 20, 18), outer)
        pygame.draw.rect(surface, (154, 92, 43), outer, 3)
        inner = pygame.Rect(x, y, width, 20)
        pygame.draw.rect(surface, (30, 16, 20), inner)
        fill = inner.copy(); fill.width = round(width * self.health / self.config.max_health)
        pygame.draw.rect(surface, (201, 67, 30) if self.phase == 2 else (221, 105, 30), fill)
        for stripe in range(fill.left + 8, fill.right, 14):
            pygame.draw.line(surface, (239, 133, 43), (stripe, fill.top + 3), (stripe - 5, fill.bottom - 3), 2)
        divider = inner.left + width // 2
        pygame.draw.line(surface, (255, 232, 166), (divider, outer.top - 3), (divider, outer.bottom + 3), 3)
        phase = small.render(tr("boss.phase", phase=self.phase), False, (255, 231, 175))
        surface.blit(phase, (outer.right + 9, outer.centery - phase.get_height() // 2))

    def _draw_result_overlay(self, surface: pygame.Surface) -> None:
        from .game_ui import pixel_overlay, pixel_window
        pixel_overlay(surface, (14, 8, 12), 145)
        font = pygame.font.Font(None, 48)
        small = pygame.font.Font(None, 26)
        victory = self.result == EncounterResult.VICTORY
        text = tr("boss.victory") if victory else tr("boss.defeat")
        color = (255, 191, 74) if victory else (240, 91, 72)
        hint_text = tr("boss.returning") if victory else self.defeat_hint
        rendered = font.render(text, False, color)
        hint = small.render(hint_text, False, (245, 225, 196))
        width = max(rendered.get_width(), hint.get_width()) + 80
        panel = pygame.Rect(0, 0, width, 124)
        panel.center = (surface.get_width() // 2, surface.get_height() // 2)
        pixel_window(surface, panel, accent=(237, 177, 62) if victory else (196, 82, 60))
        surface.blit(rendered, rendered.get_rect(center=(panel.centerx, panel.y + 46)))
        surface.blit(hint, hint.get_rect(center=(panel.centerx, panel.y + 90)))


class _DemoGameVisuals:
    """Lazy adapter to current side-effect-safe game visual systems.

    None of these imports occur when the reusable boss module is imported. The
    standalone demo gets the exact current character, combat, dash, and HUD art;
    integrated hosts remain free to render their own future player implementation.
    """

    def __init__(self, assets_dir: Path) -> None:
        from .character_animation import CharacterAnimator, load_character_sheet
        from .game_ui import PixelHUD
        from .gameplay_systems import CombatSystem
        # main.py has a guarded application entry point. Importing these pure draw
        # functions does not initialize Pygame, generate a world, or open a window.
        from main import draw_dash_effects, draw_player, draw_sword_attack

        cached_sheet = load_character_sheet(assets_dir)
        if cached_sheet is None:
            raise FileNotFoundError(
                f"Standalone Treant demo requires the main-game manchar character asset in {assets_dir}"
            )
        # Never mutate the lru-cached main-game sheet, and never rebuild its alpha
        # from JPEG paper colors. The previous post-processor flood-filled each raw
        # crop and then changed enclosed alpha-zero pixels back to 255; those pixels
        # already had RGB (0, 0, 0), so particular moving poses acquired opaque dark
        # blocks. The canonical CharacterSheet alpha is the source of truth.
        self.sheet = copy.copy(cached_sheet)
        self.sheet.frames = {
            direction: [self._sanitized_frame(frame) for frame in frames]
            for direction, frames in cached_sheet.frames.items()
        }
        self.sheet.shadow = cached_sheet.shadow.copy()
        self.animator = CharacterAnimator()
        self.combat = CombatSystem()
        self.hud = PixelHUD()
        self.draw_player_function = draw_player
        self.draw_sword_function = draw_sword_attack
        self.draw_dash_function = draw_dash_effects

    @staticmethod
    def _sanitized_frame(frame: pygame.Surface) -> pygame.Surface:
        """Copy one canonical player frame without changing its alpha mask."""
        result = frame.copy()
        alpha = pygame.surfarray.pixels_alpha(result)
        rgb = pygame.surfarray.pixels3d(result)
        rgb[alpha == 0] = [0, 0, 0]
        del alpha, rgb
        return result

    def reset_combat(self) -> None:
        from .gameplay_systems import CombatSystem
        self.combat = CombatSystem()


class _DemoPlayer:
    """Demo adapter around the real main-game character/combat renderers."""

    def __init__(self, spawn: tuple[float, float], visuals: _DemoGameVisuals) -> None:
        self.visuals = visuals
        self.visuals.reset_combat()
        self.pos = pygame.Vector2(spawn)
        self.facing = pygame.Vector2(0, -1)
        self.facing_name = "up"
        self.moving = False
        self.health = self.max_health = 8.0
        self.invulnerable = 0.0
        self.hit_flash = 0.0
        self.knockback = pygame.Vector2()
        self.attack_serial = 0
        self.attack_registered = False
        self.dash_timer = 0.0
        self.dash_cooldown = 0.0
        self.dash_direction = pygame.Vector2()
        self.dash_effect_timer = 0.0
        self.dash_effects: list[dict[str, float]] = []

    @property
    def combat(self) -> Any:
        return self.visuals.combat

    def snapshot(self) -> BossPlayerState:
        return BossPlayerState("demo-player", self.pos.x, self.pos.y, .36, .72,
                               self.health, self.max_health, tuple(self.facing), self.invulnerable > 0)

    def begin_attack(self) -> None:
        if self.combat.start_attack("normal"):
            self.attack_serial += 1
            self.attack_registered = False

    def begin_dash(self, direction: pygame.Vector2) -> None:
        if self.dash_timer <= 0 and self.dash_cooldown <= 0:
            if direction.length_squared() < .01:
                direction = self.facing.copy()
            self.dash_direction = direction.normalize()
            self.dash_timer = .24
            self.dash_cooldown = 3.0
            self.invulnerable = max(self.invulnerable, .30)
            angle = math.atan2(self.dash_direction.y, self.dash_direction.x)
            for index in range(3):
                life = .34 + index * .035
                self.dash_effects.append({"x": self.pos.x, "y": self.pos.y,
                                          "angle": angle, "life": life,
                                          "max_life": life})

    @staticmethod
    def _facing_name(direction: pygame.Vector2, previous: str) -> str:
        if direction.length_squared() <= .001:
            return previous
        if abs(direction.x) > abs(direction.y):
            return "right" if direction.x > 0 else "left"
        return "down" if direction.y > 0 else "up"

    def update(self, dt: float, encounter: TreantBossEncounter) -> None:
        self.invulnerable = max(0.0, self.invulnerable - dt)
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.dash_cooldown = max(0.0, self.dash_cooldown - dt)
        for effect in self.dash_effects:
            effect["life"] -= dt
        self.dash_effects[:] = [effect for effect in self.dash_effects if effect["life"] > 0]

        keys = pygame.key.get_pressed()
        input_direction = pygame.Vector2(
            int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT]),
            int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]),
        )
        if input_direction.length_squared() > 0:
            input_direction.normalize_ip()
            self.facing = input_direction.copy()
            self.facing_name = self._facing_name(input_direction, self.facing_name)
        self.moving = input_direction.length_squared() > 0
        movement = input_direction * 4.5
        if self.dash_timer > 0:
            self.dash_timer = max(0.0, self.dash_timer - dt)
            movement = self.dash_direction * 15.5
            self.moving = True
            self.facing = self.dash_direction.copy()
            self.facing_name = self._facing_name(self.dash_direction, self.facing_name)
            self.dash_effect_timer -= dt
            while self.dash_effect_timer <= 0 and len(self.dash_effects) < 36:
                self.dash_effect_timer += .025
                self.dash_effects.append({
                    "x": self.pos.x, "y": self.pos.y,
                    "angle": math.atan2(self.dash_direction.y, self.dash_direction.x),
                    "life": .32, "max_life": .32,
                })

        movement += self.knockback
        desired = self.pos + movement * dt
        self.pos.update(encounter.constrain_motion(tuple(self.pos), tuple(desired)))
        self.knockback *= max(0.0, 1 - 9 * dt)
        self.visuals.animator.update(dt, self.moving, self.facing_name, 4.5)

        was_attacking = self.combat.attacking
        old_timer = self.combat.timer
        self.combat.update(dt, self.pos, self.facing_name, [], lambda _monster: None)
        if self.combat.attacking and (not was_attacking or self.combat.timer < old_timer):
            self.attack_serial += 1
            self.attack_registered = False

    def attack(self) -> Optional[PlayerAttack]:
        if not self.combat.attacking or self.attack_registered:
            return None
        profile = self.combat.attack_profile()
        if not (profile["active"][0] <= self.combat.timer <= profile["active"][1]):
            return None
        self.attack_registered = True
        x, y, width, height = self.combat.hitbox(self.pos, self.facing_name)
        return PlayerAttack(f"demo:{self.attack_serial}", "demo-player",
                            x, y, width, height, 8)

    def apply_hit(self, data: Mapping[str, Any]) -> None:
        if self.invulnerable > 0:
            return
        self.health = max(0.0, self.health - float(data["damage"]))
        self.invulnerable = float(data.get("invulnerability", .7))
        self.hit_flash = .16
        self.knockback.update(data.get("knockback", (0, 0)))

    def draw_sprite(self, surface: pygame.Surface, encounter: TreantBossEncounter,
                    cam: tuple[float, float]) -> None:
        ts = encounter.config.tile_size
        position = (round(self.pos.x * ts - cam[0]), round(self.pos.y * ts - cam[1]))
        self.visuals.draw_player_function(
            surface, position, self.moving, self.facing_name,
            character_sheet=self.visuals.sheet, animation=self.visuals.animator,
            hit_flash=self.hit_flash,
        )

    def draw_effects(self, surface: pygame.Surface, encounter: TreantBossEncounter,
                     cam: tuple[float, float]) -> None:
        ts = encounter.config.tile_size
        position = (round(self.pos.x * ts - cam[0]), round(self.pos.y * ts - cam[1]))
        self.visuals.draw_sword_function(surface, position, self.facing_name, self.combat)
        self.visuals.draw_dash_function(surface, self.dash_effects, cam[0], cam[1])


def run_demo() -> None:
    """Run the one-file test harness. All pygame lifecycle ownership stays here."""
    pygame.init()
    screen = pygame.display.set_mode((1200, 780))
    pygame.display.set_caption(f"{BOSS_NAME} - Boss Encounter Demo")
    clock = pygame.time.Clock()
    assets_dir = PROJECT_ROOT
    visuals = _DemoGameVisuals(assets_dir)
    encounter = TreantBossEncounter(assets_dir)
    player = _DemoPlayer(encounter.portal_spawn, visuals)
    encounter.start(player.snapshot())
    font = pygame.font.Font(None, 23)
    running = True
    while running:
        dt = min(.05, clock.tick(60) / 1000.0)
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                elif event.key in (pygame.K_SPACE, pygame.K_j): player.begin_attack()
                elif event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                    keys = pygame.key.get_pressed()
                    direction = pygame.Vector2(int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT]),
                                               int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]))
                    player.begin_dash(direction)
                elif event.key == pygame.K_r and encounter.get_result() != EncounterResult.IN_PROGRESS:
                    encounter = TreantBossEncounter(assets_dir)
                    player = _DemoPlayer(encounter.portal_spawn, visuals)
                    encounter.start(player.snapshot())
            encounter.handle_event(event)
        if encounter.get_result() == EncounterResult.IN_PROGRESS:
            player.update(dt, encounter)
            attack = player.attack()
            if attack: encounter.register_player_attack(attack)
            encounter.update(dt, player.snapshot())
            for emitted in encounter.consume_events():
                if emitted.type == PLAYER_HIT: player.apply_hit(emitted.data)
        else:
            encounter.update(dt, player.snapshot())
            encounter.consume_events()
        world_w, world_h = encounter.config.arena_width * encounter.config.tile_size, encounter.config.arena_height * encounter.config.tile_size
        target_cam = pygame.Vector2(player.pos.x * encounter.config.tile_size - screen.get_width() / 2,
                                    player.pos.y * encounter.config.tile_size - screen.get_height() / 2)
        cam = (((world_w - screen.get_width()) / 2 if world_w <= screen.get_width()
                else max(0, min(world_w - screen.get_width(), target_cam.x))),
               ((world_h - screen.get_height()) / 2 if world_h <= screen.get_height()
                else max(0, min(world_h - screen.get_height(), target_cam.y))))
        encounter._render_scene(
            screen, cam,
            (player.pos.y, lambda target, draw_cam: player.draw_sprite(target, encounter, draw_cam)),
            lambda target, draw_cam: player.draw_effects(target, encounter, draw_cam),
        )
        # Exact current five-heart pixel HUD from game_ui.py.
        visuals.hud.draw_health(screen, player.health, player.max_health, (14, 60))
        hint = tr("boss.demo_controls")
        screen.blit(font.render(hint, True, (244, 222, 183)), (22, screen.get_height() - 30))
        if encounter.assets.missing_assets:
            note = tr("boss.demo_missing", assets=", ".join(encounter.assets.missing_assets))
            screen.blit(font.render(note, True, (255, 157, 80)), (22, 82))
        pygame.display.flip()
    pygame.quit()


# Integration summary:
#   encounter = TreantBossEncounter(asset_directory, TreantConfig())
#   spawn = encounter.start(BossPlayerState(...))
#   encounter.update(dt_seconds, player_snapshot_or_list)
#   encounter.register_player_attack(PlayerAttack(...))
#   for event in encounter.consume_events(): apply/replicate validated outcomes
#   encounter.render(existing_display, (camera_pixel_x, camera_pixel_y))
# Full host and future authoritative-network guidance is in TREANT_INTEGRATION.md.


if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        pygame.quit()
        print("\n[PLATANUS DEMO] Stopped.")
