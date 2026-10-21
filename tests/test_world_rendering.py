"""Run: SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 -m unittest discover -s tests -v"""
import copy
import json
import math
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import numpy as np
import pygame
import main
from modules.treant_boss import EncounterResult
from modules.worldgen import make_world, generate_ports, find_spawn, can_stand, ResourceNode, WORLD_VERSION
from modules.terrain_render import TileAtlas, TerrainRenderer, prepare_terrain, ROCK, FOREST, GRASS
from modules.multiplayer import NetworkClient
from server import GameServer, ResourceAuthority


class WorldAndRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world), (main.COLS, main.ROWS), 'RGB').convert()

    def session(self, world=None, network=None):
        world = world or self.world
        return main.GameSession(world, world.ports, find_spawn(world), self.tiles, network, 42, {}, self.atlas)

    def test_multiple_seed_determinism_density_and_restrictions(self):
        for seed in (0, 42, 137, 2026):
            with self.subTest(seed=seed):
                a, b = make_world(seed), make_world(seed)
                self.assertEqual(a.heights, b.heights)
                self.assertEqual(a.nodes, b.nodes)
                self.assertEqual(a.ports, b.ports)
                trees = [n for n in a.nodes if n.type == 'Odun']
                self.assertGreater(len(trees), 500)
                self.assertEqual(len(a.nodes), len({n.id for n in a.nodes}))
                protected = a.roads | a.buildings
                for n in a.nodes:
                    x, y = int(n.x), int(n.y)
                    self.assertTrue(.09 <= a.heights[y][x] < .48)
                    self.assertFalse(any((x + dx, y + dy) in protected for dx in (-1, 0, 1) for dy in (-1, 0, 1)))
                    self.assertGreater(math.dist((n.x, n.y), find_spawn(a)), 2)
                dense = [p for p, density in a.woodland.items() if density > .6 and p not in protected]
                sparse = [p for p, density in a.woodland.items() if density < .35 and p not in protected]
                tree_cells = {(int(n.x), int(n.y)) for n in trees}
                self.assertGreater(sum(p in tree_cells for p in dense) / len(dense),
                                   2 * sum(p in tree_cells for p in sparse) / len(sparse))

    def test_boss_session_preserves_geography_buildings_roads_and_collision(self):
        world = copy.deepcopy(self.world)
        expected_heights = copy.deepcopy(world.heights)
        expected_owners = copy.deepcopy(world.owners)
        expected_buildings = set(world.buildings)
        expected_roads = set(world.roads)
        probes = list(world.roads)[:80] + list(world.buildings)[:80] + [(0, 0)]
        expected_collision = {
            (x, y, sailing): can_stand(world, x + .5, y + .5, sailing)
            for x, y in probes for sailing in (True, False)
        }
        session = self.session(world)
        session.treant_progress.portal_unlocked = True
        self.assertTrue(session.enter_treant_boss())
        session.leave_treant_boss(EncounterResult.DEFEAT)
        self.assertEqual(world.heights, expected_heights)
        self.assertEqual(world.owners, expected_owners)
        self.assertEqual(world.buildings, expected_buildings)
        self.assertEqual(world.roads, expected_roads)
        for (x, y, sailing), expected in expected_collision.items():
            self.assertEqual(can_stand(world, x + .5, y + .5, sailing), expected)
        for node in world.nodes:
            self.assertTrue(can_stand(world, node.x, node.y, False))

    def test_ports_are_idempotent_and_access_is_clear(self):
        before = set(self.world.roads)
        self.assertIs(generate_ports(self.world), self.world.ports)
        self.assertEqual(before, self.world.roads)
        for port in self.world.ports:
            self.assertTrue(can_stand(self.world, *port.spawn, False))
            self.assertTrue(can_stand(self.world, port.x + port.dx * 1.5 + .5,
                                      port.y + port.dy * 1.5 + .5, True))
            for step in range(4):
                self.assertIn((port.x - port.dx * step, port.y - port.dy * step), self.world.roads)

    def test_real_chopping_event_removes_canopy_and_respawns(self):
        world = copy.deepcopy(self.world)
        node = next(n for n in world.nodes if n.type == 'Odun')
        session = self.session(world)
        camera = (round(node.x * 48) - 90, round(node.y * 48) - 110)
        before = pygame.Surface((180, 160), pygame.SRCALPHA)
        after = before.copy()
        main.draw_node(before, node, *camera, self.atlas)
        session.wood_game.open(node)
        session.wood_game.bar_pos = 200
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE), (0, 0))
        self.assertFalse(node.active)
        self.assertFalse(session.wood_game.active)
        self.assertTrue(30 <= node.cooldown <= 40)
        main.draw_node(after, node, *camera, self.atlas)
        self.assertGreater(np.count_nonzero(pygame.surfarray.array_alpha(before)[:, :75]), 500)
        self.assertEqual(np.count_nonzero(pygame.surfarray.array_alpha(after)[:, :75]), 0)
        session.sync_resources(41)
        self.assertTrue(node.active)

    def test_nearest_tree_interaction(self):
        session = self.session(copy.deepcopy(self.world))
        node = next(n for n in session.world.nodes if n.type == 'Odun')
        session.player.update(node.x, node.y)
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e), (0, 0))
        self.assertIs(session.wood_game.node, node)

    def test_no_atlas_paper_in_ground_or_cliffs(self):
        for surface in [s for variants in self.atlas.ground.values() for s in variants] + [self.atlas.cliff_texture]:
            rgb = pygame.surfarray.array3d(surface).astype(int)
            paper = (rgb.min(axis=2) > 225) & (rgb.max(axis=2) - rgb.min(axis=2) < 25)
            # A few white pebble/wave highlights belong to the art; atlas gutters
            # instead form continuous light borders and large flat paper areas.
            self.assertLess(paper.mean(), .03)
            self.assertFalse(paper.all(axis=0).any())
            self.assertFalse(paper.all(axis=1).any())

    def test_all_neighbor_configurations_opaque_and_pixel_sharp(self):
        for mask in range(512):
            # All outer/inner coast corners, opposite shores, islands and diagonal-only joins.
            tile = self.atlas.compose((511, mask, 0, 0, 0, 0), -1, mask % 256, False)
            rgb = pygame.surfarray.array3d(tile)
            self.assertEqual(tile.get_size(), (48, 48))
            np.testing.assert_array_equal(rgb[::2, ::2], rgb[1::2, 1::2])
            self.assertFalse((rgb == (32, 39, 41)).all(axis=2).any())

    def test_paths_connect_every_arm_and_fill_plazas(self):
        for bits in range(512):
            alpha = pygame.surfarray.array_alpha(self.atlas.paths[bits])
            for bit, position in ((1, (12, 0)), (7, (12, 23)), (3, (0, 12)), (5, (23, 12))):
                self.assertEqual(alpha[position] == 255, bool(bits & (1 << bit)))
        self.assertTrue((pygame.surfarray.array_alpha(self.atlas.paths[511]) == 255).all())

    def test_ordinary_paths_never_render_neighboring_rock(self):
        kinds = (511, 511, 511, 511, 511, 511)
        a = self.atlas.compose(kinds, 511, 0, False)
        b = self.atlas.compose(kinds[:-1] + (0,), 511, 0, False)
        self.assertEqual(pygame.image.tobytes(a, 'RGB'), pygame.image.tobytes(b, 'RGB'))
        ground = self.world.terrain_data[0]
        for x, y in self.world.roads:
            self.assertNotEqual(ground[y, x], ROCK)

    def test_camera_and_chunk_boundaries_no_seams_after_scaling(self):
        renderer = TerrainRenderer(self.world, self.atlas)
        first, second = pygame.Surface((1200, 780)), pygame.Surface((1200, 780))
        x, y = self.session().cam_x, self.session().cam_y
        x, y = round(x), round(y)
        renderer.draw(first, x + .1, y + .1)
        renderer.draw(second, x + .4, y + .4)
        self.assertEqual(pygame.image.tobytes(first, 'RGB'), pygame.image.tobytes(second, 'RGB'))
        renderer.draw(second, x + 1, y + 1)
        np.testing.assert_array_equal(pygame.surfarray.array3d(first)[1:, 1:], pygame.surfarray.array3d(second)[:-1, :-1])
        for size in ((800, 520), (1537, 999), (1920, 1080)):
            scaled = pygame.transform.scale(first, size)
            rgb = pygame.surfarray.array3d(scaled)
            self.assertFalse((rgb == (32, 39, 41)).all(axis=2).any())

    def test_trees_and_player_share_depth_order(self):
        world = copy.deepcopy(self.world)
        node = next(n for n in world.nodes if n.type == 'Odun')
        world.nodes, world.buildings, world.village_props = [node], set(), []
        session = self.session(world)
        canvas = pygame.Surface((1200, 780))
        for offset, expected in ((-.3, ['player', 'tree']), (.3, ['tree', 'player'])):
            order = []
            session.player.update(node.x, node.y + offset)
            session.cam_x, session.cam_y = main.get_local_camera(session.player)
            with patch('main.draw_node', side_effect=lambda *args: order.append('tree')), patch('main.draw_player', side_effect=lambda *args: order.append('player')):
                session.render(canvas, (0, 0))
            self.assertEqual(order, expected)

    def test_missing_atlas_fallback_map_pause_and_sailing(self):
        session = self.session()
        session.atlas = session.terrain_renderer = None
        canvas = pygame.Surface((1200, 780))
        session.render(canvas, (0, 0))
        self.assertGreaterEqual(session.map_rect.left, 0)
        self.assertGreaterEqual(session.map_rect.top - 38, 0)
        self.assertLessEqual(session.map_rect.right, canvas.get_width())
        self.assertLessEqual(session.map_rect.bottom + 34, canvas.get_height())
        self.assertAlmostEqual(session.map_rect.width / session.map_rect.height,
                               main.COLS / main.ROWS, places=2)
        for key in (pygame.K_m, pygame.K_m, pygame.K_ESCAPE, pygame.K_ESCAPE):
            session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key), (0, 0))
            session.render(canvas, (0, 0))
        port = session.ports[0]
        session.player.update(port.x + .5, port.y + .5)
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f), (0, 0))
        self.assertTrue(session.is_sailing)
        session.render(canvas, (0, 0))
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f), (0, 0))
        self.assertFalse(session.is_sailing)
        self.assertEqual(tuple(session.player), port.spawn)


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        cls.world = make_world(42)

    def setUp(self):
        self.game = GameServer(self.world)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.clients = []
        self.threads = []
        self.current_id = 0

    def connect(self):
        thread = threading.Thread(target=self.accept_one, daemon=True)
        thread.start()
        client = NetworkClient('127.0.0.1', self.listener.getsockname()[1])
        self.assertTrue(client.try_connect())
        self.clients.append(client)
        self.threads.append(thread)
        return client

    def accept_one(self):
        conn, addr = self.listener.accept()
        pid = self.current_id
        self.current_id += 1
        self.game.handle_client(conn, addr, pid)

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.listener.close()
        for thread in self.threads:
            thread.join(1)

    def pump(self, clients, node, condition):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            for client in clients:
                client.send_and_receive(node.x, node.y, 'down', False, False)
            if condition():
                return
            time.sleep(.003)
        self.fail('Network condition did not converge')

    def test_two_clients_harvest_late_join_respawn_and_pause(self):
        a, b = self.connect(), self.connect()
        node = next(n for n in self.world.nodes if n.type == 'Odun')
        a.harvest(node.id)
        self.pump((a, b), node, lambda: node.id in a.resource_states and node.id in b.resource_states and not a.pending_harvests)
        deadline = self.game.resources.depleted[node.id]
        # Retrying/simultaneous chopping must not extend the original cooldown.
        b.harvest(node.id)
        self.pump((a, b), node, lambda: not b.pending_harvests)
        self.assertEqual(deadline, self.game.resources.depleted[node.id])
        c = self.connect()
        self.pump((c,), node, lambda: node.id in c.resource_states)
        with self.game.lock:
            self.game.resources.depleted[node.id] = time.monotonic() - 1
        self.pump((a, b, c), node, lambda: all(node.id not in client.resource_states for client in (a, b, c)))
        # Paused game sessions continue applying authoritative state.
        session = main.GameSession(copy.deepcopy(self.world), self.world.ports, (node.x, node.y),
                                   pygame.Surface((main.COLS, main.ROWS)), a, 42, {}, None)
        session.paused = True
        a.harvest(node.id)
        self.pump((a,), node, lambda: node.id in a.resource_states)
        session.update(.05, (0, 0))
        self.assertFalse(next(n for n in session.world.nodes if n.id == node.id).active)

    def test_partial_socket_writes_do_not_drop_harvest(self):
        a = self.connect()
        real_socket = a.client
        class PartialSocket:
            def send(self, data): return real_socket.send(data[:7])
            def recv(self, size): return real_socket.recv(11)
            def close(self): return real_socket.close()
        a.client = PartialSocket()
        node = self.world.nodes[0]
        a.harvest(node.id)
        self.pump((a,), node, lambda: node.id in a.resource_states and not a.pending_harvests)

    def test_authority_rejects_unknown_distant_sailing_and_duplicate_requests(self):
        now = [100.0]
        authority = ResourceAuthority(self.world, clock=lambda: now[0])
        node = self.world.nodes[0]
        self.assertFalse(authority.harvest('missing', dict(x=node.x, y=node.y)))
        self.assertFalse(authority.harvest(node.id, dict(x=0, y=0)))
        self.assertFalse(authority.harvest(node.id, dict(x=node.x, y=node.y, sailing=True)))
        self.assertTrue(authority.harvest(node.id, dict(x=node.x, y=node.y)))
        self.assertFalse(authority.harvest(node.id, dict(x=node.x, y=node.y)))
        self.assertTrue(30 <= authority.snapshot()[node.id] <= 40)
        now[0] += 41
        self.assertNotIn(node.id, authority.snapshot())

    def test_reconnect_cannot_attach_different_seed_to_loaded_world(self):
        a = self.connect()
        a.expected_seed = 137
        thread = threading.Thread(target=self.accept_one, daemon=True)
        thread.start()
        self.threads.append(thread)
        self.assertFalse(a.try_connect())
        self.assertIn('seed differs', a.error_msg)

    def test_legacy_player_response_and_coalesced_packets(self):
        modern = self.connect()
        thread = threading.Thread(target=self.accept_one, daemon=True)
        thread.start()
        legacy = socket.create_connection(self.listener.getsockname())
        legacy.settimeout(2)
        stream = legacy.makefile('rb')
        self.assertEqual(json.loads(stream.readline())['seed'], 42)
        legacy.sendall(b'{"x":10,"y":20}\n{"x":11,"y":21}\n')
        first, second = json.loads(stream.readline()), json.loads(stream.readline())
        self.assertNotIn('players', first)
        self.assertIn(str(modern.id), second)
        stream.close()
        legacy.close()
        thread.join(1)

    def test_pvp_damage_death_respawn_and_sail_state_are_authoritative(self):
        a, b = self.connect(), self.connect()
        # Complete the initial spawn handshake first.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not (a.spawn_confirmed and b.spawn_confirmed):
            a.send_and_receive(*(a.spawn + ('right', False, False)))
            b.send_and_receive(*(b.spawn + ('left', False, False)))
            time.sleep(.003)
        self.assertTrue(a.spawn_confirmed and b.spawn_confirmed)

        ax, ay = a.spawn
        bx, by = ax + 1.0, ay
        with self.game.lock:
            self.game.players[a.id].update(x=ax, y=ay, spawn_confirmed=True, facing='right')
            self.game.players[b.id].update(x=bx, y=by, spawn_confirmed=True, facing='left')

        self.assertTrue(a.pvp_attack(b.id, 'normal'))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and (b.health == 8 or a.pending_pvp_attacks):
            a.send_and_receive(ax, ay, 'right', False, False, attack_kind='normal', attack_timer=.5,
                               combo_step=1)
            b.send_and_receive(bx, by, 'left', False, False)
            time.sleep(.003)
        self.assertEqual(b.health, 7)
        self.assertFalse(a.pending_pvp_attacks)

        # Invalid boolean state is rejected, while a real lowered sail is relayed.
        with self.game.lock:
            self.game.players[a.id]['sailing'] = True
            self.game.players[b.id]['sailing'] = True
        a.send_and_receive(ax, ay, 'right', False, True, sail_raised=False)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            b.send_and_receive(bx, by, 'left', False, True)
            pdata = b.other_players.get(str(a.id), {})
            if pdata.get('sail_raised') is False:
                break
            time.sleep(.003)
        self.assertIs(b.other_players[str(a.id)]['sail_raised'], False)

        # Force a legal finishing blow and verify server-owned death + new spawn.
        with self.game.lock:
            attacker = self.game.players[a.id]
            target = self.game.players[b.id]
            attacker.update(x=ax, y=ay, sailing=False, last_attack_at=-100.0)
            target.update(x=bx, y=by, sailing=False, health=2, invulnerable_until=0.0)
        old_spawn_revision = b.spawn_revision
        self.assertTrue(a.pvp_attack(b.id, 'dash'))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and b.spawn_revision == old_spawn_revision:
            a.send_and_receive(ax, ay, 'right', False, False)
            b.send_and_receive(bx, by, 'left', False, False)
            time.sleep(.003)
        self.assertGreater(b.spawn_revision, old_spawn_revision)
        self.assertEqual(b.health, 8)
        self.assertEqual(b.deaths, 1)
        self.assertEqual(a.kills, 1)

    def test_online_platanus_entry_snapshot_and_retreat_are_authoritative(self):
        client = self.connect()
        self.assertTrue(client.treant_boss_authority)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not client.spawn_confirmed:
            client.send_and_receive(*(client.spawn + ('down', False, False)))
            time.sleep(.003)
        self.assertTrue(client.spawn_confirmed)

        px, py = self.world.boss_portal
        with self.game.lock:
            self.game.players[client.id].update(
                x=px, y=py, portal_unlocked=True, ancient_keys=0,
                spawn_confirmed=True, sailing=False,
            )
        self.assertTrue(client.enter_treant_boss())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not client.treant_progress.get('boss_active'):
            client.send_and_receive(px, py, 'down', False, False)
            time.sleep(.003)
        self.assertTrue(client.treant_progress.get('boss_active'))
        self.assertEqual(client.treant_progress['boss']['version'], 1)
        self.assertEqual(client.treant_progress['boss']['result'], 'IN_PROGRESS')

        self.assertTrue(client.retreat_treant_boss())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            position = client.treant_progress.get('player_position', (px, py))
            client.send_and_receive(position[0], position[1], 'down', False, False)
            if (client.treant_progress.get('boss_result') == 'DEFEAT'
                    and not client.treant_progress.get('boss_active')):
                break
            time.sleep(.01)
        self.assertFalse(client.treant_progress.get('boss_active'))
        self.assertEqual(client.treant_progress.get('boss_result'), 'DEFEAT')
        self.assertFalse(client.treant_progress.get('boss_defeated'))


if __name__ == '__main__':
    unittest.main()
