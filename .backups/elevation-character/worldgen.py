"""Shared deterministic world data. No display or Pygame initialization required.

Heights/roads/buildings retain the original movement rules. Resources (including
all trees) are nonblocking, as in the original game. IDs are stable world positions,
not list indices. Client and server must use the same WORLD_VERSION.
"""
import math
import random
import time
from dataclasses import dataclass, field
from perlin_noise import PerlinNoise

WORLD_VERSION = 2
COLS, ROWS = 400, 240
ISLAND_COUNT = 25
MIN_RADIUS, MAX_RADIUS = 19, 36
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


def stable_random(x, y, seed):
    """Integer hash; independent of Python hash randomization and RNG call order."""
    n = (x * 374761393 + y * 668265263 + seed * 1442695041) & 0xffffffff
    n = ((n ^ (n >> 13)) * 1274126177) & 0xffffffff
    return ((n ^ (n >> 16)) & 0xffffffff) / 4294967296


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


@dataclass
class Port:
    island_index: int
    x: int
    y: int
    dx: int
    dy: int
    spawn: tuple


def terrain(height):
    if height < -0.16: return "Derin deniz", DEEP_WATER
    if height < SEA_LEVEL: return "Sig su", SHALLOW_WATER
    if height < SAND_LEVEL: return "Kum", SAND
    if height < MOUNTAIN_LEVEL: return "Cimen", GRASS
    return "Dag", MOUNTAIN


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
        islands.append(Island(f"Ada {len(islands) + 1:02}", x, y, rx, ry, resources))

    heights = [[-0.4] * COLS for _ in range(ROWS)]
    owners = [[-1] * COLS for _ in range(ROWS)]

    # perlin_noise treats zero as an unseeded RNG; keep zero reproducible too.
    coarse = PerlinNoise(octaves=2, seed=seed or 1000003)
    detail = PerlinNoise(octaves=7, seed=(seed + 1) or 1000033)

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

    world = World(seed, heights, owners, islands)
    generate_villages(world)

    # Finalize access routes before placing any harvestable objects.
    world.ports = generate_ports(world)
    populate_resources(world)

    if progress:
        progress(0.90)
    return world


def generate_villages(world):
    for index, island in enumerate(world.islands):
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
        village = Village(f"Koy {index + 1:02}", (cx, cy))

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
        if ports and rng.random() > 0.45: continue
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
    raise RuntimeError("Uygun kara bulunamadi.")



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
