"""Verified Fall Tile Set extraction and cached, pixel-sharp terrain composition.

The supplied 1448x1086 image is an illustrated atlas, NOT a regular sprite grid.
All rectangles below are hand-checked interiors or complete isolated objects.
Ground, transitions, paths and entities deliberately have separate asset tables.
"""
from collections import OrderedDict
import math
import time
import numpy as np
import pygame

from .elevation import prepare_elevation, MountainRenderer
from .worldgen import COLS, ROWS, SEA_LEVEL, SAND_LEVEL, MOUNTAIN_LEVEL, stable_random

TILE = 48
PIXELS = 24  # Compose at two screen pixels per art pixel, then nearest-neighbor scale.
DEEP, WATER, BEACH, GRASS, FOREST, DIRT, ROCK = range(7)
# Row-major 3x3 mask, including center (bit 4); all eight neighbors participate.
NEIGHBORS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]

GROUND_RECTS = {
    DEEP: (28, 47, 46, 46),
    WATER: (180, 47, 43, 43),
    BEACH: (763, 48, 36, 36),
    GRASS: (1020, 108, 35, 36),
    FOREST: (763, 247, 41, 37),
    DIRT: (1140, 109, 32, 34),
    ROCK: (1327, 45, 34, 39),
    7: (643, 384, 35, 29),  # Path interior, used only by the path overlay.
}
OBJECT_RECTS = {
    "oak": (17, 585, 132, 154),
    "pine": (154, 586, 87, 156),
    "stump": (454, 595, 72, 56),
    "stone": (698, 601, 94, 108),
    "rubble": (647, 731, 34, 29),
    "wheat": (1335, 589, 47, 79),
    "wheat2": (1390, 590, 44, 79),
    "cottage": (17, 807, 159, 166),
    "red_house": (464, 806, 164, 168),
    "boat": (1282, 363, 56, 131),
    "campfire": (1071, 808, 83, 105),
    "well": (966, 803, 91, 117),
    "lamp": (1366, 800, 66, 124),
    "barrels": (1282, 813, 52, 76),
    "signpost": (916, 942, 73, 101),
    "fence": (833, 815, 123, 54),
}


def prepare_terrain(world):
    """CPU-only preparation, called in the existing preload worker."""
    heights = np.asarray(world.heights)
    ground = np.full(heights.shape, ROCK, dtype=np.uint8)
    for limit, kind in ((MOUNTAIN_LEVEL, GRASS), (SAND_LEVEL, BEACH), (SEA_LEVEL, WATER), (-0.16, DEEP)):
        ground[heights < limit] = kind
    for (x, y), density in world.woodland.items():
        if density > 0.56:
            ground[y, x] = FOREST
    for x, y in world.roads:
        ground[y, x] = DIRT
    road = np.zeros(ground.shape, dtype=np.uint8)
    for x, y in world.roads:
        road[y, x] = 1
    # Precompute cumulative terrain masks, so three-way joins cannot expose holes.
    padded = np.pad(ground, 1, mode='edge')
    masks = np.zeros((7, ROWS, COLS), dtype=np.uint16)
    for bit, (dx, dy) in enumerate(NEIGHBORS):
        neighbor = padded[1 + dy:1 + dy + ROWS, 1 + dx:1 + dx + COLS]
        for level in range(1, 7):
            masks[level] |= (neighbor >= level).astype(np.uint16) << bit
    rp = np.pad(road, 1)
    paths = np.zeros(road.shape, dtype=np.uint16)
    for bit, (dx, dy) in enumerate(NEIGHBORS):
        paths |= rp[1 + dy:1 + dy + ROWS, 1 + dx:1 + dx + COLS].astype(np.uint16) << bit
    yy, xx = np.indices(ground.shape)
    variants = (((yy + world.seed // 16) % 16) * 16 + (xx + world.seed) % 16).astype(np.uint8)
    prepare_elevation(world)
    world.terrain_data = (ground, masks, road, paths, variants)
    return world.terrain_data


class TileAtlas:
    def __init__(self, filepath, deferred=False):
        raw = pygame.image.load(str(filepath)).convert_alpha()
        if raw.get_size() != (1448, 1086):
            raise ValueError(f"Expected the verified 1448x1086 Fall atlas, got {raw.get_size()}")
        self.raw = raw
        self.build_steps = self._build_steps()
        if not deferred:
            for _ in self.build_steps:
                pass

    def _build_steps(self):
        raw = self.raw
        self.ground = {}
        for kind, rect in GROUND_RECTS.items():
            self.ground[kind] = yield from self._textures(rect, kind)
        self.deep_water, self.shallow_water = self.ground[DEEP], self.ground[WATER]
        self.sand, self.grass, self.mountain = self.ground[BEACH], self.ground[GRASS], self.ground[ROCK]
        self.tree_species = {
            'oak': self._object('oak', (76, 90)),
            'pine': self._object('pine', (58, 100)),
        }
        self.tree_variants = {name: [sprite, pygame.transform.flip(sprite, True, False)]
                              for name, sprite in self.tree_species.items()}
        self.stump = self._object('stump', (32, 26))
        self.rocks = [self._object('stone', (42, 46))]
        self.mined_rubble = self._object('rubble', (26, 20))
        self.crops = [self._object('wheat', (32, 46)), self._object('wheat2', (30, 46))]
        self.houses = [self._object('cottage', (86, 90)), self._object('red_house', (86, 90))]
        self.boat = self._object('boat', (32, 64))
        for name, size in {'campfire': (36, 44), 'well': (42, 54), 'lamp': (28, 60),
                           'barrels': (28, 38), 'signpost': (32, 46), 'fence': (64, 28)}.items():
            setattr(self, name, self._object(name, size))
        # Interior planks only: contiguous dock spans without white end margins.
        self.dock_h = pygame.transform.scale(raw.subsurface((941, 375, 79, 37)), (48, 26))
        self.dock_v = pygame.transform.rotate(self.dock_h, 90)
        self.path_texture = pygame.transform.scale(raw.subsurface((643, 384, 35, 29)), (PIXELS, PIXELS))
        self.cliff_texture = pygame.transform.scale(raw.subsurface((119, 471, 32, 49)), (16, 25))
        self.fields = self._fields()
        self.masks = []
        self.vegetation_masks = []
        xx, yy = np.meshgrid(np.arange(PIXELS), np.arange(PIXELS))
        breakup = (((xx * 73 + yy * 151 + xx * yy * 13) % 101) / 100 - 0.5) * 0.19
        self.foam = []
        for expanded in self.fields:
            field = expanded[:PIXELS]
            self.masks.append(self._alpha(field >= 0.5))
            self.vegetation_masks.append(self._alpha(field >= 0.5 + breakup))
            # Narrow wet edge / foam from the shoreline's palette. Never opaque squares.
            foam = pygame.Surface((PIXELS, PIXELS), pygame.SRCALPHA)
            rgb = pygame.surfarray.pixels3d(foam)
            rgb[:] = (224, 244, 224)
            del rgb
            alpha = pygame.surfarray.pixels_alpha(foam)
            alpha[:] = ((field >= 0.39) & (field < 0.47)).T * 255
            del alpha
            self.foam.append(foam)
            if len(self.masks) % 32 == 0:
                yield
        self.paths = {mask: self._path(mask) for mask in range(512)}
        self.composites = OrderedDict()

    def _object(self, name, size):
        surf = self.raw.subsurface(OBJECT_RECTS[name]).copy()
        rgb = pygame.surfarray.array3d(surf)
        # This paper is ivory, not pure white. Remove low-chroma paper pixels;
        # object outlines and colored highlights remain. Rectangles exclude labels.
        paper = (rgb.min(axis=2) > 216) & (rgb.max(axis=2) - rgb.min(axis=2) < 30)
        alpha = pygame.surfarray.pixels_alpha(surf)
        alpha[paper] = 0
        del alpha
        bounds = surf.get_bounding_rect(min_alpha=1)
        surf = surf.subsurface(bounds).copy()
        # Normalize the illustration's uneven source pixel pitch, without filtering.
        small = pygame.transform.scale(surf, (max(1, size[0] // 2), max(1, size[1] // 2)))
        return pygame.transform.scale(small, size)

    def _textures(self, rect, kind):
        """Quilt a continuous 16x16-tile material from verified atlas interiors.

        Irregular binary patch masks preserve source colors; no blur or interpolation.
        Patches wrap on a torus, then the material is cut into tiles. Neighboring
        samples are literally adjacent pixels, rather than independently randomized
        tile edges. The large material is reused and never regenerated during play.
        """
        source = pygame.transform.scale(self.raw.subsurface(rect), (24, 24))
        rgb = pygame.surfarray.array3d(source)
        if kind in (GRASS, FOREST):
            # Lift only the deepest brown/black pockets. The atlas' forest floor
            # reached near-black and merged into oak trunks; midtones and bright
            # leaf litter stay untouched so the original pixel shading survives.
            work = rgb.astype(np.int16)
            luminance = (work[:, :, 0] * 3 + work[:, :, 1] * 5 + work[:, :, 2] * 2) / 10
            limit = 96 if kind == FOREST else 92
            mask = luminance < limit
            target = np.array((132, 82, 32) if kind == FOREST else (154, 86, 27), dtype=np.int16)
            maximum = .72 if kind == FOREST else .58
            strength = np.clip((limit - luminance) / limit, 0.0, maximum)[:, :, None]
            work = np.where(mask[:, :, None], work * (1 - strength) + target * strength, work)
            rgb = np.clip(work, 0, 255).astype(np.uint8)
        span = PIXELS * 16
        material = rgb[np.arange(span)[:, None] % 24, np.arange(span)[None, :] % 24].copy()
        rng = np.random.default_rng(31871 + kind)
        # Overlapping samples cross logical tile boundaries and the periodic border.
        px, py = np.meshgrid(np.arange(16), np.arange(16), indexing='ij')
        distance = (px - 7.5) ** 2 + (py - 7.5) ** 2
        for pass_index in range(2):
            for x in range(0, span, 9):
                for y in range(0, span, 9):
                    ox, oy, sx, sy = rng.integers(0, 8, size=4)
                    mask = distance < (52 + rng.integers(-14, 15, size=(16, 16)))
                    patch = rgb[sx:sx + 16, sy:sy + 16]
                    if rng.integers(2):
                        patch = patch[::-1]
                    xs, ys = (x + ox + px) % span, (y + oy + py) % span
                    material[xs[mask], ys[mask]] = patch[mask]
                yield
        sheet = pygame.surfarray.make_surface(material)
        return [sheet.subsurface((x * PIXELS, y * PIXELS, PIXELS, PIXELS)).copy()
                for y in range(16) for x in range(16)]

    @staticmethod
    def _alpha(mask):
        result = pygame.Surface((PIXELS, PIXELS), pygame.SRCALPHA)
        result.fill((255, 255, 255, 0))
        alpha = pygame.surfarray.pixels_alpha(result)
        alpha[:] = mask.T * 255
        del alpha
        return result

    @staticmethod
    def _fields():
        """Bilinear occupancy with rounded corners and periodic pixel edge breakup.

        Samples are centered on logical tiles. Shared edge samples use the same
        neighbor values, so straight edges, concavities and narrow strips agree.
        The periodic disturbance is identical on either side of every tile boundary.
        """
        coords = (np.arange(PIXELS) + 0.5) / PIXELS + 0.5
        indices = coords.astype(int)
        weights = coords - indices
        ix, iy = indices[:PIXELS], indices
        xx, yy = np.meshgrid(np.arange(PIXELS), np.arange(PIXELS))
        ripple = 0.035 * (np.sin((xx + .5) * math.tau / 12) + np.sin((yy + .5) * math.tau / 12))
        fields = []
        for bits in range(512):
            grid = np.array([(bits >> b) & 1 for b in range(9)]).reshape(3, 3)
            a = grid[iy[:, None], ix[None, :]]
            b = grid[iy[:, None], ix[None, :] + 1]
            c = grid[iy[:, None] + 1, ix[None, :]]
            d = grid[iy[:, None] + 1, ix[None, :] + 1]
            fx, fy = weights[None, :PIXELS], weights[:, None]
            field = a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy
            fields.append(field + ripple)
        return fields

    def _path(self, bits):
        mask = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255), (12, 12), 9)
        for bit, end in ((1, (12, -1)), (7, (12, 24)), (3, (-1, 12)), (5, (24, 12))):
            if bits & (1 << bit):
                pygame.draw.line(mask, (255, 255, 255), (12, 12), end, 18)
        # Fill the interior of road plazas only when the diagonal also connects.
        for neighbors, rect in (((0, 1, 3), (0, 0, 13, 13)),
                                ((1, 2, 5), (12, 0, 12, 13)),
                                ((3, 6, 7), (0, 12, 13, 12)),
                                ((5, 7, 8), (12, 12, 12, 12))):
            if all(bits & (1 << bit) for bit in neighbors):
                pygame.draw.rect(mask, (255, 255, 255), rect)
        return mask

    def compose(self, kinds, path, variant, rocky):
        key = (kinds, path, variant, rocky)
        cached = self.composites.get(key)
        if cached is not None:
            self.composites.move_to_end(key)
            return cached
        surface = self.ground[DEEP][variant].copy()
        for level, bits in enumerate(kinds, 1):
            if not bits or (level == ROCK and path >= 0):
                continue
            if bits == 511:
                surface.blit(self.ground[level][variant], (0, 0))
            else:
                layer = self.ground[level][variant].copy().convert_alpha()
                mask = self.vegetation_masks[bits] if level in (GRASS, FOREST, DIRT) else self.masks[bits]
                layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                if level == BEACH:
                    surface.blit(self.foam[bits], (0, 0))
                surface.blit(layer, (0, 0))
        if path >= 0:
            path_layer = self.ground[7][variant].copy().convert_alpha()
            path_layer.blit(self.paths[path], (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(path_layer, (0, 0))
        result = pygame.transform.scale(surface, (TILE, TILE)).convert()
        self.composites[key] = result
        if len(self.composites) > 4096:
            self.composites.popitem(last=False)
        return result


class TerrainRenderer:
    """Bounded chunk cache. Per-frame work is viewport blits, never pixel processing."""
    CHUNK = 8
    LIMIT = 96  # At most ~54 MiB at 32 bits/pixel; entire world would be ~850 MiB.

    def __init__(self, world, atlas):
        self.world, self.atlas = world, atlas
        self.data = getattr(world, 'terrain_data', None) or prepare_terrain(world)
        self.chunks = OrderedDict()
        self.mountains = MountainRenderer(world, atlas)

    def _chunk(self, cx, cy):
        key = (cx, cy)
        if key in self.chunks:
            self.chunks.move_to_end(key)
            return self.chunks[key]
        ground, masks, roads, paths, variants = self.data
        size = self.CHUNK
        chunk = pygame.Surface((size * TILE, size * TILE)).convert()
        for y in range(cy * size, min((cy + 1) * size, ROWS)):
            for x in range(cx * size, min((cx + 1) * size, COLS)):
                kinds = tuple(int(masks[level, y, x]) for level in range(1, 7))
                tile = self.atlas.compose(kinds, int(paths[y, x]) if roads[y, x] else -1,
                                          int(variants[y, x]), ground[y, x] == ROCK)
                chunk.blit(tile, ((x % size) * TILE, (y % size) * TILE))
        self.mountains.compose_chunk(chunk, cx, cy, size)
        self.chunks[key] = chunk
        if len(self.chunks) > self.LIMIT:
            self.chunks.popitem(last=False)
        return chunk

    def warm_view(self, camera_x, camera_y, width=1200, height=780):
        span = self.CHUNK * TILE
        for y in range(max(0, int(camera_y) // span), min(math.ceil(ROWS / self.CHUNK), (int(camera_y) + height) // span + 1)):
            for x in range(max(0, int(camera_x) // span), min(math.ceil(COLS / self.CHUNK), (int(camera_x) + width) // span + 1)):
                self._chunk(x, y)
                yield

    def draw(self, screen, camera_x, camera_y):
        started = time.perf_counter()
        # Round the camera ONCE. Never round independently calculated tile widths.
        cx, cy = round(camera_x), round(camera_y)
        span = self.CHUNK * TILE
        left, top = max(0, cx // span), max(0, cy // span)
        right = min(math.ceil(COLS / self.CHUNK), (cx + screen.get_width()) // span + 1)
        bottom = min(math.ceil(ROWS / self.CHUNK), (cy + screen.get_height()) // span + 1)
        for y in range(top, bottom):
            for x in range(left, right):
                screen.blit(self._chunk(x, y), (x * span - cx, y * span - cy))

        # Prepare one neighboring chunk while the current view is cheap to draw.
        # The border is ready before normal walking/sailing reaches it; avoid
        # adding work to a frame already busy rebuilding a teleported viewport.
        if time.perf_counter() - started < .008:
            for y in range(max(0, top - 1), min(math.ceil(ROWS / self.CHUNK), bottom + 1)):
                for x in range(max(0, left - 1), min(math.ceil(COLS / self.CHUNK), right + 1)):
                    if (x, y) not in self.chunks:
                        self._chunk(x, y)
                        return
