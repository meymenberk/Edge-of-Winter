"""Small, cached pixel artwork for the gameplay HUD and world charts."""
from functools import lru_cache

import pygame

from worldgen import COLS, ROWS, SEA_LEVEL, MOUNTAIN_LEVEL

INK = (30, 19, 17)
GOLD = (245, 207, 128)
CREAM = (255, 237, 194)
MUTED = (187, 148, 105)

# Original 5 x 7 bitmap alphabet. No host fonts, smoothing, or external assets.
GLYPHS = dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /%+-.:[]?",
    [
        "0E11111F111111", "1E11111E11111E", "0F10101010100F", "1E11111111111E",
        "1F10101E10101F", "1F10101E101010", "0F10101711110F", "1111111F111111",
        "0E04040404040E", "0702020212120C", "11121418141211", "1010101010101F",
        "111B1515111111", "11191915131311", "0E11111111110E", "1E11111E101010",
        "0E11111115120D", "1E11111E141211", "0F10100E01011E", "1F040404040404",
        "1111111111110E", "11111111110A04", "1111111515150A", "11110A040A1111",
        "11110A04040404", "1F01020408101F",
        "0E11131519110E", "040C040404040E", "0E11010204081F", "1E01010601011E",
        "02060A121F0202", "1F10101E01011E", "0E10101E11110E", "1F010204080808",
        "0E11110E11110E", "0E11110F01010E",
        "00000000000000", "01010204081010", "19190204081313", "0004041F040400",
        "0000001F000000", "00000000000C0C", "000C0C000C0C00", "0E08080808080E",
        "0E02020202020E", "0E110102040004",
    ], strict=True))
# Turkish HUD labels retain their accents in an eleven-row cell.
ACCENTS = {"İ": ("I", "dot"), "Ç": ("C", "tail"), "Ş": ("S", "tail"),
           "Ö": ("O", "dots"), "Ü": ("U", "dots"), "Ğ": ("G", "breve")}


@lru_cache(maxsize=512)
def pixel_text(text, scale=2, color=CREAM):
    text = str(text).upper()
    surface = pygame.Surface((max(1, len(text) * 6 - 1), 11), pygame.SRCALPHA)
    for index, char in enumerate(text):
        base, accent = ACCENTS.get(char, (char, None))
        bitmap = GLYPHS.get(base, GLYPHS["?"])
        for y in range(7):
            bits = int(bitmap[y * 2:y * 2 + 2], 16)
            for x in range(5):
                if bits & (1 << (4 - x)):
                    surface.set_at((index * 6 + x, y + 2), color)
        if accent == "dot":
            surface.set_at((index * 6 + 2, 0), color)
        elif accent in ("dots", "breve"):
            for x in (1, 3):
                surface.set_at((index * 6 + x, 0), color)
            if accent == "breve":
                surface.set_at((index * 6 + 2, 1), color)
        elif accent == "tail":
            surface.set_at((index * 6 + 2, 9), color)
            surface.set_at((index * 6 + 1, 10), color)
    return pygame.transform.scale(surface, (surface.get_width() * scale, 11 * scale))


def label(screen, text, pos, scale=2, color=CREAM):
    screen.blit(pixel_text(text, scale, INK), (pos[0] + scale, pos[1] + scale))
    screen.blit(pixel_text(text, scale, color), pos)


def panel(screen, rect, hovered=False):
    rect = pygame.Rect(rect)
    pygame.draw.rect(screen, INK, rect.move(3, 3))
    pygame.draw.rect(screen, (104, 65, 37), rect)
    pygame.draw.rect(screen, (220, 164, 88) if hovered else (172, 119, 65), rect, 2)
    pygame.draw.rect(screen, (65, 41, 28) if hovered else (47, 31, 24), rect.inflate(-6, -6))
    pygame.draw.line(screen, (112, 75, 43), (rect.x + 4, rect.y + 4), (rect.right - 5, rect.y + 4))
    for x in (rect.left + 2, rect.right - 4):
        for y in (rect.top + 2, rect.bottom - 4):
            pygame.draw.rect(screen, GOLD, (x, y, 2, 2))


@lru_cache(maxsize=16)
def icon(kind):
    """Draw at 16px, then scale by an integer to preserve hard pixel edges."""
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    def box(color, rect):
        pygame.draw.rect(s, color, rect)
    def shape(color, points):
        pygame.draw.polygon(s, color, points)
    brown, light, dark = (157, 88, 41), (225, 166, 87), (79, 44, 27)
    if kind == "bag":
        box(INK, (5, 1, 6, 5)); box(light, (6, 2, 4, 3)); box(INK, (7, 3, 2, 2))
        shape(INK, [(4, 4), (12, 4), (14, 7), (14, 14), (2, 14), (2, 7)])
        box(brown, (3, 7, 10, 6)); box(light, (4, 5, 8, 4)); box(dark, (4, 9, 8, 1))
        box(GOLD, (7, 8, 3, 3)); box(dark, (8, 9, 1, 1)); box(light, (4, 11, 1, 2))
    elif kind == "Odun":
        shape(INK, [(1, 9), (9, 2), (14, 3), (16, 7), (7, 15), (2, 14)])
        shape(brown, [(2, 9), (10, 3), (13, 4), (14, 7), (6, 13), (3, 13)])
        pygame.draw.line(s, light, (4, 9), (11, 4), 2)
        pygame.draw.line(s, dark, (7, 11), (14, 6))
        box(dark, (2, 9, 6, 5)); box(light, (2, 10, 5, 3)); box(brown, (4, 11, 2, 1))
    elif kind == "Tas":
        shape(INK, [(1, 11), (4, 5), (9, 2), (13, 5), (15, 12), (12, 14), (3, 14)])
        shape((112, 112, 111), [(2, 11), (5, 6), (9, 3), (12, 6), (14, 11), (11, 13), (3, 13)])
        shape((190, 183, 163), [(3, 10), (6, 6), (9, 4), (11, 7), (8, 10)])
        box((143, 144, 136), (9, 9, 3, 3)); box((220, 212, 186), (6, 6, 2, 2))
    elif kind == "Tahil":
        pygame.draw.line(s, dark, (7, 14), (7, 2), 3)
        pygame.draw.line(s, light, (7, 14), (7, 2))
        for y in (3, 6, 9):
            shape(dark, [(7, y + 3), (3, y + 1), (3, y - 2), (7, y)])
            shape(GOLD, [(6, y + 1), (4, y), (4, y - 1), (6, y)])
            shape(dark, [(8, y + 3), (12, y + 1), (12, y - 2), (8, y)])
            shape((232, 167, 50), [(8, y + 1), (11, y), (11, y - 1), (8, y)])
        box(GOLD, (7, 1, 2, 3)); box(light, (5, 13, 6, 1))
    elif kind == "Balik":
        shape(INK, [(1, 4), (5, 6), (8, 3), (12, 4), (15, 8), (12, 12), (8, 13), (5, 10), (1, 12)])
        shape((75, 137, 145), [(2, 6), (6, 8), (9, 4), (12, 5), (14, 8), (11, 11), (8, 12), (6, 9), (2, 10)])
        shape((152, 206, 189), [(6, 7), (9, 5), (12, 6), (13, 8), (8, 9)])
        box(INK, (11, 6, 1, 1)); box((229, 159, 80), (7, 10, 3, 2))
    elif kind == "Ada":
        box((54, 115, 136), (1, 12, 14, 3)); box(GOLD, (3, 10, 10, 3))
        box((116, 133, 72), (5, 9, 6, 2)); box(INK, (6, 1, 2, 10))
        box(light, (6, 2, 1, 8)); shape((226, 106, 53), [(8, 2), (14, 2), (12, 4), (14, 6), (8, 6)])
        box(GOLD, (8, 2, 4, 1))
    elif kind == "Enflasyon":
        for x, y in ((1, 10), (5, 7), (9, 4)):
            box(INK, (x, y, 4, 5)); box((192, 128, 48), (x + 1, y, 3, 4)); box(GOLD, (x + 1, y, 2, 1))
        pygame.draw.lines(s, (234, 139, 79), False, [(2, 7), (7, 2), (13, 2)], 1)
        shape(GOLD, [(11, 0), (15, 2), (11, 4)])
    elif kind == "trade":
        shape((161, 184, 101), [(2, 3), (10, 3), (10, 1), (15, 5), (10, 8), (10, 6), (2, 6)])
        shape(GOLD, [(14, 10), (6, 10), (6, 8), (1, 12), (6, 15), (6, 13), (14, 13)])
    return pygame.transform.scale(s, (32, 32))


class PixelHUD:
    def __init__(self):
        self.inventory_button = pygame.Rect(14, 14, 62, 40)
        self.trade_button = pygame.Rect(82, 14, 62, 40)
        self.items = [(key, pygame.Rect(152 + i * 116, 14, 110, 40)) for i, key in enumerate(
            ("Odun", "Tas", "Tahil", "Balik", "Ada", "Enflasyon"))]

    def draw(self, screen, mouse, inventory, rescued, target, inflation):
        tooltip = None
        for rect, kind, key, title in ((self.inventory_button, "bag", "I", "ÇANTA [I / TAB]"),
                                       (self.trade_button, "trade", "T", "TİCARET [T]")):
            panel(screen, rect, rect.collidepoint(mouse))
            screen.blit(icon(kind), (rect.x + 5, rect.y + 4))
            label(screen, key, (rect.x + 42, rect.y + 9), color=GOLD)
            if rect.collidepoint(mouse):
                tooltip = (rect, title)
        names = {"Odun": "ODUN", "Tas": "TAŞ", "Tahil": "TAHIL", "Balik": "BALIK",
                 "Ada": "KURTARILAN ADA", "Enflasyon": "ERZAK MALİYET ARTIŞI"}
        for kind, rect in self.items:
            value = (f"{rescued}/{target}" if kind == "Ada" else f"+{inflation}%" if kind == "Enflasyon"
                     else str(inventory.get(kind, 0)))
            panel(screen, rect, rect.collidepoint(mouse))
            screen.blit(icon(kind), (rect.x + 5, rect.y + 4))
            # Exact counts remain readable when the inventory grows; no clipped digits.
            scale = 2 if pixel_text(value).get_width() <= rect.width - 44 else 1
            display = value if pixel_text(value, scale).get_width() <= rect.width - 44 else value[:7] + "+"
            label(screen, display, (rect.x + 42, rect.centery - 11 * scale // 2), scale)
            if rect.collidepoint(mouse):
                tooltip = (rect, f"{names[kind]}: {value}")
        if tooltip:
            rect, text = tooltip
            width = pixel_text(text).get_width() + 20
            tip = pygame.Rect(min(rect.x, screen.get_width() - width - 14), rect.bottom + 8, width, 34)
            panel(screen, tip)
            label(screen, text, (tip.x + 10, tip.y + 5), color=GOLD)


class WorldMapUI:
    """Static geography is cached once; only markers are redrawn each frame."""
    def __init__(self, world, tiles, width, height):
        self.world = world
        self.art = tiles.copy()
        # Forest tint is terrain, not a claim that every tree is still unharvested.
        for (x, y), density in world.woodland.items():
            if density > .56 and (x, y) not in world.roads:
                if SEA_LEVEL <= world.heights[y][x] < MOUNTAIN_LEVEL:
                    self.art.set_at((x, y), (153, 107, 46) if (x + y) % 3 else (180, 121, 43))
        for x, y in world.buildings:
            self.art.set_at((x, y), (247, 220, 160))
        self.minimap_rect = pygame.Rect(width - 234, 14, 220, 164)
        self.mini_rect = pygame.Rect(width - 224, 40, 200, 120)
        self.mini_surface = pygame.transform.scale(self.art, self.mini_rect.size)
        scale = min((width - 100) / COLS, (height - 120) / ROWS)
        self.full_surface = pygame.transform.scale(self.art, (round(COLS * scale), round(ROWS * scale)))
        self.full_rect = self.full_surface.get_rect(center=(width // 2, height // 2 + 10))
        self.close_rect = pygame.Rect(self.full_rect.right - 106, self.full_rect.top - 42, 106, 32)

    @staticmethod
    def position(rect, x, y):
        # Clamp world-edge markers to the last map pixel, never into its frame.
        return (rect.x + max(0, min(rect.width - 1, int(x / COLS * rect.width))),
                rect.y + max(0, min(rect.height - 1, int(y / ROWS * rect.height))))

    def markers(self, screen, rect, player, network, owners, my_id, small=False, camera=None):
        previous_clip = screen.get_clip()
        screen.set_clip(rect.clip(previous_clip))
        if camera is not None:
            x, y, width, height = camera
            left, top = self.position(rect, x, y)
            right, bottom = self.position(rect, x + width, y + height)
            pygame.draw.rect(screen, (143, 198, 184), (left, top, max(2, right - left), max(2, bottom - top)), 1)
        for index, island in enumerate(self.world.islands):
            center = island.village.center if island.village else (island.x, island.y)
            pos = self.position(rect, center[0] + .5, center[1] + .5)
            owner = owners.get(index)
            color = ((255, 220, 78) if owner == my_id else (226, 90, 78)) if owner is not None else (214, 193, 149)
            size = 3 if small else 7
            marker = pygame.Rect(0, 0, size, size)
            marker.center = pos
            pygame.draw.rect(screen, INK, marker.inflate(2, 2))
            pygame.draw.rect(screen, color, marker)
        for port in self.world.ports or ():
            x, y = self.position(rect, port.x + .5, port.y + .5)
            pygame.draw.rect(screen, (177, 239, 235), (x - 1, y - 1, 2 if small else 4, 2 if small else 4))
        if network and network.connected:
            with network.lock:
                players = [dict(p) for p in network.other_players.values()]
            for data in players:
                pos = self.position(rect, data["x"], data["y"])
                marker = pygame.Rect(0, 0, 3 if small else 7, 3 if small else 7)
                marker.center = pos
                pygame.draw.rect(screen, INK, marker.inflate(2, 2))
                pygame.draw.rect(screen, (243, 132, 159), marker)
        x, y = self.position(rect, player.x, player.y)
        radius = 3 if small else 6
        points = [(x, y - radius - 2), (x + radius + 2, y), (x, y + radius + 2), (x - radius - 2, y)]
        pygame.draw.polygon(screen, INK, points)
        pygame.draw.polygon(screen, CREAM, [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)])
        pygame.draw.rect(screen, (39, 90, 97), (x - 1, y - 1, 3, 3))
        screen.set_clip(previous_clip)

    def draw_mini(self, screen, mouse, player, network, owners, my_id, camera):
        panel(screen, self.minimap_rect, self.minimap_rect.collidepoint(mouse))
        label(screen, "ADALAR / N", (self.minimap_rect.x + 10, self.minimap_rect.y + 4), scale=1, color=GOLD)
        label(screen, "M", (self.minimap_rect.right - 23, self.minimap_rect.y + 2), color=GOLD)
        screen.blit(self.mini_surface, self.mini_rect)
        self.markers(screen, self.mini_rect, player, network, owners, my_id, small=True, camera=camera)
        label(screen, "DÜNYA HARİTASI", (self.minimap_rect.x + 10, self.mini_rect.bottom + 1), scale=1, color=MUTED)

    def draw_full(self, screen, mouse, player, network, owners, my_id):
        screen.fill((26, 26, 26))
        panel(screen, self.full_rect.inflate(12, 12))
        header = pygame.Rect(self.full_rect.x - 6, self.full_rect.y - 48, self.full_rect.width + 12, 40)
        panel(screen, header)
        count = sum(owner == my_id for owner in owners.values())
        label(screen, f"SONBAHAR ADALARI   /   KURTARILAN {count}/6", (header.x + 12, header.y + 8), color=GOLD)
        if network and network.connected:
            with network.lock:
                player_ids = list(network.other_players)
            scores = " / ".join(f"OYUNCU {pid}: {sum(str(o) == str(pid) for o in owners.values())}/6"
                                for pid in player_ids)
            # Preserve the live multiplayer scoreboard without covering Close.
            available = max(0, (self.close_rect.left - header.x - 570) // 6)
            if len(scores) > available:
                scores = scores[:max(0, available - 3)] + "..."
            label(screen, scores, (header.x + 556, header.y + 14), scale=1, color=MUTED)
        panel(screen, self.close_rect, self.close_rect.collidepoint(mouse))
        label(screen, "M / ESC", (self.close_rect.x + 12, self.close_rect.y + 5), scale=2)
        screen.blit(self.full_surface, self.full_rect)
        self.markers(screen, self.full_rect, player, network, owners, my_id)
        legend = pygame.Rect(header.x, self.full_rect.bottom + 8, header.width, 26)
        panel(screen, legend)
        # Color keys correspond to live map markers, including remote players.
        keys = [(CREAM, "SEN"), ((243, 132, 159), "OYUNCU"), ((255, 220, 78), "SENİN ADAN"),
                ((226, 90, 78), "RAKİP ADA"), ((214, 193, 149), "SAHİPSİZ"), ((177, 239, 235), "LİMAN")]
        for index, (color, title) in enumerate(keys):
            x = legend.x + 14 + index * 170
            pygame.draw.rect(screen, color, (x, legend.y + 9, 7, 7))
            label(screen, title, (x + 14, legend.y + 6), scale=1)
