"""Extensible NPC, quest, dialogue and melee-combat gameplay systems.

The data objects deliberately carry asset keys rather than loaded surfaces/sounds.
Renderers can later resolve those keys from any sprite, model or audio registry.
"""
from dataclasses import dataclass, field
import math
import random

from .localization import PROFESSION_TITLES, VILLAGER_DIALOGUE
from .worldgen import can_stand


FACING_VECTORS = {
    "up": (0.0, -1.0), "down": (0.0, 1.0),
    "left": (-1.0, 0.0), "right": (1.0, 0.0),
}


@dataclass
class NPC:
    id: str
    name: str
    island_index: int
    x: float
    y: float
    quest_id: str
    sprite_key: str = "villager/default"
    profession: str = "villager"
    appearance_variant: int = 0
    facing: str = "down"
    moving: bool = False
    walk_phase: float = 0.0
    visual_x: float = None
    visual_y: float = None

    def __post_init__(self):
        self.visual_x = self.x if self.visual_x is None else self.visual_x
        self.visual_y = self.y if self.visual_y is None else self.visual_y


@dataclass
class Monster:
    id: str
    island_index: int
    x: float
    y: float
    kind: str = "wolf"
    health: int = 3
    max_health: int = 3
    alive: bool = True
    hit_flash: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    sprite_key: str = "monster/wolf"
    attack_timer: float = 0.0
    damage: int = 1
    move_speed: float = 1.35
    awareness: float = 12.0
    attack_range: float = 1.05
    attack_windup: float = 0.48
    attack_cooldown: float = 0.0
    state: str = "idle"
    home_x: float = None
    home_y: float = None
    decision_timer: float = 0.0
    strafe_sign: int = 1
    facing: str = "right"
    walk_phase: float = 0.0
    death_handled: bool = False

    def __post_init__(self):
        if self.home_x is None:
            self.home_x = self.x
        if self.home_y is None:
            self.home_y = self.y


@dataclass
class Animal:
    id: str
    island_index: int
    x: float
    y: float
    kind: str
    health: int
    max_health: int
    alive: bool = True
    hit_flash: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    facing: str = "right"
    walk_phase: float = 0.0
    home_x: float = None
    home_y: float = None
    target_x: float = 0.0
    target_y: float = 0.0
    decision_timer: float = 0.0
    idle_timer: float = 0.0
    flee_timer: float = 0.0
    death_handled: bool = False

    def __post_init__(self):
        self.home_x = self.x if self.home_x is None else self.home_x
        self.home_y = self.y if self.home_y is None else self.home_y
        self.target_x, self.target_y = self.x, self.y


@dataclass
class LootDrop:
    id: str
    x: float
    y: float
    item: str
    count: int = 1
    life: float = 90.0
    phase: float = 0.0
    authoritative: bool = False


class AnimalSystem:
    """Deterministic, low-cost sheep/cow herds for grassland islands."""
    def __init__(self, world):
        self.world = world
        self.animals = []
        self.rng = random.Random(world.seed + 0xC0A5)
        self._populate()

    def _populate(self):
        rows, cols = len(self.world.heights), len(self.world.heights[0])
        for island_index, island in enumerate(self.world.islands):
            # Villages receive small pasture groups; some wild meadow islands do too.
            count = (2 + (island_index % 2)) if island.village else (2 if island_index % 4 == 0 else 0)
            made = 0
            for attempt in range(180):
                if made >= count:
                    break
                angle = self.rng.random() * math.tau
                radius = self.rng.uniform(3.5, max(5.0, min(island.rx, island.ry) * .62))
                x = island.x + math.cos(angle) * radius
                y = island.y + math.sin(angle) * radius
                tx, ty = int(x), int(y)
                if not (1 <= tx < cols - 1 and 1 <= ty < rows - 1):
                    continue
                height = self.world.heights[ty][tx]
                if (self.world.owners[ty][tx] != island_index or not .09 <= height < .43
                        or (tx, ty) in self.world.buildings
                        or not can_stand(self.world, x, y, False)
                        or any(math.hypot(x - a.x, y - a.y) < 1.4 for a in self.animals)):
                    continue
                kind = "cow" if (island_index + made) % 3 == 0 else "sheep"
                health = 6 if kind == "cow" else 4
                self.animals.append(Animal(f"{kind}:{island_index}:{made}", island_index,
                                           x, y, kind, health, health,
                                           decision_timer=self.rng.uniform(.2, 2.0)))
                made += 1

    def flee(self, animal, source_x, source_y):
        dx, dy = animal.x - source_x, animal.y - source_y
        distance = max(.001, math.hypot(dx, dy))
        animal.target_x = animal.x + dx / distance * 4.5
        animal.target_y = animal.y + dy / distance * 4.5
        animal.flee_timer = 1.15
        animal.decision_timer = 0.0

    def suitable_step(self, animal, x, y, can_move):
        tx, ty = int(x), int(y)
        return (0 <= ty < len(self.world.heights) and 0 <= tx < len(self.world.heights[ty])
                and self.world.owners[ty][tx] == animal.island_index
                and .09 <= self.world.heights[ty][tx] < .43
                and (tx, ty) not in self.world.buildings and can_move(x, y))

    def update(self, dt, player, can_move):
        dt = min(.1, max(0.0, dt))
        for animal in self.animals:
            if not animal.alive or animal.hit_flash > 0:
                continue
            animal.decision_timer -= dt
            animal.idle_timer = max(0.0, animal.idle_timer - dt)
            animal.flee_timer = max(0.0, animal.flee_timer - dt)
            distance_to_player = math.hypot(player.x - animal.x, player.y - animal.y)
            if distance_to_player < 2.2 and animal.flee_timer <= 0:
                self.flee(animal, player.x, player.y)
            if animal.decision_timer <= 0:
                animal.decision_timer = self.rng.uniform(1.2, 3.4)
                if animal.flee_timer <= 0 and self.rng.random() < .42:
                    animal.idle_timer = self.rng.uniform(.8, 2.1)
                else:
                    angle = self.rng.random() * math.tau
                    radius = self.rng.uniform(1.5, 4.0)
                    animal.target_x = animal.home_x + math.cos(angle) * radius
                    animal.target_y = animal.home_y + math.sin(angle) * radius
            if animal.idle_timer > 0:
                continue
            dx, dy = animal.target_x - animal.x, animal.target_y - animal.y
            distance = math.hypot(dx, dy)
            if distance < .15:
                animal.idle_timer = self.rng.uniform(.5, 1.5)
                continue
            speed = (2.35 if animal.flee_timer > 0 else
                     (1.0 if animal.kind == "sheep" else .82))
            nx, ny = dx / distance, dy / distance
            tx, ty = animal.x + nx * speed * dt, animal.y + ny * speed * dt
            moved = False
            if self.suitable_step(animal, tx, animal.y, can_move):
                animal.x, moved = tx, True
            if self.suitable_step(animal, animal.x, ty, can_move):
                animal.y, moved = ty, True
            if moved:
                animal.facing = "right" if nx >= 0 else "left"
                animal.walk_phase = (animal.walk_phase + dt * speed * 5.0) % 2
            else:
                animal.decision_timer = 0.0


@dataclass
class Quest:
    id: str
    island_index: int
    giver_id: str
    target_kind: str
    required: int
    reward: dict
    progress: int = 0
    state: str = "available"  # available, active, ready, completed


class DialogueBox:
    def __init__(self, chars_per_second=42.0):
        self.chars_per_second = chars_per_second
        self.speaker = ""
        self.pages = []
        self.page = 0
        self.visible_chars = 0.0
        self.active = False
        self.on_finish = None

    @property
    def text(self):
        return self.pages[self.page] if self.active and self.pages else ""

    @property
    def visible_text(self):
        return self.text[:int(self.visible_chars)]

    @property
    def page_complete(self):
        return self.visible_chars >= len(self.text)

    def open(self, speaker, pages, on_finish=None):
        self.speaker, self.pages = speaker, list(pages)
        self.page, self.visible_chars, self.active = 0, 0.0, bool(self.pages)
        self.on_finish = on_finish

    def update(self, dt):
        if self.active:
            self.visible_chars = min(len(self.text), self.visible_chars + max(0.0, dt) * self.chars_per_second)

    def advance(self):
        if not self.active:
            return False
        if not self.page_complete:
            self.visible_chars = float(len(self.text))
            return True
        if self.page + 1 < len(self.pages):
            self.page += 1
            self.visible_chars = 0.0
            return True
        callback = self.on_finish
        self.active, self.on_finish = False, None
        if callback:
            callback()
        return True


class QuestSystem:
    def __init__(self, world):
        self.npcs = []
        self.monsters = []
        self.quests = {}
        self._populate(world)

    def _populate(self, world):
        rng = random.Random(world.seed + 982451653)
        enemy_types = ("wolf", "pirate", "bandit", "thief", "boar")
        for idx, island in enumerate(world.islands):
            if idx == getattr(world, "boss_island_index", -1):
                continue
            cx, cy = island.village.center if island.village else (island.x, island.y)
            npc_id = f"villager:{idx}"
            profession = self._profession_for(world, island, idx, npc_id)
            identity = self._identity_value(world.seed, idx, npc_id, profession)
            # Merchants always carry one of the authentic atlas props; other
            # professions may also use their clean directional base pose.
            variant = 1 + identity % 4 if profession == "merchant" else identity % 5
            title = PROFESSION_TITLES.get(profession, PROFESSION_TITLES["villager"])
            home = getattr(island, "name", "")
            npc = NPC(npc_id, f"{title} of {home}" if home else f"{title} {idx + 1}", idx, cx + 0.5, cy + 1.5,
                      f"danger:{idx}", sprite_key=f"villager/{profession}",
                      profession=profession, appearance_variant=variant)
            self.npcs.append(npc)
            enemy_kind = enemy_types[idx % len(enemy_types)]
            quest = Quest(npc.quest_id, idx, npc.id, enemy_kind, 3, {})
            self.quests[quest.id] = quest
            made = 0
            for _ in range(100):
                angle = rng.random() * math.tau
                radius = rng.uniform(5.0, max(6.0, min(island.rx, island.ry) * 0.65))
                x, y = island.x + math.cos(angle) * radius, island.y + math.sin(angle) * radius
                tx, ty = int(x), int(y)
                if (0 <= ty < len(world.owners) and 0 <= tx < len(world.owners[0])
                        and world.owners[ty][tx] == idx and (tx, ty) not in world.buildings):
                    stats = {
                        "wolf": (5, 1.95, 1, 13.0, .38),
                        "pirate": (7, 1.55, 2, 14.0, .48),
                        "bandit": (6, 1.65, 2, 14.0, .44),
                        "thief": (4, 2.05, 1, 15.0, .34),
                        "boar": (6, 1.85, 2, 12.0, .52),
                    }
                    health, speed, damage, awareness, windup = stats[enemy_kind]
                    self.monsters.append(Monster(f"{enemy_kind}:{idx}:{made}", idx, x, y,
                                                 enemy_kind, health, health,
                                                 sprite_key=f"enemy/{enemy_kind}", move_speed=speed,
                                                 damage=damage, awareness=awareness,
                                                 attack_windup=windup,
                                                 strafe_sign=-1 if made % 2 else 1))
                    made += 1
                    if made >= quest.required:
                        break

    @staticmethod
    def _identity_value(world_seed, island_index, npc_id, profession=""):
        """Stable FNV-style identity; independent of Python's randomized hash."""
        value = (int(world_seed) ^ (int(island_index) * 0x9E3779B1)) & 0xffffffff
        for byte in f"{npc_id}:{profession}".encode("utf-8"):
            value ^= byte
            value = (value * 16777619) & 0xffffffff
        return value

    @classmethod
    def _profession_for(cls, world, island, island_index, npc_id):
        # Generic quest villagers choose among professions supported by their
        # island and village. This is visual metadata only; quest behavior stays
        # unchanged. Every client reaches the same choice from shared world data.
        choices = ["fisherman"]
        resources = getattr(island, "resources", ())
        if "Tahil" in resources:
            choices.append("farmer")
        if "Tas" in resources:
            choices.append("miner")
        if island.village is not None:
            choices.extend(("elder", "merchant"))
        value = cls._identity_value(world.seed, island_index, npc_id, "profession")
        return choices[value % len(choices)]

    def update_npc_animations(self, dt):
        """Advance visuals from actual position deltas without adding NPC AI."""
        dt = max(0.0, min(0.1, float(dt)))
        for npc in self.npcs:
            dx, dy = npc.x - npc.visual_x, npc.y - npc.visual_y
            npc.moving = abs(dx) + abs(dy) > 1e-5
            if npc.moving:
                if abs(dx) >= abs(dy):
                    npc.facing = "right" if dx > 0 else "left"
                else:
                    npc.facing = "down" if dy > 0 else "up"
                npc.walk_phase = (npc.walk_phase + dt * 8.0) % 4
            else:
                npc.walk_phase = 0.0
            npc.visual_x, npc.visual_y = npc.x, npc.y

    def nearby_npc(self, position, radius=1.8):
        return min((npc for npc in self.npcs if math.hypot(position.x - npc.x, position.y - npc.y) <= radius),
                   key=lambda npc: math.hypot(position.x - npc.x, position.y - npc.y), default=None)

    def interact(self, npc, dialogue, grant_reward, start_encounter=None, complete_quest=None):
        quest = self.quests[npc.quest_id]
        if quest.state == "available":
            def accept():
                quest.state = "ready" if quest.progress >= quest.required else "active"
                if start_encounter:
                    start_encounter(quest)
            dialogue.open(npc.name, [page.format(required=quest.required)
                                     for page in VILLAGER_DIALOGUE["offer"]], accept)
        elif quest.state == "active":
            dialogue.open(npc.name, [page.format(progress=quest.progress, required=quest.required)
                                     for page in VILLAGER_DIALOGUE["active"]])
        elif quest.state == "ready":
            def complete():
                if complete_quest and complete_quest(quest):
                    quest.state = "completed"
                elif not complete_quest:
                    quest.state = "completed"
                    grant_reward(quest.reward)
            dialogue.open(npc.name, list(VILLAGER_DIALOGUE["ready"]), complete)
        else:
            dialogue.open(npc.name, list(VILLAGER_DIALOGUE["done"]))

    def monster_defeated(self, monster):
        quest = next((q for q in self.quests.values()
                      if q.island_index == monster.island_index and q.state in ("available", "active")
                      and q.target_kind == monster.kind), None)
        if quest:
            quest.progress = min(quest.required, quest.progress + 1)
            if quest.progress >= quest.required:
                quest.state = "ready"


class CombatSystem:
    """Frame-driven sword attacks with buffered input and per-swing hit tracking."""
    ATTACKS = {
        "normal": {"duration": 0.30, "active": (0.07, 0.20), "reach": 1.45, "width": 1.15, "damage": 1},
        "crouch": {"duration": 0.44, "active": (0.10, 0.33), "reach": 1.30, "width": 1.85, "damage": 2},
        "dash": {"duration": 0.48, "active": (0.04, 0.32), "reach": 2.45, "width": 2.15, "damage": 3},
    }
    NORMAL_COMBO = (
        {"duration": .30, "active": (.07, .20), "reach": 1.45, "width": 1.15, "damage": 1},
        {"duration": .28, "active": (.06, .19), "reach": 1.55, "width": 1.25, "damage": 1},
        {"duration": .42, "active": (.10, .31), "reach": 1.85, "width": 1.55, "damage": 3},
    )

    def __init__(self):
        self.state = "idle"
        self.attack_kind = None
        self.timer = 0.0
        self.combo_step = 0
        self.combo_window = 0.0
        self.queued_kind = None
        self.hit_targets = set()
        self.hit_stop = 0.0
        self.impact_pulse = 0.0
        self.lunge_pending = 0.0
        self.damage_bonus = 0
        self.range_multiplier = 1.0
        self.attack_speed_multiplier = 1.0
        self.attack_power = 1.0
        self.on_attack = None

    def configure_weapon(self, damage_bonus=0, range_multiplier=1.0,
                         attack_speed_multiplier=1.0):
        """Apply the current sword tier without coupling combat to inventory code."""
        self.damage_bonus = max(0, int(damage_bonus))
        self.range_multiplier = max(.1, float(range_multiplier))
        self.attack_speed_multiplier = max(.1, float(attack_speed_multiplier))

    @property
    def attacking(self):
        return self.state == "attacking"

    def start_attack(self, kind="normal", power=1.0):
        kind = kind if kind in self.ATTACKS else "normal"
        if self.attacking:
            self.queued_kind = kind
            return False
        self.state, self.attack_kind, self.timer = "attacking", kind, 0.0
        self.attack_power = max(.1, min(1.0, float(power))) if kind == "dash" else 1.0
        if kind == "dash":
            self.combo_step = 3
            self.lunge_pending = 0.0
        else:
            self.combo_step = self.combo_step + 1 if self.combo_window > 0 else 1
            self.combo_step = min(self.combo_step, 3)
            self.lunge_pending = (.18 if kind == "crouch" else (.55 if self.combo_step == 3 else .32))
        self.hit_targets.clear()
        if callable(self.on_attack):
            self.on_attack(kind)
        return True

    def consume_lunge(self):
        distance, self.lunge_pending = self.lunge_pending, 0.0
        return distance

    def attack_profile(self):
        if self.attack_kind == "normal":
            base = self.NORMAL_COMBO[max(0, min(2, self.combo_step - 1))]
        else:
            base = self.ATTACKS[self.attack_kind]
        speed = self.attack_speed_multiplier
        power = self.attack_power if self.attack_kind == "dash" else 1.0
        return {
            "duration": base["duration"] / speed,
            "active": (base["active"][0] / speed, base["active"][1] / speed),
            "reach": base["reach"] * self.range_multiplier * (.55 + .45 * power),
            "width": base["width"] * self.range_multiplier * (.7 + .3 * power),
            "damage": max(1, round((base["damage"] + self.damage_bonus) * power)),
        }

    def hitbox(self, position, facing):
        attack = self.attack_profile()
        dx, dy = FACING_VECTORS.get(facing, (0.0, 1.0))
        cx = position.x + dx * attack["reach"] * 0.65
        cy = position.y + dy * attack["reach"] * 0.65
        if dx:
            return (cx - attack["reach"] / 2, cy - attack["width"] / 2,
                    attack["reach"], attack["width"])
        return (cx - attack["width"] / 2, cy - attack["reach"] / 2,
                attack["width"], attack["reach"])

    def update(self, dt, position, facing, monsters, on_defeat, can_move=None):
        dt = max(0.0, dt)
        self.hit_stop = max(0.0, self.hit_stop - dt)
        self.impact_pulse = max(0.0, self.impact_pulse - dt)
        self.combo_window = max(0.0, self.combo_window - dt)
        def movement_allowed(entity, x, y):
            if can_move is None:
                return True
            try:
                return can_move(x, y, entity)
            except TypeError:
                return can_move(x, y)
        for monster in monsters:
            monster.hit_flash = max(0.0, monster.hit_flash - dt)
            if monster.alive and (abs(monster.vx) + abs(monster.vy)) > .01:
                next_x, next_y = monster.x + monster.vx * dt, monster.y + monster.vy * dt
                if movement_allowed(monster, next_x, monster.y):
                    monster.x = next_x
                else:
                    monster.vx = 0.0
                if movement_allowed(monster, monster.x, next_y):
                    monster.y = next_y
                else:
                    monster.vy = 0.0
            monster.vx *= max(0.0, 1.0 - 8.0 * dt)
            monster.vy *= max(0.0, 1.0 - 8.0 * dt)
        if not self.attacking or self.hit_stop > 0:
            return []
        self.timer += dt
        attack = self.attack_profile()
        hits = []
        if attack["active"][0] <= self.timer <= attack["active"][1]:
            x, y, w, h = self.hitbox(position, facing)
            dx, dy = FACING_VECTORS.get(facing, (0.0, 1.0))
            for monster in monsters:
                if (monster.alive and monster.id not in self.hit_targets
                        and x <= monster.x <= x + w and y <= monster.y <= y + h):
                    self.hit_targets.add(monster.id)
                    monster.health -= attack["damage"]
                    monster.hit_flash = 0.16
                    knockback = 6.5 if self.combo_step == 3 else 4.5
                    monster.vx, monster.vy = dx * knockback, dy * knockback
                    self.hit_stop = 0.055 if self.combo_step == 3 else 0.038
                    self.impact_pulse = .16
                    defeated = monster.health <= 0
                    hits.append((monster, attack["damage"], defeated))
                    if defeated:
                        monster.alive = False
                        if not getattr(monster, "death_handled", False):
                            monster.death_handled = True
                            on_defeat(monster)
        if self.timer >= attack["duration"]:
            self.state, self.combo_window = "idle", 0.38
            queued, self.queued_kind = self.queued_kind, None
            if queued:
                self.start_attack(queued)
        return hits


class EnemyAISystem:
    """Type-aware pursuit, flanking, pack separation and telegraphed attacks."""

    def update(self, dt, player, monsters, island_index, can_move):
        attackers = []
        active = [m for m in monsters if m.alive and m.island_index == island_index]
        for enemy in active:
            enemy.attack_cooldown = max(0.0, enemy.attack_cooldown - dt)
            enemy.decision_timer -= dt
            dx, dy = player.x - enemy.x, player.y - enemy.y
            distance = max(.001, math.hypot(dx, dy))
            nx, ny = dx / distance, dy / distance

            if distance > enemy.awareness:
                enemy.state = "returning" if math.hypot(enemy.x - enemy.home_x,
                                                         enemy.y - enemy.home_y) > 2.0 else "idle"
                target_dx, target_dy = enemy.home_x - enemy.x, enemy.home_y - enemy.y
                target_len = max(.001, math.hypot(target_dx, target_dy))
                move_x, move_y = target_dx / target_len, target_dy / target_len
                speed = enemy.move_speed * .55
            elif distance <= enemy.attack_range and enemy.attack_cooldown <= 0 and enemy.hit_flash <= 0:
                enemy.state = "windup"
                enemy.attack_timer += dt
                if enemy.attack_timer >= enemy.attack_windup:
                    enemy.attack_timer = 0.0
                    enemy.attack_cooldown = .68 if enemy.kind == "thief" else .92
                    enemy.vx, enemy.vy = nx * 5.5, ny * 5.5
                    attackers.append(enemy)
                continue
            else:
                enemy.attack_timer = max(0.0, enemy.attack_timer - dt * 1.8)
                if enemy.decision_timer <= 0:
                    enemy.decision_timer = .45 + (sum(ord(c) for c in enemy.id) % 25) / 100
                    if enemy.kind in ("pirate", "bandit", "thief"):
                        enemy.strafe_sign *= -1

                low_health = enemy.health <= max(1, enemy.max_health * .3)
                if enemy.kind == "thief" and low_health and distance < 5.0:
                    enemy.state, move_x, move_y = "retreat", -nx, -ny
                    speed = enemy.move_speed * 1.2
                elif enemy.kind in ("pirate", "bandit", "thief") and 1.8 < distance < 5.5:
                    enemy.state = "flank"
                    tangent_x, tangent_y = -ny * enemy.strafe_sign, nx * enemy.strafe_sign
                    move_x, move_y = nx * .72 + tangent_x * .68, ny * .72 + tangent_y * .68
                    move_len = max(.001, math.hypot(move_x, move_y))
                    move_x, move_y = move_x / move_len, move_y / move_len
                    speed = enemy.move_speed
                else:
                    enemy.state, move_x, move_y = "chase", nx, ny
                    charging = enemy.kind in ("wolf", "boar") and 2.0 < distance < 6.5
                    speed = enemy.move_speed * (1.38 if charging else 1.0)

            # Prevent a group from collapsing into one unreadable stack.
            repel_x = repel_y = 0.0
            for other in active:
                if other is enemy:
                    continue
                ox, oy = enemy.x - other.x, enemy.y - other.y
                gap = math.hypot(ox, oy)
                if .001 < gap < .85:
                    repel_x += ox / gap * (.85 - gap)
                    repel_y += oy / gap * (.85 - gap)
            move_x += repel_x * 1.8
            move_y += repel_y * 1.8
            move_len = max(1.0, math.hypot(move_x, move_y))
            tx = enemy.x + move_x / move_len * speed * dt
            ty = enemy.y + move_y / move_len * speed * dt
            if enemy.hit_flash <= 0 and can_move(tx, ty):
                enemy.x, enemy.y = tx, ty
                enemy.facing = "right" if move_x >= 0 else "left"
                enemy.walk_phase = (enemy.walk_phase + dt * speed * 5.0) % 2
        return attackers


@dataclass
class SeaShip:
    id: str
    kind: str
    x: float
    y: float
    angle: float
    target_angle: float
    speed: float
    health: int
    max_health: int
    attack_cooldown: float = 0.0
    decision_timer: float = 0.0
    hit_flash: float = 0.0
    alive: bool = True
    aggro_timer: float = 0.0


class NavalEncounterSystem:
    """Deterministic roaming merchant and hostile pirate traffic."""

    def __init__(self, world, seed, is_water, count=18):
        self.rng = random.Random(seed + 73129)
        self.ships = []
        self.cannonballs = []
        ports = list(getattr(world, "ports", ()))
        for index in range(count):
            kind = "merchant" if index % 3 == 0 else "pirate"
            position = self._spawn_position(world, ports, is_water)
            if position is None:
                continue
            angle = self.rng.random() * math.tau
            health = 8 if kind == "merchant" else 11
            self.ships.append(SeaShip(f"sea:{kind}:{index}", kind, position[0], position[1],
                                      angle, angle, 1.15 if kind == "merchant" else 1.5,
                                      health, health, decision_timer=self.rng.uniform(.4, 2.0)))

    def _spawn_position(self, world, ports, is_water):
        for _ in range(240):
            if ports and self.rng.random() < .82:
                port = self.rng.choice(ports)
                angle = self.rng.random() * math.tau
                radius = self.rng.uniform(7.0, 22.0)
                x, y = port.x + .5 + math.cos(angle) * radius, port.y + .5 + math.sin(angle) * radius
            else:
                x = self.rng.uniform(3, len(world.heights[0]) - 3)
                y = self.rng.uniform(3, len(world.heights) - 3)
            if is_water(x, y):
                return x, y
        return None

    def nearby_merchant(self, player, radius=3.0):
        return min((s for s in self.ships if s.alive and s.kind == "merchant"
                    and math.hypot(player.x - s.x, player.y - s.y) <= radius),
                   key=lambda s: math.hypot(player.x - s.x, player.y - s.y), default=None)

    def update(self, dt, player, player_sailing, is_water):
        # Projectiles spawned this tick begin moving on the next tick; otherwise a
        # long frame can create and delete a cannonball before it is ever visible.
        existing_balls = {id(ball) for ball in self.cannonballs}
        for ship in self.ships:
            if not ship.alive:
                continue
            ship.attack_cooldown = max(0.0, ship.attack_cooldown - dt)
            ship.hit_flash = max(0.0, ship.hit_flash - dt)
            ship.decision_timer -= dt
            dx, dy = player.x - ship.x, player.y - ship.y
            distance = math.hypot(dx, dy)
            hunting = ship.kind == "pirate" and player_sailing and distance < 18.0
            if hunting:
                ship.aggro_timer += dt
                ship.target_angle = math.atan2(dy, dx)
                speed = 3.35 if distance > 5.5 else 2.15
                if distance < 9.0 and ship.attack_cooldown <= 0 and ship.aggro_timer + 1e-9 >= .8:
                    length = max(.001, distance)
                    self.cannonballs.append({"x": ship.x, "y": ship.y,
                                             "vx": dx / length * 8.5, "vy": dy / length * 8.5,
                                             "life": 2.2, "owner": ship.id})
                    ship.attack_cooldown = 1.45
            else:
                ship.aggro_timer = 0.0
                speed = ship.speed
                if ship.decision_timer <= 0:
                    ship.target_angle += self.rng.uniform(-1.0, 1.0)
                    ship.decision_timer = self.rng.uniform(1.5, 4.0)
            turn = (ship.target_angle - ship.angle + math.pi) % math.tau - math.pi
            ship.angle += max(-1.3 * dt, min(1.3 * dt, turn))
            tx = ship.x + math.cos(ship.angle) * speed * dt
            ty = ship.y + math.sin(ship.angle) * speed * dt
            if is_water(tx, ty):
                ship.x, ship.y = tx, ty
            else:
                ship.target_angle += math.pi * (.65 + self.rng.random() * .7)
                ship.decision_timer = .2

        hits = 0
        for ball in self.cannonballs:
            if id(ball) not in existing_balls:
                continue
            ball["x"] += ball["vx"] * dt
            ball["y"] += ball["vy"] * dt
            ball["life"] -= dt
            if player_sailing and math.hypot(ball["x"] - player.x, ball["y"] - player.y) < .62:
                ball["life"] = 0
                hits += 1
        self.cannonballs = [ball for ball in self.cannonballs if ball["life"] > 0]
        return hits


@dataclass
class ArenaPoint:
    x: float
    y: float


class ArenaCombatScene:
    """Self-contained encounter state; rendering assets remain external."""
    WIDTH, HEIGHT = 22.0, 12.0

    def __init__(self):
        self.active = False
        self.quest_id = None
        self.island_index = None
        self.player = ArenaPoint(self.WIDTH / 2, self.HEIGHT - 2)
        self.facing = "up"
        self.health = 5
        self.max_health = 5
        self.monsters = []
        self.combat = CombatSystem()
        self.contact_cooldown = 0.0
        self.player_hit_flash = 0.0
        self.player_vx = self.player_vy = 0.0
        self.result = None
        self.defeated = []

    def open(self, quest, seed=0):
        self.active, self.result = True, None
        self.quest_id, self.island_index = quest.id, quest.island_index
        self.player = ArenaPoint(self.WIDTH / 2, self.HEIGHT - 2)
        self.facing, self.health = "up", self.max_health
        self.combat = CombatSystem()
        self.contact_cooldown, self.defeated = 0.0, []
        self.player_hit_flash = 0.0
        self.player_vx = self.player_vy = 0.0
        rng = random.Random(seed + quest.island_index * 7919)
        self.monsters = [Monster(f"arena:{quest.id}:{i}", quest.island_index,
                                 rng.uniform(3, self.WIDTH - 3), rng.uniform(2, self.HEIGHT / 2),
                                 quest.target_kind)
                         for i in range(quest.required)]

    def attack(self, crouch=False):
        if self.active:
            self.combat.start_attack("crouch" if crouch else "normal")

    def _defeated(self, monster):
        self.defeated.append(monster)

    def update(self, dt, move_x=0.0, move_y=0.0):
        if not self.active:
            return self.result
        length = math.hypot(move_x, move_y)
        if length:
            move_x, move_y = move_x / length, move_y / length
            speed = 3.2 if self.combat.attacking and self.combat.attack_kind == "crouch" else 4.8
            self.player.x = min(self.WIDTH - .7, max(.7, self.player.x + move_x * speed * dt))
            self.player.y = min(self.HEIGHT - .7, max(.7, self.player.y + move_y * speed * dt))
            self.facing = ("right" if move_x > 0 else "left") if abs(move_x) > abs(move_y) else ("down" if move_y > 0 else "up")
        self.combat.update(dt, self.player, self.facing, self.monsters, self._defeated)
        self.contact_cooldown = max(0.0, self.contact_cooldown - dt)
        self.player_hit_flash = max(0.0, self.player_hit_flash - dt)
        self.player.x = min(self.WIDTH - .7, max(.7, self.player.x + self.player_vx * dt))
        self.player.y = min(self.HEIGHT - .7, max(.7, self.player.y + self.player_vy * dt))
        self.player_vx *= max(0.0, 1.0 - 9.0 * dt)
        self.player_vy *= max(0.0, 1.0 - 9.0 * dt)
        for monster in self.monsters:
            if not monster.alive:
                continue
            dx, dy = self.player.x - monster.x, self.player.y - monster.y
            distance = max(.001, math.hypot(dx, dy))
            if distance > .82 and monster.hit_flash <= 0:
                monster.attack_timer = max(0.0, monster.attack_timer - dt)
                monster.x += dx / distance * 1.35 * dt
                monster.y += dy / distance * 1.35 * dt
                monster.facing = "right" if dx >= 0 else "left"
                monster.walk_phase = (monster.walk_phase + dt * 6.0) % 2
            elif monster.hit_flash <= 0:
                monster.attack_timer += dt
                if monster.attack_timer >= .45 and self.contact_cooldown <= 0:
                    self.health -= 1
                    self.contact_cooldown = .75
                    self.player_hit_flash = .16
                    self.player_vx, self.player_vy = dx / distance * 4.2, dy / distance * 4.2
                    monster.attack_timer = 0.0
                    monster.x -= dx / distance * .45
                    monster.y -= dy / distance * .45
        if self.health <= 0:
            self.active, self.result = False, "lost"
        elif not any(monster.alive for monster in self.monsters):
            self.active, self.result = False, "won"
        return self.result
