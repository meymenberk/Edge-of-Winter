"""Focused regression coverage for event-driven audio behavior."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.audio_manager import AudioManager
from modules.gameplay_systems import CombatSystem


ROOT = Path(__file__).resolve().parents[1]


class AudioManagerTests(unittest.TestCase):
    def setUp(self):
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        self.audio = AudioManager(ROOT / "music", seed=7)
        self.audio.activate_gameplay()

    def tearDown(self):
        self.audio.stop_all()
        pygame.quit()

    def test_assets_resolve_cache_and_reserved_loops_are_idempotent(self):
        self.assertTrue(self.audio.enabled)
        self.assertEqual(self.audio.missing_assets, [])
        self.assertEqual(self.audio.paths["monster_growl_1"].name, "monster growl.mp3")
        self.assertEqual(self.audio.active_loop("environment"), "ocean_waves")

        self.assertTrue(self.audio.start_loop("walking_on_grass", "movement"))
        channel = pygame.mixer.Channel(self.audio.LOOP_CHANNELS["movement"])
        playing = channel.get_sound()
        self.assertTrue(self.audio.start_loop("walking_on_grass", "movement"))
        self.assertIs(channel.get_sound(), playing)
        self.audio.stop_category_loop("movement")
        self.assertIsNone(self.audio.active_loop("movement"))

    def test_music_switch_is_stateful_and_creatures_are_globally_staggered(self):
        self.assertTrue(self.audio.switch_music("main_theme", 0))
        self.assertEqual(self.audio.current_music, "main_theme")
        self.assertTrue(self.audio.switch_music("main_theme", 1000))
        self.assertIsNone(self.audio.pending_music)
        self.assertTrue(self.audio.switch_music("boss_1", 1000))
        self.audio.update(1.1)
        self.assertEqual(self.audio.current_music, "boss_1")

        entities = [("sheep:1", "sheep", 1.0, 1.0, True),
                    ("cow:1", "cow", 1.5, 1.0, True)]
        self.audio.update_creatures(0, entities, (1.0, 1.0))
        for timer in self.audio._creature_timers.values():
            timer.remaining = 0
        self.audio.update_creatures(.01, entities, (1.0, 1.0))
        busy = sum(pygame.mixer.Channel(index).get_busy()
                   for index in self.audio.CHANNEL_POOLS["creature"])
        self.assertEqual(busy, 1)
        self.assertGreater(self.audio._creature_global_cooldown, 0)


class AudioEventBoundaryTests(unittest.TestCase):
    def test_combat_callback_only_marks_accepted_swings(self):
        events = []
        combat = CombatSystem()
        combat.on_attack = events.append
        self.assertTrue(combat.start_attack("normal"))
        self.assertFalse(combat.start_attack("crouch"))
        self.assertEqual(events, ["normal"])
        combat.update(1.0, pygame.Vector2(0, 0), "down", [], lambda _target: None)
        self.assertEqual(events, ["normal", "crouch"])

    def test_resource_and_cast_callbacks_use_real_transitions(self):
        impacts = []
        falls = []
        node = SimpleNamespace(x=2, y=3, active=True, cooldown=0.0,
                               harvest=lambda: None)

        wood = main.WoodChopping()
        wood.open(node, required_hits=1)
        wood.on_impact = lambda: impacts.append("wood")
        wood.on_fall = lambda: falls.append("fall")
        wood.good_hit = True
        wood.state, wood.timer = "SWING", .14
        wood.update(0)
        self.assertEqual(impacts, ["wood"])
        wood.state, wood.timer = "RETURN", .22
        wood.update(0)
        self.assertEqual(falls, ["fall"])

        stone = main.StoneMining()
        stone.open(node)
        stone.on_impact = lambda: impacts.append("stone")
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                   pos=stone.targets[0]["rect"].center)
        stone.handle_event(event, event.pos)
        self.assertEqual(impacts, ["wood", "stone"])

        casts = []
        fishing = main.OpenWaterFishing(3)
        fishing.on_cast = lambda: casts.append("cast")
        fishing.open(SimpleNamespace(dx=1, dy=0), pygame.Vector2(4, 5))
        self.assertEqual(casts, ["cast"])


if __name__ == "__main__":
    unittest.main()
