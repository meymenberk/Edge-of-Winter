"""Regression tests for actual sprite extraction/playback and coherent height faces."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import numpy as np
import pygame
import main
from modules.character_animation import CharacterSheet, CharacterAnimator, find_character_asset, load_character_sheet
from modules.elevation import prepare_elevation, MountainRenderer
from modules.terrain_render import TileAtlas, TerrainRenderer, prepare_terrain


class CharacterElevationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        cls.sheet = load_character_sheet(main.BASE_DIR)
        cls.world = main.make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world), (main.COLS, main.ROWS), 'RGB').convert()

    def session(self, network=None):
        return main.GameSession(self.world, self.world.ports, main.find_spawn(self.world),
                                self.tiles, network, 42, {}, self.atlas, self.sheet)

    def test_lookup_extensions_case_variations_and_missing(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            self.assertIsNone(find_character_asset(root))
            for ext in ('.png', '.jpg', '.jpeg', '.webp'):
                p = root / ('MANCHAR walk' + ext.upper())
                p.touch()
                self.assertEqual(find_character_asset(root), p)
                p.unlink()
            (root / 'assets').mkdir()
            nested = root / 'assets' / 'manchar.png'
            nested.touch()
            self.assertEqual(find_character_asset(root), nested)
            direct = root / 'ManChar.JPEG'
            direct.touch()
            self.assertEqual(find_character_asset(root), direct)

    def test_actual_sixteen_poses_and_true_left_direction(self):
        self.assertEqual(self.sheet.path.name, 'manchar.jpeg')
        self.assertEqual(tuple(self.sheet.frames), ('down', 'right', 'up', 'left'))
        for direction, frames in self.sheet.frames.items():
            self.assertEqual(len(frames), 4)
            self.assertEqual(len({pygame.image.tobytes(f, 'RGBA') for f in frames}), 4)
        self.assertNotEqual(pygame.image.tobytes(self.sheet.frames['left'][0], 'RGBA'),
                            pygame.image.tobytes(pygame.transform.flip(self.sheet.frames['right'][0], True, False), 'RGBA'))

    def test_feet_anchor_transparency_and_crisp_scaling(self):
        for frames in self.sheet.frames.values():
            for frame in frames:
                self.assertEqual(frame.get_size(), (40, 56))
                self.assertEqual(frame.get_bounding_rect().bottom, self.sheet.ANCHOR[1])
                self.assertEqual(frame.get_at((0, 0)).a, 0)
                alpha = pygame.surfarray.array_alpha(frame)
                self.assertTrue(set(np.unique(alpha)).issubset({0, 255}))
                pixels = pygame.surfarray.array3d(frame)
                np.testing.assert_array_equal(pixels[::2, ::2], pixels[1::2, 1::2])
                np.testing.assert_array_equal(alpha[::2, ::2], alpha[1::2, 1::2])

    def test_dt_timing_idle_stop_turning_and_slope_speed(self):
        small, large = CharacterAnimator(), CharacterAnimator()
        for _ in range(60):
            small.update(1 / 60, True, 'right')
        large.update(1, True, 'right')
        self.assertEqual(small.frame, large.frame)
        for direction in ('down', 'left', 'up', 'right'):
            small.update(.2, True, direction)
            self.assertEqual(small.facing, direction)
            self.assertEqual(small.frame, 1)
            small.update(20, False, direction)
            self.assertEqual(small.frame, 0)
            self.assertEqual(small.phase, 0)
        slow = CharacterAnimator()
        slow.update(.3, True, 'down', speed=2.475)
        self.assertEqual(slow.frame, 1)

    def test_render_does_not_advance_animation_and_uses_manchar(self):
        session = self.session()
        canvas = pygame.Surface((1200, 780))
        session.player_animation.update(.2, True, 'left')
        phase = session.player_animation.phase
        with patch.object(self.sheet, 'draw', wraps=self.sheet.draw) as draw:
            for _ in range(3):
                session.render(canvas, (0, 0))
            self.assertEqual(draw.call_count, 3)
        self.assertEqual(session.player_animation.phase, phase)
        with patch.object(self.sheet, 'draw', wraps=self.sheet.draw) as draw:
            session.is_sailing = True
            session.render(canvas, (0, 0))
            draw.assert_not_called()

    def test_real_movement_directions_and_blocked_idle(self):
        session = self.session()
        island = self.world.islands[0]
        session.player.update(island.x + .5, island.y + .5)
        session.previous_pos = tuple(session.player)
        for key, facing in ((pygame.K_s, 'down'), (pygame.K_d, 'right'), (pygame.K_w, 'up'), (pygame.K_a, 'left')):
            keys = defaultdict(bool, {key: True})
            with patch('pygame.key.get_pressed', return_value=keys):
                session.update(.16, (0, 0))
            self.assertEqual(session.facing, facing)
            self.assertEqual(session.player_animation.facing, facing)
            self.assertTrue(session.player_animation.moving)
        # Collision refusal must stop walking even with a key held.
        with patch('pygame.key.get_pressed', return_value=defaultdict(bool, {pygame.K_d: True})), patch('main.can_stand', return_value=False):
            position = tuple(session.player)
            session.update(.16, (0, 0))
        self.assertEqual(tuple(session.player), position)
        self.assertFalse(session.player_animation.moving)
        self.assertEqual(session.player_animation.frame, 0)

    def test_remote_direction_animation_and_departure(self):
        network = SimpleNamespace(connected=True, lock=threading.RLock(),
                                  other_players={'7': dict(x=120, y=100, moving=True, facing='left')})
        session = self.session(network)
        session.update_characters(.2)
        remote = session.remote_animations['7']
        self.assertIsNot(remote, session.player_animation)
        self.assertEqual(remote.facing, 'left')
        self.assertTrue(remote.moving)
        network.other_players['7']['moving'] = False
        session.update_characters(.5)
        self.assertEqual(remote.frame, 0)
        network.other_players.clear()
        session.update_characters(.1)
        self.assertFalse(session.remote_animations)

    def test_elevation_deterministic_and_gameplay_data_unchanged(self):
        before = copy.deepcopy((self.world.heights, self.world.roads, self.world.buildings, self.world.nodes))
        levels, allowed = prepare_elevation(self.world)
        other_levels, other_allowed = prepare_elevation(self.world)
        np.testing.assert_array_equal(levels, other_levels)
        np.testing.assert_array_equal(allowed, other_allowed)
        self.assertEqual(before, (self.world.heights, self.world.roads, self.world.buildings, self.world.nodes))
        self.assertEqual(set(np.unique(levels)), {0, 1, 2, 3})
        self.assertFalse((levels[np.asarray(self.world.heights) < .48] > 0).any())
        for x, y in self.world.roads | self.world.buildings:
            self.assertEqual(levels[y, x], 0)
            self.assertFalse(allowed[y, x])

    def test_faces_stay_on_mountain_and_preserve_routes_exactly(self):
        renderer = TerrainRenderer(self.world, self.atlas)
        cx, cy = self.world.islands[0].x // 8, self.world.islands[0].y // 8
        with patch.object(renderer.mountains, 'compose_chunk'):
            base = renderer._chunk(cx, cy).copy()
        painted = base.copy()
        renderer.mountains.compose_chunk(painted, cx, cy, 8)
        original = pygame.surfarray.array3d(base)
        actual = pygame.surfarray.array3d(painted)
        self.assertGreater(np.count_nonzero(np.any(original != actual, axis=2)), 1000)
        allowed = renderer.mountains.allowed[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8]
        allowed = np.repeat(np.repeat(allowed, 48, axis=0), 48, axis=1).T
        np.testing.assert_array_equal(actual[~allowed], original[~allowed])
        # Also sample a village chunk containing roads and buildings.
        x, y = main.find_spawn(self.world)
        cx, cy = int(x) // 8, int(y) // 8
        with patch.object(renderer.mountains, 'compose_chunk'):
            base = renderer._chunk(cx, cy).copy()
        painted = base.copy()
        renderer.mountains.compose_chunk(painted, cx, cy, 8)
        for tx, ty in self.world.roads | self.world.buildings:
            if cx * 8 <= tx < cx * 8 + 8 and cy * 8 <= ty < cy * 8 + 8:
                rect = ((tx % 8) * 48, (ty % 8) * 48, 48, 48)
                self.assertEqual(pygame.image.tobytes(base.subsurface(rect), 'RGB'), pygame.image.tobytes(painted.subsurface(rect), 'RGB'))

    def test_cliff_geometry_agrees_across_chunk_boundaries(self):
        small = TerrainRenderer(self.world, self.atlas)
        large = TerrainRenderer(self.world, self.atlas)
        large.CHUNK = 16
        cx, cy = self.world.islands[0].x // 16, self.world.islands[0].y // 16
        joined = pygame.Surface((768, 768))
        for dy in range(2):
            for dx in range(2):
                joined.blit(small._chunk(cx * 2 + dx, cy * 2 + dy), (dx * 384, dy * 384))
        self.assertEqual(pygame.image.tobytes(joined, 'RGB'), pygame.image.tobytes(large._chunk(cx, cy), 'RGB'))


if __name__ == '__main__':
    unittest.main()
