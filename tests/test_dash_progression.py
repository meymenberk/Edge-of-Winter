"""Dash (Windstep) is locked until the Wandering Sage teaches it after a liberation."""
import copy
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.worldgen import can_stand, compute_tile_pixels, find_spawn, make_world


def key(session, code):
    session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False), (0, 0))
    session.handle_event(pygame.event.Event(pygame.KEYUP, key=code), (0, 0))


class DashProgressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.world = make_world(42)
        cls.tiles = pygame.image.frombuffer(compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patch = mock.patch.object(main, "SAVE_FILE", Path(folder.name) / "savegame.json")
        patch.start()
        self.addCleanup(patch.stop)

    def session(self, save=None, network=None):
        world = copy.deepcopy(self.world)
        return main.GameSession(world, world.ports, find_spawn(world), self.tiles,
                                network, world.seed, {}, save_data=save)

    def liberate_current_island(self, session):
        index, _, _ = session.current_island_info()
        for quest in session.quest_system.quests.values():
            if quest.island_index == index:
                quest.state = "ready"
        for item in ("Odun", "Tas", "Tahil", "Balik"):
            session.inventory[item] = 999
        self.assertTrue(session.try_rescue_island())
        while session.dialogue.active:  # The village elder's key story comes first.
            session.dialogue.advance()

    def tick(self, session, frames=30):
        for _ in range(frames):
            session.update(1 / 60, (0, 0))

    def test_new_player_cannot_dash_and_spends_nothing(self):
        session = self.session()
        self.assertFalse(session.dash_unlocked)
        self.assertFalse(session.start_dash((1, 0)))
        session.game_time = 1.0
        key(session, pygame.K_d)
        session.game_time = 1.1
        key(session, pygame.K_d)
        self.assertEqual(session.dash_timer, 0)
        self.assertEqual(session.dash_cooldown, 0)
        self.assertEqual(session.energy, session.max_energy)
        self.tick(session)
        self.assertIsNone(session.sage)  # Nothing liberated yet.

    def test_first_liberation_brings_the_sage_who_teaches_windstep_once(self):
        session = self.session()
        self.liberate_current_island(session)
        self.tick(session, 60)
        sage = session.sage
        self.assertIsNotNone(sage)
        self.assertTrue(can_stand(session.world, sage["x"], sage["y"], False))
        session.player.update(sage["x"], sage["y"] + 1.0)
        hint = session.interaction_hint()
        self.assertEqual((hint.kind, hint.key), ("sage", session.key_label(session.INTERACT_KEY)))

        key(session, pygame.K_e)
        self.assertEqual(session.dialogue.speaker, "The Wandering Sage")
        self.assertIn("W/A/S/D", session.dialogue.pages[-1])
        key(session, pygame.K_ESCAPE)  # Leaving early must not unlock or lose the Sage.
        self.assertFalse(session.dash_unlocked)
        self.assertIsNotNone(session.sage)

        key(session, pygame.K_e)
        while session.dialogue.active:
            session.dialogue.advance()
        self.assertTrue(session.dash_unlocked)
        self.assertGreater(session.ability_popup_timer, 0)
        self.assertFalse(session.unlock_dash())  # Never granted twice.
        self.tick(session, 120)
        self.assertIsNone(session.sage)          # The Sage departs and never returns.

        session.dash_cooldown = 0
        self.assertTrue(session.start_dash((1, 0)))
        self.assertAlmostEqual(session.dash_timer, main.DASH_DURATION)
        self.assertEqual(session.dash_cooldown, main.DASH_COOLDOWN)
        self.assertEqual(session.treant_progress.keys_held, 1)  # Key quest unaffected.

    def test_unlock_persists_and_interrupted_encounters_resume(self):
        session = self.session()
        self.liberate_current_island(session)
        self.tick(session, 30)
        self.assertTrue(session.save_progress("mid-encounter"))
        resumed = self.session(main.load_local_save(self.world.seed))
        self.assertFalse(resumed.dash_unlocked)
        self.tick(resumed, 30)
        self.assertIsNotNone(resumed.sage)  # No soft-lock after quitting mid-encounter.

        resumed.unlock_dash()
        self.assertTrue(resumed.save_progress("learned"))
        restored = self.session(main.load_local_save(self.world.seed))
        self.assertTrue(restored.dash_unlocked)
        self.tick(restored, 60)
        self.assertIsNone(restored.sage)

    def test_older_saves_without_the_flag(self):
        fresh = self.session({"version": 1, "world_seed": 42, "player": {"spawn": "boss_portal"}})
        self.assertFalse(fresh.dash_unlocked)
        self.tick(fresh)
        self.assertIsNone(fresh.sage)
        island = next(i for i, isl in enumerate(self.world.islands) if isl.village)
        veteran = self.session({"version": 1, "world_seed": 42, "rescued_islands": [island]})
        self.assertFalse(veteran.dash_unlocked)
        self.assertEqual(veteran.liberated_island_count(), 1)

    def test_online_count_uses_server_confirmed_ownership(self):
        network = mock.Mock(connected=True, id=3, island_owners={}, lock=threading.Lock())
        session = self.session()
        session.network = network
        session.island_owners[5] = 3          # Optimistic local claim only.
        self.assertEqual(session.liberated_island_count(), 0)
        network.island_owners = {5: 3}         # Server confirmed.
        self.assertEqual(session.liberated_island_count(), 1)


if __name__ == "__main__":
    unittest.main()
