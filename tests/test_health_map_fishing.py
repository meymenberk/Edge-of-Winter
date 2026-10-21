"""Focused coverage for heart HUD, map navigation, names, terrain tone and fishing."""
import copy
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import numpy as np
import pygame

import main
from modules.game_ui import heart_states
from modules.terrain_render import FOREST, GRASS, TileAtlas, prepare_terrain
from modules.worldgen import make_world, medieval_island_names


class HealthMapFishingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()

    def session(self):
        world = copy.deepcopy(self.world)
        return main.GameSession(world, world.ports, main.find_spawn(world), self.tiles,
                                None, 42, {}, self.atlas)

    def test_five_hearts_support_full_half_and_empty(self):
        self.assertEqual(heart_states(8, 8), (2, 2, 2, 2, 2))
        self.assertEqual(heart_states(4, 8), (2, 2, 1, 0, 0))
        self.assertEqual(heart_states(0, 8), (0, 0, 0, 0, 0))
        self.assertEqual(heart_states(7.2, 8), (2, 2, 2, 2, 1))
        canvas = pygame.Surface((1200, 780))
        session = self.session()
        for health in (session.max_health, session.max_health / 2, 0):
            session.health = health
            session.render(canvas, (0, 0))

    def test_names_are_seeded_unique_with_reserved_boss_island(self):
        first = medieval_island_names(42, 42)
        self.assertEqual(first, medieval_island_names(42, 42))
        self.assertNotEqual(first, medieval_island_names(43, 42))
        self.assertEqual(len(first), len(set(first)))
        actual = [island.name for island in self.world.islands]
        self.assertEqual(actual[:-1], first[:len(actual) - 1])
        self.assertEqual(actual[-1], "Crimsonroot Isle")
        self.assertFalse(any(name.startswith("Ada ") for name in first))

    def test_full_and_rescue_maps_zoom_pan_and_close(self):
        session = self.session()
        session.set_map_open(True)
        center = session.map_ui.full_rect.center
        initial_zoom = session.map_ui.views["full"]["zoom"]
        session.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1), center)
        self.assertGreater(session.map_ui.views["full"]["zoom"], initial_zoom)
        before = tuple(session.map_ui.views["full"]["center"])
        session.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1), center)
        moved = (center[0] + 80, center[1] + 30)
        session.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=moved, rel=(80, 30), buttons=(1, 0, 0)), moved)
        session.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), moved)
        self.assertNotEqual(before, tuple(session.map_ui.views["full"]["center"]))
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE), center)
        self.assertFalse(session.map_open)

        # The lower rescue drawer and inventory rescue chart share zoom/pan state.
        island = self.world.islands[0]
        session.player.update(island.x, island.y)
        session.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1),
                             session.rescue_map_button.center)
        self.assertTrue(session.rescue_map_open)
        initial_zoom = session.map_ui.views["rescue"]["zoom"]
        session.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1), session.rescue_map_rect.center)
        self.assertGreater(session.map_ui.views["rescue"]["zoom"], initial_zoom)
        session.inventory_open = True
        initial_zoom = session.map_ui.views["rescue"]["zoom"]
        session.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-1),
                             session.inventory_rescue_map_rect.center)
        self.assertLess(session.map_ui.views["rescue"]["zoom"], initial_zoom)

    def test_darkest_grass_and_forest_pixels_are_lifted(self):
        for kind, minimum in ((GRASS, 16), (FOREST, 10)):
            values = np.concatenate([pygame.surfarray.array3d(tile).reshape(-1, 3)
                                     for tile in self.atlas.ground[kind]])
            # The corrected shadows retain contrast but no longer approach black.
            values = values.astype(np.int16)
            luminance = (values[:, 0] * 3 + values[:, 1] * 5 + values[:, 2] * 2) / 10
            self.assertGreater(np.percentile(luminance, 1), minimum)

    def test_fishing_has_three_sprites_four_fish_reeling_escape_and_reward(self):
        session = self.session()
        fishing = session.fishing
        port = session.ports[0]
        # Fishing opens from the shoreline trigger; port.spawn is inland.
        player = pygame.Vector2(port.x + .5, port.y + .5)
        fishing.open(port, player)
        mouse_x = fishing.rod_x + port.dx * 120
        mouse_y = fishing.rod_y + port.dy * 120
        fishing.update(.016, mouse_x, mouse_y, session.world)
        self.assertEqual(len(fishing.fishes), 4)
        self.assertEqual(len(fishing.fish_sprites), 3)
        self.assertEqual(len({pygame.image.tobytes(pair[0], "RGBA") for pair in fishing.fish_sprites}), 3)
        old_length = fishing.line_length
        fishing.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1))
        self.assertLess(fishing.line_length, old_length)
        fishing.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-1))
        self.assertEqual(fishing.line_length, old_length)

        fishing.spawn_fish(session.world)
        fish = fishing.fishes[fishing.active_fish]
        fish["x"], fish["y"] = fishing.bobber_x, fishing.bobber_y
        fishing.line_length = 60
        fishing.progress = .95
        before_reward = session.inventory["Balik"]
        fishing.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1))
        fishing.update(.016, mouse_x, mouse_y, session.world)
        self.assertEqual(session.inventory["Balik"], before_reward + 1)

        fishing.spawn_fish(session.world)
        fishing.tension = 1.2
        for _ in range(20):
            fishing.update(.06, mouse_x, mouse_y, session.world)
        self.assertEqual(fishing.state, "waiting")
        self.assertIn("got away", fishing.message)
        canvas = pygame.Surface((1200, 780), pygame.SRCALPHA)
        camera_x = player.x * main.LOCAL_TILE_SIZE - main.GAME_WIDTH / 2
        camera_y = player.y * main.LOCAL_TILE_SIZE - main.GAME_HEIGHT / 2
        fishing.draw_world(canvas, camera_x, camera_y, player)
        self.assertGreater(np.count_nonzero(pygame.surfarray.array_alpha(canvas)), 100)


if __name__ == "__main__":
    unittest.main()
