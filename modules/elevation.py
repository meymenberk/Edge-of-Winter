"""Connected visual elevation derived from the existing authoritative height field.

No coordinates, walkability, resources, or network state change. Faces are inset
inside mountain footprints, so terrain and actor ground anchors stay consistent.
"""
from collections import deque
import numpy as np
import pygame
from .worldgen import MOUNTAIN_LEVEL

THRESHOLDS = (MOUNTAIN_LEVEL, 0.65, 0.81)
FACE_DEPTHS = (22, 16, 12)  # art pixels: 44 / 32 / 24 screen pixels
ART_TILE = 24


def prepare_elevation(world):
    heights = np.asarray(world.heights)
    mountain = heights >= MOUNTAIN_LEVEL
    levels = np.zeros(heights.shape, np.uint8)
    for tier, threshold in enumerate(THRESHOLDS, 1):
        region = heights >= threshold
        if tier > 1:
            # Remove isolated spikes; keep larger nested contours, not random blocks.
            padded = np.pad(region, 1)
            count = sum(padded[dy:dy + region.shape[0], dx:dx + region.shape[1]].astype(np.uint8)
                        for dy in range(3) for dx in range(3))
            region &= count >= 5
        levels[region] = tier
    # Broad access aprons prevent tall faces beside doors or across an open route.
    protected = np.zeros(heights.shape, bool)
    for x, y in world.roads | world.buildings:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if 0 <= y + dy < heights.shape[0] and 0 <= x + dx < heights.shape[1]:
                    protected[y + dy, x + dx] = True
    levels[protected] = 0
    # Access aprons can split a contour. Leave tiny remnants as rocky ground,
    # instead of making fake boulder-like pillars near the village.
    for tier, minimum in ((1, 12), (2, 8), (3, 5)):
        region = levels >= tier
        visited = np.zeros(region.shape, bool)
        for sy, sx in zip(*np.nonzero(region)):
            if visited[sy, sx]:
                continue
            pending = deque([(int(sx), int(sy))])
            visited[sy, sx] = True
            component = []
            while pending:
                x, y = pending.popleft()
                component.append((x, y))
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if (0 <= nx < region.shape[1] and 0 <= ny < region.shape[0]
                            and region[ny, nx] and not visited[ny, nx]):
                        visited[ny, nx] = True
                        pending.append((nx, ny))
            if len(component) < minimum:
                for x, y in component:
                    levels[y, x] = tier - 1
    world.elevation_data = (levels, mountain & ~protected)
    return world.elevation_data


class MountainRenderer:
    """Compose tier tops/walls/shadows once when a terrain chunk enters its cache."""
    def __init__(self, world, atlas):
        self.levels, self.allowed = getattr(world, 'elevation_data', None) or prepare_elevation(world)
        self.wall = pygame.surfarray.array3d(atlas.cliff_texture).transpose(1, 0, 2)
        self.atlas = atlas

    def compose_chunk(self, chunk, cx, cy, tiles_per_chunk):
        start_x, start_y = cx * tiles_per_chunk, cy * tiles_per_chunk
        if not self.levels[start_y:start_y + tiles_per_chunk, start_x:start_x + tiles_per_chunk].any():
            return
        size = tiles_per_chunk * ART_TILE
        pad = max(FACE_DEPTHS) + 2
        gx = start_x * ART_TILE + np.arange(-pad, size + pad)
        gy = start_y * ART_TILE + np.arange(-pad, size + pad)
        tx, ty = (gx + .5) / ART_TILE - .5, (gy + .5) / ART_TILE - .5
        ix, iy = np.floor(tx).astype(int), np.floor(ty).astype(int)
        fx, fy = tx - ix, ty - iy
        rows, cols = self.levels.shape
        ix0, ix1 = ix.clip(0, cols - 1), (ix + 1).clip(0, cols - 1)
        iy0, iy1 = iy.clip(0, rows - 1), (iy + 1).clip(0, rows - 1)
        tile_x, tile_y = (gx // ART_TILE).clip(0, cols - 1), (gy // ART_TILE).clip(0, rows - 1)
        allowed = self.allowed[tile_y[:, None], tile_x[None, :]]
        wx, wy = np.meshgrid(gx, gy)
        ripple = .025 * (np.sin((wx + .5) * np.pi / 6) + np.sin((wy + .5) * np.pi / 6))
        small = pygame.transform.scale(chunk, (size, size))
        colors = pygame.surfarray.array3d(small).transpose(1, 0, 2).copy()
        center = np.s_[pad:pad + size, pad:pad + size]
        xcoords = wx[center]
        for tier, depth in enumerate(FACE_DEPTHS, 1):
            region = self.levels >= tier
            a = region[iy0[:, None], ix0[None, :]]
            b = region[iy0[:, None], ix1[None, :]]
            c = region[iy1[:, None], ix0[None, :]]
            d = region[iy1[:, None], ix1[None, :]]
            field = (a * (1 - fx) * (1 - fy[:, None]) + b * fx * (1 - fy[:, None])
                     + c * (1 - fx) * fy[:, None] + d * fx * fy[:, None])
            mask = (field + ripple >= .5) & allowed
            inside = mask[center]
            if not inside.any():
                continue
            distance = np.zeros((size, size), np.uint8)
            alive = inside.copy()
            for step in range(1, depth + 1):
                alive &= mask[pad + step:pad + step + size, pad:pad + size]
                distance += alive
            face = inside & (distance < depth)
            top = inside & ~face
            # Discrete terrace tones distinguish nested highlands without blurring.
            if tier > 1:
                colors[top] = np.minimum(255, colors[top].astype(np.float32) * 1.07 + 3).astype(np.uint8)
            wall_y = ((depth - 1 - distance.astype(int)).clip(0) * 24 // depth).clip(0, 24)
            stone = self.wall[wall_y, (xcoords % 16)]
            colors[face] = stone[face]
            # Thin side walls wrap the plateau; south faces have priority at corners.
            west = top & ~mask[pad:pad + size, pad - 3:pad - 3 + size]
            east = top & ~mask[pad:pad + size, pad + 3:pad + 3 + size]
            colors[west] = (stone[west] * .73).astype(np.uint8)
            colors[east] = (stone[east] * .88).astype(np.uint8)
            # Cap lip and basal contact shadow follow the same contour across chunks.
            lip = inside & (distance == depth - 1)
            colors[lip] = (181, 143, 87)
            foot = face & (distance <= 1)
            colors[foot] = (colors[foot] * .55).astype(np.uint8)
        result = pygame.surfarray.make_surface(colors.transpose(1, 0, 2))
        chunk.blit(pygame.transform.scale(result, chunk.get_size()), (0, 0))
