"""Data-driven inventory crafting and weapon progression rules.

This module intentionally has no pygame dependency.  Gameplay controllers and UI can
consume the same immutable definitions without duplicating balance values.
"""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .localization import ACHIEVEMENT_DESCRIPTION, ACHIEVEMENT_NAME, QUEST_NAME


@dataclass(frozen=True)
class FoodDefinition:
    health: int
    energy: int = 0


@dataclass(frozen=True)
class Recipe:
    ingredients: Mapping[str, int]
    output: str
    amount: int


@dataclass(frozen=True)
class WeaponStats:
    level: int
    damage_bonus: int = 0
    range_multiplier: float = 1.0
    attack_speed_multiplier: float = 1.0
    required_hits: int = 4
    impact: float = 1.0


TREANT_QUEST_NAME = QUEST_NAME
# Persistent achievement ID stored in saves; never shown to the player.
TREANT_ACHIEVEMENT = "Lanet Kıran"
TREANT_ACHIEVEMENT_NAME = ACHIEVEMENT_NAME
TREANT_ACHIEVEMENT_DESCRIPTION = ACHIEVEMENT_DESCRIPTION


@dataclass
class TreantQuestProgress:
    """Session progression for the three-key quest.

    The current project has no disk-save service, so this object is deliberately
    serializable without owning I/O.  A future save layer can store ``to_dict``
    alongside the existing session data without changing gameplay code.
    """
    rescued_village_ids: set[int] = field(default_factory=set)
    keys_held: int = 0
    # The tracker starts at 0/3 so the goal is visible before the first rescue.
    quest_active: bool = True
    portal_unlocked: bool = False
    boss_defeated: bool = False
    dialogue_steps_seen: set[int] = field(default_factory=set)
    achievements: set[str] = field(default_factory=set)

    def record_village_rescue(self, village_id):
        village_id = int(village_id)
        if village_id in self.rescued_village_ids:
            return None
        self.rescued_village_ids.add(village_id)
        if len(self.rescued_village_ids) > 3:
            return None
        self.keys_held = min(3, self.keys_held + 1)
        self.quest_active = True
        step = len(self.rescued_village_ids)
        self.dialogue_steps_seen.add(step)
        return step

    def unlock_portal(self):
        if self.portal_unlocked:
            return True
        if self.keys_held != 3:
            return False
        self.keys_held = 0
        self.portal_unlocked = True
        return True

    def complete_boss(self):
        first_completion = not self.boss_defeated
        self.boss_defeated = True
        self.achievements.add(TREANT_ACHIEVEMENT)
        return first_completion

    def to_dict(self):
        return {
            "rescued_village_ids": sorted(self.rescued_village_ids),
            "keys_held": self.keys_held,
            "quest_active": self.quest_active,
            "portal_unlocked": self.portal_unlocked,
            "boss_defeated": self.boss_defeated,
            "dialogue_steps_seen": sorted(self.dialogue_steps_seen),
            "achievements": sorted(self.achievements),
        }

    @classmethod
    def from_dict(cls, data):
        """Restore saved progress, skipping malformed values instead of failing."""
        data = data if isinstance(data, dict) else {}

        def values(key):
            raw = data.get(key, ())
            return raw if isinstance(raw, (list, tuple, set)) else ()

        def int_set(key):
            result = set()
            for value in values(key):
                try:
                    result.add(int(value))
                except (TypeError, ValueError):
                    pass
            return result

        try:
            keys_held = max(0, min(3, int(data.get("keys_held", 0))))
        except (TypeError, ValueError):
            keys_held = 0
        return cls(
            rescued_village_ids=int_set("rescued_village_ids"),
            keys_held=keys_held,
            quest_active=bool(data.get("quest_active", True)),
            portal_unlocked=bool(data.get("portal_unlocked", False)),
            boss_defeated=bool(data.get("boss_defeated", False)),
            dialogue_steps_seen=int_set("dialogue_steps_seen"),
            achievements={str(value) for value in values("achievements")},
        )


FOODS = MappingProxyType({
    "Pişmiş Et": FoodDefinition(health=2, energy=25),
    "Ekmek": FoodDefinition(health=1, energy=15),
})

RECIPES = MappingProxyType({
    "arrows": Recipe(MappingProxyType({"Odun": 2, "Tas": 1}), "Ok", 5),
})

# Each entry describes the resulting level.  Costs live separately because level 1
# is owned by default and therefore has no purchase cost.
WEAPON_TIERS = MappingProxyType({
    "axe": (
        WeaponStats(1, required_hits=4, impact=1.0),
        WeaponStats(2, required_hits=3, impact=1.25),
        WeaponStats(3, required_hits=2, impact=1.55),
        WeaponStats(4, required_hits=1, impact=1.9),
    ),
    "sword": (
        WeaponStats(1),
        WeaponStats(2, damage_bonus=1, range_multiplier=1.06, attack_speed_multiplier=1.08),
        WeaponStats(3, damage_bonus=2, range_multiplier=1.12, attack_speed_multiplier=1.16),
        WeaponStats(4, damage_bonus=3, range_multiplier=1.20, attack_speed_multiplier=1.25),
    ),
    "bow": (
        WeaponStats(1),
        WeaponStats(2, damage_bonus=1, range_multiplier=1.15, attack_speed_multiplier=1.12),
        WeaponStats(3, damage_bonus=2, range_multiplier=1.30, attack_speed_multiplier=1.24),
        WeaponStats(4, damage_bonus=3, range_multiplier=1.50, attack_speed_multiplier=1.38),
    ),
})

UPGRADE_COSTS = MappingProxyType({
    "axe": (
        MappingProxyType({"Odun": 6, "Tas": 2}),
        MappingProxyType({"Odun": 12, "Tas": 6}),
        MappingProxyType({"Odun": 20, "Tas": 12}),
    ),
    "sword": (
        MappingProxyType({"Odun": 3, "Tas": 6}),
        MappingProxyType({"Odun": 7, "Tas": 12}),
        MappingProxyType({"Odun": 12, "Tas": 20}),
    ),
    "bow": (
        MappingProxyType({"Odun": 5, "Tas": 3}),
        MappingProxyType({"Odun": 10, "Tas": 7}),
        MappingProxyType({"Odun": 18, "Tas": 12}),
    ),
})


class ProgressionSystem:
    """Owns weapon levels while inventory storage stays with the game session."""

    def __init__(self, levels=None):
        supplied = levels or {}
        self.levels = {
            weapon: max(1, min(len(tiers), int(supplied.get(weapon, 1))))
            for weapon, tiers in WEAPON_TIERS.items()
        }

    def stats(self, weapon):
        tiers = WEAPON_TIERS[weapon]
        return tiers[self.levels[weapon] - 1]

    def next_cost(self, weapon):
        level = self.levels[weapon]
        costs = UPGRADE_COSTS[weapon]
        return costs[level - 1] if level <= len(costs) else None

    def upgrade(self, weapon, inventory):
        if weapon not in self.levels:
            return False
        cost = self.next_cost(weapon)
        if cost is None or any(inventory.get(item, 0) < amount for item, amount in cost.items()):
            return False
        # Check first and mutate second so purchases are atomic.
        for item, amount in cost.items():
            inventory[item] -= amount
        self.levels[weapon] += 1
        return True


def craft(recipe_key, inventory):
    """Craft one recipe atomically and return the produced amount (zero on failure)."""
    recipe = RECIPES.get(recipe_key)
    if recipe is None or any(inventory.get(item, 0) < amount
                             for item, amount in recipe.ingredients.items()):
        return 0
    for item, amount in recipe.ingredients.items():
        inventory[item] -= amount
    inventory[recipe.output] = inventory.get(recipe.output, 0) + recipe.amount
    return recipe.amount
