"""Regression coverage for profession villagers extracted from villager.png."""
import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame

from modules.gameplay_systems import NPC, QuestSystem
from modules.paths import VILLAGER_ATLAS_ASSET
from modules.pixel_sprites import (VILLAGER_DIRECTIONS, VILLAGER_ROLES,
                                   preload_villager_sprites, villager_sprite)


class VillagerSpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))
        cls.atlas = preload_villager_sprites()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_asset_path_cache_and_player_section_exclusion(self):
        self.assertEqual(self.atlas.path, VILLAGER_ATLAS_ASSET)
        self.assertTrue(VILLAGER_ATLAS_ASSET.is_file())
        self.assertIs(preload_villager_sprites(), self.atlas)
        # Every inspected villager source cell begins below the player section.
        self.assertGreaterEqual(min(rect.y for role in VILLAGER_ROLES
                                    for direction in VILLAGER_DIRECTIONS
                                    for rect in self.atlas.source_rects[role]["idle"][direction]), 465)

    def test_professions_directions_and_walk_frames_are_real_and_distinct(self):
        role_signatures = set()
        for role in VILLAGER_ROLES:
            directions = []
            for direction in VILLAGER_DIRECTIONS:
                idle = villager_sprite(role, direction, 0, False, 0)
                self.assertEqual(idle.get_size(), self.atlas.SIZE)
                directions.append(pygame.image.tobytes(idle, "RGBA"))
                walk = [villager_sprite(role, direction, frame, True, 0)
                        for frame in range(4)]
                self.assertEqual(len({pygame.image.tobytes(item, "RGBA") for item in walk}), 4)
                for item in walk:
                    bounds = item.get_bounding_rect(min_alpha=1)
                    self.assertEqual(bounds.bottom, self.atlas.ANCHOR[1])
            self.assertEqual(len(set(directions)), 4)
            role_signatures.add(directions[0])
        self.assertEqual(len(role_signatures), len(VILLAGER_ROLES))

    def test_transparency_keeps_pale_clothes_and_has_no_paper_rectangle(self):
        for role in VILLAGER_ROLES:
            for direction in VILLAGER_DIRECTIONS:
                sprite = villager_sprite(role, direction, 0, False, 0)
                alpha = pygame.surfarray.array_alpha(sprite)
                rgb = pygame.surfarray.array3d(sprite)
                border = np.concatenate((alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))
                self.assertEqual(int(border.max()), 0)
                self.assertLess(np.count_nonzero(alpha), alpha.size // 2)
                # White shirts, helmet lamps, and the elder beard remain opaque.
                pale = (rgb.min(axis=2) >= 218) & (alpha > 0)
                self.assertGreater(np.count_nonzero(pale), 0)

    def test_variants_are_stable_and_animation_is_delta_time_driven(self):
        village = SimpleNamespace(center=(10, 10))
        island = SimpleNamespace(resources=("Balik", "Tahil", "Tas"), village=village)
        roles = {
            QuestSystem._profession_for(SimpleNamespace(seed=seed), island, 4, "villager:4")
            for seed in range(80)
        }
        self.assertEqual(roles, {"fisherman", "farmer", "miner", "elder", "merchant"})
        first = QuestSystem._identity_value(2026, 4, "villager:4", "farmer")
        self.assertEqual(first, QuestSystem._identity_value(2026, 4, "villager:4", "farmer"))

        system = QuestSystem.__new__(QuestSystem)
        npc = NPC("villager:4", "Köylü", 4, 10.0, 10.0, "danger:4",
                  profession="farmer", appearance_variant=first % 5)
        system.npcs = [npc]
        system.update_npc_animations(.05)
        self.assertFalse(npc.moving)
        npc.x += .1
        system.update_npc_animations(.05)
        self.assertTrue(npc.moving)
        self.assertEqual(npc.facing, "right")
        self.assertAlmostEqual(npc.walk_phase, .4)
        system.update_npc_animations(.05)
        self.assertFalse(npc.moving)
        self.assertEqual(npc.walk_phase, 0.0)


if __name__ == "__main__":
    unittest.main()
