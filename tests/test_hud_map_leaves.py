"""Focused regressions for canopy locality and the integrated HUD/map controls."""
import copy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.autumn_leaves import AutumnLeaves
from modules.game_ui import CREAM, WorldMapUI
from modules.worldgen import ResourceNode


class LocalLeavesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))

    def setUp(self):
        self.oak = ResourceNode("Odun", 20.5, 20.5)
        self.world = SimpleNamespace(heights=[[.2] * 80 for _ in range(60)],
                                     buildings=set(), nodes=[self.oak])
        self.player = pygame.Vector2(self.oak.x, self.oak.y)
        self.camera = (self.player.x * 48 - 600, self.player.y * 48 - 390)
        self.fx = AutumnLeaves(42, self.world)

    def advance(self, frames=600):
        for _ in range(frames):
            self.fx.update(1 / 60, self.player, self.camera)

    def test_only_local_active_oaks_emit_and_respawn_recovers(self):
        self.assertFalse(self.fx.leaves)  # No screen-wide initial shower.
        self.advance()
        self.assertTrue(self.fx.leaves)
        for leaf in self.fx.leaves:
            self.assertIs(leaf["source"], self.oak)
            self.assertLess(abs(leaf["x"] - self.oak.x * 48), 48)
        self.oak.harvest()
        self.fx.update(.02, self.player, self.camera)
        self.assertFalse(self.fx.leaves)
        self.assertFalse(self.fx.emitters)
        self.oak.active, self.oak.harvest_pending = True, False
        self.advance()
        self.assertTrue(self.fx.leaves)

    def test_water_buildings_pines_and_treeless_areas_have_no_leaves(self):
        for scenario in ("water", "building", "pine", "far"):
            with self.subTest(scenario=scenario):
                self.setUp()
                if scenario == "water":
                    self.world.heights = [[-.4] * 80 for _ in range(60)]
                elif scenario == "building":
                    self.world.buildings = {(x, y) for x in range(18, 23) for y in range(18, 23)}
                elif scenario == "pine":
                    self.oak.species = "pine"
                    self.fx = AutumnLeaves(42, self.world)
                else:
                    self.player.update(60, 40)
                    self.camera = (60 * 48 - 600, 40 * 48 - 390)
                self.advance()
                self.assertFalse(self.fx.leaves)

    def test_leaving_forest_and_entering_ui_clears_existing_particles(self):
        self.advance()
        self.assertTrue(self.fx.leaves)
        self.player.update(60, 40)
        self.fx.update(.02, self.player, self.camera)
        self.assertFalse(self.fx.leaves)
        self.player.update(self.oak.x, self.oak.y)
        self.advance()
        self.fx.update(.02, self.player, self.camera, enabled=False)
        self.assertFalse(self.fx.leaves)
        self.assertFalse(self.fx.emitters)
        self.assertEqual(self.fx.emission_credit, 0)

    def test_drift_cannot_cross_coast_and_camera_does_not_move_world_particles(self):
        self.advance()
        leaf = self.fx.leaves[0]
        before_x = leaf["x"]
        moved_camera = (self.camera[0] + 10, self.camera[1])
        self.fx.update(0, self.player, moved_camera)
        self.assertEqual(self.fx.leaves[0]["x"], before_x)
        a, b = pygame.Surface((1200, 780)), pygame.Surface((1200, 780))
        self.fx.draw(a, *self.camera)
        self.fx.draw(b, *moved_camera)
        self.assertEqual(pygame.image.tobytes(a.subsurface((10, 0, 1190, 780)), "RGB"),
                         pygame.image.tobytes(b.subsurface((0, 0, 1190, 780)), "RGB"))
        self.world.heights[int(leaf["y"] / 48)][int(leaf["x"] / 48)] = -.4
        self.fx.update(.02, self.player, self.camera)
        self.assertNotIn(leaf, self.fx.leaves)

    def test_dense_forests_and_large_dt_respect_particle_cap(self):
        self.world.nodes = [ResourceNode("Odun", 18 + x, 18 + y) for x in range(6) for y in range(6)]
        self.fx = AutumnLeaves(42, self.world, count=8)
        self.advance()
        self.assertGreater(len(self.fx.leaves), 0)
        for _ in range(100):
            self.fx.update(60, self.player, self.camera)
            self.assertLessEqual(len(self.fx.leaves), 8)


class HUDMapIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        cls.world = main.make_world(42)
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world), (640, 384), "RGB").convert()

    def setUp(self):
        world = copy.deepcopy(self.world)
        self.session = main.GameSession(world, world.ports, main.find_spawn(world), self.tiles, None, 42, {})

    def key(self, key, **extra):
        self.session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, **extra), (0, 0))

    def test_map_toggle_repeat_escape_and_click_do_not_fire_bow(self):
        s = self.session
        self.key(pygame.K_m)
        self.assertTrue(s.map_open)
        self.key(pygame.K_m, repeat=True)
        self.assertTrue(s.map_open)
        self.key(pygame.K_m)
        self.assertFalse(s.map_open)
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1)
        s.handle_event(click, s.map_button.center)
        self.assertTrue(s.map_open)
        s.handle_event(click, (600, 400))
        self.assertFalse(s.arrows)
        self.key(pygame.K_ESCAPE)
        self.assertFalse(s.map_open)
        self.assertFalse(s.paused)
        self.key(pygame.K_m)
        s.handle_event(click, s.map_ui.close_rect.center)
        self.assertFalse(s.map_open)
        s.handle_event(click, s.hud.items[0][1].center)
        self.assertFalse(s.arrows)
        s.handle_event(click, s.inventory_button.center)
        self.assertTrue(s.inventory_open)
        self.key(pygame.K_ESCAPE)
        s.handle_event(click, s.trade_button.center)
        self.assertTrue(s.trade_open)

    def test_map_suspends_local_movement_and_combat_then_resumes(self):
        s = self.session
        s.held_direction_keys.add(pygame.K_d)
        s.dash_timer = .2
        self.key(pygame.K_m)
        self.assertFalse(s.held_direction_keys)
        self.assertEqual(s.dash_timer, 0)
        position = tuple(s.player)
        with patch.object(s, "update_world_combat") as combat, patch("main.move_player") as movement:
            s.update(.05, (0, 0))
            self.assertEqual(tuple(s.player), position)
            movement.assert_not_called()
            combat.assert_not_called()
            self.key(pygame.K_ESCAPE)
            s.update(.05, (0, 0))
            movement.assert_called_once()
            combat.assert_called_once()

    def test_network_and_shared_resources_continue_while_chart_open(self):
        s = self.session
        network = main.NetworkClient()
        network.connected, network.resource_sync = True, True
        network.id = 0
        node = s.world.nodes[0]
        network.resource_states = {node.id: 15}
        network.resource_revision = 1
        network.island_owners = {0: 1}
        s.network = network
        self.key(pygame.K_m)
        with patch.object(network, "send_and_receive") as pump:
            s.update(.06, (0, 0))
            pump.assert_called_once()
        self.assertFalse(node.active)
        self.assertEqual(s.island_owners[0], 1)
        self.assertTrue(s.map_open)

    def test_resource_rewards_change_rendered_counts_without_changing_layout(self):
        s = self.session
        canvas = pygame.Surface((1200, 780))
        s.render(canvas, (0, 0))
        before = [pygame.image.tobytes(canvas.subsurface(rect), "RGB") for _, rect in s.hud.items[:4]]
        for key, _ in s.hud.items[:4]:
            s.add_resource(key, 123)
        s.render(canvas, (0, 0))
        for i, (key, rect) in enumerate(s.hud.items[:4]):
            self.assertNotEqual(before[i], pygame.image.tobytes(canvas.subsurface(rect), "RGB"))
            self.assertFalse(rect.colliderect(s.map_button))
        s.inventory["Odun"] = 123456789012
        s.render(canvas, s.hud.items[0][1].center)  # Full count is available in hover text.

    def test_map_projection_terrain_and_remote_markers(self):
        s = self.session
        map_ui = s.map_ui
        for rect in (map_ui.mini_rect, map_ui.full_rect):
            self.assertEqual(WorldMapUI.position(rect, 0, 0), rect.topleft)
            self.assertEqual(WorldMapUI.position(rect, 640, 384), (rect.right - 1, rect.bottom - 1))
            self.assertEqual(WorldMapUI.position(rect, 320, 192), rect.center)
        self.assertNotEqual(map_ui.art.get_at((0, 0)),
                            map_ui.art.get_at((int(s.player.x), int(s.player.y))))
        s.player.update(320, 192)
        network = main.NetworkClient()
        network.connected = True
        network.other_players = {"1": {"x": 330, "y": 196}}
        s.network = network
        canvas = pygame.Surface((1200, 780))
        map_ui.draw_mini(canvas, (0, 0), s.player, network, {0: 0, 1: 1}, 0, (0, 0, 25, 16))
        x, y = map_ui.position(map_ui.mini_rect, 320, 192)
        self.assertEqual(canvas.get_at((x, y - 3))[:3], CREAM)
        source = pygame.Rect(round(s.player.x - 64), round(s.player.y - 38), 128, 76)
        source.clamp_ip((0, 0, main.COLS, main.ROWS))
        pos = map_ui.view_position(map_ui.mini_rect, source, 330, 196)
        self.assertEqual(canvas.get_at(pos)[:3], (243, 132, 159))
        for pos in ((0, 0), (639.99, 383.99)):
            s.player.update(pos)
            map_ui.draw_full(canvas, (0, 0), s.player, network, {}, 0)

    def test_modal_screens_disable_leaf_emission(self):
        s = self.session
        self.assertTrue(s.ambient_leaves_enabled())
        for attr in ("paused", "map_open", "inventory_open", "trade_open"):
            setattr(s, attr, True)
            self.assertFalse(s.ambient_leaves_enabled())
            setattr(s, attr, False)
        for game in (s.fishing, s.grain_game, s.stone_game, s.wood_game, s.dialogue):
            game.active = True
            self.assertFalse(s.ambient_leaves_enabled())
            game.active = False


if __name__ == "__main__":
    unittest.main()
