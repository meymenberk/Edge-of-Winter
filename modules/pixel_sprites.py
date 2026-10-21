"""Pixel sprites used by world entities, villagers, and item drops.

Enemies and items are drawn on low-resolution transparent canvases. Villagers
are extracted once from the supplied illustrated atlas and normalized onto a
shared foot-anchored canvas. All resizing uses nearest-neighbour scaling.
"""
from collections import deque
from functools import lru_cache

import numpy as np
import pygame

from .paths import VILLAGER_ATLAS_ASSET, require_asset


OUTLINE = (43, 31, 29)
SKIN = (218, 166, 119)


def _canvas(size=(24, 28)):
    return pygame.Surface(size, pygame.SRCALPHA)


def _rect(surface, color, rect):
    pygame.draw.rect(surface, color, rect)


def _tint_red(surface):
    tinted = surface.copy()
    red = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    red.fill((255, 62, 52, 0))
    red.set_alpha(150)
    mask = pygame.mask.from_surface(tinted)
    overlay = mask.to_surface(setcolor=(255, 58, 48, 185), unsetcolor=(0, 0, 0, 0))
    tinted.blit(overlay, (0, 0))
    return tinted


def _finish(surface, flash=False, scale=2):
    if flash:
        surface = _tint_red(surface)
    return pygame.transform.scale(surface, (surface.get_width() * scale,
                                            surface.get_height() * scale))


def _humanoid(kind, facing, frame):
    s = _canvas()
    step = frame % 2
    palettes = {
        "pirate": ((118, 38, 38), (181, 57, 44), (31, 28, 31)),
        "bandit": ((91, 62, 43), (135, 86, 49), (66, 43, 32)),
        "thief": ((52, 55, 70), (82, 78, 93), (30, 30, 40)),
    }
    body, light, hood = palettes.get(kind, palettes["bandit"])
    # Grounded boots and separated legs read at the player's scale.
    _rect(s, OUTLINE, (7, 21, 4, 5)); _rect(s, OUTLINE, (14, 21, 4, 5))
    _rect(s, (49, 38, 34), (6 - step, 25, 6, 2)); _rect(s, (49, 38, 34), (14 + step, 25, 6, 2))
    _rect(s, OUTLINE, (5, 10, 15, 13)); _rect(s, body, (6, 11, 13, 11))
    _rect(s, light, (7, 12, 3, 8)); _rect(s, OUTLINE, (11, 11, 2, 11))
    _rect(s, OUTLINE, (3, 12 + step, 4, 9)); _rect(s, body, (4, 13 + step, 2, 7))
    _rect(s, OUTLINE, (18, 12 - step, 4, 9)); _rect(s, body, (19, 13 - step, 2, 7))
    _rect(s, OUTLINE, (7, 3, 11, 9)); _rect(s, SKIN, (8, 4, 9, 7))
    if facing == "up":
        _rect(s, hood, (8, 4, 9, 7))
    else:
        eye_x = 9 if facing != "right" else 15
        if facing == "down":
            _rect(s, OUTLINE, (9, 7, 2, 1)); _rect(s, OUTLINE, (14, 7, 2, 1))
        else:
            _rect(s, OUTLINE, (eye_x, 7, 2, 1))
    if kind == "pirate":
        pygame.draw.polygon(s, OUTLINE, [(5, 5), (20, 5), (17, 1), (12, 3), (8, 1)])
        _rect(s, (188, 154, 71), (7, 5, 11, 1)); _rect(s, (226, 222, 199), (11, 12, 3, 8))
    elif kind == "bandit":
        pygame.draw.polygon(s, hood, [(6, 5), (9, 1), (17, 2), (20, 6), (17, 11), (7, 11)])
        _rect(s, (152, 115, 63), (7, 15, 11, 2))
    else:
        pygame.draw.polygon(s, hood, [(6, 5), (10, 1), (17, 3), (20, 7), (17, 11), (7, 11)])
        _rect(s, (105, 91, 112), (8, 8, 9, 2))
    return s


def _quadruped(kind, facing, frame):
    s = _canvas((30, 22))
    flip = facing == "left"
    if kind == "wolf":
        fur, light, dark = (91, 96, 103), (139, 139, 132), (54, 57, 62)
    elif kind == "boar":
        fur, light, dark = (111, 70, 48), (151, 98, 59), (60, 43, 34)
    elif kind == "sheep":
        fur, light, dark = (218, 210, 184), (245, 237, 211), (73, 58, 48)
    else:  # cow
        fur, light, dark = (225, 211, 181), (248, 232, 198), (78, 52, 39)
    # Tail, body, legs and head use chunky 1px/2px clusters.
    pygame.draw.polygon(s, OUTLINE, [(4, 8), (0, 5), (1, 11), (5, 13)])
    pygame.draw.polygon(s, fur, [(5, 7), (2, 6), (3, 10), (6, 11)])
    _rect(s, OUTLINE, (5, 5, 18, 12)); _rect(s, fur, (6, 6, 16, 10))
    if kind == "sheep":
        for x, y in ((7, 6), (11, 5), (15, 6), (19, 5), (8, 10), (13, 9), (18, 11)):
            pygame.draw.circle(s, light, (x, y), 3)
    elif kind == "cow":
        _rect(s, dark, (8, 6, 5, 5)); _rect(s, dark, (17, 10, 5, 5)); _rect(s, light, (13, 6, 4, 4))
    else:
        _rect(s, light, (7, 6, 10, 3)); _rect(s, dark, (7, 14, 14, 2))
    leg_shift = frame % 2
    for x, shift in ((7, leg_shift), (12, 1 - leg_shift), (18, leg_shift), (22, 1 - leg_shift)):
        _rect(s, OUTLINE, (x, 15, 3, 6)); _rect(s, dark, (x + shift, 17, 2, 4))
    _rect(s, OUTLINE, (21, 6, 8, 10)); _rect(s, dark if kind == "sheep" else fur, (22, 7, 6, 8))
    if kind == "wolf":
        pygame.draw.polygon(s, OUTLINE, [(21, 7), (22, 1), (25, 6), (27, 1), (29, 8)])
        pygame.draw.polygon(s, dark, [(22, 6), (23, 3), (25, 7), (27, 3), (28, 8)])
        _rect(s, light, (24, 9, 4, 2)); _rect(s, (226, 174, 55), (26, 8, 1, 1))
    elif kind == "boar":
        pygame.draw.polygon(s, dark, [(21, 7), (23, 2), (25, 7)])
        _rect(s, light, (26, 12, 4, 2)); _rect(s, (232, 217, 171), (28, 13, 2, 2))
    elif kind == "sheep":
        _rect(s, OUTLINE, (23, 4, 2, 4)); _rect(s, OUTLINE, (27, 5, 2, 4)); _rect(s, (214, 173, 91), (27, 10, 1, 1))
    else:
        _rect(s, (238, 214, 151), (22, 4, 2, 4)); _rect(s, (238, 214, 151), (27, 4, 2, 4))
        _rect(s, light, (25, 12, 4, 3)); _rect(s, OUTLINE, (27, 9, 1, 1))
    return pygame.transform.flip(s, True, False) if flip else s


@lru_cache(maxsize=8)
def wizard_sprite(frame=0):
    """The Wandering Sage: indigo robe, pointed hat, white beard, crystal staff."""
    s = _canvas((26, 34))
    sway = frame % 2
    robe, light, dark = (58, 46, 122), (92, 78, 172), (34, 27, 76)
    trim, beard = (214, 176, 84), (232, 228, 214)
    # Wooden staff with a glowing crystal (brightness pulses between frames).
    _rect(s, OUTLINE, (20, 5, 3, 28)); _rect(s, (128, 86, 48), (21, 6, 1, 26))
    crystal = (176, 244, 255) if sway else (120, 214, 255)
    pygame.draw.polygon(s, OUTLINE, [(21, 0), (24, 3), (21, 7), (18, 3)])
    pygame.draw.polygon(s, crystal, [(21, 1), (23, 3), (21, 6), (19, 3)])
    _rect(s, (245, 255, 255), (20, 2, 1, 1))
    # Robe flaring toward a hem that sways one pixel.
    pygame.draw.polygon(s, OUTLINE, [(7, 14), (17, 14), (20 + sway, 33), (3 - sway, 33)])
    pygame.draw.polygon(s, robe, [(8, 15), (16, 15), (19 + sway, 32), (4 - sway, 32)])
    pygame.draw.polygon(s, light, [(9, 16), (11, 16), (8, 31), (5 - sway, 31)])
    pygame.draw.polygon(s, dark, [(14, 18), (16, 16), (18 + sway, 31), (14, 31)])
    _rect(s, trim, (4 - sway, 31, 16 + 2 * sway, 1)); _rect(s, trim, (11, 17, 2, 13))
    # Sleeve reaching to the staff, with a hand gripping it.
    _rect(s, OUTLINE, (14, 16, 7, 5)); _rect(s, light, (15, 17, 5, 3))
    _rect(s, SKIN, (20, 17, 2, 3))
    # Face and long beard under the hat brim.
    _rect(s, OUTLINE, (7, 9, 10, 7)); _rect(s, SKIN, (8, 10, 8, 4))
    _rect(s, OUTLINE, (9, 11, 2, 1)); _rect(s, OUTLINE, (13, 11, 2, 1))
    pygame.draw.polygon(s, beard, [(8, 13), (16, 13), (14, 21), (12, 23), (10, 21)])
    pygame.draw.polygon(s, (196, 192, 182), [(12, 15), (14, 15), (12, 22)])
    # Pointed hat with a drooping tip, gold band and wide brim.
    pygame.draw.polygon(s, OUTLINE, [(4, 10), (20, 10), (14, 3), (11, 0), (6, 1), (10, 3)])
    pygame.draw.polygon(s, robe, [(6, 9), (18, 9), (13, 3), (11, 1), (8, 2), (11, 4)])
    _rect(s, trim, (7, 8, 10, 1)); _rect(s, (255, 236, 150), (13, 5, 1, 1))
    _rect(s, OUTLINE, (3, 9, 18, 2)); _rect(s, dark, (4, 9, 16, 1))
    return _finish(s)


@lru_cache(maxsize=128)
def entity_sprite(kind, facing="right", frame=0, flash=False):
    if kind in ("wolf", "boar", "sheep", "cow"):
        return _finish(_quadruped(kind, facing, frame), flash)
    return _finish(_humanoid(kind, facing, frame), flash)


VILLAGER_DIRECTIONS = ("down", "up", "left", "right")
VILLAGER_ROLES = ("fisherman", "farmer", "miner", "elder")

# The source is an illustrated layout, not a regular grid. These inspected
# cells contain only character art; headings, direction labels, and the player
# section above y=420 are deliberately excluded.
_VILLAGER_IDLE_CELLS = {
    "fisherman": ((20, 465, 88, 125), (106, 465, 84, 125),
                   (188, 465, 79, 125), (265, 465, 82, 125)),
    "farmer": ((388, 465, 86, 125), (472, 465, 83, 125),
               (554, 465, 79, 125), (632, 465, 85, 125)),
    "miner": ((754, 465, 72, 125), (836, 465, 72, 125),
              (915, 465, 71, 125), (992, 465, 73, 125)),
    "elder": ((1105, 465, 91, 125), (1195, 465, 83, 125),
              (1277, 465, 80, 125), (1356, 465, 87, 125)),
}

_WALK_COLUMNS = {
    "fisherman": ((85, 66), (151, 65), (216, 64), (280, 65)),
    "farmer": ((450, 68), (518, 65), (583, 65), (648, 67)),
    "miner": ((809, 64), (873, 65), (938, 65), (1003, 65)),
    "elder": ((1166, 72), (1238, 66), (1304, 67), (1371, 73)),
}
_WALK_ROWS = ((645, 78), (718, 75), (789, 75), (862, 74))

_VILLAGER_PROP_CELLS = {
    "fisherman": ((18, 965, 100, 121), (118, 965, 80, 121),
                   (198, 965, 81, 121), (279, 965, 80, 121)),
    "farmer": ((370, 965, 94, 121), (464, 965, 90, 121),
               (554, 965, 85, 121), (639, 965, 91, 121)),
    "miner": ((734, 965, 100, 121), (834, 965, 89, 121),
              (923, 965, 86, 121), (1009, 965, 76, 121)),
    "elder": ((1100, 965, 88, 121), (1188, 965, 82, 121),
              (1270, 965, 86, 121), (1356, 965, 90, 121)),
}


def _rect_cell(cell):
    return pygame.Rect(*cell)


class VillagerAtlas:
    """Cached extraction and normalization of the four villager professions."""

    SIZE = (80, 60)
    ANCHOR = (40, 58)
    TARGET_HEIGHT = {"idle": 56, "walk": 55, "props": 56}

    def __init__(self, path=VILLAGER_ATLAS_ASSET):
        self.path = require_asset(path)
        self.source = pygame.image.load(str(self.path))
        if self.source.get_size() != (1448, 1086):
            raise ValueError(
                f"{self.path}: expected the inspected 1448x1086 villager atlas, "
                f"found {self.source.get_width()}x{self.source.get_height()}"
            )

        extracted = {role: {"idle": {}, "walk": {}, "props": []}
                     for role in VILLAGER_ROLES}
        self.source_rects = {role: {"idle": {}, "walk": {}, "props": []}
                             for role in VILLAGER_ROLES}
        for role in VILLAGER_ROLES:
            for direction, cell in zip(VILLAGER_DIRECTIONS, _VILLAGER_IDLE_CELLS[role]):
                rect = _rect_cell(cell)
                self.source_rects[role]["idle"][direction] = [rect]
                extracted[role]["idle"][direction] = [self._extract(rect)]
            for direction, (top, height) in zip(VILLAGER_DIRECTIONS, _WALK_ROWS):
                rects = [pygame.Rect(left, top, width, height)
                         for left, width in _WALK_COLUMNS[role]]
                self.source_rects[role]["walk"][direction] = rects
                extracted[role]["walk"][direction] = [self._extract(rect) for rect in rects]
            prop_rects = [_rect_cell(cell) for cell in _VILLAGER_PROP_CELLS[role]]
            self.source_rects[role]["props"] = prop_rects
            extracted[role]["props"] = [self._extract(rect) for rect in prop_rects]

        self.frames = {role: {"idle": {}, "walk": {}, "props": []}
                       for role in VILLAGER_ROLES}
        for role in VILLAGER_ROLES:
            for state in ("idle", "walk"):
                all_frames = [item for direction in VILLAGER_DIRECTIONS
                              for item in extracted[role][state][direction]]
                scale = self.TARGET_HEIGHT[state] / max(item[0].get_height()
                                                         for item in all_frames)
                for direction in VILLAGER_DIRECTIONS:
                    self.frames[role][state][direction] = [
                        self._normalize(sprite, anchor_x, scale)
                        for sprite, anchor_x in extracted[role][state][direction]
                    ]
            prop_scale = self.TARGET_HEIGHT["props"] / max(
                item[0].get_height() for item in extracted[role]["props"]
            )
            self.frames[role]["props"] = [
                self._normalize(sprite, anchor_x, prop_scale)
                for sprite, anchor_x in extracted[role]["props"]
            ]

    def _extract(self, rect):
        """Remove only edge-connected atlas paper, preserving enclosed pale art."""
        crop = self.source.subsurface(rect).copy()
        rgb = pygame.surfarray.array3d(crop)
        low = rgb.min(axis=2)
        spread = rgb.max(axis=2) - low
        paper = (low >= 218) & (spread <= 42)
        width, height = paper.shape
        outside = np.zeros((width, height), dtype=bool)
        queue = deque()
        for x in range(width):
            if paper[x, 0]:
                outside[x, 0] = True; queue.append((x, 0))
            if paper[x, height - 1] and not outside[x, height - 1]:
                outside[x, height - 1] = True; queue.append((x, height - 1))
        for y in range(height):
            if paper[0, y] and not outside[0, y]:
                outside[0, y] = True; queue.append((0, y))
            if paper[width - 1, y] and not outside[width - 1, y]:
                outside[width - 1, y] = True; queue.append((width - 1, y))
        while queue:
            x, y = queue.popleft()
            for nx in range(max(0, x - 1), min(width, x + 2)):
                for ny in range(max(0, y - 1), min(height, y + 2)):
                    if paper[nx, ny] and not outside[nx, ny]:
                        outside[nx, ny] = True
                        queue.append((nx, ny))

        result = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.surfarray.blit_array(result, rgb)
        alpha = pygame.surfarray.pixels_alpha(result)
        alpha[:] = np.where(outside, 0, 255).astype(np.uint8)
        del alpha
        bounds = result.get_bounding_rect(min_alpha=1)
        if not bounds.width or not bounds.height:
            raise ValueError(f"{VILLAGER_ATLAS_ASSET}: empty villager cell {rect}")
        # Track the atlas cell center through the tight crop. Props are often
        # asymmetric, so their equipment must not pull the body off its anchor.
        anchor_x = rect.width / 2 - bounds.x
        return result.subsurface(bounds).copy(), anchor_x

    @classmethod
    def _normalize(cls, sprite, anchor_x, scale):
        size = (max(1, round(sprite.get_width() * scale)),
                max(1, round(sprite.get_height() * scale)))
        art = pygame.transform.scale(sprite, size)
        canvas = pygame.Surface(cls.SIZE, pygame.SRCALPHA)
        left = cls.ANCHOR[0] - round(anchor_x * scale)
        # Reduction can leave one transparent sampled row. Align the actual
        # opaque bound, not merely the scaled surface rectangle.
        art_bounds = art.get_bounding_rect(min_alpha=1)
        canvas.blit(art, (left, cls.ANCHOR[1] - art_bounds.bottom))
        return canvas

    @staticmethod
    def canonical_role(role):
        aliases = {
            "fisher": "fisherman", "balikci": "fisherman",
            "merchant": "elder", "villager": "elder", "generic": "elder",
        }
        role = str(role).casefold()
        role = aliases.get(role, role)
        return role if role in VILLAGER_ROLES else "elder"

    def sprite(self, role, facing="down", frame=0, moving=False, variant=0):
        role = self.canonical_role(role)
        facing = facing if facing in VILLAGER_DIRECTIONS else "down"
        if moving:
            frames = self.frames[role]["walk"][facing]
            return frames[int(frame) % len(frames)]
        # Prop/accessory variants are front-facing art. Other facings use the
        # authentic directional idle pose rather than mirroring or recolouring.
        if facing == "down" and int(variant) > 0:
            props = self.frames[role]["props"]
            return props[(int(variant) - 1) % len(props)]
        return self.frames[role]["idle"][facing][0]


@lru_cache(maxsize=1)
def preload_villager_sprites():
    return VillagerAtlas()


@lru_cache(maxsize=256)
def villager_sprite(role="villager", facing="down", frame=0, moving=None, variant=0):
    # A nonzero legacy frame still requests walking art. New callers should pass
    # moving explicitly so the first walking frame is not mistaken for idle.
    moving = bool(frame) if moving is None else bool(moving)
    return preload_villager_sprites().sprite(role, facing, frame, moving, variant)


@lru_cache(maxsize=32)
def item_sprite(item, scale=2):
    s = _canvas((12, 12))
    if item == "Çiğ Et":
        pygame.draw.polygon(s, OUTLINE, [(1, 5), (4, 2), (10, 3), (11, 8), (7, 11), (2, 9)])
        pygame.draw.polygon(s, (190, 64, 61), [(2, 5), (5, 3), (9, 4), (10, 8), (7, 10), (3, 8)])
        _rect(s, (244, 174, 144), (5, 4, 3, 2))
    elif item == "Pişmiş Et":
        pygame.draw.polygon(s, OUTLINE, [(1, 5), (4, 2), (10, 3), (11, 8), (7, 11), (2, 9)])
        pygame.draw.polygon(s, (132, 67, 38), [(2, 5), (5, 3), (9, 4), (10, 8), (7, 10), (3, 8)])
        _rect(s, (226, 150, 66), (4, 4, 5, 2))
    elif item == "Ekmek":
        pygame.draw.ellipse(s, OUTLINE, (1, 2, 10, 9)); pygame.draw.ellipse(s, (211, 145, 62), (2, 3, 8, 7))
        for x in (4, 7): pygame.draw.line(s, (245, 202, 112), (x, 4), (x - 1, 7), 1)
    elif item == "Odun":
        _rect(s, OUTLINE, (1, 3, 10, 7)); _rect(s, (139, 77, 39), (2, 4, 8, 5)); _rect(s, (220, 145, 66), (8, 5, 2, 3))
    elif item == "Tas":
        pygame.draw.polygon(s, OUTLINE, [(1, 9), (3, 3), (8, 1), (11, 5), (10, 10)])
        pygame.draw.polygon(s, (153, 151, 146), [(2, 8), (4, 4), (8, 2), (10, 5), (9, 9)])
        _rect(s, (206, 198, 184), (5, 4, 3, 2))
    elif item == "Tahil":
        pygame.draw.line(s, (112, 72, 34), (6, 11), (6, 2), 2)
        for x, y in ((3, 3), (8, 4), (3, 6), (8, 7)):
            pygame.draw.ellipse(s, (230, 183, 62), (x, y, 4, 3))
    elif item == "Ok":
        pygame.draw.line(s, OUTLINE, (1, 10), (10, 1), 3)
        pygame.draw.line(s, (181, 121, 61), (1, 10), (10, 1), 1)
        pygame.draw.polygon(s, (184, 190, 191), [(8, 1), (11, 0), (10, 4)])
        pygame.draw.polygon(s, (183, 73, 52), [(1, 10), (1, 6), (4, 9), (5, 11)])
    else:
        pygame.draw.polygon(s, (239, 189, 66), [(6, 0), (8, 4), (12, 6), (8, 8), (6, 12), (4, 8), (0, 6), (4, 4)])
    return pygame.transform.scale(s, (12 * scale, 12 * scale))
