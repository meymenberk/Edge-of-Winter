"""Local, world-anchored canopy litter. Never emits from the screen boundary."""
from collections import defaultdict
import math
import random

import pygame

from .worldgen import SEA_LEVEL


class AutumnLeaves:
    CELL_TILES = 8
    NEAR_TILES = 12

    def __init__(self, seed, world, atlas=None, tile_size=48, viewport=(1200, 780), count=32):
        self.rng = random.Random(seed + 9981)
        self.world, self.tile_size, self.viewport = world, tile_size, viewport
        self.limit = count
        self.leaves = []
        self.emitters = []
        self.emission_credit = 0.0
        self.refresh_in = 0.0
        self.last_cell = None
        self.buckets = defaultdict(list)
        # Nodes keep their identities across harvest, respawn and network updates.
        # Evergreen pines deliberately do not shed broad autumn leaves.
        for node in world.nodes:
            if node.type == "Odun" and node.species == "oak":
                self.buckets[self.cell(node.x, node.y)].append(node)
        self.canopy_size = (28, 28)  # Match draw_node's primitive fallback canopy.
        if atlas:
            self.canopy_size = atlas.tree_variants["oak"][0].get_size()
        self.sprites = []
        for color in ((211, 118, 43), (190, 81, 37), (232, 154, 53), (169, 91, 40)):
            sprite = pygame.Surface((5, 5), pygame.SRCALPHA)
            pygame.draw.polygon(sprite, color, [(2, 0), (4, 1), (3, 3), (1, 4), (0, 2)])
            pygame.draw.line(sprite, (116, 65, 31), (1, 4), (3, 1))
            sprite = pygame.transform.scale(sprite, (10, 10))
            self.sprites.append(tuple(pygame.transform.rotate(sprite, angle) for angle in (0, 90, 180, 270)))

    def cell(self, x, y):
        return math.floor(x / self.CELL_TILES), math.floor(y / self.CELL_TILES)

    def on_land(self, x, y):
        x, y = math.floor(x / self.tile_size), math.floor(y / self.tile_size)
        return (0 <= y < len(self.world.heights) and 0 <= x < len(self.world.heights[y])
                and self.world.heights[y][x] >= SEA_LEVEL and (x, y) not in self.world.buildings)

    def local_tree(self, node, player, camera):
        x, y = node.x * self.tile_size - camera[0], node.y * self.tile_size - camera[1]
        return (node.active and not node.harvest_pending
                and (node.x - player.x) ** 2 + (node.y - player.y) ** 2 <= self.NEAR_TILES ** 2
                and -40 <= x <= self.viewport[0] + 40
                and 0 <= y <= self.viewport[1] + self.canopy_size[1])

    def clear(self):
        self.leaves.clear()
        self.emitters.clear()
        self.emission_credit = 0.0
        self.refresh_in = 0.0

    def burst(self, node, count=10):
        """Emit a short world-space canopy burst after a confirmed sword/tree hit."""
        if not node.active:
            return 0
        made = 0
        for _ in range(min(14, max(1, count))):
            if len(self.leaves) >= self.limit + 24:
                break
            x = node.x * self.tile_size + self.rng.uniform(-.28, .28) * self.canopy_size[0]
            y = node.y * self.tile_size + self.rng.uniform(-4, 5)
            height = self.rng.uniform(.52, .90) * self.canopy_size[1]
            lifetime = self.rng.uniform(1.1, 2.0)
            self.leaves.append(dict(source=node, x=x, y=y, height=height, life=lifetime,
                                    fall=height / lifetime * self.rng.uniform(.85, 1.15),
                                    wind=self.rng.uniform(-22, 22),
                                    phase=self.rng.uniform(0, math.tau),
                                    color=self.rng.randrange(len(self.sprites)), burst=True))
            made += 1
        return made

    def update(self, dt, player, camera, enabled=True):
        if not enabled:
            self.clear()
            return
        # A frame hitch must not create a burst of particles or unbounded catch-up.
        dt = min(.1, max(0.0, dt))
        self.refresh_in -= dt
        cell = self.cell(player.x, player.y)
        if self.refresh_in <= 0 or cell != self.last_cell:
            self.refresh_in, self.last_cell = .25, cell
            self.emitters = []
            radius = math.ceil(self.NEAR_TILES / self.CELL_TILES)
            for cy in range(cell[1] - radius, cell[1] + radius + 1):
                for cx in range(cell[0] - radius, cell[0] + radius + 1):
                    self.emitters.extend(n for n in self.buckets.get((cx, cy), ())
                                         if self.local_tree(n, player, camera))
        self.emitters = [n for n in self.emitters if self.local_tree(n, player, camera)]
        alive = []
        for leaf in self.leaves:
            if not self.local_tree(leaf["source"], player, camera):
                continue
            leaf["life"] -= dt
            leaf["phase"] += dt * 2.2
            leaf["x"] += (leaf["wind"] + math.sin(leaf["phase"]) * 5) * dt
            if leaf.get("burst"):
                leaf["wind"] *= max(0.0, 1.0 - dt * 2.4)
            leaf["height"] -= leaf["fall"] * dt
            sy = leaf["y"] - leaf["height"]
            # Ground footprint and projected position both stay on land. Leaves
            # near a coast cannot drift across water or through house interiors.
            if (leaf["life"] > 0 and leaf["height"] > 0 and self.on_land(leaf["x"], leaf["y"])
                    and self.on_land(leaf["x"], sy)
                    and -12 <= leaf["x"] - camera[0] <= self.viewport[0] + 12
                    and -12 <= sy - camera[1] <= self.viewport[1] + 12):
                alive.append(leaf)
        self.leaves = alive
        if not self.emitters:
            self.emission_credit = 0.0
            return
        self.emission_credit += min(9.0, len(self.emitters) * .32) * dt
        while self.emission_credit >= 1:
            self.emission_credit -= 1
            if len(self.leaves) >= self.limit:
                continue
            node = self.rng.choice(self.emitters)
            x = node.x * self.tile_size + self.rng.uniform(-.32, .32) * self.canopy_size[0]
            y = node.y * self.tile_size + self.rng.uniform(-6, 5)
            height = self.rng.uniform(.45, .82) * self.canopy_size[1]
            if not (self.on_land(x, y) and self.on_land(x, y - height)):
                continue
            lifetime = self.rng.uniform(2.0, 3.4)
            self.leaves.append(dict(source=node, x=x, y=y, height=height, life=lifetime,
                                    fall=height / lifetime, wind=self.rng.uniform(2, 7),
                                    phase=self.rng.uniform(0, math.tau), color=self.rng.randrange(len(self.sprites))))

    def draw(self, screen, camera_x, camera_y):
        for leaf in self.leaves:
            if not leaf["source"].active:
                continue
            frame = int(leaf["phase"] * 1.5) % 4
            sprite = self.sprites[leaf["color"]][frame]
            x, y = round(leaf["x"] - camera_x), round(leaf["y"] - leaf["height"] - camera_y)
            screen.blit(sprite, sprite.get_rect(center=(x, y)))
