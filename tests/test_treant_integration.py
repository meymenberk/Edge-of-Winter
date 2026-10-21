import copy
import json
import os
import random
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import main
from modules.progression import (TREANT_ACHIEVEMENT, TREANT_ACHIEVEMENT_DESCRIPTION,
                                 TREANT_ACHIEVEMENT_NAME,
                                 TreantQuestProgress)
from server import GameServer
from modules.treant_boss import (BOSS_ATTACK_STARTED, BOSS_DEFEATED, BOSS_NAME,
                                 BOSS_PHASE_CHANGED, ENCOUNTER_COMPLETED, BossPlayerState,
                                 BossState, EncounterResult, PlayerAttack,
                                 TreantBossEncounter, TreantConfig,
                                 resolve_boss_assets_dir)
from modules.worldgen import can_stand, compute_tile_pixels, find_spawn, make_world


class TreantProgressTests(unittest.TestCase):
    def test_platanus_player_facing_names_and_zero_of_three_start(self):
        progress = TreantQuestProgress()
        self.assertTrue(progress.quest_active)
        self.assertEqual(progress.keys_held, 0)
        self.assertEqual(BOSS_NAME, "PLATANUS")
        self.assertEqual(TREANT_ACHIEVEMENT, "Lanet Kıran")
        self.assertEqual(TREANT_ACHIEVEMENT_NAME, "Cursebreaker")
        self.assertEqual(
            TREANT_ACHIEVEMENT_DESCRIPTION,
            "You defeated PLATANUS, the ancient forest guardian, and lifted the curse "
            "of Crimsonroot Isle.",
        )

    def test_three_unique_rescues_unlock_once_and_serialize(self):
        progress = TreantQuestProgress()
        self.assertEqual(progress.record_village_rescue(12), 1)
        self.assertIsNone(progress.record_village_rescue(12))
        self.assertEqual(progress.record_village_rescue(7), 2)
        self.assertEqual(progress.record_village_rescue(31), 3)
        self.assertEqual(progress.keys_held, 3)
        self.assertTrue(progress.unlock_portal())
        self.assertEqual(progress.keys_held, 0)
        self.assertTrue(progress.unlock_portal())
        self.assertEqual(progress.keys_held, 0)
        self.assertTrue(progress.complete_boss())
        self.assertFalse(progress.complete_boss())
        restored = TreantQuestProgress.from_dict(progress.to_dict())
        self.assertTrue(restored.portal_unlocked)
        self.assertTrue(restored.boss_defeated)
        self.assertIn(TREANT_ACHIEVEMENT, restored.achievements)


class TreantWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = make_world(42)

    def test_single_reachable_boss_island_and_clear_portal(self):
        matches = [island for island in self.world.islands if island.name == "Crimsonroot Isle"]
        self.assertEqual(len(matches), 1)
        island = self.world.islands[self.world.boss_island_index]
        self.assertIsNone(island.village)
        self.assertTrue(any(port.island_index == self.world.boss_island_index
                            for port in self.world.ports))
        self.assertTrue(can_stand(self.world, *self.world.boss_portal, False))
        self.assertTrue(can_stand(self.world, *self.world.boss_return, False))
        px, py = self.world.boss_portal
        self.assertFalse(any(abs(node.x - px) <= 3 and abs(node.y - py) <= 3
                             for node in self.world.nodes))

    def test_boss_atlases_resolve_only_from_dedicated_folder(self):
        expected = (Path(main.__file__).resolve().parent / "assets" / "bosses" / "platanus")
        self.assertEqual(resolve_boss_assets_dir(main.BASE_DIR), expected)
        self.assertEqual(resolve_boss_assets_dir(), expected)
        self.assertEqual(resolve_boss_assets_dir("assets/bosses/platanus"), expected)
        self.assertTrue((expected / "bossanim.png").is_file())
        self.assertTrue((expected / "bosstile.png").is_file())
        self.assertFalse((Path(main.__file__).resolve().parent / "bossanim.png").exists())
        self.assertFalse((Path(main.__file__).resolve().parent / "bosstile.png").exists())


class PlatanusCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def make_encounter(self):
        encounter = TreantBossEncounter(
            main.BASE_DIR, TreantConfig(tile_size=main.LOCAL_TILE_SIZE, auto_start=True)
        )
        player = BossPlayerState(
            "tester", encounter.boss_x + 2.0, encounter.boss_y,
            health=100, max_health=100, facing=(-1.0, 0.0),
        )
        encounter.start(player)
        return encounter, player

    def test_phase_one_uses_arm_then_phase_two_can_earthquake(self):
        encounter, player = self.make_encounter()
        phase_one_attacks = []
        for _ in range(90):
            encounter.update(.05, player)
            phase_one_attacks.extend(
                event.data["attack"] for event in encounter.consume_events()
                if event.type == BOSS_ATTACK_STARTED
            )
        self.assertTrue(phase_one_attacks)
        self.assertEqual(set(phase_one_attacks), {"arm"})

        # A unique validated strike crosses the exact 50% threshold once.
        hitbox = encounter.boss_hitbox
        attack = PlayerAttack(
            "phase-hit", player.player_id, hitbox.x, hitbox.y,
            hitbox.width, hitbox.height, encounter.config.max_health / 2,
        )
        # Wait until the current phase-one attack has recovered so the hit is legal.
        while encounter.state not in (BossState.IDLE, BossState.APPROACH):
            encounter.update(.05, player)
            encounter.consume_events()
        self.assertTrue(encounter.register_player_attack(attack))
        self.assertFalse(encounter.register_player_attack(attack))
        phase_events = encounter.consume_events()
        self.assertTrue(any(event.type == BOSS_PHASE_CHANGED for event in phase_events))
        self.assertEqual(encounter.phase, 2)
        # Seed the post-transition choice independently of cosmetic burst RNG.
        # The first roll chooses quake; the anti-repeat rule then forces an arm.
        encounter.rng = random.Random(1)

        phase_two_attacks = []
        for _ in range(160):
            encounter.update(.05, player)
            phase_two_attacks.extend(
                event.data["attack"] for event in encounter.consume_events()
                if event.type == BOSS_ATTACK_STARTED
            )
            if "earthquake" in phase_two_attacks and "arm" in phase_two_attacks:
                break
        self.assertIn("earthquake", phase_two_attacks)
        self.assertIn("arm", phase_two_attacks)

    def test_defeat_animation_emits_platanus_victory_once(self):
        encounter, player = self.make_encounter()
        hitbox = encounter.boss_hitbox
        killing_attack = PlayerAttack(
            "finisher", player.player_id, hitbox.x, hitbox.y,
            hitbox.width, hitbox.height, encounter.config.max_health,
        )
        self.assertTrue(encounter.register_player_attack(killing_attack))
        events = encounter.consume_events()
        for _ in range(40):
            encounter.update(.05, player)
            events.extend(encounter.consume_events())
        defeated = [event for event in events if event.type == BOSS_DEFEATED]
        completed = [event for event in events if event.type == ENCOUNTER_COMPLETED]
        self.assertEqual([event.data["boss_name"] for event in defeated], ["PLATANUS"])
        self.assertEqual([event.data["result"] for event in completed], ["VICTORY"])

    def test_authority_snapshot_drives_render_replica(self):
        authority, player = self.make_encounter()
        authority.update(.5, player)
        replica, _ = self.make_encounter()
        snapshot = authority.get_state_snapshot()
        replica.apply_state_snapshot(snapshot)
        self.assertEqual(replica.state, authority.state)
        self.assertEqual(replica.phase, authority.phase)
        self.assertEqual(replica.health, authority.health)
        self.assertEqual(replica.get_result(), authority.get_result())
        replica.update_replica(.05)
        self.assertGreater(replica.total_time, snapshot["total_time"])


class TreantSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.world = make_world(42)
        cls.tiles = pygame.image.frombuffer(
            compute_tile_pixels(cls.world), (main.COLS, main.ROWS), "RGB"
        ).convert()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def make_session(self):
        world = copy.deepcopy(self.world)
        return main.GameSession(world, world.ports, find_spawn(world), self.tiles,
                                None, 42, {})

    def test_portal_transition_preserves_overworld_and_awards_once(self):
        session = self.make_session()
        world_identity = session.world
        inventory_identity = session.inventory
        for village_id in (2, 4, 6):
            session.award_ancient_key(village_id)
        session.dialogue.active = False
        session.player.update(session.world.boss_return)
        self.assertTrue(session.interact_treant_portal())
        self.assertTrue(session.treant_progress.portal_unlocked)
        self.assertEqual(session.inventory["Kadim Anahtar"], 0)
        session.portal_unlock_timer = 0
        self.assertTrue(session.interact_treant_portal())
        self.assertTrue(session.boss_active)
        session.leave_treant_boss(EncounterResult.VICTORY)
        self.assertIs(session.world, world_identity)
        self.assertIs(session.inventory, inventory_identity)
        self.assertEqual(tuple(session.player), tuple(session.world.boss_return))
        self.assertIn(TREANT_ACHIEVEMENT, session.treant_progress.achievements)
        self.assertFalse(session.enter_treant_boss())

    def test_portal_stays_locked_with_fewer_than_three_keys(self):
        session = self.make_session()
        session.player.update(session.world.boss_portal)
        self.assertTrue(session.near_treant_portal())
        session.award_ancient_key(2)
        session.dialogue.active = False
        self.assertFalse(session.interact_treant_portal())
        self.assertFalse(session.treant_progress.portal_unlocked)
        self.assertEqual(session.treant_progress.keys_held, 1)
        self.assertEqual(session.inventory["Kadim Anahtar"], 1)

    def test_defeat_keeps_unlocked_portal_and_allows_retry(self):
        session = self.make_session()
        session.treant_progress.portal_unlocked = True
        session.player.update(session.world.boss_return)
        self.assertTrue(session.enter_treant_boss())
        session.health = 0
        session.leave_treant_boss(EncounterResult.DEFEAT)
        self.assertTrue(session.treant_progress.portal_unlocked)
        self.assertFalse(session.treant_progress.boss_defeated)
        self.assertEqual(session.health, session.max_health)
        self.assertTrue(session.enter_treant_boss())

    def test_completed_encounter_waits_for_visible_result_before_return(self):
        session = self.make_session()
        session.treant_progress.portal_unlocked = True
        self.assertTrue(session.enter_treant_boss())
        session.treant_encounter.result = EncounterResult.VICTORY
        session.treant_encounter._completion_emitted = True
        session.treant_encounter._emit(ENCOUNTER_COMPLETED, result="VICTORY")
        session.update_treant_boss(0.01)
        self.assertTrue(session.boss_active)
        self.assertTrue(session.boss_completion_pending)
        session.update_treant_boss(2.0)
        self.assertFalse(session.boss_active)
        self.assertTrue(session.treant_progress.boss_defeated)

    def test_context_prompts_cover_portal_villager_campfire_and_resources(self):
        session = self.make_session()

        session.player.update(session.world.boss_portal)
        hint = session.interaction_hint()
        self.assertEqual((hint.key, hint.kind, hint.action), ("E", "portal", "Seals 0/3"))
        session.treant_progress.rescued_village_ids.update((1, 2, 3))
        session.treant_progress.keys_held = 3
        self.assertEqual(session.interaction_hint().action, "Unseal")
        session.treant_progress.portal_unlocked = True
        self.assertEqual(session.interaction_hint().action, "Enter")

        fire = next((x, y) for kind, x, y in session.world.village_props
                    if kind == "campfire")
        session.player.update(fire)
        self.assertEqual((session.interaction_hint().key, session.interaction_hint().kind,
                          session.interaction_hint().action), ("E", "campfire", "Cook"))

        fires = [(x, y) for kind, x, y in session.world.village_props if kind == "campfire"]
        npc = next(npc for npc in session.quest_system.npcs
                   if all(((npc.x - x) ** 2 + (npc.y - y) ** 2) ** .5 > 2.0
                          for x, y in fires))
        session.player.update(npc.x, npc.y)
        self.assertEqual((session.interaction_hint().key, session.interaction_hint().kind,
                          session.interaction_hint().action), ("E", "npc", "Talk"))

        blockers = fires + [(npc.x, npc.y) for npc in session.quest_system.npcs]
        for node_type, action in (("Odun", "Chop"), ("Tas", "Mine"), ("Tahil", "Harvest")):
            node = next(node for node in session.world.nodes if node.type == node_type
                        and all(((node.x - x) ** 2 + (node.y - y) ** 2) ** .5 > 3.0
                                for x, y in blockers)
                        and all(((node.x - (port.x + .5)) ** 2
                                 + (node.y - (port.y + .5)) ** 2) ** .5 > 3.0
                                for port in session.ports))
            session.player.update(node.x, node.y)
            hint = session.interaction_hint()
            self.assertEqual((hint.key, hint.kind, hint.action),
                             ("E", f"resource:{node_type}", action))

    def test_context_prompt_uses_real_port_keys_and_hides_during_ui(self):
        session = self.make_session()
        port = session.ports[0]
        session.player.update(port.x + .5, port.y + .5)
        # Remove higher-priority objects only from this focused selection check.
        session.world.village_props = []
        session.quest_system.npcs = []
        self.assertEqual((session.interaction_hint().key, session.interaction_hint().action),
                         ("E", "Fish"))
        session.player.update(port.x + 2.2, port.y + .5)
        self.assertEqual((session.interaction_hint().key, session.interaction_hint().action),
                         ("F", "Set Sail"))
        session.is_sailing = True
        self.assertEqual((session.interaction_hint().key, session.interaction_hint().action),
                         ("F", "Go Ashore"))
        session.dialogue.active = True
        self.assertIsNone(session.interaction_hint())
        session.dialogue.active = False
        session.is_sailing = True
        merchant = next(ship for ship in session.naval.ships
                        if ship.alive and ship.kind == "merchant")
        session.player.update(merchant.x, merchant.y)
        self.assertEqual((session.interaction_hint().key, session.interaction_hint().action),
                         ("E", "Trade"))
        session.is_sailing = False
        session.player.update(-100, -100)
        self.assertIsNone(session.interaction_hint())

    def test_pixel_prompt_is_cached_and_clamped_above_world(self):
        session = self.make_session()
        from modules.game_ui import InteractionHint
        screen = pygame.Surface((320, 180), pygame.SRCALPHA)
        hint = InteractionHint("E", "Talk", (-50.0, -50.0), "npc")
        first = session.interaction_prompt.surface(hint.key, hint.action)
        second = session.interaction_prompt.surface(hint.key, hint.action)
        self.assertIs(first, second)
        rect = session.interaction_prompt.draw(screen, hint, (0, 0), main.LOCAL_TILE_SIZE)
        self.assertGreaterEqual(rect.left, 7)
        self.assertGreaterEqual(rect.top, 7)
        self.assertLessEqual(rect.bottom, screen.get_height() - 36)
        self.assertGreater(pygame.mask.from_surface(first).count(), 0)


class TreantServerSafeguardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = make_world(42)

    def test_server_deduplicates_keys_and_validates_portal_proximity(self):
        game = GameServer(copy.deepcopy(self.world))
        village_ids = [i for i, island in enumerate(game.world.islands) if island.village][:3]
        first = game.world.islands[village_ids[0]]
        game.players[9] = dict(
            x=first.village.center[0] + .5, y=first.village.center[1] + .5,
            sailing=False, spawn_confirmed=True, rescued_villages=[], ancient_keys=0,
            portal_unlocked=False,
        )
        self.assertTrue(game.apply_village_rescue(9, village_ids[0]))
        self.assertTrue(game.apply_village_rescue(9, village_ids[0]))
        self.assertEqual(game.players[9]["ancient_keys"], 1)
        for island_id in village_ids[1:]:
            village = game.world.islands[island_id].village
            game.players[9].update(x=village.center[0] + .5, y=village.center[1] + .5)
            self.assertTrue(game.apply_village_rescue(9, island_id))
        self.assertEqual(game.players[9]["ancient_keys"], 3)
        self.assertFalse(game.apply_portal_unlock(9))
        game.players[9].update(x=game.world.boss_portal[0], y=game.world.boss_portal[1])
        self.assertTrue(game.apply_portal_unlock(9))
        self.assertEqual(game.players[9]["ancient_keys"], 0)
        self.assertTrue(game.apply_portal_unlock(9))

    def test_server_owns_online_boss_damage_and_return(self):
        game = GameServer(copy.deepcopy(self.world))
        px, py = game.world.boss_portal
        game.players[9] = dict(
            x=px, y=py, facing='up', sailing=False, moving=False,
            spawn_confirmed=True, health=8, max_health=8,
            combat_xp=0, combat_revision=0, damage_revision=0,
            invulnerable_until=0.0, portal_unlocked=True,
            boss_defeated=False, boss_active=False,
            boss_result=EncounterResult.IN_PROGRESS.value,
        )
        self.assertTrue(game.start_treant_boss(9))
        encounter = game.boss_encounters[9]
        game.players[9].update(x=encounter.boss_x, y=encounter.boss_y + 1.0, facing='up')
        before = encounter.health
        request = dict(seq=1, attack_id='one', kind='normal', combo_step=3,
                       weapon_level=4, damage=99999,
                       x=encounter.boss_x, y=encounter.boss_y)
        self.assertTrue(game.apply_treant_boss_attack(9, request))
        self.assertEqual(before - encounter.health, 1)
        self.assertFalse(game.apply_treant_boss_attack(9, request))
        json.dumps(game.treant_state(9))

        self.assertTrue(game.retreat_treant_boss(9))
        game.update_treant_boss(9)
        self.assertEqual(game.players[9]['boss_result'], EncounterResult.DEFEAT.value)
        game.boss_completion_deadlines[9] = 0.0
        game.update_treant_boss(9)
        self.assertFalse(game.players[9]['boss_active'])
        self.assertEqual((game.players[9]['x'], game.players[9]['y']),
                         tuple(game.world.boss_return))
        self.assertFalse(game.players[9]['boss_defeated'])

    def test_server_victory_marks_reward_once_and_returns_same_world(self):
        game = GameServer(copy.deepcopy(self.world))
        world_identity = game.world
        px, py = game.world.boss_portal
        game.players[3] = dict(
            x=px, y=py, facing='up', sailing=False, moving=False,
            spawn_confirmed=True, health=8, max_health=8,
            combat_xp=0, combat_revision=0, damage_revision=0,
            invulnerable_until=0.0, portal_unlocked=True,
            boss_defeated=False, boss_active=False,
            boss_result=EncounterResult.IN_PROGRESS.value,
        )
        self.assertTrue(game.start_treant_boss(3))
        encounter = game.boss_encounters[3]
        hitbox = encounter.boss_hitbox
        self.assertTrue(encounter.register_player_attack(PlayerAttack(
            'authority-finisher', '3', hitbox.x, hitbox.y,
            hitbox.width, hitbox.height, encounter.config.max_health,
        )))
        player = BossPlayerState('3', encounter.portal_spawn[0], encounter.portal_spawn[1],
                                 health=8, max_health=8)
        for _ in range(40):
            encounter.update(.05, player)
        game.update_treant_boss(3)
        self.assertTrue(game.players[3]['boss_defeated'])
        self.assertEqual(game.players[3]['boss_result'], EncounterResult.VICTORY.value)
        game.boss_completion_deadlines[3] = 0.0
        game.update_treant_boss(3)
        self.assertFalse(game.players[3]['boss_active'])
        self.assertIs(game.world, world_identity)
        self.assertFalse(game.start_treant_boss(3))


if __name__ == "__main__":
    unittest.main()
