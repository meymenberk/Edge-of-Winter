"""Regression coverage for the categorized runtime artwork layout."""
import hashlib
import importlib
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import main
from modules.character_animation import find_character_asset
from modules.treant_boss import resolve_boss_assets_dir


class AssetStructureTests(unittest.TestCase):
    EXPECTED = {
        "backgrounds/main_menu/bg.jpeg": "1c4d1fc5d8686831baa036aca1bc0e0bae5bdd54a2456dc7f4e75da38bc70c99",
        "bosses/platanus/bossanim.png": "d385c5c66c919f0e9b9cecf5da5826d0c39a8351cb05c27f4fecb0ed9f250724",
        "bosses/platanus/bosstile.png": "5d809bf2c8a7ef57f784e6517ac221600e21385520be388ec181602f9ae2dda4",
        "characters/player/manchar.jpeg": "e4c99cfb0a60f4b5b9f2c8cf88189541b7d434c3449212f5ad8185a1d8f595ad",
        "characters/player/menu_character_preview.png": "5b547f3c897787a830522a4fdba261eaba812882de87e665b8ae7475d8d8f50a",
        "characters/villagers/villager.png": "61a72f3fda778931543114d83e1be30da2d1bef5907e2752673ea9553823be47",
        "terrain/overworld/Fall Tile Set.png": "5a6ba34edb85dec891dccc8e4cd788f3035ceef8685048d150602a457e896295",
        "ui/character_customization/clothing_options.png": "d8acec6d4b72306f6268234ac2e73fc9de327d161d2b80698401c083716ebe0e",
        "ui/character_customization/hair_and_skin_options.png": "1b69342fbc947a381b51c252b67df4e48781e3e2091e5b2143e1ec6b3f1bf8ec",
        "ui/menus/edge_of_winter_logo.png": "8a46fadbc48cc3a985c90c4140079f2f2879062b093d1fc8e2fc720c1a16d1e9",
        "ui/menus/main_menu_buttons.png": "75c128f21aef8ce63f4454d1b15a011db649e2064b83d92cfe79f50aeb857fba",
        "vehicles/sailboat_hull.png": "3d4f6aab85d602216e0602762a3aaa7c55e5d2acd1a4670c3eaf4c89e9535289",
    }

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_all_runtime_images_are_categorized_and_unchanged(self):
        discovered = {
            path.relative_to(main.ASSETS_DIR).as_posix(): path
            for path in main.ASSETS_DIR.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        }
        self.assertEqual(set(discovered), set(self.EXPECTED))
        for relative, expected_hash in self.EXPECTED.items():
            with self.subTest(relative=relative):
                self.assertEqual(hashlib.sha256(discovered[relative].read_bytes()).hexdigest(),
                                 expected_hash)
                self.assertGreater(pygame.image.load(str(discovered[relative])).get_width(), 0)

    def test_explicit_loaders_do_not_depend_on_working_directory(self):
        original = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as elsewhere:
                os.chdir(elsewhere)
                self.assertEqual(main.find_tileset_file(), main.OVERWORLD_TILESET_ASSET)
                self.assertEqual(find_character_asset(main.BASE_DIR),
                                 main.PLAYER_CHARACTER_DIR / "manchar.jpeg")
                self.assertEqual(resolve_boss_assets_dir(),
                                 main.ASSETS_DIR / "bosses" / "platanus")
                for path in (main.MAIN_MENU_BACKGROUND_ASSET, main.MENU_CHARACTER_ASSET,
                             main.MENU_BUTTONS_ASSET, main.HAIR_SKIN_ASSET,
                             main.CLOTHING_ASSET, main.SAILBOAT_HULL_ASSET,
                             main.VILLAGER_ATLAS_ASSET):
                    self.assertEqual(main.require_asset(path), path)
        finally:
            os.chdir(original)

    def test_old_runtime_locations_are_empty(self):
        old_names = (
            "bg.jpeg", "Fall Tile Set.png", "manchar.jpeg",
            "ChatGPT Görseli 16 Eki 2026 19_34_26.png",
            "ChatGPT Görseli 16 Eki 2026 19_43_03.png",
            "Retro Piksel Karakter Özelleştirme Arayüzü.png",
            "Sonbahar Temalı Piksel Kıyafet Paneli.png",
        )
        self.assertFalse(any((main.BASE_DIR / name).exists() for name in old_names))
        self.assertFalse((main.ASSETS_DIR / "sailboat_hull.png").exists())

    def test_project_root_has_no_loose_artwork(self):
        image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        loose_images = {
            path.name for path in main.BASE_DIR.iterdir()
            if path.is_file() and path.suffix.casefold() in image_extensions
        }
        self.assertEqual(loose_images, set())
        self.assertEqual(
            len(list((main.BASE_DIR / "validation" / "root_diagnostics").iterdir())),
            62,
        )

    def test_python_layout_and_runtime_package_imports(self):
        root_python = {path.name for path in main.BASE_DIR.glob("*.py")}
        self.assertEqual(root_python, {"main.py", "server.py"})
        expected_modules = {
            "audio_manager", "autumn_leaves", "character_animation", "display", "economy", "elevation",
            "game_ui", "gameplay_systems", "localization", "multiplayer", "paths",
            "pixel_sprites", "progression", "save_game", "settings", "terrain_render",
            "treant_boss", "worldgen",
        }
        actual_modules = {
            path.stem for path in (main.BASE_DIR / "modules").glob("*.py")
            if path.name != "__init__.py"
        }
        self.assertEqual(actual_modules, expected_modules)
        for name in sorted(expected_modules):
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(f"modules.{name}"))
        self.assertTrue((main.BASE_DIR / "legacy" / "main2.py").is_file())


if __name__ == "__main__":
    unittest.main()
