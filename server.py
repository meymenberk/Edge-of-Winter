"""Player relay plus authoritative resource cooldowns, using the shared world seed.

Legacy clients retain the original player-dictionary response. Updated clients
negotiate protocol 2 and receive sparse depleted-resource snapshots and harvest
acknowledgements. The server owns respawn deadlines, including during client pause.
"""
import argparse
import json
import math
import socket
import threading
import time
from types import SimpleNamespace

from modules.worldgen import WORLD_VERSION, SpawnPool, can_stand, make_world, stable_random
from modules.economy import inflation_multiplier
from modules.settings import stable_seed
from modules.gameplay_systems import AnimalSystem
from modules.treant_boss import (BOSS_DAMAGED, ENCOUNTER_COMPLETED, PLAYER_HIT,
                                 BossPlayerState, EncounterResult, PlayerAttack,
                                 TreantBossEncounter, TreantConfig)

HOST = '127.0.0.1'
PORT = 5555
WORLD_SEED = 42


class ResourceAuthority:
    def __init__(self, world, clock=time.monotonic):
        self.nodes = {node.id: node for node in world.nodes}
        self.depleted = {}
        self.clock = clock
        self.seed = world.seed

    def harvest(self, uid, player):
        node = self.nodes.get(uid)
        now = self.clock()
        if (node is None or self.depleted.get(uid, 0) > now or player.get('sailing', False)
                or player.get('boss_active', False)
                or math.hypot(player['x'] - node.x, player['y'] - node.y) >= 1.65):
            return False
        self.depleted[uid] = now + 30 + stable_random(int(node.x * 100), int(node.y * 100), 83) * 10
        return True

    def snapshot(self):
        now = self.clock()
        self.depleted = {uid: deadline for uid, deadline in self.depleted.items() if deadline > now}
        return {uid: round(deadline - now, 3) for uid, deadline in self.depleted.items()}


class GameServer:
    def __init__(self, world):
        self.world = world
        self.resources = ResourceAuthority(world)
        self.players = {}
        self.island_owners = {}
        self.capture_count = 0
        self.winner = None
        self.trades = {}  # trade_id -> dict
        self.next_trade_id = 1
        self.start_time = time.monotonic()
        self.lock = threading.Lock()
        self.spawn_islands = {}
        self.spawn_cursor = 0
        self.spawn_pool = SpawnPool(world)
        self.animal_system = AnimalSystem(world)
        self.world_loot = {}
        self.next_world_loot_id = 1
        self.pickup_events = {}
        self.last_animal_update = time.monotonic()
        self.boss_encounters = {}
        self.boss_last_update = {}
        self.boss_completion_deadlines = {}

    def get_inflation(self):
        # Real elapsed time, shared by every client; slow growth is capped at 35%.
        return inflation_multiplier(time.monotonic() - self.start_time)

    def allocate_spawn(self, player_id):
        occupied = set(self.spawn_islands.values())
        island_idx, spawn = self.spawn_pool.acquire(occupied)
        self.spawn_islands[player_id] = island_idx
        return island_idx, spawn

    def update_animals(self):
        now = time.monotonic()
        dt = min(.1, max(0.0, now - self.last_animal_update))
        self.last_animal_update = now
        self.animal_system.update(dt, SimpleNamespace(x=-9999.0, y=-9999.0),
                                  lambda x, y: can_stand(self.world, x, y, False))

    def animal_snapshot(self):
        return [dict(id=a.id, island_index=a.island_index, kind=a.kind,
                     x=round(a.x, 3), y=round(a.y, 3), health=a.health,
                     max_health=a.max_health, alive=a.alive, facing=a.facing,
                     walk_phase=round(a.walk_phase, 2))
                for a in self.animal_system.animals]

    def loot_snapshot(self):
        return [dict(drop) for drop in self.world_loot.values()]

    def apply_entity_attack(self, player_id, request):
        player = self.players.get(player_id)
        target_id, kind = str(request.get('target_id')), request.get('kind')
        rules = {'normal': (1.85, 1, .18), 'crouch': (2.15, 2, .34),
                 'dash': (3.25, 3, .42), 'bow': (8.5, 2, .32)}
        target = next((a for a in self.animal_system.animals if a.id == target_id), None)
        if (player is None or player.get('boss_active') or target is None or not target.alive or kind not in rules
                or player.get('sailing') or not player.get('spawn_confirmed')):
            return False
        reach, damage, cooldown = rules[kind]
        try:
            weapon_level = max(1, min(4, int(request.get('weapon_level', 1))))
        except (TypeError, ValueError):
            weapon_level = 1
        damage += weapon_level - 1
        if kind == 'bow':
            reach *= 1.0 + .15 * (weapon_level - 1)
            cooldown /= 1.0 + .12 * (weapon_level - 1)
        else:
            reach *= 1.0 + .06 * (weapon_level - 1)
            cooldown /= 1.0 + .08 * (weapon_level - 1)
        dx, dy = target.x - player['x'], target.y - player['y']
        distance = math.hypot(dx, dy)
        if distance > reach:
            return False
        if kind != 'bow':
            fx, fy = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0),
                      'right': (1, 0)}.get(player.get('facing'), (0, 1))
            if distance > .001 and (dx / distance) * fx + (dy / distance) * fy < -.12:
                return False
        now = time.monotonic()
        if now - player.get('last_entity_attack_at', -100.0) < cooldown:
            return False
        player['last_entity_attack_at'] = now
        target.health = max(0, target.health - damage)
        player['combat_xp'] = player.get('combat_xp', 0) + 1
        player['combat_revision'] = player.get('combat_revision', 0) + 1
        if distance > .001:
            force = .58 if kind == 'dash' else .38
            nx, ny = target.x + dx / distance * force, target.y + dy / distance * force
            if self.animal_system.suitable_step(
                    target, nx, target.y, lambda x, y: can_stand(self.world, x, y, False)):
                target.x = nx
            if self.animal_system.suitable_step(
                    target, target.x, ny, lambda x, y: can_stand(self.world, x, y, False)):
                target.y = ny
        self.animal_system.flee(target, player['x'], player['y'])
        if target.health <= 0:
            target.alive = False
            target.death_handled = True
            base = 2 if target.kind == 'cow' else 1
            extra_range = 3 if target.kind == 'cow' else 2
            extra = int(stable_random(int(target.x * 100), int(target.y * 100), self.world.seed + 919)
                        * extra_range)
            drop_id = f"animal-loot:{self.next_world_loot_id}"
            self.next_world_loot_id += 1
            self.world_loot[drop_id] = dict(id=drop_id, x=round(target.x, 3), y=round(target.y, 3),
                                            item='Çiğ Et', count=base + extra)
        return True

    def apply_pickup(self, player_id, request):
        player = self.players.get(player_id)
        drop_id = str(request.get('id'))
        drop = self.world_loot.get(drop_id)
        if (player is None or player.get('boss_active') or drop is None or not player.get('spawn_confirmed')
                or math.hypot(player['x'] - drop['x'], player['y'] - drop['y']) > .95):
            return False
        self.world_loot.pop(drop_id, None)
        self.pickup_events.setdefault(player_id, []).append({
            'id': drop_id, 'item': drop['item'], 'count': drop['count'],
        })
        return True

    def apply_village_rescue(self, player_id, island_index):
        """Validate the existing capture event and derive non-duplicating key state."""
        player = self.players.get(player_id)
        if (player is None or player.get('boss_active') or not isinstance(island_index, int)
                or not 0 <= island_index < len(self.world.islands)):
            return False
        island = self.world.islands[island_index]
        tx, ty = int(player['x']), int(player['y'])
        if island_index in self.island_owners:
            return self.island_owners[island_index] == player_id
        self.island_owners[island_index] = player_id
        self.capture_count += 1
        rescued = player.setdefault('rescued_villages', [])
        key_eligible = (player.get('spawn_confirmed') and not player.get('sailing')
                        and island.village is not None
                        and 0 <= tx < len(self.world.owners[0])
                        and 0 <= ty < len(self.world.owners)
                        and self.world.owners[ty][tx] == island_index)
        if key_eligible and island_index not in rescued and len(rescued) < 3:
            rescued.append(island_index)
            player['ancient_keys'] = min(3, player.get('ancient_keys', 0) + 1)
        owned = sum(1 for owner in self.island_owners.values() if owner == player_id)
        if owned >= 6 and self.winner is None:
            self.winner = player_id
        return True

    def apply_portal_unlock(self, player_id):
        player = self.players.get(player_id)
        if player is None or not player.get('spawn_confirmed') or player.get('sailing'):
            return False
        if player.get('portal_unlocked'):
            return True
        px, py = self.world.boss_portal
        if (player.get('ancient_keys') != 3
                or math.hypot(player['x'] - px, player['y'] - py) > 2.1):
            return False
        player['ancient_keys'] = 0
        player['portal_unlocked'] = True
        return True

    def start_treant_boss(self, player_id):
        """Start one server-owned encounter after validating portal progression."""
        player = self.players.get(player_id)
        if (player is None or player.get('boss_active') or player.get('boss_defeated')
                or not player.get('portal_unlocked') or player.get('sailing')
                or not player.get('spawn_confirmed')):
            return False
        px, py = self.world.boss_portal
        if math.hypot(player['x'] - px, player['y'] - py) > 2.1:
            return False
        encounter = TreantBossEncounter(config=TreantConfig(auto_start=True))
        snapshot = BossPlayerState(
            str(player_id), player['x'], player['y'], health=player.get('health', 8),
            max_health=player.get('max_health', 8),
        )
        spawn = encounter.start(snapshot)
        self.boss_encounters[player_id] = encounter
        self.boss_last_update[player_id] = time.monotonic()
        self.boss_completion_deadlines.pop(player_id, None)
        player.update(x=spawn[0], y=spawn[1], sailing=False, moving=False,
                      boss_active=True, boss_result=EncounterResult.IN_PROGRESS.value,
                      boss_return=tuple(self.world.boss_return))
        return True

    @staticmethod
    def _boss_attack_profile(kind, combo=1, level=1):
        combo = max(1, min(3, int(combo)))
        level = max(1, min(4, int(level)))
        if kind == 'normal':
            base = ((1.45, 1.15, 1), (1.55, 1.25, 1), (1.85, 1.55, 3))[combo - 1]
        elif kind == 'crouch':
            base = (1.30, 1.85, 2)
        elif kind == 'dash':
            base = (2.45, 2.15, 3)
        else:
            return None
        range_multiplier = (1.0, 1.06, 1.12, 1.20)[level - 1]
        return (base[0] * range_multiplier, base[1] * range_multiplier,
                base[2] + level - 1, kind)

    def apply_treant_boss_attack(self, player_id, request):
        """Derive hitbox and damage server-side; client damage/hitboxes are ignored."""
        player = self.players.get(player_id)
        encounter = self.boss_encounters.get(player_id)
        kind = request.get('kind')
        if (player is None or encounter is None or not player.get('boss_active')
                or kind not in ('normal', 'crouch', 'dash')
                or encounter.get_result() != EncounterResult.IN_PROGRESS):
            return False
        now = time.monotonic()
        cooldown = {'normal': .16, 'crouch': .34, 'dash': 3.0}[kind]
        if now - player.get('last_boss_attack_at', -100.0) < cooldown:
            return False
        combo = (min(3, player.get('boss_combo_step', 0) + 1)
                 if kind == 'normal' and now - player.get('last_boss_attack_at', -100.0) <= .65
                 else 1)
        # Weapon upgrades are not yet server-owned. Stay at the trusted baseline
        # online instead of accepting a client-claimed level or arbitrary damage.
        profile = self._boss_attack_profile(kind, combo, player.get('sword_level', 1))
        reach, width, damage, kind = profile
        facing = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
        dx, dy = facing.get(player.get('facing'), (0, 1))
        cx, cy = player['x'] + dx * reach * .65, player['y'] + dy * reach * .65
        if dx:
            x, y, hit_w, hit_h = cx - reach / 2, cy - width / 2, reach, width
        else:
            x, y, hit_w, hit_h = cx - width / 2, cy - reach / 2, width, reach
        supplied_id = str(request.get('attack_id', request.get('seq', 0)))[:80]
        attack_id = f"net:{player_id}:{supplied_id}"
        accepted = encounter.register_player_attack(
            PlayerAttack(attack_id, str(player_id), x, y, hit_w, hit_h, damage)
        )
        if accepted:
            player['last_boss_attack_at'] = now
            player['boss_combo_step'] = combo if kind == 'normal' else 0
        return accepted

    def retreat_treant_boss(self, player_id):
        player = self.players.get(player_id)
        encounter = self.boss_encounters.get(player_id)
        if player is None or encounter is None or not player.get('boss_active'):
            return False
        encounter.forfeit()
        return True

    def update_treant_boss(self, player_id):
        player = self.players.get(player_id)
        encounter = self.boss_encounters.get(player_id)
        if player is None or encounter is None or not player.get('boss_active'):
            return
        now = time.monotonic()
        dt = min(.05, max(0.0, now - self.boss_last_update.get(player_id, now)))
        self.boss_last_update[player_id] = now
        invulnerable = now < player.get('invulnerable_until', 0.0)
        facing = {'up': (0.0, -1.0), 'down': (0.0, 1.0),
                  'left': (-1.0, 0.0), 'right': (1.0, 0.0)}
        snapshot = BossPlayerState(
            str(player_id), player['x'], player['y'], health=player.get('health', 8),
            max_health=player.get('max_health', 8),
            facing=facing.get(player.get('facing'), (0.0, 1.0)),
            invulnerable=invulnerable,
        )
        encounter.update(dt, snapshot)
        for event in encounter.consume_events():
            if (event.type == PLAYER_HIT and event.data.get('player_id') == str(player_id)
                    and now >= player.get('invulnerable_until', 0.0)):
                player['health'] = max(0, player.get('health', 8) - event.data.get('damage', 0))
                player['invulnerable_until'] = now + float(event.data.get('invulnerability', .7))
                player['damage_revision'] = player.get('damage_revision', 0) + 1
                player['combat_revision'] = player.get('combat_revision', 0) + 1
                knock_x, knock_y = event.data.get('knockback', (0.0, 0.0))
                nx, ny = encounter.constrain_motion(
                    (player['x'], player['y']),
                    (player['x'] + float(knock_x) * .08, player['y'] + float(knock_y) * .08),
                )
                player['x'], player['y'] = nx, ny
            elif event.type == BOSS_DAMAGED:
                player['combat_xp'] = player.get('combat_xp', 0) + max(
                    1, round(event.data.get('damage', 1))
                )
                player['combat_revision'] = player.get('combat_revision', 0) + 1
            elif event.type == ENCOUNTER_COMPLETED:
                result = EncounterResult(event.data['result'])
                player['boss_result'] = result.value
                if result == EncounterResult.VICTORY:
                    player['boss_defeated'] = True
                self.boss_completion_deadlines[player_id] = now + (
                    1.8 if result == EncounterResult.VICTORY else 1.0
                )
        deadline = self.boss_completion_deadlines.get(player_id)
        if deadline is not None and now >= deadline:
            victory = player.get('boss_result') == EncounterResult.VICTORY.value
            return_position = tuple(player.get('boss_return') or self.world.boss_return)
            player.update(x=return_position[0], y=return_position[1], boss_active=False,
                          moving=False, health=max(1, player.get('health', 0)) if victory
                          else player.get('max_health', 8),
                          invulnerable_until=now + .7)

    def treant_state(self, player_id):
        player = self.players[player_id]
        encounter = self.boss_encounters.get(player_id)
        return dict(
            rescued_villages=list(player.get('rescued_villages', [])),
            ancient_keys=player.get('ancient_keys', 0),
            portal_unlocked=player.get('portal_unlocked', False),
            boss_defeated=player.get('boss_defeated', False),
            boss_active=player.get('boss_active', False),
            boss_result=player.get('boss_result', EncounterResult.IN_PROGRESS.value),
            boss=(encounter.get_state_snapshot() if encounter is not None else None),
            player_position=[player.get('x', 0), player.get('y', 0)],
            health=player.get('health', 8),
            max_health=player.get('max_health', 8),
        )

    def respawn_combat_player(self, player_id, player):
        self.spawn_islands.pop(player_id, None)
        new_island, new_spawn = self.allocate_spawn(player_id)
        player.update(x=new_spawn[0], y=new_spawn[1], sailing=False, sail_raised=True,
                      health=player.get('max_health', 8), spawn_confirmed=False,
                      spawn_revision=player.get('spawn_revision', 0) + 1,
                      combat_revision=player.get('combat_revision', 0) + 1,
                      invulnerable_until=time.monotonic() + 1.0)

    def apply_pvp_attack(self, attacker_id, request):
        attacker = self.players.get(attacker_id)
        try:
            target_id = int(request.get('target_id'))
        except (TypeError, ValueError):
            return False
        target = self.players.get(target_id)
        kind = request.get('kind')
        rules = {
            'normal': (1.85, 1, .18),
            'crouch': (2.15, 2, .34),
            'dash': (3.25, 3, .42),
            'bow': (8.5, 2, .32),
        }
        if (attacker is None or target is None or target_id == attacker_id or kind not in rules
                or attacker.get('boss_active') or target.get('boss_active')
                or not attacker.get('spawn_confirmed') or not target.get('spawn_confirmed')):
            return False
        reach, damage, cooldown = rules[kind]
        try:
            weapon_level = max(1, min(4, int(request.get('weapon_level', 1))))
        except (TypeError, ValueError):
            weapon_level = 1
        damage += weapon_level - 1
        if kind == 'bow':
            reach *= 1.0 + .15 * (weapon_level - 1)
            cooldown /= 1.0 + .12 * (weapon_level - 1)
        else:
            reach *= 1.0 + .06 * (weapon_level - 1)
            cooldown /= 1.0 + .08 * (weapon_level - 1)
        # A sailor cannot perform a grounded sword attack.  The target's last
        # relayed sail flag is not an invulnerability toggle: a boat beside a
        # dock can still be struck, and stale movement packets cannot cancel a hit.
        if kind != 'bow' and attacker.get('sailing'):
            return False
        if kind == 'bow' and bool(attacker.get('sailing')) != bool(target.get('sailing')):
            return False
        if math.hypot(attacker['x'] - target['x'], attacker['y'] - target['y']) > reach:
            return False
        if kind != 'bow':
            facing = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
            fx, fy = facing.get(attacker.get('facing'), (0, 1))
            dx, dy = target['x'] - attacker['x'], target['y'] - attacker['y']
            distance = max(.001, math.hypot(dx, dy))
            if (dx / distance) * fx + (dy / distance) * fy < -.12:
                return False
        now = time.monotonic()
        if now - attacker.get('last_attack_at', -100.0) < cooldown:
            return False
        if now < target.get('invulnerable_until', 0.0):
            return False
        attacker['last_attack_at'] = now
        target['health'] = max(0, target.get('health', 8) - damage)
        target['last_hit_by'] = attacker_id
        target['combat_revision'] = target.get('combat_revision', 0) + 1
        target['damage_revision'] = target.get('damage_revision', 0) + 1
        attacker['combat_xp'] = attacker.get('combat_xp', 0) + (2 if kind == 'bow' else max(1, damage))
        attacker['combat_revision'] = attacker.get('combat_revision', 0) + 1
        if kind != 'bow':
            dx, dy = target['x'] - attacker['x'], target['y'] - attacker['y']
            distance = max(.001, math.hypot(dx, dy))
            force = .52 if kind == 'dash' else .34
            nx, ny = target['x'] + dx / distance * force, target['y'] + dy / distance * force
            if can_stand(self.world, nx, target['y'], False):
                target['x'] = nx
            if can_stand(self.world, target['x'], ny, False):
                target['y'] = ny
        if target['health'] <= 0:
            attacker['kills'] = attacker.get('kills', 0) + 1
            target['deaths'] = target.get('deaths', 0) + 1
            self.respawn_combat_player(target_id, target)
        else:
            target['invulnerable_until'] = now + .42
        return True

    def handle_client(self, conn, addr, player_id):
        with self.lock:
            spawn_island, spawn = self.allocate_spawn(player_id)
            self.players[player_id] = dict(x=spawn[0], y=spawn[1], facing='down', moving=False,
                                           sailing=False, sail_raised=True, spawn_confirmed=False,
                                           spawn_revision=0, health=8, max_health=8,
                                           combat_revision=0, kills=0, deaths=0,
                                           combat_xp=0,
                                           damage_revision=0,
                                           last_hit_by=None, last_attack_at=-100.0,
                                           invulnerable_until=0.0, attack_kind=None,
                                           attack_timer=0.0, combo_step=0,
                                           last_entity_attack_at=-100.0,
                                           rescued_villages=[], ancient_keys=0,
                                           portal_unlocked=False, boss_defeated=False,
                                           boss_active=False,
                                           boss_result=EncounterResult.IN_PROGRESS.value,
                                           last_boss_attack_at=-100.0,
                                           boss_combo_step=0, sword_level=1)
        last_sequence = 0
        last_combat_sequence = 0
        last_entity_sequence = 0
        last_progress_sequence = 0
        last_animal_snapshot_at = 0.0
        try:
            with self.lock:
                hello = dict(id=player_id, seed=self.world.seed, world_version=WORLD_VERSION, resources=True,
                             pvp=True, animal_authority=True, treant_progress=True,
                             treant_boss_authority=True,
                             islands={str(k): v for k, v in self.island_owners.items()}, winner=self.winner,
                             inflation=self.get_inflation(), capture_count=self.capture_count,
                             spawn=list(spawn), spawn_island=spawn_island,
                             health=8, max_health=8, combat_revision=0, combat_xp=0,
                            kills=0, deaths=0,
                             treant=self.treant_state(player_id),
                             animals=self.animal_snapshot(), world_loot=self.loot_snapshot())
            conn.sendall((json.dumps(hello) + '\n').encode())
            buffer = b''
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                buffer += data
                if len(buffer) > 2_000_000:
                    break
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if not line:
                        continue
                    update = json.loads(line)
                    modern = update.get('protocol') == 2
                    if modern and update.get('world_version') != WORLD_VERSION:
                        return
                    with self.lock:
                        self.update_animals()
                        player = self.players[player_id]
                        was_spawn_confirmed = player.get('spawn_confirmed', False)
                        if update.get('respawn') and player.get('spawn_confirmed'):
                            self.respawn_combat_player(player_id, player)
                        sent_x, sent_y = update.get('x'), update.get('y')
                        spawn_confirmed = (bool(update.get('spawn_confirmed'))
                                           and isinstance(sent_x, (int, float))
                                           and isinstance(sent_y, (int, float))
                                           and math.hypot(sent_x - player['x'], sent_y - player['y']) < 0.5)
                        if spawn_confirmed:
                            player['spawn_confirmed'] = True
                        for key in ('x', 'y', 'boat_angle', 'sail_angle'):
                            value = update.get(key, player.get(key, 0))
                            if isinstance(value, (int, float)) and math.isfinite(value):
                                if (key in ('x', 'y') and player.get('boss_active')):
                                    continue
                                if key not in ('x', 'y') or player.get('spawn_confirmed'):
                                    player[key] = value
                        if (player.get('boss_active')
                                and isinstance(sent_x, (int, float)) and math.isfinite(sent_x)
                                and isinstance(sent_y, (int, float)) and math.isfinite(sent_y)):
                            encounter = self.boss_encounters.get(player_id)
                            if encounter is not None:
                                dx, dy = sent_x - player['x'], sent_y - player['y']
                                distance = math.hypot(dx, dy)
                                if distance > .65:
                                    dx, dy = dx / distance * .65, dy / distance * .65
                                player['x'], player['y'] = encounter.constrain_motion(
                                    (player['x'], player['y']),
                                    (player['x'] + dx, player['y'] + dy),
                                )
                        facing = update.get('facing')
                        if facing in ('up', 'down', 'left', 'right'):
                            player['facing'] = facing
                        for key in ('moving', 'sailing', 'sail_raised'):
                            if isinstance(update.get(key), bool):
                                player[key] = update[key]
                        attack_kind = update.get('attack_kind')
                        player['attack_kind'] = attack_kind if attack_kind in ('normal', 'crouch', 'dash') else None
                        attack_timer = update.get('attack_timer', 0.0)
                        player['attack_timer'] = (max(0.0, min(1.0, attack_timer))
                                                  if isinstance(attack_timer, (int, float)) else 0.0)
                        combo_step = update.get('combo_step', 0)
                        player['combo_step'] = max(0, min(3, combo_step)) if isinstance(combo_step, int) else 0
                        if modern:
                            for request in update.get('harvests', []):
                                seq = request.get('seq', 0)
                                if isinstance(seq, int) and seq > last_sequence and was_spawn_confirmed:
                                    self.resources.harvest(request.get('id'), player)
                                    last_sequence = seq
                            for request in update.get('captures', []):
                                seq = request.get('seq', 0)
                                island_idx = request.get('island_index')
                                if isinstance(seq, int) and seq > last_sequence and isinstance(island_idx, int):
                                    self.apply_village_rescue(player_id, island_idx)
                                    last_sequence = seq
                            for request in update.get('treant_actions', []):
                                if not isinstance(request, dict):
                                    continue
                                seq = request.get('seq', 0)
                                if isinstance(seq, int) and seq > last_progress_sequence:
                                    action = request.get('action')
                                    if action == 'unlock_portal':
                                        self.apply_portal_unlock(player_id)
                                    elif action == 'enter_boss':
                                        self.start_treant_boss(player_id)
                                    elif action == 'boss_attack':
                                        self.apply_treant_boss_attack(player_id, request)
                                    elif action == 'retreat_boss':
                                        self.retreat_treant_boss(player_id)
                                    last_progress_sequence = seq
                            for request in update.get('pvp_attacks', []):
                                if not isinstance(request, dict):
                                    continue
                                seq = request.get('seq', 0)
                                if isinstance(seq, int) and seq > last_combat_sequence:
                                    self.apply_pvp_attack(player_id, request)
                                    last_combat_sequence = seq
                            entity_actions = [(req.get('seq', 0), 'attack', req)
                                              for req in update.get('entity_attacks', []) if isinstance(req, dict)]
                            entity_actions += [(req.get('seq', 0), 'pickup', req)
                                               for req in update.get('pickups', []) if isinstance(req, dict)]
                            for seq, action, request in sorted(entity_actions, key=lambda entry: entry[0]):
                                if not isinstance(seq, int) or seq <= last_entity_sequence:
                                    continue
                                if action == 'attack':
                                    self.apply_entity_attack(player_id, request)
                                else:
                                    self.apply_pickup(player_id, request)
                                last_entity_sequence = seq
                            # Trade requests
                            for treq in update.get('trade_actions', []):
                                action = treq.get('action')
                                if action == 'create':
                                    tid = str(self.next_trade_id)
                                    self.next_trade_id += 1
                                    self.trades[tid] = {
                                        'id': tid,
                                        'from_pid': player_id,
                                        'to_pid': treq.get('to_pid'),
                                        'offer': treq.get('offer', {}),
                                        'request': treq.get('request', {}),
                                        'status': 'pending',
                                        'time': time.time(),
                                    }
                                elif action == 'accept':
                                    tid = str(treq.get('trade_id'))
                                    trade = self.trades.get(tid)
                                    if trade and trade.get('status') == 'pending':
                                        trade['status'] = 'accepted'
                                elif action == 'cancel':
                                    tid = str(treq.get('trade_id'))
                                    trade = self.trades.get(tid)
                                    if trade and trade.get('status') == 'pending':
                                        trade['status'] = 'cancelled'

                        self.update_treant_boss(player_id)

                        # Prune old trades
                        now_t = time.time()
                        self.trades = {tid: t for tid, t in self.trades.items() if now_t - t.get('time', 0) < 180}

                        others = {pid: dict(p) for pid, p in self.players.items() if pid != player_id}
                        response = (dict(players=others, resources=self.resources.snapshot(), ack=last_sequence,
                                         combat_ack=last_combat_sequence,
                                         entity_ack=last_entity_sequence,
                                         progress_ack=last_progress_sequence,
                                         world_loot=self.loot_snapshot(),
                                         pickup_events=self.pickup_events.pop(player_id, []),
                                         islands={str(k): v for k, v in self.island_owners.items()}, winner=self.winner,
                                         inflation=self.get_inflation(), capture_count=self.capture_count,
                                         spawn=list((player['x'], player['y'])) if not player.get('spawn_confirmed') else None,
                                         spawn_island=self.spawn_islands.get(player_id),
                                         spawn_revision=player.get('spawn_revision', 0),
                                         spawn_confirmed=player.get('spawn_confirmed', False),
                                         health=player.get('health', 8), max_health=player.get('max_health', 8),
                                         combat_revision=player.get('combat_revision', 0),
                                         combat_xp=player.get('combat_xp', 0),
                                         authoritative_position=[player.get('x', 0), player.get('y', 0)],
                                         kills=player.get('kills', 0), deaths=player.get('deaths', 0),
                                         last_hit_by=player.get('last_hit_by'),
                                         treant=self.treant_state(player_id),
                                         trades=[t for t in self.trades.values() if t.get('to_pid') == player_id or t.get('from_pid') == player_id or t.get('to_pid') is None])
                                    if modern else others)
                        if modern and time.monotonic() - last_animal_snapshot_at >= .20:
                            response['animals'] = self.animal_snapshot()
                            last_animal_snapshot_at = time.monotonic()
                    conn.sendall((json.dumps(response) + '\n').encode())
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        finally:
            with self.lock:
                self.players.pop(player_id, None)
                self.spawn_islands.pop(player_id, None)
                self.boss_encounters.pop(player_id, None)
                self.boss_last_update.pop(player_id, None)
                self.boss_completion_deadlines.pop(player_id, None)
                # Cancel pending trades by this player
                for t in self.trades.values():
                    if t.get('from_pid') == player_id and t.get('status') == 'pending':
                        t['status'] = 'cancelled'
            conn.close()


def serve(host=HOST, port=PORT, seed=WORLD_SEED):
    print(f'[SERVER] Generating shared world {seed}...', flush=True)
    game = GameServer(make_world(seed))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(8)
        print(f'[SERVER] Ready on {host}:{port}', flush=True)
        player_id = 0
        while True:
            conn, addr = listener.accept()
            threading.Thread(target=game.handle_client, args=(conn, addr, player_id), daemon=True).start()
            player_id += 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='EDGE OF WINTER multiplayer server')
    parser.add_argument('--host', default=HOST,
                        help='address to listen on (use 0.0.0.0 for LAN play; default %(default)s)')
    parser.add_argument('--port', type=int, default=PORT, help='TCP port (default %(default)s)')
    parser.add_argument('--seed', default=str(WORLD_SEED),
                        help='world seed, a number or any text (default %(default)s)')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        args.seed = stable_seed(args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    return args


if __name__ == '__main__':
    options = parse_args()
    try:
        serve(options.host, options.port, options.seed)
    except KeyboardInterrupt:
        print('\n[SERVER] Stopped.', flush=True)
