"""Central, side-effect-free project and runtime asset paths."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"

MAIN_MENU_BACKGROUND_ASSET = ASSETS_DIR / "backgrounds" / "main_menu" / "bg.jpeg"
PLAYER_CHARACTER_DIR = ASSETS_DIR / "characters" / "player"
PLAYER_CHARACTER_ASSET = PLAYER_CHARACTER_DIR / "manchar.jpeg"
VILLAGER_ATLAS_ASSET = ASSETS_DIR / "characters" / "villagers" / "villager.png"
MENU_CHARACTER_ASSET = PLAYER_CHARACTER_DIR / "menu_character_preview.png"
MENU_BUTTONS_ASSET = ASSETS_DIR / "ui" / "menus" / "main_menu_buttons.png"
# Optional: the menu falls back to the text title / silence when these are absent.
GAME_LOGO_ASSET = ASSETS_DIR / "ui" / "menus" / "edge_of_winter_logo.png"
MENU_MUSIC_ASSET = ASSETS_DIR / "audio" / "music" / "main_menu.wav"
HAIR_SKIN_ASSET = ASSETS_DIR / "ui" / "character_customization" / "hair_and_skin_options.png"
CLOTHING_ASSET = ASSETS_DIR / "ui" / "character_customization" / "clothing_options.png"
OVERWORLD_TILESET_ASSET = ASSETS_DIR / "terrain" / "overworld" / "Fall Tile Set.png"
PLATANUS_ASSET_DIR = ASSETS_DIR / "bosses" / "platanus"
SAILBOAT_HULL_ASSET = ASSETS_DIR / "vehicles" / "sailboat_hull.png"


def require_asset(path: Path) -> Path:
    """Return one explicit runtime asset or fail without selecting a fallback."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Required game asset not found: {path}")
    return path
