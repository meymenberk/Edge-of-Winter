import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import pygame

from modules.gameplay_systems import (ArenaCombatScene, CombatSystem, DialogueBox, EnemyAISystem,
                                      Monster, NavalEncounterSystem, Quest, QuestSystem)
from modules.worldgen import SpawnPool


class GameplaySystemTests(unittest.TestCase):
    def test_spawn_pool_uses_different_islands_before_reuse(self):
        islands = [SimpleNamespace(x=3, y=3, rx=2, ry=2, village=None),
                   SimpleNamespace(x=9, y=3, rx=2, ry=2, village=None),
                   SimpleNamespace(x=15, y=3, rx=2, ry=2, village=None)]
        owners = [[-1] * 20 for _ in range(8)]
        heights = [[.2] * 20 for _ in range(8)]
        for y in range(1, 6):
            for x in range(1, 6): owners[y][x] = 0
            for x in range(7, 12): owners[y][x] = 1
            for x in range(13, 18): owners[y][x] = 2
        world = SimpleNamespace(islands=islands, owners=owners, heights=heights,
                                buildings=set(), village_props=[])
        pool = SpawnPool(world)
        chosen = [pool.acquire()[0] for _ in range(3)]
        self.assertEqual(len(set(chosen)), 3)
        self.assertNotEqual(pool.acquire()[0], chosen[-1])

    def test_typewriter_advances_and_calls_completion(self):
        completed = []
        dialogue = DialogueBox(chars_per_second=10)
        dialogue.open('Köylü', ['Birinci sayfa', 'İkinci'], lambda: completed.append(True))
        dialogue.update(.3)
        self.assertEqual(dialogue.visible_text, 'Bir')
        dialogue.advance()
        self.assertTrue(dialogue.page_complete)
        dialogue.advance()
        self.assertEqual(dialogue.page, 1)
        dialogue.advance()
        dialogue.advance()
        self.assertFalse(dialogue.active)
        self.assertEqual(completed, [True])

    def test_normal_combo_and_crouch_attack_hitboxes(self):
        combat = CombatSystem()
        player = pygame.Vector2(10, 10)
        monster = Monster('m', 0, 10, 11)
        combat.start_attack('normal')
        combat.update(.15, player, 'down', [monster], lambda _: None)
        self.assertEqual(monster.health, 2)
        self.assertGreater(monster.hit_flash, 0)
        normal_box = combat.hitbox(player, 'down')
        combat.state = 'idle'
        combat.start_attack('crouch')
        crouch_box = combat.hitbox(player, 'down')
        self.assertGreater(crouch_box[2], normal_box[2])

    def test_third_combo_is_heavy_and_enemy_ai_telegraphs(self):
        combat = CombatSystem()
        player = pygame.Vector2(10, 10)
        monster = Monster('combo-target', 0, 10, 11, health=5, max_health=5)
        combat.combo_step = 2
        combat.combo_window = .2
        combat.start_attack('normal')
        self.assertEqual(combat.combo_step, 3)
        combat.update(.15, player, 'down', [monster], lambda _: None)
        self.assertEqual(monster.health, 2)

        attacker = Monster('attacker', 0, 10, 10.7, kind='bandit', attack_windup=.2)
        ai = EnemyAISystem()
        self.assertEqual(ai.update(.1, player, [attacker], 0, lambda x, y: True), [])
        hits = ai.update(.12, player, [attacker], 0, lambda x, y: True)
        self.assertEqual(hits, [attacker])
        self.assertGreater(attacker.attack_cooldown, 0)

    def test_naval_merchants_roam_and_pirates_fire(self):
        world = SimpleNamespace(seed=5, heights=[[-.4] * 80 for _ in range(50)], ports=[])
        naval = NavalEncounterSystem(world, 5, lambda x, y: True, count=6)
        self.assertEqual(sum(s.kind == 'merchant' for s in naval.ships), 2)
        self.assertEqual(sum(s.kind == 'pirate' for s in naval.ships), 4)
        pirate = next(s for s in naval.ships if s.kind == 'pirate')
        player = pygame.Vector2(30, 20)
        pirate.x, pirate.y = 35, 20
        naval.update(.1, player, True, lambda x, y: True)
        self.assertFalse(naval.cannonballs)
        naval.update(.7, player, True, lambda x, y: True)
        self.assertTrue(naval.cannonballs)

        merchant = next(s for s in naval.ships if s.kind == 'merchant')
        merchant.x, merchant.y = 30.5, 20
        self.assertIs(naval.nearby_merchant(player), merchant)

    def test_quest_accept_progress_and_reward(self):
        village = SimpleNamespace(center=(10, 10))
        island = SimpleNamespace(x=10, y=10, rx=8, ry=8, village=village)
        owners = [[0] * 24 for _ in range(24)]
        world = SimpleNamespace(seed=7, islands=[island], owners=owners, buildings=set())
        quests = QuestSystem(world)
        npc, dialogue = quests.npcs[0], DialogueBox()
        rewards = []
        quests.interact(npc, dialogue, rewards.append)
        while dialogue.active:
            dialogue.advance()
        quest = quests.quests[npc.quest_id]
        self.assertEqual(quest.state, 'active')
        for monster in quests.monsters:
            quests.monster_defeated(monster)
        self.assertEqual(quest.state, 'ready')
        quests.interact(npc, dialogue, rewards.append)
        dialogue.advance()
        dialogue.advance()
        self.assertEqual(quest.state, 'completed')
        self.assertEqual(rewards, [quest.reward])

    def test_arena_reports_win_and_loss(self):
        quest = Quest('q', 2, 'npc', 'island_slime', 2, {})
        arena = ArenaCombatScene()
        arena.open(quest, seed=4)
        for monster in arena.monsters:
            monster.alive = False
        self.assertEqual(arena.update(.1), 'won')
        arena.open(quest, seed=4)
        arena.health = 0
        self.assertEqual(arena.update(.1), 'lost')


if __name__ == '__main__':
    unittest.main()
