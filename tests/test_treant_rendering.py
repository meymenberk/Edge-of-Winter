"""Focused alpha-compositing regressions for the Treant encounter."""
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame

import modules.treant_boss as treant_boss
from modules.character_animation import load_character_sheet
from modules.treant_boss import BossState, TreantBossEncounter, _DemoGameVisuals, _DemoPlayer


ROOT = Path(__file__).resolve().parents[1]
MAGENTA = (255, 0, 255)


class TreantRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))
        cls.visuals = _DemoGameVisuals(ROOT)

    @staticmethod
    def _border_alpha(surface):
        alpha = pygame.surfarray.array_alpha(surface)
        return np.concatenate((alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))

    def assertNoOpaqueDarkRectangle(self, surface, expected_mask=None):
        alpha = pygame.surfarray.array_alpha(surface)
        rgb = pygame.surfarray.array3d(surface)
        dark = (alpha >= 250) & (rgb.max(axis=2) <= 12)
        if expected_mask is not None:
            dark &= ~expected_mask
        mask = pygame.Mask(surface.get_size())
        xs, ys = np.nonzero(dark)
        for x, y in zip(xs, ys):
            mask.set_at((int(x), int(y)))
        for component in mask.connected_components(1):
            rects = component.get_bounding_rects()
            if not rects:
                continue
            rect = rects[0]
            fill = component.count() / max(1, rect.width * rect.height)
            self.assertFalse(
                rect.width >= 6 and rect.height >= 6 and fill >= .78,
                f"opaque dark rectangle {tuple(rect)} with {fill:.1%} fill",
            )

    def test_demo_uses_canonical_player_alpha_without_mutating_cached_frames(self):
        canonical = load_character_sheet(ROOT)
        self.assertIsNot(self.visuals.sheet, canonical)
        for direction in canonical.frames:
            for index, source in enumerate(canonical.frames[direction]):
                actual = self.visuals.sheet.frames[direction][index]
                self.assertIsNot(actual, source)
                np.testing.assert_array_equal(
                    pygame.surfarray.array_alpha(actual),
                    pygame.surfarray.array_alpha(source),
                )
                alpha = pygame.surfarray.array_alpha(actual)
                rgb = pygame.surfarray.array3d(actual)
                self.assertFalse(np.any(rgb[alpha == 0]))

    def test_every_player_movement_frame_and_damage_flash_preserves_alpha(self):
        encounter = TreantBossEncounter(ROOT)
        player = _DemoPlayer(encounter.ritual_center, self.visuals)
        anchor = (60, 82)
        for direction, frames in self.visuals.sheet.frames.items():
            for index, frame in enumerate(frames):
                with self.subTest(direction=direction, frame=index):
                    self.visuals.animator.facing = direction
                    self.visuals.animator.phase = float(index)
                    self.visuals.animator.moving = True

                    expected = pygame.Surface((120, 110), pygame.SRCALPHA)
                    expected.blit(self.visuals.sheet.shadow,
                                  (anchor[0] - 15, anchor[1] - 4))
                    expected.blit(
                        frame,
                        (anchor[0] - self.visuals.sheet.ANCHOR[0],
                         anchor[1] - self.visuals.sheet.ANCHOR[1]),
                    )
                    expected_mask = pygame.surfarray.array_alpha(expected) > 0

                    for hit_flash in (0.0, .12):
                        actual = pygame.Surface((120, 110), pygame.SRCALPHA)
                        self.visuals.draw_player_function(
                            actual, anchor, True, direction,
                            character_sheet=self.visuals.sheet,
                            animation=self.visuals.animator,
                            hit_flash=hit_flash,
                        )
                        np.testing.assert_array_equal(
                            pygame.surfarray.array_alpha(actual) > 0,
                            expected_mask,
                        )
                        self.assertNoOpaqueDarkRectangle(actual, expected_mask)

    def test_every_boss_frame_transform_has_no_rectangular_background(self):
        encounter = TreantBossEncounter(ROOT)
        checker = pygame.Surface((180, 140))
        checker.fill(MAGENTA)
        for animation, frames in encounter.assets.animations.items():
            for index, source in enumerate(frames):
                for flipped in (False, True):
                    with self.subTest(animation=animation, frame=index,
                                      flipped=flipped):
                        transformed = (pygame.transform.flip(source, True, False)
                                       if flipped else source.copy())
                        expected = (np.flip(pygame.surfarray.array_alpha(source), 0)
                                    if flipped else pygame.surfarray.array_alpha(source))
                        np.testing.assert_array_equal(
                            pygame.surfarray.array_alpha(transformed), expected
                        )
                        self.assertEqual(int(self._border_alpha(transformed).max()), 0)
                        self.assertNoOpaqueDarkRectangle(
                            transformed, pygame.surfarray.array_alpha(transformed) > 0
                        )
                        composed = checker.copy()
                        rect = transformed.get_rect(center=composed.get_rect().center)
                        before = pygame.surfarray.array3d(composed).copy()
                        composed.blit(transformed, rect)
                        after = pygame.surfarray.array3d(composed)
                        changed = np.any(before != after, axis=2)
                        expected_changed = np.zeros(changed.shape, dtype=bool)
                        local_alpha = pygame.surfarray.array_alpha(transformed) > 0
                        expected_changed[rect.left:rect.right,
                                         rect.top:rect.bottom] = local_alpha
                        self.assertFalse(np.any(changed & ~expected_changed))

    def test_all_attack_effect_transforms_keep_their_temporary_surfaces_clear(self):
        encounter = TreantBossEncounter(ROOT)
        encounter.boss_x, encounter.boss_y = 8.0, 8.0
        for sector in range(16):
            for state_time in (.04, .12, .22, .32):
                with self.subTest(effect="arm", sector=sector, time=state_time):
                    angle = sector * math.pi / 8
                    encounter._locked_direction.update(math.cos(angle), math.sin(angle))
                    encounter.state = BossState.ARM_EXTEND
                    encounter.state_time = state_time
                    layer = pygame.Surface((800, 800), pygame.SRCALPHA)
                    encounter._draw_arm_extension(layer, (0, 0))
                    alpha = pygame.surfarray.array_alpha(layer)
                    self.assertEqual(int(self._border_alpha(layer).max()), 0)
                    self.assertLess(np.count_nonzero(alpha), alpha.size * .12)

        player = _DemoPlayer((5.0, 5.0), self.visuals)
        for direction in ("up", "right", "down", "left"):
            for timer in (.03, .08, .13, .18, .23, .28):
                with self.subTest(effect="sword", direction=direction, time=timer):
                    self.visuals.reset_combat()
                    player.facing_name = direction
                    player.begin_attack()
                    player.combat.timer = timer
                    layer = pygame.Surface((500, 500), pygame.SRCALPHA)
                    player.draw_effects(layer, encounter, (0, 0))
                    alpha = pygame.surfarray.array_alpha(layer)
                    self.assertEqual(int(self._border_alpha(layer).max()), 0)
                    self.assertLess(np.count_nonzero(alpha), alpha.size * .08)

        player.dash_effects = [{
            "x": 5.0, "y": 5.0, "angle": math.pi / 4,
            "life": .2, "max_life": .32,
        }]
        layer = pygame.Surface((500, 500), pygame.SRCALPHA)
        player.draw_effects(layer, encounter, (0, 0))
        self.assertEqual(int(self._border_alpha(layer).max()), 0)
        self.assertLess(np.count_nonzero(pygame.surfarray.array_alpha(layer)),
                        500 * 500 * .12)

    def test_debug_mode_writes_all_pipeline_stages_and_alpha_report(self):
        encounter = TreantBossEncounter(ROOT)
        player = _DemoPlayer(encounter.ritual_center, self.visuals)
        target = pygame.Surface((1056, 768))
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(treant_boss, "TREANT_RENDER_DEBUG", True):
            encounter.assets_dir = Path(temp)
            encounter._render_scene(
                target, (0, 0),
                (player.pos.y,
                 lambda surface, cam: player.draw_sprite(surface, encounter, cam)),
                lambda surface, cam: player.draw_effects(surface, encounter, cam),
            )
            output = Path(temp) / "validation" / "treant_render_stages"
            captures = sorted(output.glob("*.png"))
            self.assertEqual(len(captures), 7)
            report = output / "alpha_report.json"
            self.assertTrue(report.is_file())
            report_text = report.read_text(encoding="utf-8")
            self.assertIn('"player_layer"', report_text)
            self.assertIn('"07_final"', report_text)

    def test_opaque_arena_cannot_clear_native_window_alpha(self):
        encounter = TreantBossEncounter(ROOT)
        # Terrain is an opaque framebuffer.  It must not inherit an RGBA display
        # format whose untouched alpha plane can become a black window rectangle.
        self.assertEqual(encounter._arena_surface.get_masks()[3], 0)

        # Reproduce a native alpha-capable window/offscreen target regardless of
        # which SDL video driver runs the test.  Every final scene pixel remains
        # opaque after terrain, props, entities, and effects are composed.
        target = pygame.Surface((1056, 768), pygame.SRCALPHA)
        encounter._render_scene(target, (0, 0))
        alpha = pygame.surfarray.array_alpha(target)
        self.assertEqual(int(alpha.min()), 255)
        self.assertEqual(int(alpha.max()), 255)

    def test_extracted_boss_player_and_effect_surfaces_have_real_transparency(self):
        encounter = TreantBossEncounter(ROOT)
        sprites = [frame for frames in encounter.assets.animations.values()
                   for frame in frames]
        sprites.extend(frame for frames in self.visuals.sheet.frames.values()
                       for frame in frames)

        boss_heights = sorted(frame.get_bounding_rect(min_alpha=12).height
                              for frame in encounter.assets.animations["idle"])
        player_heights = sorted(frame.get_bounding_rect(min_alpha=12).height
                                for frames in self.visuals.sheet.frames.values()
                                for frame in frames)
        rendered_height_ratio = (boss_heights[len(boss_heights) // 2] /
                                 player_heights[len(player_heights) // 2])
        self.assertGreaterEqual(rendered_height_ratio, 1.7)
        self.assertLessEqual(rendered_height_ratio, 2.0)

        for index, sprite in enumerate(sprites):
            with self.subTest(sprite=index):
                alpha = pygame.surfarray.array_alpha(sprite)
                self.assertEqual(int(self._border_alpha(sprite).max()), 0)
                self.assertGreater(int(np.count_nonzero(alpha == 0)), alpha.size // 5)
                # A rectangular atlas background would make nearly the whole
                # canvas visible even if its RGB happened not to be pure black.
                self.assertLess(int(np.count_nonzero(alpha)), alpha.size * .72)

                bright = pygame.Surface(sprite.get_size())
                bright.fill(MAGENTA)
                bright.blit(sprite, (0, 0))
                for point in ((0, 0), (sprite.get_width() - 1, 0),
                              (0, sprite.get_height() - 1),
                              (sprite.get_width() - 1, sprite.get_height() - 1)):
                    self.assertEqual(bright.get_at(point)[:3], MAGENTA)

        # Exercise the two generated attack-effect surfaces as well.
        encounter._locked_direction.update(.35, .94)
        encounter._locked_direction.normalize_ip()
        encounter.state = BossState.ARM_EXTEND
        encounter.state_time = .22
        effect = pygame.Surface((1056, 768), pygame.SRCALPHA)
        encounter._draw_arm_extension(effect, (0, 0))
        self.assertEqual(int(self._border_alpha(effect).max()), 0)

        player = _DemoPlayer(encounter.ritual_center, self.visuals)
        player.begin_attack()
        player.combat.timer = .2
        sword = pygame.Surface((1056, 768), pygame.SRCALPHA)
        player.draw_effects(sword, encounter, (0, 0))
        self.assertEqual(int(self._border_alpha(sword).max()), 0)

    def test_central_platform_positions_do_not_change_pixels_outside_silhouettes(self):
        cases = (
            ("far", (5.2, 10.1), (6.2, 10.0), BossState.IDLE, .2, False),
            ("platform", (11.0, 7.35), (10.5, 7.7), BossState.IDLE, .2, False),
            ("portal_overlap", (11.0, 13.9), (11.0, 13.8), BossState.IDLE, .2, False),
            ("arm_platform", (11.0, 7.35), (11.7, 8.1), BossState.ARM_EXTEND, .22, True),
            ("earthquake_platform", (11.0, 7.35), (10.6, 7.9), BossState.EARTHQUAKE, .30, False),
        )
        for name, boss_pos, player_pos, state, state_time, sword_active in cases:
            with self.subTest(case=name):
                encounter = TreantBossEncounter(ROOT)
                player = _DemoPlayer(player_pos, self.visuals)
                encounter.start(player.snapshot())
                encounter.started = True
                encounter.boss_x, encounter.boss_y = boss_pos
                encounter._jump_center.update(*boss_pos)
                encounter.state, encounter.state_time = state, state_time
                encounter._locked_direction.update(.35, .94)
                encounter._locked_direction.normalize_ip()
                encounter.shockwave_progress = .65
                if state == BossState.ARM_EXTEND:
                    encounter._current_attack_id = "render-regression"
                if sword_active:
                    player.begin_attack()
                    player.combat.timer = .2

                baseline = pygame.Surface((1056, 768))
                with patch.object(encounter, "_draw_boss", return_value=None):
                    encounter._render_scene(baseline, (0, 0))

                actual = pygame.Surface((1056, 768))
                encounter._render_scene(
                    actual, (0, 0),
                    (player.pos.y,
                     lambda target, cam: player.draw_sprite(target, encounter, cam)),
                    lambda target, cam: player.draw_effects(target, encounter, cam),
                )

                contribution = pygame.Surface((1056, 768), pygame.SRCALPHA)
                encounter._draw_boss(contribution, (0, 0))
                player.draw_sprite(contribution, encounter, (0, 0))
                player.draw_effects(contribution, encounter, (0, 0))
                allowed = pygame.surfarray.array_alpha(contribution) > 0
                before = pygame.surfarray.array3d(baseline)
                after = pygame.surfarray.array3d(actual)
                changed = np.any(before != after, axis=2)

                # Anything outside the actual alpha silhouettes is evidence of
                # a bounding-box background or opaque intermediate surface.
                self.assertEqual(int(np.count_nonzero(changed & ~allowed)), 0)

    def test_bottom_gate_and_player_effects_share_foot_depth(self):
        encounter = TreantBossEncounter(ROOT)
        portal = encounter.assets.props["portal"]
        foot_x = round(encounter.portal_spawn[0] * encounter.config.tile_size)
        foot_y = round((encounter.portal_spawn[1] + .2) * encounter.config.tile_size)
        local_probe = (portal.get_width() // 2, 126)
        probe = (foot_x - portal.get_width() // 2 + local_probe[0],
                 foot_y - portal.get_height() + local_probe[1])
        self.assertEqual(portal.get_at(local_probe).a, 255)

        def draw_red(target, _camera):
            target.set_at(probe, (255, 0, 0))

        def draw_blue(target, _camera):
            target.set_at(probe, (0, 0, 255))

        def render_at_depth(depth):
            target = pygame.Surface((1056, 768))
            target.fill((0, 255, 255))
            with patch.object(encounter, "_draw_boss", return_value=None):
                encounter._draw_depth_sorted_entities(
                    target, (0, 0), (depth, draw_red), draw_blue
                )
            return target

        # The gate sorts at its arch, behind its own front stairs: an actor
        # walking through the arch is occluded, while the arrival point on the
        # stairs is drawn in front so the player is visible when they arrive.
        arch_depth = encounter.portal_spawn[1] + .2 - encounter.PORTAL_ARCH_DEPTH
        behind = render_at_depth(arch_depth - .2)
        in_front = render_at_depth(encounter.portal_spawn[1])
        self.assertEqual(behind.get_at(probe)[:3], portal.get_at(local_probe)[:3])
        self.assertEqual(in_front.get_at(probe)[:3], (0, 0, 255))

        # Transparent gate corners must never paint the cyan test background.
        portal_corner = (foot_x - portal.get_width() // 2,
                         foot_y - portal.get_height())
        self.assertEqual(portal.get_at((0, 0)).a, 0)
        self.assertEqual(behind.get_at(portal_corner)[:3], (0, 255, 255))


if __name__ == "__main__":
    unittest.main()
