"""Focused coverage for food, ammo crafting, weapon tiers, and charged dashes."""
import copy
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.progression import ProgressionSystem, craft
from modules.terrain_render import TileAtlas, prepare_terrain
from modules.worldgen import compute_tile_pixels, find_spawn, make_world


class InventoryProgressionDashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()

    def session(self):
        world = copy.deepcopy(self.world)
        return main.GameSession(world, world.ports, find_spawn(world), self.tiles,
                                None, world.seed, {}, self.atlas)

    def test_arrow_recipe_is_atomic(self):
        inventory = {"Odun": 2, "Tas": 1, "Ok": 0}
        self.assertEqual(craft("arrows", inventory), 5)
        self.assertEqual(inventory, {"Odun": 0, "Tas": 0, "Ok": 5})
        self.assertEqual(craft("arrows", inventory), 0)
        self.assertEqual(inventory, {"Odun": 0, "Tas": 0, "Ok": 5})

    def test_bow_consumes_ammo_and_tier_scales_projectile(self):
        session = self.session()
        session.cam_x = session.player.x * main.LOCAL_TILE_SIZE - main.GAME_WIDTH / 2
        session.cam_y = session.player.y * main.LOCAL_TILE_SIZE - main.GAME_HEIGHT / 2
        target = (main.GAME_WIDTH // 2 + 100, main.GAME_HEIGHT // 2)
        before = session.inventory["Ok"]
        self.assertTrue(session.fire_arrow(target))
        self.assertEqual(session.inventory["Ok"], before - 1)
        self.assertEqual(session.arrows[-1]["damage"], 2)

        session.arrow_cooldown = 0
        session.inventory["Odun"], session.inventory["Tas"] = 100, 100
        self.assertTrue(session.upgrade_weapon("bow"))
        self.assertTrue(session.fire_arrow(target))
        self.assertEqual(session.arrows[-1]["damage"], 3)
        self.assertGreater(session.arrows[-1]["life"], 1.6)

        session.arrow_cooldown = 0
        session.inventory["Ok"] = 0
        self.assertFalse(session.fire_arrow(target))

    def test_weapon_upgrade_and_axe_hits_share_progression_stats(self):
        inventory = {"Odun": 100, "Tas": 100}
        progression = ProgressionSystem()
        self.assertTrue(progression.upgrade("axe", inventory))
        self.assertEqual(progression.stats("axe").required_hits, 3)

        session = self.session()
        session.inventory.update(Odun=100, Tas=100)
        self.assertTrue(session.upgrade_weapon("axe"))
        tree = next(node for node in session.world.nodes if node.type == "Odun" and node.active)
        stats = session.progression.stats("axe")
        session.wood_game.open(tree, stats.level, stats.required_hits, stats.impact)
        self.assertEqual(session.wood_game.required_hits, 3)
        self.assertGreater(session.wood_game.impact, 1.0)

    def test_food_works_for_health_or_energy_and_h_shortcut(self):
        session = self.session()
        session.health = session.max_health - 2
        session.energy = session.max_energy - 30
        session.inventory["Pişmiş Et"] = 1
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, repeat=False), (0, 0))
        self.assertEqual(session.health, session.max_health)
        self.assertEqual(session.energy, session.max_energy - 5)
        self.assertEqual(session.inventory["Pişmiş Et"], 0)

    def test_early_dash_uses_partial_charge_then_resets(self):
        session = self.session()
        session.dash_unlocked = True  # Windstep is taught by the Wandering Sage.
        session.dash_cooldown = main.DASH_COOLDOWN / 2
        self.assertAlmostEqual(session.dash_charge_ratio, .5)
        self.assertTrue(session.start_dash((1, 0)))
        self.assertAlmostEqual(session.dash_power, .5)
        self.assertAlmostEqual(session.dash_timer, main.DASH_DURATION * .5)
        self.assertEqual(session.dash_cooldown, main.DASH_COOLDOWN)
        self.assertFalse(session.start_dash((1, 0)))


if __name__ == "__main__":
    unittest.main()
