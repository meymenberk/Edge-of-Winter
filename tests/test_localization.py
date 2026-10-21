"""Regression tests for the translation helpers and every call site that uses them."""
import ast
import os
import string
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

import main
from modules import localization
from modules.localization import ACTIONS, STRINGS, action_label, tr

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [ROOT / "main.py", ROOT / "server.py", *sorted((ROOT / "modules").glob("*.py"))]
# Calls whose key is computed; each expression may only produce these keys.
DYNAMIC_KEYS = {
    "message": {"toast.boss_retreat", "toast.boss_connection_lost", "toast.boss_repelled"},
    "key": {"settings.display_label", "settings.window_size", "settings.scaling",
            "settings.music_volume"},
    "status_key": {"trade.status.pending", "trade.status.accepted", "trade.status.cancelled"},
    "RESOURCE_ACTIONS.get(node.type, 'collect')": {"chop", "mine", "harvest", "collect"},
}


def placeholders(text):
    return {name.split(".")[0].split("[")[0]
            for _, name, _, _ in string.Formatter().parse(text) if name}


class TranslateFunctionTests(unittest.TestCase):
    def test_key_placeholder_no_longer_collides_with_the_parameter(self):
        self.assertEqual(tr("hud.merchant", key="E"), "MERCHANT [E]")
        with mock.patch.dict(STRINGS, {"test.names": "{translation_key}/{key}/{values}"}):
            self.assertEqual(tr("test.names", translation_key="a", key="b", values="c"), "a/b/c")

    def test_plain_and_formatted_strings(self):
        self.assertEqual(tr("menu.back"), "BACK")
        self.assertEqual(tr("toast.gathered", count=3, item="Wood"), "+3 Wood gathered!")
        self.assertEqual(tr("hud.exhausted", seconds=1.25), "EXHAUSTED! (1.2s)")
        self.assertEqual(tr("toast.player_hit_you", pid=2, damage=1), "Player 2 struck you! -1 health")
        self.assertEqual(tr("toast.island_taken", name="Emberkeep", pid=4),
                         "NOTICE: Emberkeep was liberated by Player 4!")
        self.assertEqual(tr("quest.keys", held=1), "Ancient Keys: 1/3")
        self.assertEqual(tr("settings.online", host="::1", port=5555), "ONLINE (::1:5555)")
        self.assertEqual(action_label("seals", held=2), "Seals 2/3")
        self.assertEqual(action_label("talk"), "Talk")

    def test_values_containing_braces_are_not_reformatted(self):
        self.assertEqual(tr("toast.already_rescued", name="{name}"), "{name} has already been liberated!")

    def test_missing_key_or_value_degrades_visibly_without_crashing(self):
        with mock.patch.object(localization, "_reported_problems", set()), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(tr("does.not.exist"), "does.not.exist")
            self.assertEqual(tr("hud.exhausted"), "EXHAUSTED! ({seconds}s)")
            self.assertEqual(tr("toast.gathered", count=2), "+2 {item} gathered!")
            self.assertEqual(action_label("unknown_verb"), "Unknown_Verb")
            tr("does.not.exist")  # reported only once
        self.assertEqual(printed.call_count, 4)

    def test_genuine_errors_still_raise(self):
        with self.assertRaises(TypeError):
            tr()
        with self.assertRaises(ValueError):
            tr("hud.exhausted", seconds="not a number")


class TranslationCallSiteTests(unittest.TestCase):
    """Every tr()/action_label() call supplies exactly the placeholders it needs."""

    def test_every_call_site_matches_its_string(self):
        problems = []
        for path in SOURCES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in ("tr", "action_label")):
                    continue
                table = STRINGS if node.func.id == "tr" else ACTIONS
                where = f"{path.name}:{node.lineno}"
                given = {keyword.arg for keyword in node.keywords}
                if not node.args:
                    problems.append(f"{where}: no key")
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant):
                    keys = {first.value}
                else:
                    keys = DYNAMIC_KEYS.get(ast.unparse(first))
                    if keys is None:
                        problems.append(f"{where}: unreviewed dynamic key {ast.unparse(first)}")
                        continue
                for key in keys:
                    if key not in table:
                        problems.append(f"{where}: missing key {key}")
                    elif placeholders(table[key]) != given:
                        problems.append(f"{where}: {key} needs {placeholders(table[key])}, got {given}")
        self.assertEqual(problems, [])


class ShipLabelRenderTests(unittest.TestCase):
    """The crash happened while drawing merchant ships during gameplay."""

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))

    def test_merchant_and_pirate_labels_render_with_the_interact_key(self):
        from modules.gameplay_systems import NavalEncounterSystem
        from modules.worldgen import can_stand, make_world
        world = make_world(42)
        naval = NavalEncounterSystem(world, 42, lambda x, y: can_stand(world, x, y, True))
        screen = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        font = main.PixelFont(21)
        drawn = []
        original = main.PixelFont.render

        def record(self, text, *args, **kwargs):
            drawn.append(text)
            return original(self, text, *args, **kwargs)

        with mock.patch.object(main.PixelFont, "render", record):
            for kind in ("merchant", "pirate"):
                ship = next(s for s in naval.ships if s.kind == kind)
                camera = (ship.x * main.LOCAL_TILE_SIZE - 600, ship.y * main.LOCAL_TILE_SIZE - 390)
                main.draw_sea_ship(screen, ship, *camera, None, font)
        key = pygame.key.name(main.GameSession.INTERACT_KEY).upper()
        self.assertIn(f"MERCHANT [{key}]", drawn)
        self.assertIn("PIRATE", drawn)


if __name__ == "__main__":
    unittest.main()
