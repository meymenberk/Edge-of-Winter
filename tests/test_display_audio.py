"""Adaptive resolution, menu logo and main-menu music."""
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules.audio_manager import AudioManager
from modules.display import VIEWPORT, Viewport, fit_window_size, window_size_options
from modules.settings import GameSettings, load_settings, save_settings

ROOT = Path(__file__).resolve().parent.parent
SIZES = ((1280, 720), (1600, 900), (1920, 1080), (800, 600), (700, 900), (1200, 780))


class ViewportTests(unittest.TestCase):
    def test_aspect_is_preserved_and_centred_with_letterbox(self):
        for logical in ((1024, 576), (1200, 780)):
            for window in SIZES:
                with self.subTest(logical=logical, window=window):
                    view = Viewport().update(window, logical)
                    tw, th = view.target_size
                    self.assertAlmostEqual(tw / th, logical[0] / logical[1], delta=.01)
                    self.assertLessEqual(tw, window[0])
                    self.assertLessEqual(th, window[1])
                    self.assertTrue(tw == window[0] or th == window[1])
                    self.assertLessEqual(abs((window[0] - tw) - 2 * view.offset[0]), 1)
                    self.assertLessEqual(abs((window[1] - th) - 2 * view.offset[1]), 1)

    def test_mouse_round_trips_and_bars_are_outside(self):
        for window in SIZES:
            view = Viewport().update(window, (1200, 780))
            if view.scale >= 1:
                # Upscaled: every logical pixel owns at least one window pixel.
                for point in ((0, 0), (599, 389), (1199, 779), (37, 701)):
                    with self.subTest(window=window, point=point):
                        self.assertEqual(view.to_logical(view.to_window(point)), point)
            for point in ((view.offset[0] + 3, view.offset[1] + 3), (window[0] // 2, window[1] // 2)):
                with self.subTest(window=window, mouse=point):
                    back = view.to_window(view.to_logical(point))
                    self.assertLessEqual(abs(back[0] - point[0]), view.scale + 1)
                    self.assertLessEqual(abs(back[1] - point[1]), view.scale + 1)
            if view.offset[0] > 1:
                self.assertFalse(view.contains((view.offset[0] - 1, window[1] // 2)))
            if view.offset[1] > 1:
                self.assertFalse(view.contains((window[0] // 2, view.offset[1] - 1)))

    def test_hidpi_surface_larger_than_window_maps_points_to_pixels(self):
        view = Viewport().update((2560, 1440), (1024, 576), window_size=(1280, 720))
        self.assertEqual(view.scale, 2.5)
        self.assertEqual(view.to_logical((640, 360)), (512, 288))
        self.assertEqual(view.to_logical(view.to_window((511, 287))), (511, 287))

    def test_pixel_perfect_uses_whole_number_scales(self):
        view = Viewport().update((1920, 1080), (1200, 780), pixel_perfect=True)
        self.assertEqual(view.scale, 1.0)
        view = Viewport().update((2560, 1600), (1200, 780), pixel_perfect=True)
        self.assertEqual(view.scale, 2.0)
        # Below 1x the image still fits rather than overflowing.
        self.assertLess(Viewport().update((800, 600), (1200, 780), True).scale, 1.0)

    def test_window_size_choices_fit_the_desktop(self):
        options = window_size_options((1920, 1080))
        self.assertIn((1280, 720), options)
        self.assertIn((1920, 1080), options)
        self.assertNotIn((2560, 1440), options)
        self.assertIn((1500, 800), window_size_options((1920, 1080), (1500, 800)))
        self.assertEqual(fit_window_size((4000, 3000), (1920, 1080)), (1920, 1080))
        self.assertEqual(fit_window_size((100, 100)), (640, 360))


class DisplaySettingsPersistenceTests(unittest.TestCase):
    def test_new_fields_round_trip_and_old_files_get_defaults(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            value = GameSettings("7", "localhost", 6000, "fullscreen", 1600, 900, True, 40)
            save_settings(value, path)
            self.assertEqual(load_settings(path), value)
            path.write_text(json.dumps({"world_seed": "9", "server_address": "127.0.0.1",
                                        "server_port": 5555}), encoding="utf-8")
            loaded = load_settings(path)
            self.assertEqual((loaded.world_seed, loaded.display_mode, loaded.music_volume),
                             ("9", "windowed", 70))
            path.write_text(json.dumps({"display_mode": "huge", "window_width": 5,
                                        "music_volume": 900}), encoding="utf-8")
            loaded = load_settings(path)
            self.assertEqual((loaded.display_mode, loaded.window_width, loaded.music_volume),
                             ("windowed", 640, 100))


class MenuMusicTests(unittest.TestCase):
    def setUp(self):
        pygame.mixer.quit()
        import tempfile
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)

    def test_missing_menu_track_is_reported_and_harmless(self):
        with mock.patch("builtins.print") as printed:
            audio = AudioManager(ROOT / "music", menu_music=self.folder / "main_menu.ogg")
        self.assertIn("main_menu", audio.missing_assets)
        self.assertTrue(any("Main menu music not found" in str(call) for call in printed.call_args_list))
        self.assertFalse(audio.play_menu_music())
        audio.activate_gameplay()
        self.assertTrue(audio.switch_music("main_theme", 0))
        audio.stop_all()

    def test_menu_track_plays_fades_into_gameplay_and_returns(self):
        shutil.copy(ROOT / "music" / "main theme.wav", self.folder / "main_menu.wav")
        audio = AudioManager(ROOT / "music", menu_music=self.folder / "main_menu.ogg")
        self.assertEqual(audio.paths["main_menu"].name, "main_menu.wav")  # other format accepted
        self.assertTrue(audio.play_menu_music(0))
        self.assertEqual(audio.current_music, "main_menu")
        self.assertTrue(audio.play_menu_music(0))  # repeated calls never restart it
        audio.activate_gameplay()
        self.assertFalse(audio.play_menu_music())  # no menu track during gameplay
        audio.switch_music("main_theme", 1000)
        for _ in range(80):
            audio.update(.05)
        self.assertEqual(audio.current_music, "main_theme")
        audio.deactivate_gameplay()
        self.assertTrue(audio.play_menu_music(500))
        for _ in range(40):
            audio.update(.05)
        self.assertEqual(audio.current_music, "main_menu")
        audio.set_category_volume("music", .3)
        self.assertAlmostEqual(audio.category_volume["music"], .3)
        audio.stop_all()

    def test_shipped_menu_track_is_found(self):
        audio = AudioManager(ROOT / "music", menu_music=main.MENU_MUSIC_ASSET)
        self.assertEqual(audio.paths["main_menu"], main.MENU_MUSIC_ASSET)
        audio.stop_all()

    def test_undecodable_menu_track_fails_once_without_crashing(self):
        (self.folder / "main_menu.wav").write_bytes(b"not really a wave file")
        audio = AudioManager(ROOT / "music", menu_music=self.folder / "main_menu.wav")
        with mock.patch("builtins.print"):
            self.assertFalse(audio.play_menu_music(0))
        self.assertNotIn("main_menu", audio.paths)  # never retried every frame
        self.assertFalse(audio.play_menu_music(0))
        audio.stop_all()


class WidescreenViewTests(unittest.TestCase):
    """Gameplay adopts the display aspect: wider screens show more world, unstretched."""

    def tearDown(self):
        main.set_game_view_size((main.BASE_GAME_WIDTH, main.BASE_GAME_HEIGHT))

    def test_view_size_follows_aspect_without_changing_world_scale(self):
        wide = main.game_view_size((1920, 1080))
        classic = main.game_view_size((1024, 768))
        self.assertEqual(wide[1], main.BASE_GAME_HEIGHT)  # same tile scale vertically
        self.assertGreater(wide[0], classic[0])           # 16:9 sees more world horizontally
        for size in ((1280, 720), (1600, 900), (1920, 1080), (1440, 900), (1024, 768), (2560, 1080)):
            with self.subTest(size=size):
                view = main.game_view_size(size)
                self.assertGreaterEqual(view[0], main.BASE_GAME_WIDTH)
                self.assertGreaterEqual(view[1], main.BASE_GAME_HEIGHT)
                self.assertAlmostEqual(view[0] / view[1], size[0] / size[1], delta=.01)
        # Extreme shapes are clamped and letterboxed rather than distorted.
        self.assertAlmostEqual(main.game_view_size((4000, 1000))[0] / main.BASE_GAME_HEIGHT,
                               main.MAX_GAME_ASPECT, delta=.01)

    def test_game_fills_common_windows_and_reanchors_the_hud(self):
        patches = [mock.patch.object(main, "BackgroundPreloader", StubPreloader),
                   mock.patch.object(main, "save_settings", lambda value: None),
                   mock.patch.object(main, "load_settings", lambda: GameSettings())]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = main.AutumnGameApp()
        session = mock.Mock()
        app.preloader.game_session = session
        app.state = "GAME"
        for size in ((1280, 720), (1440, 900), (1024, 768), (1920, 1080)):
            with self.subTest(size=size):
                app.window = pygame.display.set_mode(size, pygame.RESIZABLE)
                app.update_letterbox()
                self.assertEqual(app.game_surface.get_size(), (main.GAME_WIDTH, main.GAME_HEIGHT))
                self.assertEqual(VIEWPORT.offset, (0, 0))           # no bars
                self.assertEqual(VIEWPORT.target_size, size)         # full window
                sx = VIEWPORT.target_size[0] / main.GAME_WIDTH
                sy = VIEWPORT.target_size[1] / main.GAME_HEIGHT
                self.assertAlmostEqual(sx, sy, delta=.01)            # never stretched
                # The window's last pixel maps to the view's last pixels (one
                # window pixel spans more than one logical pixel when downscaled).
                corner = VIEWPORT.to_logical((size[0] - 1, size[1] - 1))
                self.assertTrue(main.GAME_WIDTH - 3 <= corner[0] < main.GAME_WIDTH)
                self.assertTrue(main.GAME_HEIGHT - 3 <= corner[1] < main.GAME_HEIGHT)
        self.assertTrue(session.layout_view.called)

    def test_world_map_ui_reanchors_on_resize(self):
        world = mock.Mock(woodland={}, buildings=set(), roads=set())
        tiles = pygame.Surface((main.COLS, main.ROWS))
        from modules.game_ui import WorldMapUI
        ui = WorldMapUI(world, tiles, 1200, 780)
        ui.resize(1387, 780)
        self.assertEqual(ui.minimap_rect.right, 1387 - 14)
        self.assertEqual(ui.full_rect.centerx, 1387 // 2)


class StubPreloader:
    def __init__(self, host, port, audio, seed):
        from modules.multiplayer import NetworkClient
        self.network = NetworkClient(host, port, offline_seed=seed)
        self.status = main.PreloadStatus.LOADING
        self.progress = .5
        self.game_session = None

    def start(self):
        pass

    def poll(self, customization):
        return False

    def cancel(self):
        pass


class MenuWindowTests(unittest.TestCase):
    """The real menu: clicks land on buttons at every window size."""

    @classmethod
    def setUpClass(cls):
        patches = [mock.patch.object(main, "BackgroundPreloader", StubPreloader),
                   mock.patch.object(main, "save_settings", lambda value: None),
                   mock.patch.object(main, "load_settings", lambda: GameSettings())]
        for patch in patches:
            patch.start()
            cls.addClassCleanup(patch.stop)
        cls.app = main.AutumnGameApp()

    def setUp(self):
        self.app.show_settings = self.app.show_credits = self.app.show_customize = False
        self.app.settings_pending = None

    def click(self, logical):
        window = VIEWPORT.to_window(logical)
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=window))
        self.app.handle_events()

    def resize(self, size):
        self.app.window = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, size=size, w=size[0], h=size[1]))
        self.app.handle_events()
        self.app.render()

    def button_center(self, name):
        mx, my = self.app.menu_pos
        button = next(b for b in self.app.menu_buttons if b["name"] == name)
        return mx + button["local_rect"].centerx, my + button["local_rect"].centery

    def test_buttons_work_after_resizing(self):
        for size in SIZES:
            with self.subTest(size=size):
                self.resize(size)
                self.assertAlmostEqual(self.app.target_w / self.app.target_h, 1024 / 576, delta=.01)
                self.click(self.button_center("Credits"))
                self.assertTrue(self.app.show_credits)
                self.click((MENU_BACK := (main.MENU_WIDTH // 2, 370 + 16)))
                self.assertFalse(self.app.show_credits)
                self.click(self.button_center("Settings"))
                self.assertTrue(self.app.show_settings)
                layout = self.app.settings_layout()
                self.click(layout["volume_down"].center)
                self.assertEqual(self.app.settings_draft["music_volume"], 60)
                self.click(layout["cancel"].center)
                self.assertFalse(self.app.show_settings)
                del MENU_BACK

    def test_letterbox_clicks_do_not_hit_buttons(self):
        self.resize((700, 900))  # tall window: bars above and below
        bar_click = (VIEWPORT.offset[0] + VIEWPORT.target_size[0] - 5, VIEWPORT.offset[1] // 2)
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=bar_click))
        self.app.handle_events()
        self.assertFalse(self.app.show_settings or self.app.show_credits or self.app.show_customize)

    def test_logo_loads_keeps_aspect_and_avoids_menu_elements(self):
        app = self.app
        self.assertIsNotNone(app.logo, "assets/ui/menus/edge_of_winter_logo.png should load")
        source = app.logo.get_size()
        self.assertAlmostEqual(app.logo_rect.width / app.logo_rect.height, source[0] / source[1], delta=.02)
        self.assertTrue(app.LOGO_BOX.contains(app.logo_rect))
        char = pygame.Rect(app.char_pos, app.char_scaled.get_size())
        sign = pygame.Rect(app.menu_pos, app.menu_scaled.get_size())
        for blocked in (char, sign):
            self.assertFalse(app.logo_rect.colliderect(blocked))
        # While customizing, the logo shrinks into a box clear of the panel too.
        compact = app._logo_rects[True]
        self.assertTrue(app.LOGO_BOX_COMPACT.contains(compact))
        for blocked in (char, sign, app.panel_rect):
            self.assertFalse(compact.colliderect(blocked))
        app.show_customize = True
        try:
            app.render()
            self.assertEqual(app.logo_rect, compact)
        finally:
            app.show_customize = False
            app.render()
        for size in ((1280, 720), (1920, 1080)):
            self.resize(size)
            cached = app._logo_cache[1]
            self.assertEqual(cached.get_width(), round(app.logo_rect.width * app.scale))
            self.assertGreater(app.window.get_at(VIEWPORT.to_window(app.logo_rect.center)).a, 0)

    def test_missing_logo_falls_back_to_text_title(self):
        with mock.patch.object(main, "GAME_LOGO_ASSET", ROOT / "no_such_logo.png"):
            self.app.load_logo()
        try:
            self.assertIsNone(self.app.logo)
            self.app.render()  # draws the text title instead
        finally:
            self.app.load_logo()

    @mock.patch.object(main, "desktop_size", lambda: (1920, 1080))
    def test_display_settings_apply_without_touching_the_world(self):
        app = self.app
        app.open_settings()
        app.settings_draft["window_size"] = (1280, 720)
        app.settings_draft["pixel_perfect"] = True
        app._apply_settings()
        self.assertEqual(app.window.get_size(), (1280, 720))
        self.assertTrue(VIEWPORT.pixel_perfect)
        self.assertEqual(app.settings.window_width, 1280)
        self.assertIsNone(app.settings_pending)
        app.open_settings()
        app.settings_draft["pixel_perfect"] = False
        app._apply_settings()
        app.close_settings()


if __name__ == "__main__":
    unittest.main()
