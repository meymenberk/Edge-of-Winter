"""Unit tests for island conquest, inventory, multiplayer conquest sync, and 6-island win condition."""
import copy
import json
import math
import os
import socket
import threading
import time
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import pygame
import main
from modules.worldgen import make_world, find_spawn, generate_ports
from modules.terrain_render import TileAtlas, prepare_terrain
from modules.multiplayer import NetworkClient
from server import GameServer


class IslandConquestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world), (main.COLS, main.ROWS), 'RGB').convert()

    def create_session(self, world=None, network=None):
        w = world or copy.deepcopy(self.world)
        return main.GameSession(w, w.ports, find_spawn(w), self.tiles, network, 42, {}, self.atlas)

    def test_initial_inventory_and_harvest_rewards(self):
        session = self.create_session()
        # Verify initial inventory values
        self.assertIn("Odun", session.inventory)
        self.assertIn("Tas", session.inventory)
        self.assertIn("Tahil", session.inventory)
        self.assertIn("Balik", session.inventory)
        initial_wood = session.inventory["Odun"]

        # Harvest wood
        session.add_resource("Odun", 4)
        self.assertEqual(session.inventory["Odun"], initial_wood + 4)
        self.assertTrue(len(session.floating_texts) > 0)
        self.assertTrue(len(session.toasts) > 0)

        # Harvest fish
        initial_fish = session.inventory["Balik"]
        session.add_resource("Balik", 1)
        self.assertEqual(session.inventory["Balik"], initial_fish + 1)

    def test_debug_equipment_loot_bow_and_wind_systems(self):
        session = self.create_session()
        self.assertTrue(session.equipment["sword"])
        self.assertTrue(session.equipment["bow"])

        class GuaranteedLoot:
            def random(self): return 0.0
            def choice(self, values): return values[0]

        session.equipment = {"sword": False, "bow": False}
        session.loot_rng = GuaranteedLoot()
        session.harvest_reward("Odun", 1)
        self.assertTrue(any(session.equipment.values()))

        session.equipment["bow"] = True
        session.cam_x = session.player.x * main.LOCAL_TILE_SIZE - main.GAME_WIDTH / 2
        session.cam_y = session.player.y * main.LOCAL_TILE_SIZE - main.GAME_HEIGHT / 2
        self.assertTrue(session.fire_arrow((main.GAME_WIDTH // 2 + 100, main.GAME_HEIGHT // 2)))
        self.assertEqual(len(session.arrows), 1)

        session.wind_angle = 0.0
        session.boat_speed = 0.0
        session.update_wind_sailing(.1, (main.GAME_WIDTH, main.GAME_HEIGHT // 2))
        self.assertGreater(session.boat_speed, 0.0)
        session.boat_speed = 100.0
        session.update_wind_sailing(.1, (main.GAME_WIDTH, main.GAME_HEIGHT // 2))
        self.assertEqual(session.boat_speed, 8.0)

        hull_alpha = pygame.surfarray.array_alpha(session.sailboat_hull)
        self.assertGreater((hull_alpha == 255).sum(), ((hull_alpha > 0) & (hull_alpha < 255)).sum())

    def test_sail_can_be_lowered_raised_and_controls_wind_capture(self):
        session = self.create_session()
        session.is_sailing = True
        session.wind_angle = 0.0
        session.sail_raised = False
        session.boat_speed = 0.0
        session.update_wind_sailing(.1, (main.GAME_WIDTH, main.GAME_HEIGHT // 2))
        self.assertEqual(session.boat_speed, 0.0)

        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r), (0, 0))
        self.assertTrue(session.sail_raised)
        session.update_wind_sailing(.1, (main.GAME_WIDTH, main.GAME_HEIGHT // 2))
        self.assertGreater(session.boat_speed, 0.0)
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r), (0, 0))
        self.assertFalse(session.sail_raised)

    def test_double_w_starts_dash_and_attack_becomes_wave_slash(self):
        session = self.create_session()
        session.dash_unlocked = True  # Windstep is taught by the Wandering Sage.
        session.game_time = 1.0
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, repeat=False), (0, 0))
        session.game_time = 1.18
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, repeat=False), (0, 0))
        self.assertGreater(session.dash_timer, 0)
        self.assertGreater(session.dash_cooldown, 0)
        self.assertGreaterEqual(len(session.dash_effects), 3)

        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_j, repeat=False), (0, 0))
        self.assertTrue(session.combat.attacking)
        self.assertEqual(session.combat.attack_kind, "dash")
        self.assertEqual(session.combat.attack_profile()["damage"], 3)

    def test_double_tap_dashes_in_four_cardinal_and_diagonal_directions(self):
        session = self.create_session()
        session.dash_unlocked = True  # Windstep is taught by the Wandering Sage.
        cases = ((pygame.K_w, (0, -1)), (pygame.K_s, (0, 1)),
                 (pygame.K_a, (-1, 0)), (pygame.K_d, (1, 0)))
        for index, (key, expected) in enumerate(cases):
            session.dash_cooldown = 0
            session.dash_timer = 0
            session.held_direction_keys.clear()
            session.last_direction_tap = {name: -10 for name in session.last_direction_tap}
            session.game_time = 2.0 + index
            session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, repeat=False), (0, 0))
            session.game_time += .15
            session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, repeat=False), (0, 0))
            self.assertAlmostEqual(session.dash_direction.x, expected[0])
            self.assertAlmostEqual(session.dash_direction.y, expected[1])

        session.dash_cooldown = 0
        session.dash_timer = 0
        session.held_direction_keys.clear()
        session.last_direction_tap = {name: -10 for name in session.last_direction_tap}
        session.game_time = 10.0
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d, repeat=False), (0, 0))
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, repeat=False), (0, 0))
        session.game_time += .15
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, repeat=False), (0, 0))
        self.assertGreater(session.dash_direction.x, 0)
        self.assertLess(session.dash_direction.y, 0)
        self.assertAlmostEqual(session.dash_direction.length(), 1.0)

    def test_melee_kill_can_start_cinematic_finisher(self):
        session = self.create_session()

        class AlwaysFinisher:
            def random(self): return 0.0
            def randrange(self, stop): return 2

        session.combat_rng = AlwaysFinisher()
        session.combat.attack_kind = "dash"
        session.combat.combo_step = 3
        monster = session.quest_system.monsters[0]
        monster.alive = False
        session.handle_monster_defeated(monster)
        self.assertIsNotNone(session.execution)
        self.assertEqual(session.execution["variant"], 2)
        self.assertGreaterEqual(len(session.dash_effects), 10)
        session.render(pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT)), (0, 0))

    def test_rescue_cost_increases_with_time_not_rescue_count(self):
        session = self.create_session()
        base = session.get_current_island_cost()
        session.update(120.0, (0, 0))
        increased = session.get_current_island_cost()
        self.assertGreater(increased["Odun"], base["Odun"])
        session.capture_count = 1
        self.assertEqual(session.get_current_island_cost(), increased)

    def test_wood_chopping_times_out_and_reports_loss(self):
        session = self.create_session()
        node = next(node for node in session.world.nodes if node.type == "Odun")
        session.wood_game.open(node)
        result = session.wood_game.update(session.wood_game.TIME_LIMIT + 0.1)
        self.assertFalse(result)
        self.assertFalse(session.wood_game.active)
        self.assertFalse(session.wood_game.result)
        self.assertTrue(node.active)

    def test_capture_neutral_island_requires_resources(self):
        session = self.create_session()
        # Empty inventory
        session.inventory = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}

        # Place player on island 0
        isl0 = session.world.islands[0]
        # Find a land tile for island 0
        found = False
        for y in range(len(session.world.owners)):
            for x in range(len(session.world.owners[0])):
                if session.world.owners[y][x] == 0:
                    session.player.x = x + 0.5
                    session.player.y = y + 0.5
                    found = True
                    break
            if found:
                break
        self.assertTrue(found)
        next(q for q in session.quest_system.quests.values() if q.island_index == 0).state = "ready"

        # Attempt to capture with insufficient resources
        success = session.try_capture_island()
        self.assertFalse(success)
        self.assertNotIn(0, session.island_owners)

        # Provide exact resources for neutral island
        session.inventory = dict(main.NEUTRAL_ISLAND_COST)
        success = session.try_capture_island()
        self.assertTrue(success)
        self.assertEqual(session.island_owners[0], 0)
        self.assertEqual(session.world.islands[0].owner, 0)
        # Resources should be deducted
        self.assertEqual(session.inventory["Odun"], 0)
        self.assertEqual(session.inventory["Tas"], 0)
        self.assertEqual(session.inventory["Tahil"], 0)
        self.assertEqual(session.inventory["Balik"], 0)

        # Attempting to capture again when already owned should do nothing
        success_again = session.try_capture_island()
        self.assertFalse(success_again)

    def test_rescued_island_cannot_be_stolen(self):
        session = self.create_session()
        isl0 = session.world.islands[0]
        # Island 0 is currently owned by Player 1 (enemy)
        session.island_owners[0] = 1
        isl0.owner = 1

        # Place player on island 0
        for y in range(len(session.world.owners)):
            for x in range(len(session.world.owners[0])):
                if session.world.owners[y][x] == 0:
                    session.player.x = x + 0.5
                    session.player.y = y + 0.5
                    break

        # Rescue is permanent; another player cannot buy or invade the island.
        session.inventory = dict(main.ENEMY_ISLAND_COST)
        self.assertFalse(session.try_capture_island())
        self.assertEqual(session.island_owners[0], 1)
        self.assertEqual(session.inventory, main.ENEMY_ISLAND_COST)

    def test_six_islands_triggers_win_condition(self):
        session = self.create_session()
        self.assertIsNone(session.winner)

        # Award player 5 islands
        for i in range(5):
            session.island_owners[i] = 0
            session.world.islands[i].owner = 0

        self.assertIsNone(session.winner)

        # Give resources and capture 6th island
        session.inventory = dict(main.NEUTRAL_ISLAND_COST)
        next(q for q in session.quest_system.quests.values() if q.island_index == 5).state = "ready"
        # Place player on island 5
        for y in range(len(session.world.owners)):
            for x in range(len(session.world.owners[0])):
                if session.world.owners[y][x] == 5:
                    session.player.x = x + 0.5
                    session.player.y = y + 0.5
                    break

        success = session.try_capture_island()
        self.assertTrue(success)
        self.assertEqual(session.winner, 0)

    def test_island_passive_income(self):
        session = self.create_session()
        session.inventory = {"Odun": 0, "Tas": 0, "Tahil": 0, "Balik": 0}
        session.island_owners[0] = 0
        session.world.islands[0].owner = 0
        # Ensure island 0 has known resources
        session.world.islands[0].resources = ("Odun", "Tas")

        session.income_timer = 0.1
        session.update_island_income(0.2)
        # Income should have fired and added +1 Odun and +1 Tas
        self.assertGreaterEqual(session.inventory["Odun"], 1)
        self.assertGreaterEqual(session.inventory["Tas"], 1)

    def test_multiplayer_island_capture_and_sync(self):
        # Set up a real GameServer and two NetworkClients
        game = GameServer(self.world)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]

        clients = []
        threads = []

        def accept_clients():
            for pid in (0, 1):
                conn, addr = listener.accept()
                t = threading.Thread(target=game.handle_client, args=(conn, addr, pid), daemon=True)
                t.start()
                threads.append(t)

        accept_thread = threading.Thread(target=accept_clients, daemon=True)
        accept_thread.start()

        c0 = NetworkClient('127.0.0.1', port)
        c1 = NetworkClient('127.0.0.1', port)
        self.assertTrue(c0.try_connect())
        self.assertTrue(c1.try_connect())
        clients.extend([c0, c1])
        self.assertNotEqual(c0.spawn_island, c1.spawn_island)
        self.assertNotEqual(c0.spawn, c1.spawn)
        spawned_session = self.create_session(network=c1)
        self.assertEqual(tuple(spawned_session.player), c1.spawn)
        sx, sy = map(int, spawned_session.player)
        self.assertEqual(spawned_session.world.owners[sy][sx], c1.spawn_island)

        # Client 0 captures island 2
        c0.capture_island(2)

        # Pump communication
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            c0.send_and_receive(10, 10, 'down', False, False)
            c1.send_and_receive(20, 20, 'down', False, False)
            if c1.island_owners.get(2) == 0 and not c0.pending_captures:
                break
            time.sleep(0.01)

        self.assertEqual(c0.island_owners.get(2), 0)
        self.assertEqual(c1.island_owners.get(2), 0)
        self.assertEqual(game.island_owners.get(2), 0)
        self.assertEqual(game.capture_count, 1)
        self.assertGreaterEqual(c0.inflation, 1.0)

        # Rescued islands cannot be stolen by another player.
        c1.capture_island(2)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            c0.send_and_receive(10, 10, 'down', False, False)
            c1.send_and_receive(20, 20, 'down', False, False)
            if not c1.pending_captures:
                break
            time.sleep(0.01)

        self.assertEqual(c0.island_owners.get(2), 0)
        self.assertEqual(c1.island_owners.get(2), 0)
        self.assertEqual(game.island_owners.get(2), 0)
        self.assertEqual(game.capture_count, 1)

        old_spawn_island = c1.spawn_island
        old_revision = c1.spawn_revision
        c1.request_respawn()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and c1.spawn_revision == old_revision:
            c0.send_and_receive(*c0.spawn, 'down', False, False)
            c1.send_and_receive(*c1.spawn, 'down', False, False)
            time.sleep(0.01)
        self.assertGreater(c1.spawn_revision, old_revision)
        self.assertNotEqual(c1.spawn_island, old_spawn_island)
        self.assertNotEqual(c1.spawn_island, c0.spawn_island)

        # Clean up
        c0.close()
        c1.close()
        listener.close()

    def test_inventory_toggle_and_conquer_key(self):
        session = self.create_session()
        self.assertFalse(session.inventory_open)

        # Press I to toggle inventory
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i), (0, 0))
        self.assertTrue(session.inventory_open)

        # Press ESC to close inventory
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE), (0, 0))
        self.assertFalse(session.inventory_open)


if __name__ == '__main__':
    unittest.main()
