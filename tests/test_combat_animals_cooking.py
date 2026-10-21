import copy
import os
import time
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import pygame

import main
from modules.economy import inflation_multiplier
from modules.gameplay_systems import AnimalSystem, Monster
from modules.pixel_sprites import entity_sprite, item_sprite, villager_sprite
from server import GameServer
from modules.terrain_render import TileAtlas, prepare_terrain
from modules.worldgen import can_stand, compute_tile_pixels, find_spawn, make_world


class CombatAnimalsCookingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), 'RGB').convert()

    def session(self):
        world = copy.deepcopy(self.world)
        return main.GameSession(world, world.ports, find_spawn(world), self.tiles,
                                None, world.seed, {}, self.atlas)

    def test_pixel_sprites_are_distinct_opaque_and_nearest_scaled(self):
        sprites = [entity_sprite(kind) for kind in
                   ('wolf', 'boar', 'pirate', 'bandit', 'thief', 'sheep', 'cow')]
        signatures = {pygame.image.tobytes(sprite, 'RGBA') for sprite in sprites}
        self.assertEqual(len(signatures), len(sprites))
        for sprite in sprites + [villager_sprite('farmer'), villager_sprite('merchant'),
                                 item_sprite('Çiğ Et'), item_sprite('Pişmiş Et'), item_sprite('Ekmek')]:
            self.assertGreater(pygame.mask.from_surface(sprite).count(), 20)
        normal = pygame.surfarray.array3d(entity_sprite('wolf', flash=False))
        flashed = pygame.surfarray.array3d(entity_sprite('wolf', flash=True))
        self.assertGreater(flashed[:, :, 0].sum(), normal[:, :, 0].sum())

    def test_animals_spawn_only_on_accessible_grass_and_server_drops_once(self):
        system = AnimalSystem(self.world)
        self.assertTrue(any(a.kind == 'sheep' for a in system.animals))
        self.assertTrue(any(a.kind == 'cow' for a in system.animals))
        for animal in system.animals:
            x, y = int(animal.x), int(animal.y)
            self.assertTrue(.09 <= self.world.heights[y][x] < .43)
            self.assertNotIn((x, y), self.world.buildings)
            self.assertTrue(can_stand(self.world, animal.x, animal.y, False))

        server = GameServer(copy.deepcopy(self.world))
        animal = server.animal_system.animals[0]
        animal.health = 1
        server.players[1] = dict(x=animal.x - 1, y=animal.y, facing='right', sailing=False,
                                 spawn_confirmed=True, combat_xp=0, combat_revision=0,
                                 last_entity_attack_at=-100.0)
        request = {'target_id': animal.id, 'kind': 'normal'}
        self.assertTrue(server.apply_entity_attack(1, request))
        self.assertFalse(animal.alive)
        self.assertEqual(len(server.world_loot), 1)
        self.assertFalse(server.apply_entity_attack(1, request))
        self.assertEqual(len(server.world_loot), 1)
        drop = next(iter(server.world_loot.values()))
        server.players[1].update(x=drop['x'], y=drop['y'])
        self.assertTrue(server.apply_pickup(1, {'id': drop['id']}))
        self.assertFalse(server.apply_pickup(1, {'id': drop['id']}))

    def test_combat_xp_requires_a_real_once_per_swing_hit(self):
        session = self.session()
        for target in session.quest_system.monsters + session.animal_system.animals:
            target.alive = False
        session.combat.start_attack('normal')
        session.update_world_combat(.15)
        self.assertEqual(session.combat_xp, 0)

        session.combat.state = 'idle'
        target = Monster('xp-target', 0, session.player.x, session.player.y + .9,
                         kind='bandit', health=5, max_health=5)
        session.quest_system.monsters.append(target)
        session.facing = 'down'
        session.combat.start_attack('normal')
        session.update_world_combat(.15)
        awarded = session.combat_xp
        self.assertGreater(awarded, 0)
        session.update_world_combat(.01)
        self.assertEqual(session.combat_xp, awarded)

    def test_tree_hit_bursts_leaves_without_xp_or_harvesting(self):
        session = self.session()
        for target in session.quest_system.monsters + session.animal_system.animals:
            target.alive = False
        tree = next(node for node in session.world.nodes if node.type == 'Odun' and node.active)
        session.player.update(tree.x, tree.y - .8)
        session.facing = 'down'
        session.combat.start_attack('normal')
        session.update_world_combat(.15)
        self.assertTrue(tree.active)
        self.assertEqual(session.combat_xp, 0)
        self.assertGreaterEqual(sum(leaf.get('burst', False) for leaf in session.leaves.leaves), 1)
        count = len(session.leaves.leaves)
        session.update_world_combat(.01)
        self.assertEqual(len(session.leaves.leaves), count)

    def test_enemy_loot_is_generated_once(self):
        session = self.session()

        class GuaranteedLoot:
            def random(self): return 0.0
            def randrange(self, stop): return 0
            def choice(self, values): return values[0]
            def randint(self, low, high): return low

        session.loot_rng = GuaranteedLoot()
        monster = session.quest_system.monsters[0]
        monster.alive = False
        session.handle_monster_defeated(monster)
        count = len(session.loot_drops)
        self.assertGreater(count, 0)
        self.assertTrue(all(drop.item in session.inventory for drop in session.loot_drops))
        session.handle_monster_defeated(monster)
        self.assertEqual(len(session.loot_drops), count)

    def test_campfire_recipes_consume_atomically_and_food_heals(self):
        session = self.session()
        fire = next((x, y) for kind, x, y in session.world.village_props if kind == 'campfire')
        session.player.update(fire)
        session.inventory['Çiğ Et'] = 1
        session.inventory['Tahil'] = 2
        self.assertTrue(session.cook_recipe('meat'))
        self.assertEqual(session.inventory['Çiğ Et'], 0)
        self.assertEqual(session.inventory['Pişmiş Et'], 1)
        self.assertFalse(session.cook_recipe('meat'))
        session.cooking_cooldown = 0
        self.assertTrue(session.cook_recipe('bread'))
        self.assertEqual(session.inventory['Tahil'], 0)
        self.assertEqual(session.inventory['Ekmek'], 1)
        session.health = session.max_health - 3
        self.assertTrue(session.consume_food('Pişmiş Et'))
        self.assertEqual(session.health, session.max_health - 1)

    def test_inflation_is_elapsed_time_based_slow_and_capped(self):
        self.assertEqual(inflation_multiplier(0), 1.0)
        self.assertGreater(inflation_multiplier(30 * 60), 1.08)
        self.assertLess(inflation_multiplier(30 * 60), 1.13)
        self.assertEqual(inflation_multiplier(10_000 * 60), 1.35)
        base = main.get_island_cost(False, 1.0)
        late = main.get_island_cost(False, 1.35)
        self.assertLess(late['Odun'], base['Odun'] * 2)

    def test_integrated_render_smoke_includes_new_entities_and_ui(self):
        session = self.session()
        fire = next((x, y) for kind, x, y in session.world.village_props if kind == 'campfire')
        session.player.update(fire)
        session.cooking_open = True
        surface = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        session.render(surface, (main.GAME_WIDTH // 2, main.GAME_HEIGHT // 2))
        self.assertGreater(pygame.surfarray.array3d(surface).sum(), 0)


if __name__ == '__main__':
    unittest.main()
