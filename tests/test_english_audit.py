"""English text audit: no Turkish player-facing strings in runtime code or UI.

Run directly (``python tests/test_english_audit.py``) to print any findings, or
as part of the test suite.  Internal identifiers that intentionally keep their
original Turkish spelling (inventory keys, the persistent achievement ID) and
the developers' names are allow-listed rather than reported.
"""
import io
import os
import re
import sys
import tokenize
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None

TURKISH_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜâ]")
# ASCII-folded Turkish words that appeared in the original UI.
TURKISH_WORDS = re.compile(
    r"\b(odun|tahil|tahıl|balik|koy|oyuncu|kurtar\w*|yelken|ticaret|teklif\w*|envanter|"
    r"harita\w*|devam|enerji|savas|kilic|balta|gemi\w*|liman|sahipsiz|rakip|tekerlek|"
    r"surukle|yetersiz|kaynak\w*|uret\w*|pisir|konus|muhur|anahtar\w*|kadim|gorev|"
    r"zafer|oyun|bitti|hazir\w*|yenildin|faz|cevrimdisi|cevrimici|diger|herkes|"
    r"iptal|kabul|istedigin|verecegin|catlak\w*|tikla|olta|yukari|asagi|kacti|"
    r"bagl\w*|bekleniyor|ziyan|kesim|vurus|sure|adasi|ve|ile|icin|bir)\b",
    re.IGNORECASE,
)

# Internal identifiers shared with saves, the server and older clients.
ALLOWED_LITERALS = {
    "Odun", "Tas", "Tahil", "Balik", "Çiğ Et", "Pişmiş Et", "Ekmek", "Ok", "Kadim Anahtar",
    "Ada", "Enflasyon",  # HUD icon keys in game_ui
    "Lanet Kıran",       # persistent achievement ID stored in saves
    "İlker",             # developer credit (proper name)
    "İ", "Ç", "Ş", "Ö", "Ü", "Ğ",  # bitmap-font accent table keys
}
RUNTIME_SOURCES = [ROOT / "main.py", ROOT / "server.py", *sorted((ROOT / "modules").glob("*.py"))]


def looks_turkish(text):
    return bool(TURKISH_CHARS.search(text) or TURKISH_WORDS.search(text))


def source_literals(path):
    """Yield (line, text) for every non-docstring string literal, f-strings included."""
    tokens = list(tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline))
    index = 0
    previous = None
    while index < len(tokens):
        token = tokens[index]
        if token.type == tokenize.STRING:
            docstring = previous in (None, tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT) \
                and token.string.lstrip("rRbBuU").startswith(('"""', "'''"))
            if not docstring:
                body = re.sub(r"^[rRbBuUfF]*(\"\"\"|'''|\"|')|(\"\"\"|'''|\"|')$", "", token.string)
                yield token.start[0], body
        elif token.type == tokenize.FSTRING_START:
            line, parts, depth = token.start[0], [], 0
            while True:
                index += 1
                inner = tokens[index]
                if inner.type == tokenize.FSTRING_START:
                    depth += 1
                elif inner.type == tokenize.FSTRING_MIDDLE:
                    parts.append(inner.string)
                elif inner.type == tokenize.FSTRING_END:
                    if depth == 0:
                        break
                    depth -= 1
            yield line, " ".join(parts)
        if token.type not in (tokenize.NL, tokenize.COMMENT):
            previous = token.type
        index += 1


def audit_sources():
    findings = []
    for path in RUNTIME_SOURCES:
        for line, text in source_literals(path):
            if text in ALLOWED_LITERALS or not looks_turkish(text):
                continue
            findings.append(f"{path.relative_to(ROOT)}:{line}: {text[:90]}")
    return findings


class EnglishSourceAuditTests(unittest.TestCase):
    def test_runtime_sources_have_no_turkish_player_text(self):
        findings = audit_sources()
        self.assertEqual(findings, [], "\n".join(findings))

    def test_localization_tables_are_english(self):
        from modules import localization as loc
        texts = list(loc.STRINGS.values()) + list(loc.ITEM_NAMES.values())
        texts += list(loc.ACTIONS.values()) + list(loc.WEAPON_NAMES.values())
        texts += list(loc.CREATURE_NAMES.values()) + list(loc.PROFESSION_TITLES.values())
        texts += [loc.QUEST_NAME, loc.ACHIEVEMENT_NAME, loc.ACHIEVEMENT_DESCRIPTION, loc.BOSS_ISLAND_NAME]
        for speaker, pages in loc.TREANT_STORY.values():
            texts += [speaker, *pages]
        for pages in loc.VILLAGER_DIALOGUE.values():
            texts += pages
        for text in texts:
            with self.subTest(text=text[:40]):
                self.assertFalse(looks_turkish(text), text)
        self.assertEqual(loc.DEVELOPER_CREDIT, "İlker · Eymen · Cevher · Arda")

    def test_every_translation_key_is_used_or_formatted(self):
        from modules.localization import STRINGS
        source = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME_SOURCES)
        unused = [key for key in STRINGS if f'"{key}"' not in source and not key.startswith("trade.status.")]
        self.assertEqual(unused, [])


class EnglishRenderedUiTests(unittest.TestCase):
    """Render every major game state and record each string actually drawn."""

    @classmethod
    def setUpClass(cls):
        import pygame
        import main
        from modules import game_ui
        from modules.terrain_render import TileAtlas, prepare_terrain
        from modules.worldgen import find_spawn, generate_ports, make_world
        pygame.init()
        pygame.display.set_mode((main.GAME_WIDTH, main.GAME_HEIGHT))
        cls.pygame, cls.main, cls.game_ui = pygame, main, game_ui
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()
        cls.ports = generate_ports(cls.world)
        cls.spawn = find_spawn(cls.world)

    def setUp(self):
        self.drawn = []
        main, game_ui = self.main, self.game_ui
        original_render = main.PixelFont.render
        original_pixel_text = game_ui.pixel_text
        drawn = self.drawn

        def recording_render(font, text, *args, **kwargs):
            drawn.append(str(text))
            return original_render(font, text, *args, **kwargs)

        def recording_pixel_text(text, *args, **kwargs):
            drawn.append(str(text))
            return original_pixel_text(text, *args, **kwargs)

        main.PixelFont.render = recording_render
        game_ui.pixel_text = recording_pixel_text
        self.addCleanup(setattr, main.PixelFont, "render", original_render)
        self.addCleanup(setattr, game_ui, "pixel_text", original_pixel_text)

    def session(self):
        main = self.main
        session = main.GameSession(self.world, self.ports, self.spawn, self.tiles, None, 42,
                                   {}, atlas=self.atlas, save_data={})
        session.add_toast("probe")
        return session

    def assert_english(self):
        bad = sorted({text for text in self.drawn if looks_turkish(text)})
        self.assertEqual(bad, [])
        self.assertTrue(self.drawn)

    def test_hud_panels_dialogue_and_popups_render_english(self):
        pygame, main = self.pygame, self.main
        from modules.localization import TREANT_STORY
        session = self.session()
        canvas = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        mouse = (0, 0)
        session.render(canvas, mouse)
        session.dialogue.open(*TREANT_STORY[1])
        session.dialogue.visible_chars = 10_000
        session.render(canvas, mouse)
        session.dialogue.active = False
        npc = session.quest_system.npcs[0]
        session.quest_system.interact(npc, session.dialogue, session.grant_quest_reward)
        session.dialogue.visible_chars = 10_000
        session.render(canvas, mouse)
        session.dialogue.active = False
        session.achievement_popup = (main.TREANT_ACHIEVEMENT_NAME, main.TREANT_ACHIEVEMENT_DESCRIPTION)
        session.achievement_popup_timer = 3
        for flag in ("inventory_open", "trade_open", "cooking_open", "paused"):
            setattr(session, flag, True)
            session.render(canvas, mouse)
            setattr(session, flag, False)
        session.map_open = True
        session.render(canvas, mouse)
        session.map_open = False
        session.winner = session.my_player_id()
        session.render(canvas, mouse)
        session.winner = 7
        session.render(canvas, mouse)
        self.assert_english()

    def test_minigames_quest_tracker_and_boss_render_english(self):
        pygame, main = self.pygame, self.main
        from modules.treant_boss import EncounterResult
        session = self.session()
        canvas = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        node = next(n for n in self.world.nodes if n.type == "Odun")
        session.wood_game.open(node)
        session.render(canvas, (0, 0))
        session.wood_game.close()
        session.stone_game.open(next(n for n in self.world.nodes if n.type == "Tas"))
        session.render(canvas, (0, 0))
        session.stone_game.close()
        session.grain_game.open(next(n for n in self.world.nodes if n.type == "Tahil"))
        session.render(canvas, (0, 0))
        session.grain_game.close()
        session.fishing.open(self.ports[0], session.player)
        session.render(canvas, (0, 0))
        session.fishing.close()
        for keys, unlocked, defeated in ((1, False, False), (3, False, False), (0, True, False), (0, True, True)):
            session.treant_progress.keys_held = keys
            session.treant_progress.portal_unlocked = unlocked
            session.treant_progress.boss_defeated = defeated
            session.render(canvas, (0, 0))
        session.treant_progress.boss_defeated = False
        session.enter_treant_boss()
        session.render(canvas, (0, 0))
        for result in (EncounterResult.VICTORY, EncounterResult.DEFEAT):
            session.treant_encounter.result = result
            self.drawn.append(session.treant_encounter.defeat_hint)
            session.render(canvas, (0, 0))
        self.assert_english()

    def test_story_pages_fit_the_dialogue_box(self):
        main = self.main
        from modules.localization import TREANT_STORY, VILLAGER_DIALOGUE
        font = main.PixelFont(21)
        pages = [page for _, story in TREANT_STORY.values() for page in story]
        pages += [page.format(required=3, progress=1) for group in VILLAGER_DIALOGUE.values()
                  for page in group]
        for page in pages:
            with self.subTest(page=page[:30]):
                lines = main.wrap_text(font, page, main.DIALOGUE_TEXT_WIDTH)
                self.assertLessEqual(len(lines), main.DIALOGUE_MAX_LINES)

    def test_bitmap_hud_font_covers_english_labels(self):
        from modules.localization import ITEM_NAMES, STRINGS
        game_ui = self.game_ui
        # Labels drawn with the bitmap alphabet (HUD strip, minimap and world map).
        bitmap_keys = ("hud.health", "hud.inventory", "hud.trade", "hud.islands", "hud.inflation",
                       "hud.nearby", "hud.world_map", "hud.map")
        labels = [STRINGS[key] for key in STRINGS if key in bitmap_keys or key.startswith("map.")]
        labels += list(ITEM_NAMES.values())
        for label in labels:
            plain = re.sub(r"\{[^}]*\}", "0", label).upper()
            missing = {ch for ch in plain if ch not in game_ui.GLYPHS and ch not in game_ui.ACCENTS}
            with self.subTest(label=label):
                self.assertEqual(missing, set())


if __name__ == "__main__":
    problems = audit_sources()
    print("\n".join(problems) if problems else "No Turkish player-facing literals found.")
    sys.exit(1 if problems else 0)
