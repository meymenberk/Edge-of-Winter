"""Extraction and dt-driven playback of the supplied manchar walking illustration.

The inspected sheet has four separated rows (down/right/up/left), four poses each,
large outer margins, and nonuniform frame spacing. It is not a 4x4 image grid.
"""
from functools import lru_cache
from pathlib import Path
import unicodedata
import numpy as np
import pygame

from .paths import PROJECT_ROOT

DIRECTIONS = ('down', 'right', 'up', 'left')
EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')
CANONICAL_CHARACTER_ASSET = Path('assets') / 'characters' / 'player' / 'manchar.jpeg'


def find_character_asset(directory):
    root = Path(directory).expanduser()
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    canonical = root / CANONICAL_CHARACTER_ASSET
    if canonical.is_file():
        return canonical
    candidates = []
    for path in root.rglob('*'):
        if not path.is_file() or any(part.startswith('.') for part in path.relative_to(root).parts):
            continue
        name = unicodedata.normalize('NFC', path.stem).casefold().strip()
        if name.startswith('manchar') and path.suffix.casefold() in EXTENSIONS:
            candidates.append(path)
    return min(candidates, key=lambda p: (p.stem.casefold() != 'manchar',
               len(p.relative_to(root).parts), EXTENSIONS.index(p.suffix.casefold()), str(p).casefold()), default=None)


def _bands(occupied, minimum, gap):
    indices = np.flatnonzero(occupied)
    if not len(indices):
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > gap) + 1)
    return [(int(group[0]), int(group[-1]) + 1) for group in groups if len(group) >= minimum]


class CharacterSheet:
    SIZE = (40, 56)
    ANCHOR = (20, 54)

    def __init__(self, filepath):
        self.path = Path(filepath)
        raw = pygame.image.load(str(filepath)).convert_alpha()
        rgb = pygame.surfarray.array3d(raw).astype(np.int16)
        alpha = pygame.surfarray.array_alpha(raw)
        # The JPEG paper is ~247 gray, with compression ringing near the outline.
        # Binary coverage removes that paper without blurring colored sprite pixels.
        foreground = ((rgb.min(2) < 212) | (rgb.max(2) - rgb.min(2) > 32)) & (alpha > 0)
        rows = _bands(foreground.sum(axis=0) > 20, minimum=20, gap=10)
        if len(rows) != 4:
            raise ValueError(f'{filepath}: expected four directional artwork rows, found {len(rows)}')
        crops = {}
        self.source_rects = {}
        for direction, (top, bottom) in zip(DIRECTIONS, rows):
            columns = _bands(foreground[:, top:bottom].sum(axis=1) > 8, minimum=20, gap=10)
            if len(columns) != 4:
                raise ValueError(f'{filepath}: expected four {direction} poses, found {len(columns)}')
            crops[direction] = []
            self.source_rects[direction] = []
            for left, right in columns:
                coverage = foreground[left:right, top:bottom]
                xs, ys = np.nonzero(coverage)
                x0, x1 = left + xs.min(), left + xs.max() + 1
                y0, y1 = top + ys.min(), top + ys.max() + 1
                rect = pygame.Rect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
                sprite = raw.subsurface(rect).copy()
                pixels = pygame.surfarray.pixels_alpha(sprite)
                pixels[:] = foreground[x0:x1, y0:y1] * 255
                del pixels
                # Align the torso rather than moving hands/boots or the hair silhouette.
                silhouette = foreground[x0:x1, y0:y1]
                centers = []
                for y in range(int(rect.height * .48), int(rect.height * .70)):
                    occupied = np.flatnonzero(silhouette[:, y])
                    if len(occupied):
                        centers.append((occupied[0] + occupied[-1] + 1) / 2)
                anchor_x = float(np.median(centers))
                crops[direction].append((sprite, anchor_x))
                self.source_rects[direction].append(rect)
        # One scale for all sixteen poses; no per-frame stretching.
        scale = 26 / max(sprite.get_height() for row in crops.values() for sprite, _ in row)
        self.frames = {}
        for direction, row in crops.items():
            self.frames[direction] = []
            for sprite, anchor_x in row:
                size = (max(1, round(sprite.get_width() * scale)), max(1, round(sprite.get_height() * scale)))
                art = pygame.transform.scale(sprite, size)
                canvas = pygame.Surface((20, 28), pygame.SRCALPHA)
                canvas.blit(art, (10 - round(anchor_x * scale), 27 - size[1]))
                self.frames[direction].append(pygame.transform.scale(canvas, self.SIZE))
        self.shadow = pygame.Surface((30, 10), pygame.SRCALPHA)
        pygame.draw.ellipse(self.shadow, (29, 23, 18, 85), self.shadow.get_rect())

    def draw(self, screen, position, animation):
        x, y = round(position[0]), round(position[1])
        frame = self.frames[animation.facing][animation.frame]
        screen.blit(self.shadow, (x - 15, y - 4))
        screen.blit(frame, (x - self.ANCHOR[0], y - self.ANCHOR[1]))


@lru_cache(maxsize=4)
def load_character_sheet(directory):
    path = find_character_asset(directory)
    # Only a genuinely absent asset uses the existing fallback. A broken supplied
    # sheet reports an error during preload rather than silently using a placeholder.
    return CharacterSheet(path) if path else None


class CharacterAnimator:
    def __init__(self):
        self.facing = 'down'
        self.phase = 0.0
        self.moving = False

    @property
    def frame(self):
        return int(self.phase + 1e-9) % 4 if self.moving else 0

    def update(self, dt, moving, facing, speed=4.5):
        facing = facing if facing in DIRECTIONS else self.facing
        if facing != self.facing or not moving:
            self.phase = 0.0
        self.facing = facing
        self.moving = bool(moving)
        if self.moving:
            # Slow the gait on high ground; cap teleports/network corrections.
            fps = max(4.0, min(10.0, 8.0 * speed / 4.5))
            self.phase = (self.phase + max(0, dt) * fps) % 4
