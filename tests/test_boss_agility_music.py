"""PLATANUS footwork, phase rules and boss-music lifecycle."""
import math
import os
import random
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.treant_boss import (BOSS_ATTACK_STARTED, BossPlayerState, BossState,
                                 EncounterResult, PlayerAttack, TreantBossEncounter, TreantConfig)
from modules.terrain_render import TileAtlas, prepare_terrain
from modules.worldgen import find_spawn, generate_ports, make_world


def player_at(x, y, health=99):
    return BossPlayerState("p", x, y, health=health, max_health=99)


class PlatanusAgilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((64, 64))

    def encounter(self):
        encounter = TreantBossEncounter(main.BASE_DIR, TreantConfig(tile_size=48, auto_start=True))
        encounter.start(player_at(0, 0))
        return encounter

    def run_until_attack(self, encounter, player, limit=8.0):
        elapsed = 0.0
        while elapsed < limit:
            encounter.update(.05, player)
            elapsed += .05
            for event in encounter.consume_events():
                if event.type == BOSS_ATTACK_STARTED:
                    return elapsed, event.data["attack"]
        return None, None

    def test_speed_is_moderately_higher_and_stays_below_the_player(self):
        encounter = self.encounter()
        self.assertGreater(encounter._move_speed(), 1.42)
        encounter.phase = 2
        self.assertGreater(encounter._move_speed(), encounter.config.boss_speed)
        self.assertLess(encounter._move_speed(), main.PLAYER_SPEED / 2)

    def test_chase_flows_directly_into_an_attack(self):
        encounter = self.encounter()
        player = player_at(encounter.boss_x, encounter.boss_y + 6.5)
        elapsed, attack = self.run_until_attack(encounter, player)
        self.assertEqual(attack, "arm")
        self.assertLess(elapsed, 3.0)
        self.assertLessEqual(math.hypot(player.x - encounter.boss_x, player.y - encounter.boss_y),
                             encounter.ATTACK_DISTANCE + .05)

    def test_backs_off_when_crowded_and_strafes_during_cooldown(self):
        encounter = self.encounter()
        player = player_at(encounter.boss_x + .7, encounter.boss_y)
        self.run_until_attack(encounter, player)
        while encounter.state not in (BossState.IDLE, BossState.APPROACH):
            encounter.update(.05, player)
        start = math.hypot(player.x - encounter.boss_x, player.y - encounter.boss_y)
        for _ in range(12):
            encounter.update(.05, player)
        self.assertGreater(math.hypot(player.x - encounter.boss_x, player.y - encounter.boss_y), start)

        encounter = self.encounter()
        player = player_at(encounter.boss_x + 2.0, encounter.boss_y)
        self.run_until_attack(encounter, player)
        positions = []
        for _ in range(60):
            encounter.update(.05, player)
            positions.append((round(encounter.boss_x, 3), round(encounter.boss_y, 3)))
        self.assertGreater(len(set(positions)), 5, "PLATANUS should reposition between attacks")

    def test_steps_around_arena_blockers(self):
        encounter = self.encounter()
        moved = []
        for bx, by, bw, bh in encounter._blockers():
            encounter.boss_x, encounter.boss_y = bx + bw / 2, by + bh + 1.0
            if not encounter.can_stand(encounter.boss_x, encounter.boss_y, .65):
                continue
            before = (encounter.boss_x, encounter.boss_y)
            encounter._step(pygame.Vector2(0, -1), .5)
            moved.append(before != (encounter.boss_x, encounter.boss_y))
        self.assertTrue(moved and all(moved))

    def test_phase_one_is_arm_only_and_phase_two_leap_is_telegraphed(self):
        encounter = self.encounter()
        player = player_at(encounter.boss_x + 2.6, encounter.boss_y + .4)
        seen = set()
        for _ in range(120):
            encounter.update(.05, player)
            seen.update(e.data["attack"] for e in encounter.consume_events() if e.type == BOSS_ATTACK_STARTED)
        self.assertEqual(seen, {"arm"})

        while encounter.state not in (BossState.IDLE, BossState.APPROACH):
            encounter.update(.05, player)
        box = encounter.boss_hitbox
        encounter.register_player_attack(PlayerAttack("half", "p", box.x, box.y, box.width, box.height,
                                                      encounter.config.max_health / 2))
        self.assertEqual(encounter.phase, 2)
        encounter.rng = random.Random(1)  # first roll chooses the earthquake
        while encounter.state != BossState.JUMP_WINDUP:
            encounter.update(.05, player)
        start = pygame.Vector2(encounter._jump_start)
        locked = None
        while encounter.state != BossState.EARTHQUAKE:
            encounter.update(.05, player)
            if encounter.state == BossState.JUMP_WINDUP and encounter.state_time >= .5 and locked is None:
                locked = pygame.Vector2(encounter._jump_center)
                lock_time = encounter.total_time
            if locked is not None:
                self.assertEqual(pygame.Vector2(encounter._jump_center), locked)
        self.assertGreaterEqual(encounter.total_time - lock_time, 1.0, "landing must be telegraphed")
        self.assertLessEqual(start.distance_to(locked), encounter.config.leap_range + 1e-6)
        self.assertAlmostEqual(encounter.boss_x, locked.x)
        self.assertAlmostEqual(encounter.boss_y, locked.y)


class RecordingAudio:
    """Stands in for AudioManager and records the music it was asked to play."""

    def __init__(self):
        self.music = None
        self.calls = []

    def switch_music(self, name, fade_ms=1000):
        if name != self.music:
            self.calls.append(("play", name))
        self.music = name
        return True

    def stop_music(self, fade_ms=800):
        if self.music is not None:
            self.calls.append(("stop", self.music))
        self.music = None

    def activate_gameplay(self):
        pass

    def deactivate_gameplay(self, fade_ms=350):
        self.music = None
        self.calls.append(("deactivate", None))

    def active_loop(self, category):
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class BossMusicLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()
        cls.ports = generate_ports(cls.world)

    def session(self):
        audio = RecordingAudio()
        session = main.GameSession(self.world, self.ports, find_spawn(self.world), self.tiles, None, 42,
                                   {}, atlas=self.atlas, audio=audio, save_data={})
        session.activate_audio()
        return session, audio

    def test_victory_fades_boss_music_and_restores_overworld_theme(self):
        session, audio = self.session()
        self.assertEqual(audio.music, "main_theme")
        session.treant_progress.portal_unlocked = True
        self.assertTrue(session.enter_treant_boss())
        session.update(.02, (0, 0))
        self.assertEqual(audio.music, "boss_1")
        # The fight begins once the player steps into the ritual circle.
        session.player.update(session.treant_encounter.ritual_center[0],
                              session.treant_encounter.ritual_center[1] + 1.5)
        session.update(.02, (0, 0))
        self.assertTrue(session.treant_encounter.started)
        box = session.treant_encounter.boss_hitbox
        session.treant_encounter.register_player_attack(PlayerAttack(
            "kill", "0", box.x, box.y, box.width, box.height, 10_000))
        for _ in range(60):
            session.update(.05, (0, 0))
            if session.boss_completion_pending:
                break
        session.update(.05, (0, 0))
        self.assertTrue(session.boss_completion_pending)
        self.assertIsNone(audio.music, "boss music must fade out once PLATANUS falls")
        for _ in range(80):
            session.update(.05, (0, 0))
        self.assertFalse(session.boss_active)
        self.assertEqual(audio.music, "main_theme")
        self.assertEqual([c for c in audio.calls if c[0] == "play"].count(("play", "boss_1")), 1)

    def test_retreat_defeat_and_lost_connection_end_boss_music(self):
        session, audio = self.session()
        session.treant_progress.portal_unlocked = True
        session.enter_treant_boss()
        session.update(.02, (0, 0))
        session.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0), (0, 0))
        session.update(.02, (0, 0))
        self.assertFalse(session.boss_active)
        self.assertEqual(audio.music, "main_theme")

        session.enter_treant_boss()
        session.update(.02, (0, 0))
        session.health = 0
        for _ in range(60):
            session.update(.05, (0, 0))
        self.assertFalse(session.boss_active)
        self.assertEqual(audio.music, "main_theme")

        session.enter_treant_boss()
        session.boss_online = True  # as if the server owned the fight, then dropped
        session.update(.02, (0, 0))
        self.assertFalse(session.boss_active)
        self.assertEqual(audio.music, "main_theme")

    def test_returning_to_menu_stops_music(self):
        session, audio = self.session()
        session.treant_progress.portal_unlocked = True
        session.enter_treant_boss()
        session.update(.02, (0, 0))
        session.deactivate_audio()
        self.assertIsNone(audio.music)


if __name__ == "__main__":
    unittest.main()
