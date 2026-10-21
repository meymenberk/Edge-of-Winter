"""Small, cached pixel artwork for the gameplay HUD and world charts."""
from dataclasses import dataclass
from functools import lru_cache
import math

import pygame

from .localization import item_name, tr
from .worldgen import COLS, ROWS, SEA_LEVEL, MOUNTAIN_LEVEL

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
# Punctuation used by the English HUD labels.
GLYPHS.update({
    "!": "04040404040004", ",": "000000000C0408", "'": "04040800000000",
    "(": "02040808080402", ")": "08040202020408", "&": "0C12140815120D",
    "=": "00001F001F0000",
})
# Accented capitals (e.g. developer names) retain their marks in an eleven-row cell.
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


# Shared medieval-autumn window palette.  Every modal, popup and notification
# uses these square-cornered frames so the whole game shares one pixel style.
WOOD_DARK = (47, 31, 24)
WOOD = (104, 65, 37)
WOOD_LIGHT = (172, 119, 65)
WOOD_HOVER = (220, 164, 88)
PARCHMENT = (236, 220, 187)
TONES = {
    "wood": ((111, 58, 30), (151, 82, 40), (238, 178, 73)),
    "green": ((54, 92, 46), (74, 124, 58), (156, 214, 120)),
    "red": ((112, 40, 30), (146, 56, 38), (232, 120, 92)),
    "disabled": ((55, 45, 39), (55, 45, 39), (102, 82, 66)),
}


def pixel_overlay(screen, color=(10, 6, 4), alpha=170):
    """Dim the scene behind a modal window."""
    veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    veil.fill((*color[:3], alpha))
    screen.blit(veil, (0, 0))


def pixel_window(screen, rect, title=None, font=None, accent=WOOD_LIGHT,
                 title_color=GOLD, alpha=None, header=34):
    """Draw a framed wooden window with hard pixel corners and an optional title bar.

    Returns the inner content rectangle below the title bar.
    """
    rect = pygame.Rect(rect)
    pygame.draw.rect(screen, INK, rect.move(4, 4))
    pygame.draw.rect(screen, INK, rect)
    pygame.draw.rect(screen, WOOD, rect.inflate(-4, -4))
    pygame.draw.rect(screen, accent, rect.inflate(-4, -4), 2)
    body = rect.inflate(-12, -12)
    if alpha is None:
        pygame.draw.rect(screen, WOOD_DARK, body)
    else:
        fill = pygame.Surface(body.size, pygame.SRCALPHA)
        fill.fill((*WOOD_DARK, alpha))
        screen.blit(fill, body)
    pygame.draw.line(screen, (130, 86, 48), (body.x, body.y), (body.right - 1, body.y))
    for x in (rect.left + 3, rect.right - 5):
        for y in (rect.top + 3, rect.bottom - 5):
            pygame.draw.rect(screen, GOLD, (x, y, 2, 2))
    content = body.copy()
    if title:
        bar = pygame.Rect(body.x, body.y, body.width, header)
        pygame.draw.rect(screen, (66, 38, 24), bar)
        pygame.draw.line(screen, accent, (bar.x, bar.bottom), (bar.right - 1, bar.bottom), 2)
        if font is None:
            text = pixel_text(title, 2, title_color)
            shadow = pixel_text(title, 2, INK)
        else:
            text = font.render(title, False, title_color)
            shadow = font.render(title, False, INK)
        pos = text.get_rect(midleft=(bar.x + 12, bar.centery))
        screen.blit(shadow, pos.move(1, 1))
        screen.blit(text, pos)
        content.top = bar.bottom + 2
        content.height = body.bottom - content.top
    return content


def pixel_box(screen, rect, fill=(30, 18, 14), border=(103, 74, 45)):
    """Inset card used inside windows."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(screen, fill, rect)
    pygame.draw.rect(screen, border, rect, 1)
    pygame.draw.line(screen, INK, (rect.x + 1, rect.bottom), (rect.right, rect.bottom))
    pygame.draw.line(screen, INK, (rect.right, rect.y + 1), (rect.right, rect.bottom))
    return rect


def pixel_button(screen, rect, text, font=None, hovered=False, enabled=True, tone="wood",
                 text_color=None):
    """Chunky bevelled button; ``font=None`` uses the bitmap HUD alphabet."""
    rect = pygame.Rect(rect)
    base, hover, edge = TONES["disabled" if not enabled else tone]
    pygame.draw.rect(screen, INK, rect.move(2, 2))
    pygame.draw.rect(screen, INK, rect)
    pygame.draw.rect(screen, hover if hovered and enabled else base, rect.inflate(-4, -4))
    pygame.draw.line(screen, edge, (rect.x + 2, rect.y + 2), (rect.right - 3, rect.y + 2))
    pygame.draw.line(screen, edge, (rect.x + 2, rect.y + 2), (rect.x + 2, rect.bottom - 3))
    color = text_color or ((255, 239, 190) if enabled else (150, 135, 125))
    if font is None:
        art = pixel_text(text, 1 if rect.height < 30 else 2, color)
        if art.get_width() > rect.width - 8:
            art = pixel_text(text, 1, color)
        screen.blit(art, art.get_rect(center=rect.center))
    else:
        art = font.render(text, False, color)
        screen.blit(art, art.get_rect(center=(rect.centerx, rect.centery + 1)))
    return rect


def pixel_bar(screen, rect, ratio, fill, background=(24, 16, 14), border=(140, 100, 50)):
    """Square progress bar with a one-pixel highlight."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(screen, background, rect)
    width = round(rect.width * max(0.0, min(1.0, ratio)))
    if width:
        pygame.draw.rect(screen, fill, (rect.x, rect.y, width, rect.height))
        light = tuple(min(255, c + 45) for c in fill[:3])
        pygame.draw.line(screen, light, (rect.x, rect.y), (rect.x + width - 1, rect.y))
    pygame.draw.rect(screen, border, rect, 1)
    return rect


@dataclass(frozen=True)
class InteractionHint:
    """One actionable world target selected by the game's input priority."""

    key: str
    action: str
    world_pos: tuple[float, float]
    kind: str = ""


class PixelInteractionPrompt:
    """Cached, crisp world-space keycap prompt; no host font or texture needed."""

    @staticmethod
    @lru_cache(maxsize=64)
    def surface(key: str, action: str) -> pygame.Surface:
        key = str(key).upper()
        action = str(action).upper()
        action_art = pixel_text(action, 1, CREAM)
        key_art = pixel_text(key, 2, (255, 244, 184))
        key_width = max(25, key_art.get_width() + 12)
        width = key_width + action_art.get_width() + 24
        height = 39
        art = pygame.Surface((width + 3, height + 3), pygame.SRCALPHA)

        # Chunky shadow, wooden speech plate, and one-pixel shine keep the
        # result aligned with the existing HUD while remaining unobtrusive.
        pygame.draw.rect(art, (25, 15, 15, 205), (3, 3, width, 33))
        pygame.draw.rect(art, INK, (0, 0, width, 33))
        pygame.draw.rect(art, (108, 65, 37), (2, 2, width - 4, 29))
        pygame.draw.rect(art, (49, 31, 25), (4, 4, width - 8, 25))
        pygame.draw.line(art, (181, 123, 62), (5, 4), (width - 6, 4))
        for x in (5, width - 7):
            pygame.draw.rect(art, GOLD, (x, 6, 2, 2))

        key_rect = pygame.Rect(7, 6, key_width, 21)
        pygame.draw.rect(art, (25, 16, 17), key_rect.move(2, 2))
        pygame.draw.rect(art, (227, 179, 91), key_rect)
        pygame.draw.rect(art, (116, 70, 39), key_rect, 2)
        pygame.draw.line(art, (255, 224, 139), key_rect.topleft,
                         (key_rect.right - 2, key_rect.top))
        art.blit(key_art, key_art.get_rect(center=(key_rect.centerx, key_rect.centery - 1)))
        art.blit(action_art, (key_rect.right + 10, 11))

        # Three square pixels form a tiny speech-bubble pointer.
        pygame.draw.rect(art, INK, (width // 2 - 4, 33, 9, 2))
        pygame.draw.rect(art, INK, (width // 2 - 2, 35, 5, 2))
        pygame.draw.rect(art, INK, (width // 2, 37, 1, 1))
        pygame.draw.rect(art, (108, 65, 37), (width // 2 - 2, 33, 5, 2))
        return art

    def draw(self, screen: pygame.Surface, hint: InteractionHint,
             camera: tuple[float, float], tile_size: int,
             bottom_margin: int = 36) -> pygame.Rect:
        art = self.surface(hint.key, hint.action)
        anchor_x = round(hint.world_pos[0] * tile_size - camera[0])
        anchor_y = round(hint.world_pos[1] * tile_size - camera[1])
        rect = art.get_rect(midbottom=(anchor_x, anchor_y))
        bounds = pygame.Rect(7, 7, max(1, screen.get_width() - 14),
                             max(1, screen.get_height() - bottom_margin - 7))
        rect.clamp_ip(bounds)
        screen.blit(art, rect)
        return rect


def heart_states(health, maximum):
    """Map any existing health scale to ten half-heart units."""
    units = max(0, min(10, int(round(float(health) / max(1, maximum) * 10))))
    return tuple(2 if units >= index + 2 else 1 if units == index + 1 else 0
                 for index in range(0, 10, 2))


@lru_cache(maxsize=3)
def heart_icon(state):
    tiny = pygame.Surface((9, 8), pygame.SRCALPHA)
    shape = ((1, 0), (3, 0), (4, 1), (5, 0), (7, 0), (8, 1), (8, 3),
             (7, 4), (7, 5), (6, 5), (6, 6), (5, 6), (5, 7), (3, 7),
             (3, 6), (2, 6), (2, 5), (1, 5), (1, 4), (0, 3), (0, 1))
    pygame.draw.polygon(tiny, INK, shape)
    inner = ((1, 1), (3, 1), (4, 2), (5, 1), (7, 1), (7, 3), (6, 4),
             (6, 5), (5, 5), (4, 7), (3, 5), (2, 5), (2, 4), (1, 3))
    pygame.draw.polygon(tiny, (68, 42, 38), inner)
    if state:
        fill = pygame.Surface((9, 8), pygame.SRCALPHA)
        pygame.draw.polygon(fill, (205, 54, 52), inner)
        if state == 1:
            fill.fill((0, 0, 0, 0), (5, 0, 4, 8))
        tiny.blit(fill, (0, 0))
        pygame.draw.rect(tiny, (255, 131, 93), (2, 1, 2, 1))
        if state == 2:
            pygame.draw.rect(tiny, (135, 34, 38), (6, 3, 1, 2))
    return pygame.transform.scale(tiny, (18, 16))


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
        for rect, kind, key, title in ((self.inventory_button, "bag", "I", tr("hud.inventory")),
                                       (self.trade_button, "trade", "T", tr("hud.trade"))):
            panel(screen, rect, rect.collidepoint(mouse))
            screen.blit(icon(kind), (rect.x + 5, rect.y + 4))
            label(screen, key, (rect.x + 42, rect.y + 9), color=GOLD)
            if rect.collidepoint(mouse):
                tooltip = (rect, title)
        names = {"Odun": item_name("Odun"), "Tas": item_name("Tas"),
                 "Tahil": item_name("Tahil"), "Balik": item_name("Balik"),
                 "Ada": tr("hud.islands"), "Enflasyon": tr("hud.inflation")}
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

    def draw_health(self, screen, health, maximum, pos=(14, 60)):
        rect = pygame.Rect(pos, (150, 28))
        panel(screen, rect)
        label(screen, tr("hud.health"), (rect.x + 7, rect.y + 8), scale=1, color=GOLD)
        for index, state in enumerate(heart_states(health, maximum)):
            screen.blit(heart_icon(state), (rect.x + 48 + index * 19, rect.y + 6))


class WorldMapUI:
    """Cached pixel chart with independent full-map and rescue-map cameras."""
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
        self.size = None
        self.resize(width, height)
        self.views = {
            "full": dict(zoom=1.0, center=[COLS / 2, ROWS / 2], dragging=False, last=None),
            "rescue": dict(zoom=2.2, center=[COLS / 2, ROWS / 2], dragging=False, last=None),
        }

    def resize(self, width, height):
        """Re-anchor the minimap (top-right) and the centred chart to a view size."""
        if self.size == (width, height):
            return
        self.size = (width, height)
        self.minimap_rect = pygame.Rect(width - 234, 14, 220, 164)
        self.mini_rect = pygame.Rect(width - 224, 40, 200, 120)
        scale = min((width - 100) / COLS, (height - 120) / ROWS)
        self.full_surface = pygame.transform.scale(self.art, (round(COLS * scale), round(ROWS * scale)))
        self.full_rect = self.full_surface.get_rect(center=(width // 2, height // 2 + 10))
        self.close_rect = pygame.Rect(self.full_rect.right - 106, self.full_rect.top - 42, 106, 32)

    @staticmethod
    def position(rect, x, y):
        # Clamp world-edge markers to the last map pixel, never into its frame.
        return (rect.x + max(0, min(rect.width - 1, int(x / COLS * rect.width))),
                rect.y + max(0, min(rect.height - 1, int(y / ROWS * rect.height))))

    @staticmethod
    def view_position(rect, source, x, y):
        return (round(rect.x + (x - source.x) / source.width * rect.width),
                round(rect.y + (y - source.y) / source.height * rect.height))

    def _source_rect(self, rect, view):
        state = self.views[view]
        aspect = rect.width / rect.height
        base_w, base_h = COLS, ROWS
        if base_w / base_h > aspect:
            base_w = ROWS * aspect
        else:
            base_h = COLS / aspect
        width, height = base_w / state["zoom"], base_h / state["zoom"]
        cx = max(width / 2, min(COLS - width / 2, state["center"][0]))
        cy = max(height / 2, min(ROWS - height / 2, state["center"][1]))
        state["center"][:] = cx, cy
        return pygame.Rect(round(cx - width / 2), round(cy - height / 2),
                           max(1, round(width)), max(1, round(height))).clip((0, 0, COLS, ROWS))

    def focus(self, view, position):
        self.views[view]["center"][:] = float(position[0]), float(position[1])
        self.stop_drag(view)

    def stop_drag(self, view):
        """Release a chart grab when its panel closes mid-drag."""
        self.views[view]["dragging"] = False
        self.views[view]["last"] = None

    def handle_event(self, event, mouse, view, rect):
        state = self.views[view]
        if event.type == pygame.MOUSEWHEEL and rect.collidepoint(mouse):
            old_source = self._source_rect(rect, view)
            world_x = old_source.x + (mouse[0] - rect.x) / rect.width * old_source.width
            world_y = old_source.y + (mouse[1] - rect.y) / rect.height * old_source.height
            maximum = 7.0 if view == "full" else 8.0
            state["zoom"] = max(1.0, min(maximum, state["zoom"] * (1.22 ** event.y)))
            new_source = self._source_rect(rect, view)
            after_x = new_source.x + (mouse[0] - rect.x) / rect.width * new_source.width
            after_y = new_source.y + (mouse[1] - rect.y) / rect.height * new_source.height
            state["center"][0] += world_x - after_x
            state["center"][1] += world_y - after_y
            self._source_rect(rect, view)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and rect.collidepoint(mouse):
            state["dragging"], state["last"] = True, mouse
            return True
        if event.type == pygame.MOUSEMOTION and state["dragging"]:
            source = self._source_rect(rect, view)
            last = state["last"] or mouse
            state["center"][0] -= (mouse[0] - last[0]) * source.width / rect.width
            state["center"][1] -= (mouse[1] - last[1]) * source.height / rect.height
            state["last"] = mouse
            self._source_rect(rect, view)
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and state["dragging"]:
            state["dragging"], state["last"] = False, None
            return True
        return False

    def _draw_region(self, screen, rect, source):
        sample = self.art.subsurface(source).copy()
        screen.blit(pygame.transform.scale(sample, rect.size), rect)

    def _labels(self, screen, rect, source, player, limit):
        occupied = []
        visible = []
        for island in self.world.islands:
            x, y = island.village.center if island.village else (island.x, island.y)
            if source.collidepoint(x, y):
                visible.append((math.dist((player.x, player.y), (x, y)), island, x, y))
        for _, island, x, y in sorted(visible)[:limit]:
            text = pixel_text(island.name, 1, CREAM)
            px, py = self.view_position(rect, source, x, y)
            label_rect = text.get_rect(midbottom=(px, py - 5)).inflate(6, 4)
            label_rect.clamp_ip(rect.inflate(-4, -4))
            if any(label_rect.colliderect(other.inflate(4, 2)) for other in occupied):
                continue
            occupied.append(label_rect)
            pygame.draw.rect(screen, (29, 22, 20), label_rect)
            pygame.draw.rect(screen, (150, 104, 57), label_rect, 1)
            screen.blit(text, text.get_rect(center=label_rect.center))

    def markers(self, screen, rect, player, network, owners, my_id, small=False, camera=None, source=None):
        previous_clip = screen.get_clip()
        screen.set_clip(rect.clip(previous_clip))
        source = source or pygame.Rect(0, 0, COLS, ROWS)
        project = lambda x, y: self.view_position(rect, source, x, y)
        if camera is not None:
            x, y, width, height = camera
            left, top = project(x, y)
            right, bottom = project(x + width, y + height)
            pygame.draw.rect(screen, (143, 198, 184), (left, top, max(2, right - left), max(2, bottom - top)), 1)
        for index, island in enumerate(self.world.islands):
            center = island.village.center if island.village else (island.x, island.y)
            if not source.collidepoint(center):
                continue
            pos = project(center[0] + .5, center[1] + .5)
            owner = owners.get(index)
            color = ((255, 220, 78) if owner == my_id else (226, 90, 78)) if owner is not None else (214, 193, 149)
            size = 3 if small else 7
            marker = pygame.Rect(0, 0, size, size)
            marker.center = pos
            pygame.draw.rect(screen, INK, marker.inflate(2, 2))
            pygame.draw.rect(screen, color, marker)
        for port in self.world.ports or ():
            if not source.collidepoint(port.x, port.y):
                continue
            x, y = project(port.x + .5, port.y + .5)
            pygame.draw.rect(screen, (177, 239, 235), (x - 1, y - 1, 2 if small else 4, 2 if small else 4))
        if network and network.connected:
            with network.lock:
                players = [dict(p) for p in network.other_players.values()]
            for data in players:
                if not source.collidepoint(data["x"], data["y"]):
                    continue
                pos = project(data["x"], data["y"])
                marker = pygame.Rect(0, 0, 3 if small else 7, 3 if small else 7)
                marker.center = pos
                pygame.draw.rect(screen, INK, marker.inflate(2, 2))
                pygame.draw.rect(screen, (243, 132, 159), marker)
        if source.collidepoint(player.x, player.y):
            x, y = project(player.x, player.y)
            radius = 3 if small else 6
            points = [(x, y - radius - 2), (x + radius + 2, y), (x, y + radius + 2), (x - radius - 2, y)]
            pygame.draw.polygon(screen, INK, points)
            pygame.draw.polygon(screen, CREAM, [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)])
            pygame.draw.rect(screen, (39, 90, 97), (x - 1, y - 1, 3, 3))
        screen.set_clip(previous_clip)

    def draw_mini(self, screen, mouse, player, network, owners, my_id, camera):
        panel(screen, self.minimap_rect, self.minimap_rect.collidepoint(mouse))
        label(screen, tr("hud.nearby"), (self.minimap_rect.x + 10, self.minimap_rect.y + 4), scale=1, color=GOLD)
        label(screen, "M", (self.minimap_rect.right - 23, self.minimap_rect.y + 2), color=GOLD)
        source = pygame.Rect(round(player.x - 64), round(player.y - 38), 128, 76)
        source.clamp_ip((0, 0, COLS, ROWS))
        self._draw_region(screen, self.mini_rect, source)
        self._labels(screen, self.mini_rect, source, player, 3)
        self.markers(screen, self.mini_rect, player, network, owners, my_id, small=True,
                     camera=camera, source=source)
        label(screen, tr("hud.world_map"), (self.minimap_rect.x + 10, self.mini_rect.bottom + 1), scale=1, color=MUTED)

    def draw_full(self, screen, mouse, player, network, owners, my_id):
        screen.fill((26, 26, 26))
        panel(screen, self.full_rect.inflate(12, 12))
        header = pygame.Rect(self.full_rect.x - 6, self.full_rect.y - 48, self.full_rect.width + 12, 40)
        panel(screen, header)
        count = sum(owner == my_id for owner in owners.values())
        label(screen, tr("map.title", count=count), (header.x + 12, header.y + 8), color=GOLD)
        if network and network.connected:
            with network.lock:
                player_ids = list(network.other_players)
            scores = " / ".join(tr("map.score", pid=pid,
                                   count=sum(str(o) == str(pid) for o in owners.values()))
                                for pid in player_ids)
            # Preserve the live multiplayer scoreboard without covering Close.
            available = max(0, (self.close_rect.left - header.x - 570) // 6)
            if len(scores) > available:
                scores = scores[:max(0, available - 3)] + "..."
            label(screen, scores, (header.x + 556, header.y + 14), scale=1, color=MUTED)
        panel(screen, self.close_rect, self.close_rect.collidepoint(mouse))
        label(screen, tr("map.close"), (self.close_rect.x + 12, self.close_rect.y + 5), scale=2)
        source = self._source_rect(self.full_rect, "full")
        self._draw_region(screen, self.full_rect, source)
        self._labels(screen, self.full_rect, source, player, 18 if self.views["full"]["zoom"] > 1.25 else 10)
        self.markers(screen, self.full_rect, player, network, owners, my_id, source=source)
        label(screen, tr("map.controls", zoom=self.views['full']['zoom']),
              (self.full_rect.x + 10, self.full_rect.y + 8), scale=1, color=CREAM)
        legend = pygame.Rect(header.x, self.full_rect.bottom + 8, header.width, 26)
        panel(screen, legend)
        # Color keys correspond to live map markers, including remote players.
        keys = [(CREAM, tr("map.legend_you")), ((243, 132, 159), tr("map.legend_player")),
                ((255, 220, 78), tr("map.legend_yours")), ((226, 90, 78), tr("map.legend_rival")),
                ((214, 193, 149), tr("map.legend_unclaimed")), ((177, 239, 235), tr("map.legend_harbor"))]
        for index, (color, title) in enumerate(keys):
            x = legend.x + 14 + index * 170
            pygame.draw.rect(screen, color, (x, legend.y + 9, 7, 7))
            label(screen, title, (x + 14, legend.y + 6), scale=1)

    def draw_rescue(self, screen, rect, player, network, owners, my_id, title=True):
        rect = pygame.Rect(rect)
        source = self._source_rect(rect, "rescue")
        self._draw_region(screen, rect, source)
        self._labels(screen, rect, source, player, 6)
        self.markers(screen, rect, player, network, owners, my_id, small=True, source=source)
        pygame.draw.rect(screen, (220, 164, 88), rect, 2)
        if title:
            pygame.draw.rect(screen, (35, 25, 21), (rect.x + 2, rect.y + 2, rect.width - 4, 17))
            pygame.draw.rect(screen, (35, 25, 21), (rect.x + 2, rect.bottom - 18, rect.width - 4, 16))
            label(screen, tr("map.chart", zoom=self.views['rescue']['zoom']),
                  (rect.x + 8, rect.y + 6), scale=1, color=GOLD)
            label(screen, tr("map.chart_controls"), (rect.x + 8, rect.bottom - 15), scale=1, color=CREAM)
