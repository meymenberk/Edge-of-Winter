import math
import random
import socket
import json
from dataclasses import dataclass, field
from pathlib import Path

import pygame
from perlin_noise import PerlinNoise

# ---------------- AYARLAR ----------------

SCREEN_W, SCREEN_H = 1200, 780
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
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOADING_BACKGROUND = PROJECT_ROOT / "assets" / "backgrounds" / "main_menu" / "bg.jpeg"

DEEP_WATER = (47, 68, 79)
SHALLOW_WATER = (83, 111, 113)
SAND = (193, 170, 128)
GRASS = (151, 145, 83)
MOUNTAIN = (128, 120, 108)
ROAD = (155, 116, 79)


# ---------------- AĞ (NETWORK) YÖNETİMİ ----------------

class Network:
    def __init__(self, host='127.0.0.1', port=5555):
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addr = (host, port)
        self.id = None
        self.seed = None
        self.other_players = {}
        self.buffer = ""
        self.connect()

    def connect(self):
        try:
            self.client.connect(self.addr)
            self.client.settimeout(5.0)
            data = self.client.recv(1024).decode('utf-8')
            lines = data.strip().split('\n')
            init_data = json.loads(lines[0])
            self.id = init_data["id"]
            self.seed = init_data["seed"]
            print(f"[BAGLANDI] ID: {self.id}, Seed: {self.seed}")
            self.client.setblocking(False)
        except Exception as e:
            print(f"[BAGLANTI HATASI] Sunucuya ulasilamadi: {e}")
            raise SystemExit

    def send_and_receive(self, x, y, facing, moving, sailing, boat_angle=0.0):
        payload = json.dumps({
            "x": x, "y": y,
            "facing": facing,
            "moving": moving,
            "sailing": sailing,
            "boat_angle": boat_angle
        }) + "\n"

        try:
            self.client.send(payload.encode('utf-8'))
        except BlockingIOError:
            pass
        except Exception:
            pass

        try:
            data = self.client.recv(4096).decode('utf-8')
            self.buffer += data
            if '\n' in self.buffer:
                lines = self.buffer.split('\n')
                self.buffer = lines[-1]
                if lines[-2]:
                    self.other_players = json.loads(lines[-2])
        except BlockingIOError:
            pass
        except Exception:
            pass


# ---------------- VERI YAPILARI ----------------

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


@dataclass
class World:
    seed: int
    heights: list
    owners: list
    islands: list
    roads: set = field(default_factory=set)
    buildings: set = field(default_factory=set)
    nodes: list = field(default_factory=list)


@dataclass
class Port:
    island_index: int
    x: int
    y: int
    dx: int
    dy: int
    spawn: tuple


# ---------------- ARAZI ----------------

def terrain(height):
    if height < -0.16: return "Derin deniz", DEEP_WATER
    if height < SEA_LEVEL: return "Sig su", SHALLOW_WATER
    if height < SAND_LEVEL: return "Kum", SAND
    if height < MOUNTAIN_LEVEL: return "Cimen", GRASS
    return "Dag", MOUNTAIN


def make_world(seed, progress=None):
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

    coarse = PerlinNoise(octaves=2, seed=seed)
    detail = PerlinNoise(octaves=7, seed=seed + 1)

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

        if progress: progress(0.85 * (index + 1) / max(1, len(islands)))

    world = World(seed, heights, owners, islands)
    generate_villages(world)

    # Fiziksel Kaynak Dugumleri Olustur (Node Generation)
    node_rng = random.Random(seed * 444)
    for index, island in enumerate(islands):
        for res in island.resources:
            for _ in range(node_rng.randint(2, 5)):
                # Adada rastgele gecerli bir nokta bul
                for _ in range(50):
                    nx = node_rng.uniform(island.x - island.rx, island.x + island.rx)
                    ny = node_rng.uniform(island.y - island.ry, island.y + island.ry)
                    ix, iy = int(nx), int(ny)
                    if 0 <= ix < COLS and 0 <= iy < ROWS and owners[iy][ix] == index:
                        h = heights[iy][ix]
                        if SAND_LEVEL <= h < MOUNTAIN_LEVEL and (ix, iy) not in world.roads and (
                        ix, iy) not in world.buildings:
                            world.nodes.append(ResourceNode(res, nx, ny))
                            break

    if progress: progress(1.0)
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


def build_tile_surface(world):
    surface = pygame.Surface((COLS, ROWS)).convert()
    rng = random.Random(world.seed)

    for y in range(ROWS):
        for x in range(COLS):
            height = world.heights[y][x]
            color = terrain(height)[1]
            if (x, y) in world.roads: color = ROAD
            shade = rng.randint(-5, 5) if height > -0.4 else 0

            if height >= SEA_LEVEL and (x, y) not in world.roads:
                left = world.heights[y][max(0, x - 1)]
                above = world.heights[max(0, y - 1)][x]
                slope = left + above - 2 * height
                shade += int(max(-20, min(20, slope * 55)))

            color = tuple(max(0, min(255, channel + shade)) for channel in color)
            surface.set_at((x, y), color)
    return surface


def generate_ports(world):
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
    return ports


# ---------------- OYUNCU HAREKETI ----------------

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
            if can_stand(world, x + 0.5, y + 0.5, False): return pygame.Vector2(x + 0.5, y + 0.5)

    for y in range(ROWS):
        for x in range(COLS):
            if can_stand(world, x + 0.5, y + 0.5, False):
                if SAND_LEVEL <= world.heights[y][x] < MOUNTAIN_LEVEL:
                    return pygame.Vector2(x + 0.5, y + 0.5)
    raise RuntimeError("Uygun kara bulunamadi.")


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


# ---------------- CIZIM ----------------

def draw_text(screen, font, text, position, color=(235, 240, 245)):
    screen.blit(font.render(text, True, color), position)


def draw_house(screen, rect):
    pygame.draw.rect(screen, (44, 48, 39), rect.move(2, 3))
    pygame.draw.rect(screen, (208, 181, 132), (rect.x + 2, rect.y + 9, rect.w - 4, rect.h - 9))
    pygame.draw.polygon(screen, (137, 65, 47),
                        [(rect.x, rect.y + 12), (rect.centerx, rect.y + 1), (rect.right, rect.y + 12)])
    pygame.draw.rect(screen, (67, 47, 32), (rect.centerx - 3, rect.bottom - 8, 6, 8))


def draw_node(screen, node, camera_x, camera_y):
    screen_x = int(node.x * LOCAL_TILE_SIZE - camera_x)
    screen_y = int(node.y * LOCAL_TILE_SIZE - camera_y)
    if not (0 <= screen_x <= SCREEN_W and 0 <= screen_y <= SCREEN_H): return

    if node.type == "Odun":
        pygame.draw.rect(screen, (80, 50, 20), (screen_x - 4, screen_y - 20, 8, 20))
        pygame.draw.circle(screen, (34, 139, 34), (screen_x, screen_y - 25), 15)
    elif node.type == "Tas":
        pygame.draw.circle(screen, (120, 120, 120), (screen_x - 5, screen_y - 5), 10)
        pygame.draw.circle(screen, (150, 150, 150), (screen_x + 5, screen_y - 2), 8)
    elif node.type == "Tahil":
        for i in range(-5, 6, 5):
            pygame.draw.line(screen, (218, 165, 32), (screen_x + i, screen_y),
                             (screen_x + i + random.randint(-2, 2), screen_y - 15), 2)


def draw_player(screen, position, moving, facing, color_override=None, is_sailing=False, boat_angle=0.0):
    scale = 1.6

    if is_sailing:
        boat = pygame.Surface((20 * scale, 30 * scale), pygame.SRCALPHA)
        pygame.draw.ellipse(boat, (120, 80, 50), (0, 0, 20 * scale, 30 * scale))
        pygame.draw.rect(boat, (200, 190, 180), (4 * scale, 10 * scale, 12 * scale, 10 * scale))

        # Orijinal koda karsi rotasyon duzeltmesi
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

    camera_x = max(0, min(target_x - SCREEN_W / 2, COLS * LOCAL_TILE_SIZE - SCREEN_W))
    camera_y = max(0, min(target_y - SCREEN_H / 2, ROWS * LOCAL_TILE_SIZE - SCREEN_H))
    return camera_x, camera_y


def draw_local_view(screen, world, tiles, player, network, is_sailing, camera_x, camera_y, boat_angle):
    start_x = int(camera_x // LOCAL_TILE_SIZE)
    start_y = int(camera_y // LOCAL_TILE_SIZE)
    visible_cols = min(COLS - start_x, math.ceil(SCREEN_W / LOCAL_TILE_SIZE) + 2)
    visible_rows = min(ROWS - start_y, math.ceil(SCREEN_H / LOCAL_TILE_SIZE) + 2)

    region = tiles.subsurface((start_x, start_y, visible_cols, visible_rows))
    enlarged = pygame.transform.scale(region, (visible_cols * LOCAL_TILE_SIZE, visible_rows * LOCAL_TILE_SIZE))
    screen.blit(enlarged, (round(start_x * LOCAL_TILE_SIZE - camera_x), round(start_y * LOCAL_TILE_SIZE - camera_y)))

    for x, y in world.buildings:
        if start_x <= x < start_x + visible_cols and start_y <= y < start_y + visible_rows:
            rect = pygame.Rect(round(x * LOCAL_TILE_SIZE - camera_x), round(y * LOCAL_TILE_SIZE - camera_y),
                               LOCAL_TILE_SIZE, LOCAL_TILE_SIZE)
            draw_house(screen, rect)

    for node in world.nodes:
        if node.active:
            draw_node(screen, node, camera_x, camera_y)

    previous = getattr(draw_local_view, "_previous_position", (player.x, player.y))
    dx = player.x - previous[0]
    dy = player.y - previous[1]
    moving = abs(dx) + abs(dy) > 0.0001
    facing = getattr(draw_local_view, "_facing", "down")

    if moving:
        if abs(dx) > abs(dy):
            facing = "right" if dx > 0 else "left"
        else:
            facing = "down" if dy > 0 else "up"

    draw_local_view._previous_position = (player.x, player.y)
    draw_local_view._facing = facing

    players_to_draw = []
    my_screen_pos = (player.x * LOCAL_TILE_SIZE - camera_x, player.y * LOCAL_TILE_SIZE - camera_y)

    players_to_draw.append({
        "y": player.y,
        "pos": my_screen_pos,
        "moving": moving,
        "facing": facing,
        "color": None,
        "is_sailing": is_sailing,
        "is_me": True,
        "boat_angle": boat_angle
    })

    for pid, pdata in network.other_players.items():
        other_screen_pos = (pdata["x"] * LOCAL_TILE_SIZE - camera_x, pdata["y"] * LOCAL_TILE_SIZE - camera_y)
        players_to_draw.append({
            "y": pdata["y"],
            "pos": other_screen_pos,
            "moving": pdata["moving"],
            "facing": pdata["facing"],
            "color": (60, 100, 150),
            "is_sailing": pdata.get("sailing", False),
            "is_me": False,
            "boat_angle": pdata.get("boat_angle", 0.0)
        })

    players_to_draw.sort(key=lambda p: p["y"])

    for p in players_to_draw:
        draw_player(screen, p["pos"], p["moving"], p["facing"], p["color"], p["is_sailing"], p.get("boat_angle", 0.0))
        if not p["is_me"]:
            font = pygame.font.Font(None, 20)
            text_surf = font.render("Diger Oyuncu", True, (255, 255, 255))
            screen.blit(text_surf, (p["pos"][0] - 25, p["pos"][1] - 55))

    return facing, moving


def draw_world_map(screen, world, map_surface, map_rect, player, network):
    screen.blit(map_surface, map_rect)

    for island in world.islands:
        if island.village:
            x, y = island.village.center
            pos = (round(map_rect.x + (x + 0.5) * MAP_TILE_SIZE), round(map_rect.y + (y + 0.5) * MAP_TILE_SIZE))
            pygame.draw.circle(screen, (44, 32, 23), pos, 4)
            pygame.draw.circle(screen, (245, 201, 107), pos, 3)

    for pid, pdata in network.other_players.items():
        marker = pygame.Rect(0, 0, 7, 7)
        marker.center = (round(map_rect.x + pdata["x"] * MAP_TILE_SIZE), round(map_rect.y + pdata["y"] * MAP_TILE_SIZE))
        pygame.draw.rect(screen, (255, 255, 255), marker.inflate(4, 4))
        pygame.draw.rect(screen, (220, 50, 50), marker)

    marker = pygame.Rect(0, 0, 7, 7)
    marker.center = (round(map_rect.x + player.x * MAP_TILE_SIZE), round(map_rect.y + player.y * MAP_TILE_SIZE))
    pygame.draw.rect(screen, (255, 255, 255), marker.inflate(4, 4))
    pygame.draw.rect(screen, (0, 0, 0), marker)


def draw_ports(screen, ports, player, camera_x, camera_y):
    tile = LOCAL_TILE_SIZE

    for port in ports:
        shore_x = round((port.x + 0.5) * tile - camera_x)
        shore_y = round((port.y + 0.5) * tile - camera_y)

        if not (-tile * 4 < shore_x < SCREEN_W + tile * 4 and -tile * 4 < shore_y < SCREEN_H + tile * 4): continue

        for step in range(1, 4):
            cx = shore_x + port.dx * step * tile
            cy = shore_y + port.dy * step * tile
            if port.dx:
                rect = pygame.Rect(cx - tile // 2, cy - 7, tile, 14)
            else:
                rect = pygame.Rect(cx - 7, cy - tile // 2, 14, tile)

            pygame.draw.rect(screen, (30, 40, 40), rect.move(3, 4))
            pygame.draw.rect(screen, (135, 93, 57), rect)
            pygame.draw.rect(screen, (81, 57, 38), rect, 1)

            if port.dx:
                for offset in range(4, tile, 6): pygame.draw.line(screen, (86, 59, 38), (rect.x + offset, rect.y),
                                                                  (rect.x + offset, rect.bottom - 1))
            else:
                for offset in range(4, tile, 6): pygame.draw.line(screen, (86, 59, 38), (rect.x, rect.y + offset),
                                                                  (rect.right - 1, rect.y + offset))


# ---------------- UCUSAN YAPRAKLAR ----------------
class AutumnLeaves:
    def __init__(self, seed, count=36):
        self.rng = random.Random(seed + 9981)
        self.leaves = []
        for _ in range(count): self.leaves.append(self.new_leaf(initial=True))

    def new_leaf(self, initial=False):
        return {
            "x": self.rng.uniform(0, SCREEN_W) if initial else self.rng.uniform(-150, SCREEN_W),
            "y": self.rng.uniform(0, SCREEN_H) if initial else self.rng.uniform(-100, -15),
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
            if leaf["y"] > SCREEN_H + 20 or leaf["x"] > SCREEN_W + 30: self.leaves[index] = self.new_leaf()

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


# ---------------- SINIR BOZUCU MINI OYUNLAR ----------------

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
        self.valid_rect.center = (SCREEN_W // 2, SCREEN_H // 2)
        self.start_rect.topleft = self.valid_rect.topleft
        self.end_rect.topright = self.valid_rect.topright

    def close(self):
        self.active = False
        self.dragging = False

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.start_rect.collidepoint(event.pos):
                self.dragging = True
                self.message = "Surukle! Ruzgara karsi diren!"
            else:
                self.message = "Once soldaki yesil alana basili tutmalisin!"
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                if self.end_rect.collidepoint(event.pos):
                    self.message = "Harika! Tahili topladin."
                    self.node.active = False
                    self.node.cooldown = random.uniform(30, 40)
                    self.close()
                else:
                    self.message = "Yarim biraktin! Ekinler ziyan oldu."
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                if not self.valid_rect.collidepoint(event.pos):
                    self.dragging = False
                    self.message = "Tirpan elinden kaydi! Ruzgar ekinleri ezdi."

    def update(self, dt):
        if not self.active: return
        self.wind_timer -= dt
        if self.wind_timer <= 0:
            self.wind_timer = self.rng.uniform(0.15, 0.3)
            if self.dragging:
                mx, my = pygame.mouse.get_pos()
                push = self.rng.choice([-1, 1]) * self.rng.uniform(30, 70)
                pygame.mouse.set_pos((mx, int(my + push)))

    def draw_ui(self, screen, font):
        if not self.active: return
        panel_rect = pygame.Rect(SCREEN_W // 2 - 320, SCREEN_H // 2 - 120, 640, 240)
        pygame.draw.rect(screen, (32, 39, 41, 230), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (186, 149, 91), panel_rect, width=2, border_radius=8)
        pygame.draw.rect(screen, (70, 90, 60), self.valid_rect)
        pygame.draw.rect(screen, (100, 120, 90), self.valid_rect, width=2)
        pygame.draw.rect(screen, (100, 200, 100) if not self.dragging else (60, 140, 60), self.start_rect)
        pygame.draw.rect(screen, (200, 100, 100), self.end_rect)
        draw_text(screen, font, self.message, (SCREEN_W // 2 - 300, SCREEN_H // 2 - 100), (244, 218, 165))
        if self.dragging:
            mx, my = pygame.mouse.get_pos()
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
            tx = random.randint(SCREEN_W // 2 - 200, SCREEN_W // 2 + 200)
            ty = random.randint(SCREEN_H // 2 - 150, SCREEN_H // 2 + 150)
            self.targets.append(pygame.Rect(tx, ty, 40, 40))

    def close(self):
        self.active = False

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_e, pygame.K_q):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = False
            for t in self.targets[:]:
                if t.collidepoint(event.pos):
                    self.targets.remove(t)
                    hit = True
                    break

            # Geri tepme - Fare imlecini rastgele koseye firlat
            corners = [(50, 50), (SCREEN_W - 50, 50), (50, SCREEN_H - 50), (SCREEN_W - 50, SCREEN_H - 50)]
            rx, ry = random.choice(corners)
            rx += random.randint(-20, 20)
            ry += random.randint(-20, 20)
            pygame.mouse.set_pos([rx, ry])

            if hit and len(self.targets) == 0:
                self.node.active = False
                self.node.cooldown = random.uniform(30, 40)
                self.close()

    def draw_ui(self, screen, font):
        if not self.active: return
        panel_rect = pygame.Rect(SCREEN_W // 2 - 250, SCREEN_H // 2 - 200, 500, 400)
        pygame.draw.rect(screen, (50, 50, 50, 230), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (100, 100, 100), panel_rect, width=2, border_radius=8)
        draw_text(screen, font, self.message, (SCREEN_W // 2 - 180, SCREEN_H // 2 - 180), (255, 255, 255))

        for t in self.targets:
            pygame.draw.circle(screen, (200, 50, 50), t.center, 20)
            pygame.draw.line(screen, (50, 50, 50), (t.centerx - 10, t.centery - 10), (t.centerx + 10, t.centery + 10),
                             3)
            pygame.draw.line(screen, (50, 50, 50), (t.centerx - 10, t.centery + 10), (t.centerx + 10, t.centery - 10),
                             3)


class WoodChopping:
    def __init__(self):
        self.active = False
        self.node = None
        self.bar_pos = 0.0
        self.bar_speed = 600.0
        self.direction = 1
        self.state = "QTE"  # "QTE" veya "STUCK"
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
                # Yesil alan kontrolu (Bar genisligi 400, yesil bolge 180-220)
                if 180 <= self.bar_pos <= 220:
                    self.node.active = False
                    self.node.cooldown = random.uniform(30, 40)
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
                            self.node.active = False
                            self.node.cooldown = random.uniform(30, 40)
                            self.close()
        return player_exhaust_timer

    def update(self, dt):
        if not self.active: return
        if self.state == "QTE":
            self.bar_pos += self.bar_speed * self.direction * dt
            if self.bar_pos >= 400 or self.bar_pos <= 0:
                self.direction *= -1
        elif self.state == "STUCK":
            self.stuck_timer -= dt
            if self.stuck_timer <= 0:
                self.close()
                return 4.0  # Player exhausted for 4 seconds
        return 0.0

    def draw_ui(self, screen, font):
        if not self.active: return
        panel_rect = pygame.Rect(SCREEN_W // 2 - 250, SCREEN_H // 2 - 100, 500, 200)
        pygame.draw.rect(screen, (60, 40, 30, 230), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (150, 100, 50), panel_rect, width=2, border_radius=8)

        draw_text(screen, font, self.message, (SCREEN_W // 2 - 230, SCREEN_H // 2 - 80), (255, 255, 255))

        if self.state == "QTE":
            pygame.draw.rect(screen, (100, 100, 100), (SCREEN_W // 2 - 200, SCREEN_H // 2, 400, 30))
            pygame.draw.rect(screen, (50, 200, 50), (SCREEN_W // 2 - 20, SCREEN_H // 2, 40, 30))
            pygame.draw.rect(screen, (200, 200, 200), (SCREEN_W // 2 - 200 + self.bar_pos, SCREEN_H // 2 - 5, 10, 40))
        elif self.state == "STUCK":
            draw_text(screen, font, f"Zaman: {self.stuck_timer:.1f} | Basim: {self.zc_count}/20",
                      (SCREEN_W // 2 - 100, SCREEN_H // 2 + 20), (255, 50, 50))


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
        pygame.draw.rect(screen, (32, 39, 41, 200), (SCREEN_W // 2 - 200, SCREEN_H - 100, 400, 60), border_radius=8)
        pygame.draw.rect(screen, (186, 149, 91), (SCREEN_W // 2 - 200, SCREEN_H - 100, 400, 60), width=2,
                         border_radius=8)
        draw_text(screen, font, self.message, (SCREEN_W // 2 - 180, SCREEN_H - 80), (244, 218, 165))


# ---------------- OYUN ANA DONGUSU ----------------

def main(server_ip, server_port):
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Sonbahar Adalari - Multiplayer (Troll Edition)")

    font = pygame.font.Font(None, 24)
    small_font = pygame.font.Font(None, 21)
    clock = pygame.time.Clock()

    bg_path = LOADING_BACKGROUND
    if not bg_path.is_file():
        raise FileNotFoundError(f"Gerekli yükleme arka planı bulunamadı: {bg_path}")
    try:
        loading_bg = pygame.image.load(str(bg_path)).convert()
        loading_bg = pygame.transform.scale(loading_bg, (SCREEN_W, SCREEN_H))
    except pygame.error as e:
        raise RuntimeError(f"Arkaplan görseli yüklenemedi ({bg_path}): {e}") from e

    map_button = pygame.Rect(SCREEN_W - 174, 14, 160, 44)
    map_open = False
    is_sailing = False

    boat_angle = 0.0
    boat_speed = 0.0
    turn_speed = 0.0

    player_exhaust_timer = 0.0

    def progress(fraction):
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                raise SystemExit

        if loading_bg:
            screen.blit(loading_bg, (0, 0))
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 80))
            screen.blit(overlay, (0, 0))
        else:
            screen.fill((32, 39, 41))

        panel_w, panel_h = 440, 140
        panel_x = (SCREEN_W - panel_w) // 2
        panel_y = (SCREEN_H - panel_h) // 2 + 100

        pygame.draw.rect(screen, (40, 28, 18, 220), (panel_x, panel_y, panel_w, panel_h), border_radius=10)
        pygame.draw.rect(screen, (190, 110, 40), (panel_x, panel_y, panel_w, panel_h), width=3, border_radius=10)

        text_surface = font.render(f"DUNYA OLUSTURULUYOR... {fraction:.0%}", True, (244, 218, 165))
        screen.blit(text_surface, text_surface.get_rect(center=(SCREEN_W // 2, panel_y + 35)))

        bar_w, bar_h = 360, 24
        bar_x = (SCREEN_W - bar_w) // 2
        bar_y = panel_y + 75
        pygame.draw.rect(screen, (24, 15, 8), (bar_x, bar_y, bar_w, bar_h), border_radius=5)
        pygame.draw.rect(screen, (139, 74, 30), (bar_x, bar_y, bar_w, bar_h), width=2, border_radius=5)

        if fraction > 0:
            fill_w = int((bar_w - 6) * fraction)
            if fill_w > 0: pygame.draw.rect(screen, (211, 118, 43), (bar_x + 3, bar_y + 3, fill_w, bar_h - 6),
                                            border_radius=3)

        pygame.display.flip()

    try:
        network = Network(host=server_ip, port=server_port)

        world = make_world(network.seed, progress)
        ports = generate_ports(world)
        player = pygame.Vector2(ports[0].spawn if ports else find_spawn(world))

        draw_local_view._previous_position = (player.x, player.y)
        draw_local_view._facing = "down"

        tiles = build_tile_surface(world)
        world_map = pygame.transform.scale(tiles, (COLS * MAP_TILE_SIZE, ROWS * MAP_TILE_SIZE))
        map_rect = world_map.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2))

        leaves = AutumnLeaves(network.seed)
        fishing = OpenWaterFishing(network.seed)

        grain_game = GrainHarvesting(network.seed)
        stone_game = StoneMining()
        wood_game = WoodChopping()

        port_trigger_ready = True

        def nearby_port():
            closest, closest_distance = None, float("inf")
            for port in ports:
                distance = math.hypot(player.x - (port.x + 0.5), player.y - (port.y + 0.5))
                if distance < closest_distance: closest_distance, closest = distance, port
            return closest, closest_distance

        clock.tick()
        running = True
        net_timer = 0.0
        current_facing = "down"
        current_moving = False

        cam_x, cam_y = get_local_camera(player)

        while running:
            dt = min(clock.tick(60) / 1000.0, 0.05)

            if player_exhaust_timer > 0:
                player_exhaust_timer -= dt

            # Kaynak dügümlerinin yeniden dogusu (Cooldown)
            for node in world.nodes:
                if not node.active:
                    node.cooldown -= dt
                    if node.cooldown <= 0:
                        node.active = True

            target_cam_x, target_cam_y = get_local_camera(player, fishing)
            cam_x += (target_cam_x - cam_x) * 4 * dt
            cam_y += (target_cam_y - cam_y) * 4 * dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT: running = False; continue
                if fishing.active: fishing.handle_event(event); continue
                if grain_game.active: grain_game.handle_event(event); continue
                if stone_game.active: stone_game.handle_event(event); continue
                if wood_game.active:
                    penalty = wood_game.handle_event(event, player_exhaust_timer)
                    if penalty > 0: player_exhaust_timer = penalty
                    continue

                if event.type == pygame.KEYDOWN:
                    if is_sailing and not map_open:
                        # Tekne İvmelenmesi
                        if event.key == pygame.K_a:
                            boat_speed += 3.5
                            turn_speed -= 2.0
                        elif event.key == pygame.K_d:
                            boat_speed += 3.5
                            turn_speed += 2.0

                    if event.key == pygame.K_m:
                        map_open = not map_open
                    elif event.key == pygame.K_ESCAPE:
                        if map_open:
                            map_open = False
                        else:
                            running = False
                    elif event.key == pygame.K_e and not map_open and not is_sailing:
                        # Limandaysa Balıkçılık
                        port, distance = nearby_port()
                        if port and distance < 1.6:
                            fishing.open(port, player)
                            port_trigger_ready = False
                        else:
                            # Kaynak node'larina yakinlik kontrolu
                            for node in world.nodes:
                                if node.active:
                                    dist = math.hypot(player.x - node.x, player.y - node.y)
                                    if dist < 1.5:
                                        if node.type == "Odun":
                                            wood_game.open(node)
                                        elif node.type == "Tas":
                                            stone_game.open(node)
                                        elif node.type == "Tahil":
                                            grain_game.open(node)
                                        break

                    elif event.key == pygame.K_f and not map_open:
                        port, distance = nearby_port()
                        if port and distance < 2.5:
                            is_sailing = not is_sailing
                            if is_sailing:
                                player.x = port.x + port.dx * 1.5 + 0.5
                                player.y = port.y + port.dy * 1.5 + 0.5
                                boat_speed = 0.0
                                turn_speed = 0.0
                            else:
                                player.x = port.spawn[0]
                                player.y = port.spawn[1]

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1 and map_button.collidepoint(event.pos): map_open = not map_open

            # Herhangi bir minigame aktif degilse hareket var
            if not map_open and not fishing.active and not grain_game.active and not stone_game.active and not wood_game.active:
                if is_sailing:
                    # Surtunme
                    boat_speed *= 0.95
                    turn_speed *= 0.88

                    boat_angle += turn_speed * dt

                    dx = math.cos(boat_angle) * boat_speed * dt
                    dy = math.sin(boat_angle) * boat_speed * dt

                    if can_stand(world, player.x + dx, player.y, is_sailing):
                        player.x += dx
                    else:
                        boat_speed *= 0.2

                    if can_stand(world, player.x, player.y + dy, is_sailing):
                        player.y += dy
                    else:
                        boat_speed *= 0.2
                else:
                    if player_exhaust_timer <= 0:
                        keys = pygame.key.get_pressed()
                        direction = pygame.Vector2(
                            int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(
                                keys[pygame.K_a] or keys[pygame.K_LEFT]),
                            int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]),
                        )
                        move_player(world, player, direction, dt, is_sailing)

                port, distance = nearby_port()
                if distance > 2.2: port_trigger_ready = True
                if port is not None and distance < 1.4 and port_trigger_ready and not is_sailing:
                    fishing.open(port, player)
                    port_trigger_ready = False

            if not map_open:
                leaves.update(dt)
                mx, my = pygame.mouse.get_pos()
                real_mx, real_my = mx, my
                if fishing.zoom_level > 1.01:
                    cx, cy = SCREEN_W // 2, SCREEN_H // 2
                    real_mx = cx + (mx - cx) / fishing.zoom_level
                    real_my = cy + (my - cy) / fishing.zoom_level

                fishing.update(dt, real_mx + cam_x, real_my + cam_y, world)
                grain_game.update(dt)
                if wood_game.active:
                    res = wood_game.update(dt)
                    if res and res > 0: player_exhaust_timer = res

            screen.fill((32, 39, 41))

            if map_open:
                draw_world_map(screen, world, world_map, map_rect, player, network)
            else:
                current_facing, current_moving = draw_local_view(screen, world, tiles, player, network, is_sailing,
                                                                 cam_x, cam_y, boat_angle)
                draw_ports(screen, ports, player, cam_x, cam_y)
                leaves.draw(screen)

                fishing.draw_world(screen, cam_x, cam_y, player)

                if fishing.zoom_level > 1.01:
                    zoom = fishing.zoom_level
                    w, h = SCREEN_W, SCREEN_H
                    new_w, new_h = int(w / zoom), int(h / zoom)
                    sub_rect = pygame.Rect((w - new_w) // 2, (h - new_h) // 2, new_w, new_h)
                    zoomed_surface = pygame.transform.scale(screen.subsurface(sub_rect).copy(), (w, h))
                    screen.blit(zoomed_surface, (0, 0))

                fishing.draw_ui(screen, font)
                grain_game.draw_ui(screen, font)
                stone_game.draw_ui(screen, font)
                wood_game.draw_ui(screen, font)

                if player_exhaust_timer > 0:
                    draw_text(screen, font, f"YORGUNLUK! ({player_exhaust_timer:.1f}s)",
                              (SCREEN_W // 2 - 70, SCREEN_H // 2 - 50), (255, 50, 50))

            net_timer += dt
            if net_timer >= 0.05:
                network.send_and_receive(player.x, player.y, current_facing, current_moving, is_sailing, boat_angle)
                net_timer = 0.0

            pygame.draw.rect(screen, (32, 39, 41), (0, SCREEN_H - 30, SCREEN_W, 30))

            px, py = int(player.x), int(player.y)
            owner = world.owners[py][px]
            current_island = world.islands[owner] if owner >= 0 else None
            location = current_island.name if current_island else "Deniz"

            info = f"{location} | Online: {len(network.other_players)}"

            port, distance = nearby_port()
            if port is not None and distance < 2.5:
                info += " | E: balik tut | F: gemiye bin/in"
            elif is_sailing:
                info += " | A: Sol Kurek | D: Sag Kurek"
            else:
                info += " | WASD: Yuru | Kaynak yaninda E: Topla"

            draw_text(screen, small_font, info, (12, SCREEN_H - 23), (229, 219, 193))

            mx, my = pygame.mouse.get_pos()
            hovered = map_button.collidepoint(mx, my)
            button_color = (100, 91, 67) if hovered else (65, 66, 54)
            pygame.draw.rect(screen, button_color, map_button, border_radius=7)
            pygame.draw.rect(screen, (181, 158, 111), map_button, width=1, border_radius=7)
            label = "Haritayi kapat" if map_open else "Harita [M]"
            label_surface = font.render(label, True, (241, 228, 198))
            screen.blit(label_surface, label_surface.get_rect(center=map_button.center))

            pygame.display.flip()

    finally:
        pygame.quit()


if __name__ == "__main__":
    print("=" * 45)
    print(" SONBAHAR ADALARI - MULTIPLAYER (TROLL SURUMU)")
    print("=" * 45)
    print("Farkli bir bilgisayara baglanmak icin sunucuyu kuran kisinin")
    print("yerel IP adresini (orn: 192.168.1.X) girmelisiniz.")
    print("Ayni bilgisayarda test ediyorsaniz bos birakip Enter'a basin.\n")

    user_ip = input("Sunucu IP adresi (Varsayilan 127.0.0asd): ").strip()
    user_port = input("Sunucu Portu (Varsayilan 5555): ").strip()

    SERVER_IP = user_ip if user_ip else '127.0.0.1'
    SERVER_PORT = int(user_port) if user_port else 5555

    print(f"\n[BILGI] Baglaniliyor -> {SERVER_IP}:{SERVER_PORT} ...")
    print("=" * 45)

    main(SERVER_IP, SERVER_PORT)
