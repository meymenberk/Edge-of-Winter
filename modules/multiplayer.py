"""Nonblocking newline-JSON client; v2 adds authoritative resource snapshots.

Partial writes/reads are retained. Harvest requests are retried until acknowledged,
so a busy socket or coalesced movement packets cannot lose a chopped tree.
"""
import json
import socket
import threading
from .worldgen import WORLD_VERSION


class NetworkClient:
    def __init__(self, host='127.0.0.1', port=5555, offline_seed=42):
        self.host, self.port = host, int(port)
        self.offline_seed = int(offline_seed)
        self.client = None
        self.connected = False
        self.id, self.seed = None, self.offline_seed
        self.expected_seed = None
        self.other_players = {}
        self.buffer = b''
        self.outgoing = b''
        self.status, self.error_msg = 'DISCONNECTED', ''
        self.lock = threading.RLock()
        self.resource_sync = False
        self.resource_states = {}
        self.resource_revision = 0
        self.pending_harvests = {}
        self.pending_captures = {}
        self.island_owners = {}
        self.winner = None
        self.inflation = 1.0
        self.capture_count = 0
        self.spawn = None
        self.spawn_island = None
        self.spawn_confirmed = False
        self.spawn_revision = 0
        self.pending_respawn = False
        self.trades = []
        self.pending_trade_actions = []
        self.next_sequence = 1
        self.pending_pvp_attacks = {}
        self.next_combat_sequence = 1
        self.health = 8
        self.max_health = 8
        self.combat_revision = 0
        self.combat_xp = 0
        self.authoritative_position = None
        self.kills = 0
        self.deaths = 0
        self.last_hit_by = None
        self.pvp_supported = False
        self.animal_authority = False
        self.animals = {}
        self.world_loot = {}
        self.pickup_events = []
        self.pending_entity_attacks = {}
        self.pending_pickups = {}
        self.next_entity_sequence = 1
        self.treant_progress_supported = False
        self.treant_boss_authority = False
        self.treant_progress = {}
        self.pending_treant_actions = {}
        self.next_progress_sequence = 1

    def try_connect(self, timeout=0.8):
        sock = None
        try:
            self.status = 'CONNECTING'
            sock = socket.create_connection((self.host, self.port), timeout)
            buffer = b''
            while b'\n' not in buffer:
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError('Server closed before handshake')
                buffer += data
            line, buffer = buffer.split(b'\n', 1)
            hello = json.loads(line)
            if self.expected_seed is not None and hello.get('seed', 42) != self.expected_seed:
                raise ValueError('Server seed differs from the loaded world; restart the game to join it')
            version = hello.get('world_version')
            if version is not None and version != WORLD_VERSION:
                raise ValueError(f'World version mismatch: client {WORLD_VERSION}, server {version}')
            with self.lock:
                if self.client:
                    self.client.close()
                self.client = sock
                self.id, self.seed = hello.get('id', 0), hello.get('seed', 42)
                self.resource_sync = hello.get('resources', False)
                self.connected, self.status = True, 'CONNECTED'
                self.buffer, self.outgoing = buffer, b''
                self.pending_harvests.clear()
                self.pending_captures.clear()
                self.pending_trade_actions.clear()
                self.pending_pvp_attacks.clear()
                self.pending_entity_attacks.clear()
                self.pending_pickups.clear()
                self.next_sequence = 1
                self.next_combat_sequence = 1
                self.next_entity_sequence = 1
                self.pending_treant_actions.clear()
                self.next_progress_sequence = 1
                self.resource_states = {}
                self.resource_revision = 0
                self.island_owners = {int(k): v for k, v in hello.get('islands', {}).items()}
                self.winner = hello.get('winner')
                self.inflation = hello.get('inflation', 1.0)
                self.capture_count = hello.get('capture_count', 0)
                raw_spawn = hello.get('spawn')
                self.spawn = tuple(raw_spawn) if isinstance(raw_spawn, list) and len(raw_spawn) == 2 else None
                self.spawn_island = hello.get('spawn_island')
                self.spawn_confirmed = False
                self.spawn_revision = hello.get('spawn_revision', 0)
                self.pending_respawn = False
                self.trades = []
                self.health = hello.get('health', 8)
                self.max_health = hello.get('max_health', 8)
                self.combat_revision = hello.get('combat_revision', 0)
                self.combat_xp = hello.get('combat_xp', 0)
                self.authoritative_position = None
                self.kills = hello.get('kills', 0)
                self.deaths = hello.get('deaths', 0)
                self.last_hit_by = None
                self.pvp_supported = bool(hello.get('pvp', False))
                self.animal_authority = bool(hello.get('animal_authority', False))
                self.animals = {a['id']: a for a in hello.get('animals', []) if isinstance(a, dict) and 'id' in a}
                self.world_loot = {d['id']: d for d in hello.get('world_loot', []) if isinstance(d, dict) and 'id' in d}
                self.pickup_events = []
                self.treant_progress_supported = bool(hello.get('treant_progress', False))
                self.treant_boss_authority = bool(hello.get('treant_boss_authority', False))
                self.treant_progress = dict(hello.get('treant', {}))
                sock.setblocking(False)
            print(f'[NET] Connected: player {self.id}, seed {self.seed}, resource sync={self.resource_sync}')
            return True
        except Exception as exc:
            if sock:
                sock.close()
            self.disconnect()
            self.error_msg = str(exc)
            self.id, self.seed = 0, self.offline_seed
            print(f'[NET] Offline: {exc}')
            return False

    def harvest(self, node_id):
        with self.lock:
            if node_id not in self.pending_harvests:
                self.pending_harvests[node_id] = self.next_sequence
                self.next_sequence += 1

    def capture_island(self, island_idx):
        with self.lock:
            if island_idx not in self.pending_captures:
                self.pending_captures[island_idx] = self.next_sequence
                self.next_sequence += 1

    def request_respawn(self):
        with self.lock:
            self.pending_respawn = True

    def unlock_treant_portal(self):
        if not self.treant_progress_supported:
            return False
        return self._queue_treant_action('unlock_portal')

    def _queue_treant_action(self, action, **data):
        if not self.treant_progress_supported:
            return False
        with self.lock:
            sequence = self.next_progress_sequence
            self.next_progress_sequence += 1
            request = {'seq': sequence, 'action': action}
            request.update(data)
            self.pending_treant_actions[sequence] = request
        return True

    def enter_treant_boss(self):
        if not self.treant_boss_authority:
            return False
        return self._queue_treant_action('enter_boss')

    def attack_treant_boss(self, attack_id, kind, combo_step=1, weapon_level=1):
        if not self.treant_boss_authority or kind not in ('normal', 'crouch', 'dash'):
            return False
        return self._queue_treant_action(
            'boss_attack', attack_id=str(attack_id), kind=kind,
            combo_step=max(1, min(3, int(combo_step))),
            weapon_level=max(1, min(4, int(weapon_level))),
        )

    def retreat_treant_boss(self):
        if not self.treant_boss_authority:
            return False
        return self._queue_treant_action('retreat_boss')

    def propose_trade(self, to_pid, offer, request):
        with self.lock:
            self.pending_trade_actions.append({
                'action': 'create',
                'to_pid': to_pid,
                'offer': offer,
                'request': request,
            })

    def accept_trade(self, trade_id):
        with self.lock:
            self.pending_trade_actions.append({
                'action': 'accept',
                'trade_id': trade_id,
            })

    def cancel_trade(self, trade_id):
        with self.lock:
            self.pending_trade_actions.append({
                'action': 'cancel',
                'trade_id': trade_id,
            })

    def pvp_attack(self, target_id, kind, weapon_level=1):
        if not self.pvp_supported or kind not in ('normal', 'crouch', 'dash', 'bow'):
            return False
        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            return False
        with self.lock:
            sequence = self.next_combat_sequence
            self.next_combat_sequence += 1
            self.pending_pvp_attacks[sequence] = {
                'seq': sequence, 'target_id': target_id, 'kind': kind,
                'weapon_level': max(1, min(4, int(weapon_level))),
            }
        return True

    def entity_attack(self, target_id, kind, weapon_level=1):
        if not self.animal_authority or kind not in ('normal', 'crouch', 'dash', 'bow'):
            return False
        with self.lock:
            sequence = self.next_entity_sequence
            self.next_entity_sequence += 1
            self.pending_entity_attacks[sequence] = {
                'seq': sequence, 'target_id': str(target_id), 'kind': kind,
                'weapon_level': max(1, min(4, int(weapon_level))),
            }
        return True

    def pickup(self, drop_id):
        if not self.animal_authority:
            return False
        with self.lock:
            if drop_id in self.pending_pickups:
                return False
            sequence = self.next_entity_sequence
            self.next_entity_sequence += 1
            self.pending_pickups[str(drop_id)] = sequence
        return True

    def send_and_receive(self, x, y, facing, moving, sailing, boat_angle=0.0,
                         sail_angle=0.0, sail_raised=True, attack_kind=None,
                         attack_timer=0.0, combo_step=0):
        with self.lock:
            if not self.connected or not self.client:
                return
            if not self.spawn_confirmed and self.spawn:
                x, y = self.spawn
                moving, sailing = False, False
            payload = dict(x=x, y=y, facing=facing, moving=moving, sailing=sailing,
                           boat_angle=boat_angle, sail_angle=sail_angle, sail_raised=bool(sail_raised),
                           attack_kind=attack_kind, attack_timer=attack_timer,
                           combo_step=combo_step,
                           spawn_confirmed=True,
                           respawn=self.pending_respawn)
            if self.resource_sync:
                actions = list(self.pending_trade_actions)
                self.pending_trade_actions.clear()
                payload.update(protocol=2, world_version=WORLD_VERSION,
                               harvests=([{'id': uid, 'seq': seq} for uid, seq in self.pending_harvests.items()]
                                         if self.spawn_confirmed else []),
                               captures=([{'island_index': idx, 'seq': seq} for idx, seq in self.pending_captures.items()]
                                         if self.spawn_confirmed else []),
                               pvp_attacks=(list(self.pending_pvp_attacks.values())
                                            if self.spawn_confirmed else []),
                               entity_attacks=(list(self.pending_entity_attacks.values())
                                               if self.spawn_confirmed else []),
                               pickups=([{'id': uid, 'seq': seq} for uid, seq in self.pending_pickups.items()]
                                        if self.spawn_confirmed else []),
                               treant_actions=(list(self.pending_treant_actions.values())
                                                if self.spawn_confirmed else []),
                               trade_actions=actions)
            # Finish a partial packet before scheduling the next position snapshot.
            if not self.outgoing:
                self.outgoing = (json.dumps(payload) + '\n').encode('utf-8')
            try:
                sent = self.client.send(self.outgoing)
                self.outgoing = self.outgoing[sent:]
            except BlockingIOError:
                pass
            except OSError:
                self.disconnect()
                return
            urgent_reply = (not self.outgoing and
                            bool(self.pending_pvp_attacks or self.pending_entity_attacks
                                 or self.pending_pickups))
            if urgent_reply and hasattr(self.client, 'settimeout'):
                self.client.settimeout(.012)
            try:
                while True:
                    data = self.client.recv(65536)
                    if not data:
                        self.disconnect()
                        return
                    self.buffer += data
                    while b'\n' in self.buffer:
                        line, self.buffer = self.buffer.split(b'\n', 1)
                        if not line:
                            continue
                        response = json.loads(line)
                        if self.resource_sync and 'players' in response:
                            self.other_players = response['players']
                            ack = response.get('ack', 0)
                            self.pending_harvests = {uid: seq for uid, seq in self.pending_harvests.items() if seq > ack}
                            self.pending_captures = {idx: seq for idx, seq in self.pending_captures.items() if seq > ack}
                            combat_ack = response.get('combat_ack', 0)
                            self.pending_pvp_attacks = {
                                seq: attack for seq, attack in self.pending_pvp_attacks.items()
                                if seq > combat_ack
                            }
                            entity_ack = response.get('entity_ack', 0)
                            self.pending_entity_attacks = {
                                seq: attack for seq, attack in self.pending_entity_attacks.items()
                                if seq > entity_ack
                            }
                            self.pending_pickups = {
                                uid: seq for uid, seq in self.pending_pickups.items() if seq > entity_ack
                            }
                            progress_ack = response.get('progress_ack', 0)
                            self.pending_treant_actions = {
                                seq: action for seq, action in self.pending_treant_actions.items()
                                if seq > progress_ack
                            }
                            if 'treant' in response:
                                self.treant_progress = dict(response.get('treant', {}))
                            if 'animals' in response:
                                self.animals = {a['id']: a for a in response.get('animals', [])
                                                if isinstance(a, dict) and 'id' in a}
                            if 'world_loot' in response:
                                self.world_loot = {d['id']: d for d in response.get('world_loot', [])
                                                   if isinstance(d, dict) and 'id' in d}
                            self.pickup_events.extend(response.get('pickup_events', []))
                            self.resource_states = response.get('resources', {})
                            self.resource_revision += 1
                            if 'islands' in response:
                                self.island_owners = {int(k): v for k, v in response['islands'].items()}
                            if 'winner' in response:
                                self.winner = response.get('winner')
                            if 'inflation' in response:
                                self.inflation = response.get('inflation', 1.0)
                            if 'capture_count' in response:
                                self.capture_count = response.get('capture_count', 0)
                            if 'spawn_revision' in response and response['spawn_revision'] > self.spawn_revision:
                                raw_spawn = response.get('spawn')
                                if isinstance(raw_spawn, list) and len(raw_spawn) == 2:
                                    self.spawn = tuple(raw_spawn)
                                    self.spawn_island = response.get('spawn_island')
                                    self.spawn_revision = response['spawn_revision']
                                    self.spawn_confirmed = False
                                    self.pending_respawn = False
                            if response.get('spawn_confirmed'):
                                self.spawn_confirmed = True
                            if 'trades' in response:
                                self.trades = response.get('trades', [])
                            if 'health' in response:
                                self.health = response.get('health', self.health)
                                self.max_health = response.get('max_health', self.max_health)
                                self.combat_revision = response.get('combat_revision', self.combat_revision)
                                self.combat_xp = response.get('combat_xp', self.combat_xp)
                                raw_position = response.get('authoritative_position')
                                if isinstance(raw_position, list) and len(raw_position) == 2:
                                    self.authoritative_position = tuple(raw_position)
                                self.kills = response.get('kills', self.kills)
                                self.deaths = response.get('deaths', self.deaths)
                                self.last_hit_by = response.get('last_hit_by')
                        else:
                            self.other_players = response
                    if len(self.buffer) > 2_000_000:
                        raise ValueError('Oversized network frame')
            except (BlockingIOError, socket.timeout):
                pass
            except (OSError, ValueError):
                self.disconnect()
            finally:
                if urgent_reply and self.client and hasattr(self.client, 'setblocking'):
                    self.client.setblocking(False)

    def disconnect(self):
        with self.lock:
            if self.client:
                self.client.close()
            self.client = None
            self.connected, self.status = False, 'DISCONNECTED'
            self.other_players = {}
            self.outgoing, self.buffer = b'', b''
            self.pending_harvests.clear()
            self.pending_captures.clear()
            self.pending_pvp_attacks.clear()
            self.pending_entity_attacks.clear()
            self.pending_pickups.clear()
            self.pending_treant_actions.clear()
            self.pvp_supported = False
            self.animal_authority = False
            self.animals = {}
            self.world_loot = {}
            self.pickup_events = []
            self.treant_progress_supported = False
            self.treant_boss_authority = False
            self.treant_progress = {}
            self.island_owners = {}
            self.winner = None
            self.spawn = None
            self.spawn_island = None
            self.spawn_confirmed = False
            self.pending_respawn = False

    def close(self):
        self.disconnect()
