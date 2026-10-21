"""Shared deterministic world data. No display or Pygame initialization required.

Heights/roads/buildings retain the original movement rules. Resources (including
all trees) are nonblocking, as in the original game. IDs are stable world positions,
not list indices. Client and server must use the same WORLD_VERSION.
"""
import math
import random
import time
from dataclasses import dataclass, field

from .localization import BOSS_ISLAND_NAME

WORLD_VERSION = 7
COLS, ROWS = 640, 384
ISLAND_COUNT = 42
MIN_RADIUS, MAX_RADIUS = 26, 46
PLAYER_HALF_SIZE = 0.17
SEA_LEVEL, SAND_LEVEL, MOUNTAIN_LEVEL = 0.0, 0.09, 0.48
VILLAGE_CHANCE = 0.60
RESOURCES = ("Odun", "Tahil", "Tas")
DEEP_WATER = (17, 88, 158)
SHALLOW_WATER = (50, 173, 201)
SAND = (246, 192, 114)
GRASS = (208, 128, 34)
MOUNTAIN = (158, 126, 116)
ROAD = (148, 76, 36)

MEDIEVAL_NAME_PREFIXES = (
    "Amber", "Ashen", "Black", "Briar", "Bronze", "Cinder", "Crow", "Dawn",
    "Dragon", "Elder", "Ember", "Fallow", "Frost", "Gilden", "Grey", "Hawthorn",
    "High", "Iron", "Kings", "Mist", "Moon", "North", "Oak", "Raven", "Red",
    "Rose", "Silver", "Storm", "Thorn", "West", "White", "Willow",
)
MEDIEVAL_NAME_SUFFIXES = (
    "bay", "cliff", "crown", "fall", "fen", "ford", "haven", "holm", "keep",
    "mere", "moor", "reach", "rest", "rock", "watch", "wick", "wynd",
)


def medieval_island_names(seed, count):
    """Return unique old-world place names without perturbing terrain RNG state."""
    names = [prefix + suffix for prefix in MEDIEVAL_NAME_PREFIXES
             for suffix in MEDIEVAL_NAME_SUFFIXES]
    random.Random(seed * 104729 + 0xA11CE).shuffle(names)
    return names[:count]


def stable_random(x, y, seed):
    """Integer hash; independent of Python hash randomization and RNG call order."""
    n = (x * 374761393 + y * 668265263 + seed * 1442695041) & 0xffffffff
    n = ((n ^ (n >> 13)) * 1274126177) & 0xffffffff
    return ((n ^ (n >> 16)) & 0xffffffff) / 4294967296


def _fade(t):
    return 6 * math.pow(t, 5) - 15 * math.pow(t, 4) + 10 * math.pow(t, 3)


class StablePerlin:
    """2-D Perlin noise numerically identical to ``perlin_noise.PerlinNoise``.

    The library seeds the process-global ``random`` module for every gradient
    vector.  World generation runs on a background thread while the menu draws
    random leaf particles, so a thread switch could perturb those vectors and
    give one seed different terrain.  This version draws each gradient from a
    private ``random.Random`` with the same seed and call order, so existing
    worlds are unchanged while generation no longer depends on other threads.
    """

    def __init__(self, octaves, seed):
        if not seed:
            raise ValueError("StablePerlin requires a non-zero seed")
        self.octaves = octaves
        self.seed = int(seed)
        self._vectors = {}

    def _vector(self, cx, cy):
        vector = self._vectors.get((cx, cy))
        if vector is None:
            # perlin_noise.tools.hasher for two dimensions.
            coordinate_hash = max(1, int(abs(cx + cy * 10 + 1)))
            rng = random.Random(self.seed * coordinate_hash)
            vector = (rng.uniform(-1, 1), rng.uniform(-1, 1))
            self._vectors[(cx, cy)] = vector
        return vector

    def __call__(self, point):
        x, y = point[0] * self.octaves, point[1] * self.octaves
        x0, y0 = math.floor(x), math.floor(y)
        # Keep the library's sum() calls: Python's float sum() is compensated,
        # so replacing it with ``+`` would drift by an ulp and alter worlds.
        contributions = []
        for cx in (x0, x0 + 1):
            for cy in (y0, y0 + 1):
                vx, vy = self._vector(cx, cy)
                dx, dy = x - cx, y - cy
                weight = _fade(1 - abs(dx)) * _fade(1 - abs(dy))
                contributions.append(weight * sum([vx * dx, vy * dy]))
        return sum(contributions)


def woodland_noise(x, y, seed, scale=8):
    ix, iy = math.floor(x / scale), math.floor(y / scale)
    fx, fy = x / scale - ix, y / scale - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = stable_random(ix, iy, seed) * (1 - fx) + stable_random(ix + 1, iy, seed) * fx
    b = stable_random(ix, iy + 1, seed) * (1 - fx) + stable_random(ix + 1, iy + 1, seed) * fx
    return a * (1 - fy) + b * fy


@dataclass
class Island:
    name: str
    x: int
    y: int
    rx: float
    ry: float
    resources: tuple
    village: object = None
    owner: object = None



@dataclass
class Village:
    name: str
    center: tuple
    houses: list = field(default_factory=list)


@dataclass
class ResourceNode:
    type: str
    x: float
    y: float
    active: bool = True
    cooldown: float = 0.0
    id: str = ""
    species: str = "oak"
    variant: int = 0
    harvest_pending: bool = False

    def harvest(self):
        if self.active:
            self.active = False
            self.cooldown = 30.0 + stable_random(int(self.x * 100), int(self.y * 100), 83) * 10
            self.harvest_pending = True


@dataclass
class World:
    seed: int
    heights: list
    owners: list
    islands: list
    roads: set = field(default_factory=set)
    buildings: set = field(default_factory=set)
    nodes: list = field(default_factory=list)
    woodland: dict = field(default_factory=dict)
    ports: object = None
    village_props: list = field(default_factory=list)
    boss_island_index: int = -1
    boss_portal: tuple = None
    boss_return: tuple = None


@dataclass
class Port:
    island_index: int
    x: int
    y: int
    dx: int
    dy: int
    spawn: tuple


def terrain(height):
    if height < -0.16: return "Deep sea", DEEP_WATER
    if height < SEA_LEVEL: return "Shallows", SHALLOW_WATER
    if height < SAND_LEVEL: return "Sand", SAND
    if height < MOUNTAIN_LEVEL: return "Meadow", GRASS
    return "Mountain", MOUNTAIN


def make_world(seed, progress=None):
    """Pure CPU world generation algorithm with progress reporting and sleep yielding."""
    rng = random.Random(seed)
    islands = []

    for _ in range(30000):
        if len(islands) >= ISLAND_COUNT: break
        rx = rng.uniform(MIN_RADIUS, MAX_RADIUS)
        ry = rx * rng.uniform(0.65, 1.15)
        x = rng.randint(math.ceil(rx) + 3, COLS - math.ceil(rx) - 4)
        y = rng.randint(math.ceil(ry) + 3, ROWS - math.ceil(ry) - 4)

        overlaps = any(
            abs(x - other.x) < rx + other.rx + 3 and abs(y - other.y) < ry + other.ry + 3
            for other in islands
        )
        if overlaps: continue

        resources = tuple(rng.sample(RESOURCES, rng.randint(1, 3)))
        islands.append(Island("", x, y, rx, ry, resources))

    for island, name in zip(islands, medieval_island_names(seed, len(islands))):
        island.name = name
    # Reuse one deterministic generated island instead of adding a disconnected
    # bespoke map.  It retains the normal coast, port and sailing rules.
    boss_island_index = len(islands) - 1
    islands[boss_island_index].name = BOSS_ISLAND_NAME

    heights = [[-0.4] * COLS for _ in range(ROWS)]
    owners = [[-1] * COLS for _ in range(ROWS)]

    # perlin_noise treats zero as an unseeded RNG; keep zero reproducible too.
    coarse = StablePerlin(octaves=2, seed=seed or 1000003)
    detail = StablePerlin(octaves=7, seed=(seed + 1) or 1000033)

    for index, island in enumerate(islands):
        shape_rng = random.Random(seed * 1009 + index * 9176)
        phases = [shape_rng.uniform(0, math.tau) for _ in range(4)]
        offset_x = shape_rng.uniform(-50, 50)
        offset_y = shape_rng.uniform(-50, 50)

        left = max(0, math.floor(island.x - island.rx - 2))
        right = min(COLS, math.ceil(island.x + island.rx + 3))
        top = max(0, math.floor(island.y - island.ry - 2))
        bottom = min(ROWS, math.ceil(island.y + island.ry + 3))

        for y in range(top, bottom):
            for x in range(left, right):
                dx = (x - island.x) / island.rx
                dy = (y - island.y) / island.ry
                distance = math.hypot(dx, dy)

                if distance > 1.08: continue
                angle = math.atan2(dy, dx)
                coastline = (0.72 + 0.15 * math.sin(2 * angle + phases[0])
                             + 0.10 * math.sin(3 * angle + phases[1])
                             + 0.06 * math.sin(5 * angle + phases[2])
                             + 0.03 * math.sin(8 * angle + phases[3]))

                point = [dx * 0.9 + offset_x, dy * 0.9 + offset_y]
                broad_noise = coarse(point)
                fine_noise = detail(point)
                relative_distance = distance / coastline
                height = 0.78 - relative_distance ** 1.6 + broad_noise * 0.65 + fine_noise * 0.15
                edge = max(0.0, min(1.0, (distance - 0.85) / 0.20))
                height = height * (1 - edge) - 0.4 * edge

                if height > heights[y][x]:
                    heights[y][x] = height
                    owners[y][x] = index if height >= SEA_LEVEL else -1

        if progress:
            progress(0.80 * (index + 1) / max(1, len(islands)))
        time.sleep(0.003)

    world = World(seed, heights, owners, islands,
                  boss_island_index=boss_island_index)
    generate_villages(world)

    # Finalize access routes before placing any harvestable objects.
    world.ports = generate_ports(world)
    world.boss_portal, world.boss_return = find_boss_portal(world)
    populate_resources(world)

    if progress:
        progress(0.90)
    return world


def generate_villages(world):
    for index, island in enumerate(world.islands):
        if index == world.boss_island_index:
            continue
        rng = random.Random(world.seed * 65537 + index * 31337 + 111)
        if rng.random() > VILLAGE_CHANCE: continue

        candidates = []
        left = max(4, int(island.x - island.rx))
        right = min(COLS - 4, int(island.x + island.rx + 1))
        top = max(4, int(island.y - island.ry))
        bottom = min(ROWS - 4, int(island.y + island.ry + 1))

        for y in range(top, bottom):
            for x in range(left, right):
                height = world.heights[y][x]
                if not SAND_LEVEL <= height < MOUNTAIN_LEVEL: continue
                clear = all(world.owners[yy][xx] == index for yy in range(y - 3, y + 4) for xx in range(x - 3, x + 4))
                if clear: candidates.append((x, y))

        if not candidates: continue
        cx, cy = rng.choice(candidates)
        village = Village(f"Village {index + 1:02}", (cx, cy))

        for y in range(cy - 1, cy + 2):
            for x in range(cx - 1, cx + 2):
                world.roads.add((x, y))

        house_offsets = [(-2, -2), (2, -2), (-2, 2), (2, 2)]
        rng.shuffle(house_offsets)
        house_count = rng.randint(3, 4)

        for ox, oy in house_offsets[:house_count]:
            hx, hy = cx + ox, cy + oy
            village.houses.append((hx, hy))
            world.buildings.add((hx, hy))
            door_y = hy + 1
            for y in range(min(cy, door_y), max(cy, door_y) + 1): world.roads.add((cx, y))
            for x in range(min(cx, hx), max(cx, hx) + 1): world.roads.add((x, door_y))

        world.roads.difference_update(world.buildings)
        island.village = village

        # Add Village Props (Campfire in center, well, street lamps, barrels)
        world.village_props.append(('campfire', cx + 0.5, cy + 0.5))
        world.village_props.append(('well', cx + 1.6, cy - 0.5))
        world.village_props.append(('lamp', cx - 1.2, cy + 1.2))
        world.village_props.append(('barrels', cx + 1.8, cy + 1.2))
        world.village_props.append(('signpost', cx - 1.5, cy - 1.2))


def compute_tile_pixels(world) -> bytes:
    """Pre-computes raw RGB bytes for mini-map in worker thread, thread-safe."""
    buf = bytearray(COLS * ROWS * 3)
    rng = random.Random(world.seed)
    idx = 0
    for y in range(ROWS):
        for x in range(COLS):
            height = world.heights[y][x]
            color = terrain(height)[1]
            if (x, y) in world.roads:
                color = ROAD
            shade = rng.randint(-5, 5) if height > -0.4 else 0

            if height >= SEA_LEVEL and (x, y) not in world.roads:
                left = world.heights[y][max(0, x - 1)]
                above = world.heights[max(0, y - 1)][x]
                slope = left + above - 2 * height
                shade += int(max(-20, min(20, slope * 55)))

            buf[idx] = max(0, min(255, color[0] + shade))
            buf[idx + 1] = max(0, min(255, color[1] + shade))
            buf[idx + 2] = max(0, min(255, color[2] + shade))
            idx += 3
    return bytes(buf)


def generate_ports(world):
    if world.ports is not None:
        return world.ports
    rng = random.Random(world.seed + 74021)
    ports = []
    directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    for island_index, island in enumerate(world.islands):
        candidates = []
        left = max(4, int(island.x - island.rx))
        right = min(COLS - 4, int(island.x + island.rx + 1))
        top = max(4, int(island.y - island.ry))
        bottom = min(ROWS - 4, int(island.y + island.ry + 1))

        for y in range(top, bottom):
            for x in range(left, right):
                if world.owners[y][x] != island_index: continue
                for dx, dy in directions:
                    water_clear = all(world.heights[y + dy * step][x + dx * step] < SEA_LEVEL for step in range(1, 4))
                    if not water_clear: continue
                    land_clear = all(world.owners[y - dy * step][x - dx * step] == island_index and can_stand(world,
                                                                                                              x - dx * step + 0.5,
                                                                                                              y - dy * step + 0.5,
                                                                                                              False)
                                     for step in range(4))
                    if land_clear: candidates.append((x, y, dx, dy))

        if not candidates: continue
        x, y, dx, dy = rng.choice(candidates)
        spawn = (x - dx * 3 + 0.5, y - dy * 3 + 0.5)
        ports.append(Port(island_index, x, y, dx, dy, spawn))

        if "Balik" not in island.resources:
            island.resources = island.resources + ("Balik",)

        for step in range(4): world.roads.add((x - dx * step, y - dy * step))
    world.ports = ports
    return ports


def can_stand(world, x, y, is_sailing):
    for ox in (-PLAYER_HALF_SIZE, PLAYER_HALF_SIZE):
        for oy in (-PLAYER_HALF_SIZE, PLAYER_HALF_SIZE):
            tx, ty = math.floor(x + ox), math.floor(y + oy)
            if not (0 <= tx < COLS and 0 <= ty < ROWS): return False

            if is_sailing:
                if world.heights[ty][tx] >= SEA_LEVEL: return False
            else:
                if world.heights[ty][tx] < SEA_LEVEL: return False
                if (tx, ty) in world.buildings: return False
    return True


def find_spawn(world):
    for island in world.islands:
        if island.village:
            x, y = island.village.center
            for dx, dy in ((0, 1), (0, 0), (-1, 0), (1, 0), (0, -1)):
                px, py = x + dx + 0.5, y + dy + 0.5
                if (can_stand(world, px, py, False)
                        and all(math.hypot(px - ox, py - oy) > 0.8 for _, ox, oy in world.village_props)):
                    return (px, py)

    for y in range(ROWS):
        for x in range(COLS):
            if can_stand(world, x + 0.5, y + 0.5, False):
                if SAND_LEVEL <= world.heights[y][x] < MOUNTAIN_LEVEL:
                    return (x + 0.5, y + 0.5)
    raise RuntimeError("No suitable land was found for the player spawn.")


def find_boss_portal(world):
    """Choose deterministic, walkable portal and return anchors on Crimsonroot Isle."""
    index = world.boss_island_index
    island = world.islands[index]
    candidates = []
    for radius in range(0, max(4, int(min(island.rx, island.ry) * .55))):
        for dx, dy in ((0, radius), (radius, 0), (0, -radius), (-radius, 0),
                       (radius, radius), (-radius, radius),
                       (radius, -radius), (-radius, -radius)):
            x, y = island.x + dx + .5, island.y + dy + .5
            tx, ty = int(x), int(y)
            if not (1 <= tx < COLS - 1 and 1 <= ty < ROWS - 1):
                continue
            if world.owners[ty][tx] != index or not can_stand(world, x, y, False):
                continue
            if not SAND_LEVEL <= world.heights[ty][tx] < MOUNTAIN_LEVEL:
                continue
            clearance = sum(
                world.owners[ty + oy][tx + ox] == index
                and world.heights[ty + oy][tx + ox] >= SAND_LEVEL
                and (tx + ox, ty + oy) not in world.buildings
                for ox in range(-2, 3) for oy in range(-2, 3)
            )
            candidates.append((clearance, -radius, x, y))
    if not candidates:
        raise RuntimeError("No safe portal location was found on Crimsonroot Isle")
    _, _, px, py = max(candidates)
    returns = ((px, py + 2.0), (px + 2.0, py), (px - 2.0, py), (px, py - 2.0))
    return_point = next((point for point in returns
                         if can_stand(world, point[0], point[1], False)), (px, py + 1.0))
    return (px, py), return_point


def island_spawn_points(world):
    """Return one collision-safe spawn point for every usable island."""
    points = []
    for island_index, island in enumerate(world.islands):
        candidates = []
        if island.village:
            x, y = island.village.center
            candidates.extend((x + dx + 0.5, y + dy + 0.5)
                              for dx, dy in ((0, 1), (-1, 0), (1, 0), (0, -1), (0, 0)))
        left = max(0, int(island.x - island.rx))
        right = min(COLS, int(island.x + island.rx + 1))
        top = max(0, int(island.y - island.ry))
        bottom = min(ROWS, int(island.y + island.ry + 1))
        candidates.extend((x + 0.5, y + 0.5) for y in range(top, bottom) for x in range(left, right)
                          if world.owners[y][x] == island_index)
        point = next(((x, y) for x, y in candidates if can_stand(world, x, y, False)), None)
        if point:
            points.append((island_index, point))
    return points


class SpawnPool:
    """Random, without-replacement island allocation for entries and respawns."""
    def __init__(self, world, rng=None):
        self.entries = island_spawn_points(world)
        self.rng = rng or random.SystemRandom()
        self.available = []
        self.last_island = None

    def acquire(self, occupied=()):
        occupied = set(occupied)
        valid_ids = {idx for idx, _ in self.entries if idx not in occupied}
        self.available = [entry for entry in self.available if entry[0] in valid_ids]
        if not self.available:
            self.available = [entry for entry in self.entries
                              if entry[0] in valid_ids and entry[0] != self.last_island]
        if not self.available:
            self.available = [entry for entry in self.entries if entry[0] in valid_ids]
        if not self.available:
            raise RuntimeError("No unoccupied spawn island remains")
        chosen = self.rng.choice(self.available)
        self.available.remove(chosen)
        self.last_island = chosen[0]
        return chosen



def populate_resources(world):
    """Clustered forests with jittered trunks and clear access/spawn corridors."""
    spawn = find_spawn(world)
    reserved = set()
    for x, y in world.roads | world.buildings:
        reserved.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    for _, x, y in world.village_props:
        reserved.add((int(x), int(y)))
    for px, py in [spawn] + [p.spawn for p in world.ports]:
        reserved.update((int(px) + dx, int(py) + dy) for dx in range(-2, 3) for dy in range(-2, 3))
    if world.boss_portal:
        px, py = map(int, world.boss_portal)
        reserved.update((px + dx, py + dy) for dx in range(-3, 4) for dy in range(-3, 4))

    occupied = {}
    def suitable(x, y):
        return (0 <= x < COLS and 0 <= y < ROWS
                and SAND_LEVEL <= world.heights[y][x] < MOUNTAIN_LEVEL
                and (x, y) not in reserved)

    def add(kind, x, y):
        ix, iy = int(x), int(y)
        if (ix, iy) in occupied or not can_stand(world, x, y, False):
            return False
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for other in occupied.get((ix + dx, iy + dy), ()):
                    if math.hypot(x - other.x, y - other.y) < 1.15:
                        return False
        species = "pine" if world.heights[iy][ix] > 0.34 else "oak"
        node = ResourceNode(kind, x, y, id=f"{kind}:{ix}:{iy}", species=species,
                            variant=int(stable_random(ix, iy, world.seed + 97) * 4))
        world.nodes.append(node)
        occupied.setdefault((ix, iy), []).append(node)
        return True

    # Preserve the original grain/stone availability per island.
    rng = random.Random(world.seed * 444)
    for index, island in enumerate(world.islands):
        for kind in island.resources:
            if kind not in ("Tahil", "Tas"):
                continue
            for _ in range(rng.randint(2, 5)):
                for attempt in range(100):
                    x = rng.uniform(island.x - island.rx, island.x + island.rx)
                    y = rng.uniform(island.y - island.ry, island.y + island.ry)
                    ix, iy = int(x), int(y)
                    if suitable(ix, iy) and world.owners[iy][ix] == index and add(kind, x, y):
                        break

    wooded_islands = set()
    for y in range(ROWS):
        for x in range(COLS):
            if not SAND_LEVEL <= world.heights[y][x] < MOUNTAIN_LEVEL:
                continue
            density = (0.78 * woodland_noise(x, y, world.seed + 777)
                       + 0.22 * woodland_noise(x, y, world.seed + 778, 3))
            world.woodland[x, y] = density
            if not suitable(x, y):
                continue
            # Broad stands, sparse edges and open meadows, with occasional lone trees.
            cover = max(0, min(1, (density - 0.30) / 0.44))
            probability = 0.025 + 0.42 * cover ** 2
            if stable_random(x, y, world.seed + 779) >= probability:
                continue
            tx = x + 0.5 + (stable_random(x, y, world.seed + 780) - 0.5) * 0.46
            ty = y + 0.5 + (stable_random(x, y, world.seed + 781) - 0.5) * 0.46
            if add("Odun", tx, ty):
                wooded_islands.add(world.owners[y][x])
    for index in wooded_islands:
        island = world.islands[index]
        if "Odun" not in island.resources:
            island.resources += ("Odun",)
