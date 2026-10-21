"""English player-facing text for EDGE OF WINTER.

Internal identifiers deliberately keep their original values: inventory item
keys (``"Odun"``, ``"Tas"`` ...), quest and achievement IDs, resource-node IDs
and network/save fields are shared with saves, the server and older clients.
This module maps those identifiers to the English text players see, and owns
the repeated UI labels, notifications and story dialogue.
"""

GAME_TITLE = "EDGE OF WINTER"
DEVELOPERS = ("İlker", "Eymen", "Cevher", "Arda")
DEVELOPER_CREDIT = " · ".join(DEVELOPERS)

BOSS_ISLAND_NAME = "Crimsonroot Isle"
QUEST_NAME = "The Autumn Curse"
ACHIEVEMENT_NAME = "Cursebreaker"
ACHIEVEMENT_DESCRIPTION = (
    "You defeated PLATANUS, the ancient forest guardian, and lifted the curse "
    "of Crimsonroot Isle."
)

# Inventory/resource identifiers -> display names.
ITEM_NAMES = {
    "Odun": "Wood",
    "Tas": "Stone",
    "Tahil": "Wheat",
    "Balik": "Fish",
    "Çiğ Et": "Raw Meat",
    "Pişmiş Et": "Cooked Meat",
    "Ekmek": "Bread",
    "Ok": "Arrows",
    "Kadim Anahtar": "Ancient Key",
}

WEAPON_NAMES = {"axe": "Axe", "sword": "Sword", "bow": "Bow"}

CREATURE_NAMES = {
    "wolf": "Wolf", "boar": "Boar", "pirate": "Pirate", "bandit": "Bandit",
    "thief": "Thief", "sheep": "Sheep", "cow": "Cow", "monster": "Monster",
}

PROFESSION_TITLES = {
    "fisherman": "Fisherman", "farmer": "Farmer", "miner": "Miner",
    "elder": "Village Elder", "merchant": "Merchant", "villager": "Villager",
}

# Short verbs shown beside the pixel-art keycap prompts.
ACTIONS = {
    "talk": "Talk", "chop": "Chop", "mine": "Mine", "harvest": "Harvest",
    "cook": "Cook", "fish": "Fish", "trade": "Trade", "embark": "Set Sail",
    "disembark": "Go Ashore", "enter": "Enter", "inspect": "Inspect",
    "unseal": "Unseal", "seals": "Seals {held}/3", "collect": "Collect",
}

RESOURCE_ACTIONS = {"Odun": "chop", "Tas": "mine", "Tahil": "harvest"}

STRINGS = {
    # Main menu, loading and settings
    "menu.start_hint": "[ Click to Enter / Resume ]",
    "menu.world_ready": "WORLD READY",
    "menu.world_loading": "PREPARING WORLD... {pct}%",
    "menu.load_error": "Loading Failed!",
    "menu.customize_title": "CHARACTER CUSTOMIZATION",
    "menu.back": "BACK",
    "menu.credits": "CREDITS",
    "menu.developed_by": "Developed by",
    "credits.art": "Pixel Art & Artwork: Fall Tile Set Collection",
    "credits.engine": "Game Engine: Python 3 & Pygame 2",
    "credits.network": "Multiplayer: Standalone TCP Server & Client",
    "credits.world": "Worlds: Seeded Procedural Generation",
    "preload.not_started": "Not started",
    "preload.preparing": "Preparing world...",
    "preload.network": "Checking network...",
    "preload.terrain": "Generating island terrain...",
    "preload.ports": "Building ports and waterways...",
    "preload.spawn": "Locating player spawn point...",
    "preload.tiles": "Preparing tile map...",
    "preload.finalizing": "Finalizing...",
    "preload.artwork": "Preparing autumn artwork...",
    "preload.ready": "Ready!",
    "preload.error": "Error: {error}",
    "settings.title": "SETTINGS",
    "settings.world_seed": "World Seed",
    "settings.server_address": "Server Address",
    "settings.port": "Port",
    "settings.random": "RANDOM",
    "settings.display_label": "Display",
    "settings.windowed": "WINDOWED",
    "settings.fullscreen": "FULLSCREEN",
    "settings.window_size": "Window Size",
    "settings.size_note": "(windowed)",
    "settings.scaling": "Scaling",
    "settings.fit": "FIT TO WINDOW",
    "settings.pixel_perfect": "PIXEL PERFECT",
    "settings.music_volume": "Music Volume",
    "settings.menu_music_missing": "(no menu track)",
    "settings.display_applied": "Display and audio settings applied.",
    "settings.apply": "APPLY",
    "settings.cancel": "CANCEL",
    "settings.confirm": "CONFIRM",
    "settings.status": "Configured seed: {configured}   Active world: {active}   {status}",
    "settings.online": "ONLINE ({host}:{port})",
    "settings.offline": "OFFLINE",
    "settings.tab_hint": "TAB: next field   ENTER: apply   ESC: close",
    "settings.saved": "Settings saved. Preparing the world...",
    "settings.unchanged": "No changes to apply.",
    "settings.busy": "Finish the PLATANUS battle before changing the world.",
    "settings.confirm_title": "APPLY NEW SETTINGS?",
    "settings.confirm_regen": "The world will be regenerated from the new seed.",
    "settings.confirm_disconnect": "Your online session will be disconnected.",
    "settings.confirm_reconnect": "The game will reconnect to the new server.",
    "settings.confirm_progress": "Offline progress in the current world is saved first.",
    "settings.save_failed": "Could not save settings: {error}",
    "settings.connection_failed": "Could not reach {host}:{port} - playing offline. ({error})",
    "error.seed_empty": "World seed cannot be empty.",
    "error.address_invalid": "Server address is not a valid IP address or hostname.",
    "error.port_number": "Port must be a number.",
    "error.port_range": "Port must be between 1 and 65535.",

    # HUD and status bar
    "hud.health": "HEALTH",
    "hud.inventory": "INVENTORY [I / TAB]",
    "hud.trade": "TRADE [T]",
    "hud.islands": "ISLANDS LIBERATED",
    "hud.inflation": "SUPPLY COST INCREASE",
    "hud.nearby": "LOCAL AREA / N",
    "hud.world_map": "M: WORLD MAP",
    "hud.map": "MAP",
    "hud.exhausted": "EXHAUSTED! ({seconds:.1f}s)",
    "hud.gear": "Axe {axe}  Sword {sword}  Bow {bow}  Arrows: {arrows}  Combat Lv.{level} ({xp} XP)",
    "hud.pvp": "  PvP K/D: {kills}/{deaths}",
    "hud.dash_ready": "DASH READY",
    "hud.dash_charging": "DASH {pct}% (early = short)",
    "hud.dash_locked": "DASH LOCKED - liberate an island",
    "hud.wind": "Wind {strength:.1f}",
    "hud.sail_raised": "SAIL RAISED",
    "hud.sail_lowered": "SAIL LOWERED [R]",
    "hud.sea": "Open Sea",
    "hud.your_island": "{name} [Your Island]",
    "hud.player_island": "{name} [Player {owner}]",
    "hud.unclaimed": "{name} [Unclaimed]",
    "hud.offline": "Single Player (Offline)",
    "hud.online": "Online: {count} Players",
    "hud.quick_eat": "H: Quick Eat",
    "hud.port_controls": "{interact}: Fish | {embark}: Board / Leave Boat",
    "hud.sail_controls": "Mouse: Sail Angle | R: Raise/Lower Sail | A/D: Row & Steer | Left Click: Bow",
    "hud.portal_enter": "{interact}: Enter the Ancient Portal",
    "hud.portal_locked": "{interact}: Ancient Portal ({held}/3)",
    "hud.campfire": "{interact}: Cook at the campfire",
    "hud.talk_to": "{interact}: Talk to {name}",
    "hud.walk_controls": "WASD: Walk | Double Tap: 8-Way Dash | Dash+J: Wave | J/SPACE: Sword | K: Low Strike",
    "hud.walk_controls_no_dash": "WASD: Walk | J/SPACE: Sword | K: Low Strike",
    "hud.boss_controls": "WASD: Walk | J/SPACE: Sword | K: Low Strike | ESC: Retreat",
    "hud.other_player": "Player {pid}",
    "hud.merchant": "MERCHANT [{key}]",
    "hud.pirate": "PIRATE",
    "hud.inflation_tag": " [+{pct}%]",
    "hud.rescue_ready": "Liberate {name} [C] ({cost}){inflation}",
    "hud.rescue_short": "Liberate {name}: Need Supplies{inflation}",
    "hud.rescued": "{name} Liberated (Village Safe)",

    # The Wandering Sage teaches Dash (Windstep) after the first liberation
    "sage.name": "The Wandering Sage",
    "sage.arrives": "A mysterious figure appears in a swirl of starlight...",
    "sage.line1": "Well met, brave wanderer! Word of thy triumph has traveled farther than the autumn winds.",
    "sage.line2": "Many before thee have sought to free these forgotten isles, yet few possessed the courage to succeed.",
    "sage.line3": "But courage alone shall not carry thee through the dangers that lie ahead.",
    "sage.line4": "Long ago, the swiftest guardians of the old kingdoms mastered an art known as the Windstep - a sudden burst of movement quicker than the eye could follow.",
    "sage.line5": "I shall entrust this ancient technique to thee. Use it wisely, for even the swiftest feet cannot outrun fate.",
    "sage.line6": "Ability Unlocked: DASH - Windstep",
    "sage.line7": "{binding} to swiftly evade danger. Let the wind guide thy steps!",
    "ability.unlocked": "NEW ABILITY UNLOCKED",
    "ability.windstep": "WINDSTEP - DASH",
    "ability.binding": "Double-tap {keys} or an arrow key",
    "ability.toast": "Windstep learned! {binding} to dash.",

    # Map
    "map.title": "AUTUMN ISLES   /   LIBERATED {count}/6",
    "map.score": "PLAYER {pid}: {count}/6",
    "map.close": "M / ESC",
    "map.controls": "WHEEL: ZOOM   DRAG: PAN   {zoom:.1f}X",
    "map.chart": "ISLAND CHART  {zoom:.1f}X",
    "map.chart_controls": "WHEEL / DRAG",
    "map.legend_you": "YOU",
    "map.legend_player": "PLAYER",
    "map.legend_yours": "YOUR ISLAND",
    "map.legend_rival": "RIVAL ISLAND",
    "map.legend_unclaimed": "UNCLAIMED",
    "map.legend_harbor": "HARBOR",

    # Pause menu
    "pause.title": "GAME PAUSED",
    "pause.resume": "RESUME (ESC)",
    "pause.menu": "RETURN TO MAIN MENU",

    # Dialogue and combat effects
    "dialogue.continue": "E / ENTER: Continue",
    "dialogue.skip": "E / ENTER: Show All",
    "combat.finisher": "FINISHER!",
    "combat.wave_dash": "WAVE DASH!",
    "combat.combo": "COMBO x{combo}",
    "combat.xp": "+{amount} Combat XP",
    "arena.title": "ISLAND PERIL - BATTLE ARENA",
    "arena.controls": "WASD: Move  |  J/SPACE: Strike  |  K: Low Strike",

    # Quest tracker and achievements
    "quest.keys": "Ancient Keys: {held}/3",
    "quest.goal_keys": "Liberate villages to recover the keys",
    "quest.goal_portal": "Find Crimsonroot Isle - Unlock the Ancient Portal",
    "quest.goal_boss": "The portal is open: Defeat PLATANUS",
    "quest.complete": "Quest Complete",
    "achievement.unlocked": "ACHIEVEMENT UNLOCKED - {name}",
    "achievement.toast": "Achievement Unlocked: {name}",

    # Minigames
    "grain.start": "Drag the scythe along the line!",
    "grain.follow": "Follow the line!",
    "grain.start_left": "Start from the left end of the line!",
    "grain.too_early": "You let go too soon! The wheat was spoiled.",
    "grain.perfect": "Perfect cut! You gathered 3 wheat!",
    "grain.good": "Good cut! You gathered 2 wheat.",
    "grain.poor": "A shaky cut... You gathered 1 wheat.",
    "grain.missed": "The scythe slipped! The wheat was spoiled.",
    "grain.accuracy": "Accuracy",
    "stone.start": "Click the cracks! (Mind the recoil)",
    "stone.timeout": "Time is up! The stone would not break.",
    "wood.start": "Press SPACE when the axe lines up with the notch!",
    "wood.hit": "A clean strike! The notch grows deeper.",
    "wood.miss": "Missed! Line the blade up with the notch.",
    "wood.felled": "Splendid! The tree has fallen.",
    "wood.timeout": "Time is up! The tree still stands.",
    "wood.title": "AUTUMN FOREST",
    "wood.status": "WOODCUTTING   /   {hits} / {required} strikes   AXE Lv.{level}",
    "wood.time": "Time: {seconds:04.1f}",
    "wood.controls": "SPACE: Strike     ESC / E / Q: Close",
    "fish.escaped": "The fish got away! Waiting for another bite...",
    "fish.waiting": "Your line is in the water, waiting for a bite...",
    "fish.hooked": "A fish is biting! Reel with the wheel and keep the tension steady.",
    "fish.caught": "Splendid! {count} fish caught in total. Waiting for the next...",
    "fish.controls": "Line: {length} px   Up: Reel In / Down: Let Out   ESC: Close",

    # Cooking, inventory and crafting
    "cook.title": "COOK AT THE CAMPFIRE",
    "cook.button": "COOK",
    "cook.requires": "Requires: {requirement}  (Have: {have})",
    "cook.food_line": "{name} x{count} (+{heal} health)",
    "cook.village_bread": "Village Bread",
    "eat.button": "EAT",
    "inventory.title": "INVENTORY & ISLAND LIBERATION",
    "inventory.items": "INVENTORY",
    "inventory.material": "Building material",
    "inventory.provisions": "Provisions",
    "inventory.food_stats": "+{health} health / +{energy} energy",
    "inventory.ammo": "Bow ammunition",
    "inventory.quick_eat": "H: Quick Eat",
    "craft.title": "CRAFTING & WEAPONS",
    "craft.arrows": "Craft {amount} Arrows",
    "craft.button": "CRAFT",
    "weapon.level": "{name}  Lv.{level}",
    "weapon.hits": "{hits} strikes per tree",
    "weapon.stats": "+{damage} damage  x{range:.2f} range",
    "weapon.axe_note": "Fewer strikes to fell a tree",
    "weapon.combat_note": "Damage, range and speed",
    "weapon.max": "MAX",
    "weapon.upgrade": "UPGRADE",
    "rescue.title": "WINTER RESCUE OF THE ISLES",
    "rescue.goal": "Victory Goal: Liberate 6 Islands",
    "rescue.progress": "Islands Liberated: {count} / {target}",
    "rescue.location": "Location: {name}",
    "rescue.status_mine": "Status: Liberated - Ready for Winter",
    "rescue.status_other": "Status: Liberated by Player {owner}",
    "rescue.status_threat": "Status: Under Threat - Supplies Needed",
    "rescue.inflation": " (+{pct}%)",
    "rescue.needs": "Winter Supplies Needed{inflation}:",
    "rescue.deliver": "DELIVER WINTER SUPPLIES [C]",
    "rescue.insufficient": "INSUFFICIENT RESOURCES",
    "rescue.owned": "This island is free; its villagers work in safety.",
    "rescue.at_sea": "You are at sea!",
    "rescue.at_sea_hint": "Land on an island, speak with the villagers and end the local threat.",
    "rescue.map_hint": "Wheel: Zoom  |  Drag: Pan the chart",

    # Trading
    "trade.title": "PLAYER TRADING POST",
    "trade.new_offer": "CREATE A NEW OFFER",
    "trade.partner": "Trade With:",
    "trade.everyone": "Everyone",
    "trade.give": "You Give (Your Pack):",
    "trade.have": "{name} (have: {count})",
    "trade.want": "You Request:",
    "trade.send": "Send Offer [Enter]",
    "trade.active": "ACTIVE & INCOMING OFFERS",
    "trade.empty": "There are no active trade offers yet.",
    "trade.empty_hint1": "Create an offer on the left to swap",
    "trade.empty_hint2": "resources with other players!",
    "trade.yours": "Your Offer",
    "trade.from": "Offer from Player {pid}",
    "trade.status.pending": "PENDING",
    "trade.status.accepted": "ACCEPTED",
    "trade.status.cancelled": "CANCELLED",
    "trade.you_give": "You Give: {items}",
    "trade.you_want": "You Request: {items}",
    "trade.they_give": "You Receive: {items}",
    "trade.they_want": "They Request: {items}",
    "trade.cancel": "Cancel",
    "trade.accept": "Accept",
    "trade.insufficient": "Insufficient",

    # Victory
    "victory.title": "GLORIOUS VICTORY! 6 ISLANDS LIBERATED!",
    "victory.sub": "You defeated the island threats and readied the villages for winter!",
    "defeat.title": "THE GAME IS OVER!",
    "defeat.sub": "Player {winner} liberated six islands and readied their villages for winter!",
    "victory.islands": "Islands Liberated: {count} / {target}",
    "victory.inventory": "Inventory: {items}",
    "victory.flavor": "The islands under your protection live in peace and plenty.",
    "victory.continue": "KEEP EXPLORING",
    "victory.menu": "MAIN MENU",

    # PLATANUS encounter
    "boss.phase": "PHASE {phase}",
    "boss.victory": "PLATANUS Defeated!",
    "boss.defeat": "You Were Defeated",
    "boss.returning": "Returning to Crimsonroot Isle...",
    "boss.restart": "Press R to try again",
    "boss.demo_controls": "WASD/Arrows: Move  SPACE/J: Sword  SHIFT: Dodge  ESC: Quit",
    "boss.demo_missing": "Placeholder art: missing {assets}",

    # Notifications
    "toast.gathered": "+{count} {item} gathered!",
    "toast.hunted": "{creature} hunted: {count} Raw Meat dropped.",
    "toast.cook_missing": "Missing ingredients: {missing}",
    "toast.cooked": "Campfire: +{amount} {item}",
    "toast.ate": "You ate {item}: {gains}",
    "toast.health_gain": "+{amount} health",
    "toast.energy_gain": "+{amount} energy",
    "toast.no_food": "You have no food, or your health and energy are already full.",
    "toast.craft_missing": "Insufficient Resources for crafting: {missing}",
    "toast.crafted": "Crafted: +{amount} {item}",
    "toast.weapon_max": "This weapon is already at its highest level.",
    "toast.upgrade_missing": "Insufficient Resources for the upgrade: {missing}",
    "toast.upgraded": "{weapon} reached Lv.{level}!",
    "toast.rare_loot": "RARE LOOT: You found a {item}!",
    "toast.quest_complete": "Quest Complete! {reward}",
    "toast.key_found": "Ancient Key found! ({held}/3)",
    "toast.curse_broken": "The ancient curse is broken. The portal lies silent now.",
    "toast.seals_missing": "The ancient seals are incomplete. Three keys are required. ({held}/3)",
    "toast.seals_verifying": "The seals are being verified...",
    "toast.portal_opening": "The three ancient seals unite - the portal opens!",
    "toast.no_boss_authority": "This server does not host the PLATANUS battle.",
    "toast.boss_verifying": "Crossing into the realm of PLATANUS...",
    "toast.boss_repelled": "PLATANUS drove you back. The portal may be attempted again.",
    "toast.boss_retreat": "You retreated through the portal.",
    "toast.boss_connection_lost": "Connection lost - the PLATANUS battle was abandoned.",
    "toast.server_portal": "The server verified the three seals - the portal is open!",
    "toast.must_land": "You must go ashore to liberate an island!",
    "toast.already_rescued": "{name} has already been liberated!",
    "toast.quest_first": "First accept the villager's quest and defeat the island's threats!",
    "toast.supplies_missing": "Insufficient Resources for winter supplies! Missing: {missing}",
    "toast.insufficient": "Insufficient Resources!",
    "toast.rescued": "{name} LIBERATED! ({count}/{target})",
    "toast.rescued_short": "{name} LIBERATED!",
    "toast.income": "Island Income: {gains}",
    "toast.no_arrows": "Out of arrows! Craft more in the inventory with 2 Wood + 1 Stone.",
    "toast.creature_hit": "{creature} hit you! -{damage} health",
    "toast.fainted": "You fainted! You awaken on another island.",
    "toast.cannonball": "A pirate cannonball struck! -{damage} health",
    "toast.pirate_sunk": "Pirate ship sunk!",
    "toast.pirate_ram": "A pirate ship rammed your boat!",
    "toast.boat_sunk": "Your boat sank! You awaken on another island.",
    "toast.merchant_need": "Merchant: Bring 2 Fish to trade.",
    "toast.sea_trade": "Sea trade: 2 Fish for 4 {item}",
    "toast.trade_accepted": "Trade accepted! Resources exchanged.",
    "toast.trade_cancelled": "Trade offer cancelled.",
    "toast.sail_raised": "Sail raised. [R]",
    "toast.sail_lowered": "Sail lowered. [R]",
    "toast.player_defeated_you": "Player {pid} defeated you - you awaken on another island!",
    "toast.player_hit_you": "Player {pid} struck you! -{damage} health",
    "toast.island_taken": "NOTICE: {name} was liberated by Player {pid}!",
    "toast.wood_failed": "Woodcutting failed: time ran out!",
    "toast.trade_select": "Choose resources both to give and to request!",
    "toast.trade_lacking": "Your pack does not hold the resources you offered!",
    "toast.trade_sent": "Trade offer sent!",
    "toast.trade_offline": "Trading requires a multiplayer connection!",
    "toast.trade_complete": "Trade complete! Your offer was accepted.",
}

# Three-key PLATANUS storyline, keyed by the number of keys recovered.
TREANT_STORY = {
    1: ("The Village Elder", [
        "Listen well, brave wanderer! Long ago, beyond the restless seas, there was said "
        "to be an island where the autumn leaves never withered.",
        "Deep within its ancient woods dwelt PLATANUS, a guardian older than the kingdoms "
        "of men. They say his eyes burned like embers, and his roots reached beneath the "
        "earth to drag even the bravest knights into darkness.",
        "Three wise elders sealed the creature behind an ancient gate, and entrusted its "
        "three keys to three distant villages.",
        "Take this key, brave soul, and heed my warning: no mortal may open the gate until "
        "all three seals are gathered.",
    ]),
    2: ("The Village Sage", [
        "So, you have found the first seal, bold traveller! Then hear a secret that has "
        "passed down from the elder days.",
        "Once, seven knights set sail for the isle of PLATANUS. On the first night the "
        "forest whispered; on the second, the earth trembled; and on the third, crimson "
        "leaves rained from the sky.",
        "When dawn broke, not one of the knights remained. Only their rusted swords were "
        "ever found, tangled among the roots.",
        "Take the second seal. Find the last, and the ancient gate may yield to you. Yet "
        "mark my words: a gate once opened is far harder to close than to open!",
    ]),
    3: ("The Last Warden", [
        "Hail, valiant wayfarer! At long last, the hour of the third seal has come.",
        "The old chronicles tell that PLATANUS slumbers in the depths of Crimsonroot Isle. "
        "Each year, as autumn draws near, he opens his eyes, sinks his roots into the soil "
        "and holds dominion over every living thing in the forest.",
        "Here is the final key! Now all three seals rest in your hands.",
        "Sail to Crimsonroot Isle and seek the ancient ring of stones. Set the three keys "
        "in their places and open the sealed gate.",
        "But remember this well, brave one: what waits beyond that gate is no mere beast, "
        "but a curse that has not slept for centuries!",
    ]),
}

# Generic island-villager quest dialogue.
VILLAGER_DIALOGUE = {
    "offer": [
        "Our island is beset by raiders and wild beasts. We cannot gather provisions for "
        "the winter.",
        "Will you aid us, traveller? Defeat the {required} threats on this island, then "
        "bring us the winter supplies.",
    ],
    "active": ["Danger still haunts our island. Progress: {progress}/{required}."],
    "ready": ["The danger has passed. Deliver the winter supplies and our island will be saved."],
    "done": ["Thanks to you our island is safe and our stores are full. We shall weather "
             "this winter!"],
}


_reported_problems = set()


def _report(problem):
    """Log each localization problem once instead of crashing the render loop."""
    if problem not in _reported_problems:
        _reported_problems.add(problem)
        print(f"[LOCALIZATION] {problem}")


class _KeepMissing(dict):
    """format_map mapping that leaves an unsupplied ``{placeholder}`` visible."""

    def __init__(self, values, translation_key):
        super().__init__(values)
        self.translation_key = translation_key

    def __missing__(self, name):
        _report(f"'{self.translation_key}' is missing a value for {{{name}}}")
        return _Placeholder(name)


class _Placeholder:
    """Renders as ``{name}`` whatever format spec the string applies to it."""

    def __init__(self, name):
        self.name = name

    def __format__(self, spec):
        return "{" + self.name + "}"


def _format(text, translation_key, values):
    return text.format_map(_KeepMissing(values, translation_key))


def tr(translation_key, /, **values):
    """Return the English text for ``translation_key`` formatted with ``values``.

    The key is positional-only, so any placeholder name -- including ``key`` as
    used by keycap labels -- can be passed as a formatting argument.  An unknown
    key falls back to the key itself and is reported once.
    """
    text = STRINGS.get(translation_key)
    if text is None:
        _report(f"missing translation key '{translation_key}'")
        return translation_key
    return _format(text, translation_key, values)


def item_name(item):
    """Display name for an inventory identifier; unknown names pass through."""
    return ITEM_NAMES.get(item, item)


def weapon_name(weapon):
    return WEAPON_NAMES.get(weapon, str(weapon).title())


def creature_name(kind):
    return CREATURE_NAMES.get(kind, str(kind).title())


def action_label(action, /, **values):
    text = ACTIONS.get(action)
    if text is None:
        _report(f"missing action label '{action}'")
        return str(action).title()
    return _format(text, action, values)


def format_amounts(amounts, separator=", ", sign=""):
    """Render ``{item_id: amount}`` as e.g. ``"3 Wood, 2 Stone"``."""
    return separator.join(f"{sign}{amount} {item_name(item)}"
                          for item, amount in amounts.items())
