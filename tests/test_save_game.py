"""Offline save file: robust loading, safe writing and session round trips."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.progression import TreantQuestProgress
from modules.save_game import backup_path, load_save, seed_archive_path, write_save
from modules.worldgen import can_stand, compute_tile_pixels, find_spawn, make_world


class SaveFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.path = self.folder / "savegame.json"

    def test_missing_save_starts_fresh(self):
        self.assertEqual(load_save(42, self.path), {})

    def test_corrupt_save_is_kept_aside_and_backup_is_used(self):
        write_save({"world_seed": 42, "inventory": {"Odun": 1}}, self.path)
        write_save({"world_seed": 42, "inventory": {"Odun": 2}}, self.path)
        self.assertEqual(json.loads(backup_path(self.path).read_text())["inventory"]["Odun"], 1)
        self.path.write_text("{truncated", encoding="utf-8")
        data = load_save(42, self.path)
        self.assertEqual(data["inventory"]["Odun"], 1)
        corrupt = list(self.folder.glob("savegame.corrupt-*.json"))
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(corrupt[0].read_text(), "{truncated")  # never destroyed

    def test_unsupported_shapes_do_not_raise(self):
        shapes = ("[]", "null", '{"version": 99}', '{"version": "x"}', "")
        for text in shapes:
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertEqual(load_save(42, self.path), {})
        # Each unreadable file is preserved under its own name.
        self.assertEqual(len(list(self.folder.glob("savegame.corrupt-*.json"))), len(shapes))

    def test_other_world_save_is_archived_not_overwritten(self):
        write_save({"world_seed": 42, "inventory": {"Odun": 5}}, self.path)
        write_save({"world_seed": 7, "inventory": {"Odun": 9}}, self.path)
        self.assertEqual(load_save(7, self.path)["inventory"]["Odun"], 9)
        self.assertEqual(load_save(42, self.path)["inventory"]["Odun"], 5)
        self.assertTrue(seed_archive_path(self.path, 42).is_file())

    def test_legacy_minimal_save_still_loads(self):
        self.path.write_text(json.dumps({"version": 1, "world_seed": 42,
                                         "player": {"spawn": "boss_portal"}}))
        self.assertEqual(load_save(42, self.path)["player"]["spawn"], "boss_portal")

    def test_malformed_quest_progress_values_are_skipped(self):
        progress = TreantQuestProgress.from_dict({
            "rescued_village_ids": [1, "x", None, "2"], "keys_held": "lots",
            "dialogue_steps_seen": "not-a-list", "achievements": 5})
        self.assertEqual(progress.rescued_village_ids, {1, 2})
        self.assertEqual(progress.keys_held, 0)
        self.assertEqual(progress.dialogue_steps_seen, set())
        self.assertEqual(progress.achievements, set())


class SessionSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.world = make_world(42)
        cls.tiles = pygame.image.frombuffer(compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()

    def session(self, save=None):
        world = copy.deepcopy(self.world)
        return main.GameSession(world, world.ports, find_spawn(world), self.tiles,
                                None, world.seed, {}, save_data=save)

    def test_progress_round_trips_through_disk(self):
        session = self.session()
        session.inventory["Odun"] = 31
        session.progression.levels["sword"] = 3
        session.health, session.combat_xp = 5, 17
        session.treant_progress.record_village_rescue(4)
        quest = next(iter(session.quest_system.quests.values()))
        quest.state, quest.progress = "active", 2
        monster = session.quest_system.monsters[0]
        monster.alive = False
        island = next(i for i, isl in enumerate(session.world.islands) if isl.village)
        session.island_owners[island] = 0
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(main, "SAVE_FILE", Path(folder) / "savegame.json"):
            self.assertTrue(session.save_progress("test"))
            restored = self.session(main.load_local_save(self.world.seed))
        self.assertEqual(restored.inventory["Odun"], 31)
        self.assertEqual(restored.inventory["Kadim Anahtar"], 1)
        self.assertEqual(restored.progression.levels["sword"], 3)
        self.assertEqual((restored.health, restored.combat_xp), (5, 17))
        self.assertEqual(restored.quest_system.quests[quest.id].state, "active")
        self.assertEqual(restored.quest_system.quests[quest.id].progress, 2)
        self.assertFalse(next(m for m in restored.quest_system.monsters if m.id == monster.id).alive)
        self.assertEqual(restored.island_owners.get(island), 0)
        self.assertAlmostEqual(restored.player.x, session.player.x, places=2)
        self.assertAlmostEqual(restored.player.y, session.player.y, places=2)

    def test_only_entered_sessions_autosave(self):
        session = self.session()
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(main, "SAVE_FILE", Path(folder) / "savegame.json"):
            session.request_autosave(0)
            session._tick_autosave(1.0)
            self.assertFalse(main.SAVE_FILE.exists())  # preloaded/tool sessions stay silent
            session.autosave_enabled = True
            session._tick_autosave(1.0)
            self.assertTrue(main.SAVE_FILE.exists())

    def test_garbage_fields_never_crash_session_start(self):
        save = {"version": 1, "world_seed": 42, "player": "nowhere",
                "inventory": {"Odun": "many", "Tas": -4, 7: 3}, "equipment": [],
                "weapon_levels": {"sword": "max"}, "stats": {"health": "dead", "game_time": "nan"},
                "rescued_islands": ["x", 10 ** 9, -1], "quests": {"bogus": 1},
                "defeated_monsters": "all", "treant_progress": []}
        session = self.session(save)
        self.assertEqual(session.island_owners, {})  # out-of-range indices rejected
        self.assertEqual(session.inventory["Tas"], 0)
        self.assertEqual(session.health, session.max_health)
        self.assertTrue(can_stand(session.world, session.player.x, session.player.y, False))

    def test_position_in_water_falls_back_to_a_safe_spawn(self):
        session = self.session({"version": 1, "world_seed": 42, "player": {"x": 0.5, "y": 0.5}})
        self.assertTrue(can_stand(session.world, session.player.x, session.player.y, False))

    def test_other_seed_save_is_ignored(self):
        session = self.session({"version": 1, "world_seed": 43, "inventory": {"Odun": 99}})
        self.assertNotEqual(session.inventory["Odun"], 99)


if __name__ == "__main__":
    unittest.main()
