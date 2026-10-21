"""Centralized, event-driven audio playback for the game.

Gameplay code refers to logical sound names only.  This module owns asset
resolution, decoding/caching, channel allocation, loop state, music transitions,
volume balancing, and creature ambience scheduling.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import re
import unicodedata

import pygame


SUPPORTED_EXTENSIONS = {".wav", ".ogg", ".mp3", ".flac"}


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


@dataclass
class LoopState:
    name: str
    category: str
    channel_index: int
    gain: float
    current_volume: float
    target_volume: float
    fade_seconds: float = 0.0
    stopping: bool = False


@dataclass
class CreatureTimer:
    kind: str
    remaining: float
    last_seen: float = 0.0


class AudioManager:
    """Cache sounds and safely mix music, ambience, activities and effects."""

    ASSET_CANDIDATES = {
        "main_theme": ("main theme",),
        "boss_1": ("boss 1",),
        "ocean_waves": ("ocean waves",),
        "axe_chop_1": ("axe chop 1",),
        "axe_chop_2": ("axe chop 2",),
        "tree_falling": ("tree falling",),
        "breaking_stone": ("breaking stone",),
        "platanus_landing": ("platanus landing",),
        "platanus_slash": ("platanus slash",),
        "platanus_arm_grow": ("platanus arm grow",),
        "throwing_fishing_rod": ("throwing fishing rod",),
        "fishing": ("fishing",),
        "boat_paddle": ("boat paddle",),
        "walking_on_grass": ("walking on grass",),
        "walking_on_dirt": ("walking on dirt",),
        "sword_slice_1": ("sword slice 1",),
        "sword_slice_2": ("sword slice 2",),
        "bow_and_arrow": ("bow and arrow",),
        "cooking": ("cooking",),
        "eating": ("eating",),
        "sheep": ("sheep",),
        "cow": ("cow",),
        "wolf_growling": ("wolf growling",),
        # The task calls the first file "moster growl".  The shipped asset is
        # correctly spelled, so both spellings are accepted without fuzzy matching.
        "monster_growl_1": ("moster growl", "monster growl"),
        "monster_growl_2": ("monster growl 2",),
        "pirate_laugh": ("pirate laugh",),
        "evil_laugh": ("evil laugh",),
    }

    MENU_MUSIC = "main_menu"
    MUSIC_NAMES = {"main_theme", "boss_1", MENU_MUSIC}
    SOUND_GAIN = {
        "main_menu": .45, "main_theme": .40, "boss_1": .50, "ocean_waves": .12,
        "axe_chop_1": .70, "axe_chop_2": .70, "tree_falling": .75,
        "breaking_stone": .65, "platanus_landing": .80,
        "platanus_slash": .80, "platanus_arm_grow": .80,
        "throwing_fishing_rod": .55, "fishing": .40,
        "boat_paddle": .30, "walking_on_grass": .22,
        "walking_on_dirt": .22, "sword_slice_1": .65,
        "sword_slice_2": .65, "bow_and_arrow": .65,
        "cooking": .40, "eating": .55, "sheep": .32, "cow": .32,
        "wolf_growling": .32, "monster_growl_1": .45,
        "monster_growl_2": .45, "pirate_laugh": .40, "evil_laugh": .40,
    }
    CATEGORY_VOLUME = {
        "music": 1.0,
        "environment": 1.0,
        "movement": 1.0,
        "combat": 1.0,
        "interaction": 1.0,
        "creature": 1.0,
        "boss": 1.0,
    }
    # Dedicated channels cannot be stolen by ordinary effects.
    LOOP_CHANNELS = {"environment": 0, "movement": 1, "fishing": 2,
                     "interaction": 19}
    CHANNEL_POOLS = {
        "boss": (3, 4),
        "creature": (5, 6),
        "combat": (7, 8, 9, 10),
        "interaction": (11, 12, 13, 14),
        "movement": (15, 16),
        "environment": (17, 18),
    }
    DEFAULT_COOLDOWN = {
        "breaking_stone": .12,
        "sword_slice_1": .12,
        "sword_slice_2": .12,
        "bow_and_arrow": .12,
        "eating": .18,
        "cooking": .20,
    }
    DEFAULT_MAX_INSTANCES = {
        "breaking_stone": 2,
        "sword_slice_1": 2,
        "sword_slice_2": 2,
        "wolf_growling": 1,
        "monster_growl_1": 1,
        "monster_growl_2": 1,
        "pirate_laugh": 1,
        "evil_laugh": 1,
    }
    CREATURE_INTERVALS = {
        "sheep": (12.0, 25.0),
        "cow": (15.0, 30.0),
        "wolf": (10.0, 22.0),
        "monster": (12.0, 25.0),
        "pirate": (18.0, 35.0),
    }
    CREATURE_SOUNDS = {
        "sheep": ("sheep",),
        "cow": ("cow",),
        "wolf": ("wolf_growling",),
        "monster": ("monster_growl_1", "monster_growl_2"),
        "pirate": ("pirate_laugh", "evil_laugh"),
    }

    def __init__(self, music_dir: Path | str, seed: int = 0,
                 menu_music: Path | str | None = None):
        self.music_dir = Path(music_dir)
        # Main-menu soundtrack: an exact file, or the same stem in any supported format.
        self.menu_music_file = Path(menu_music) if menu_music is not None else None
        self.enabled = False
        self.gameplay_active = False
        self.rng = random.Random(seed + 0xA0D10)
        self.category_volume = dict(self.CATEGORY_VOLUME)
        self.paths: dict[str, Path] = {}
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.missing_assets: list[str] = []
        self._loops: dict[str, LoopState] = {}
        self._channel_uses: dict[int, tuple[str, str]] = {}
        self._cooldowns: dict[str, float] = {}
        self.current_music: str | None = None
        self.pending_music: str | None = None
        self._music_transition = 0.0
        self._music_fade_ms = 0
        self._clock = 0.0
        self._creature_timers: dict[str, CreatureTimer] = {}
        self._creature_global_cooldown = 0.0
        self._warned: set[str] = set()
        self._initialise()

    def _initialise(self) -> None:
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(7)
        except pygame.error as exc:
            print(f"[AUDIO] Disabled: mixer initialization failed: {exc}")
            return

        index = {}
        try:
            for path in self.music_dir.iterdir():
                if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS:
                    index.setdefault(_normalise(path.stem), path)
        except OSError as exc:
            print(f"[AUDIO] Disabled: cannot inspect {self.music_dir}: {exc}")
            return

        for logical_name, candidates in self.ASSET_CANDIDATES.items():
            path = next((index.get(_normalise(candidate)) for candidate in candidates
                         if index.get(_normalise(candidate)) is not None), None)
            if path is None:
                self.missing_assets.append(logical_name)
                print(f"[AUDIO] Missing asset for '{logical_name}': {', '.join(candidates)}")
                continue
            self.paths[logical_name] = path
            if logical_name in self.MUSIC_NAMES:
                continue
            try:
                self.sounds[logical_name] = pygame.mixer.Sound(str(path))
            except (pygame.error, OSError) as exc:
                self.missing_assets.append(logical_name)
                print(f"[AUDIO] Could not load '{path.name}': {exc}")
        self._resolve_menu_music()
        self.enabled = True

    def _resolve_menu_music(self) -> None:
        if self.menu_music_file is None:
            return
        candidates = [self.menu_music_file] + [
            self.menu_music_file.with_suffix(ext) for ext in sorted(SUPPORTED_EXTENSIONS)
            if ext != self.menu_music_file.suffix.casefold()]
        found = next((path for path in candidates if path.is_file()), None)
        if found is None:
            self.missing_assets.append(self.MENU_MUSIC)
            print(f"[AUDIO] Main menu music not found at {self.menu_music_file} "
                  "(.ogg/.mp3/.wav/.flac); the menu will stay silent until it is added.")
            return
        self.paths[self.MENU_MUSIC] = found

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def set_category_volume(self, category: str, volume: float) -> None:
        if category not in self.category_volume:
            raise KeyError(f"Unknown audio category: {category}")
        self.category_volume[category] = self._clamp(volume)
        for loop in self._loops.values():
            if loop.category == category and not loop.stopping:
                loop.target_volume = self._effective_volume(loop.name, category, loop.gain)
        if category == "music" and self.current_music:
            pygame.mixer.music.set_volume(self._effective_volume(self.current_music, "music", 1.0))

    def _effective_volume(self, name: str, category: str, gain: float) -> float:
        return self._clamp(self.category_volume.get(category, 1.0)
                           * self.SOUND_GAIN.get(name, 1.0) * self._clamp(gain))

    def activate_gameplay(self) -> None:
        if not self.enabled or self.gameplay_active:
            return
        self.gameplay_active = True
        self.start_loop("ocean_waves", "environment", fade_ms=900)

    def deactivate_gameplay(self, fade_ms: int = 350) -> None:
        if not self.enabled or not self.gameplay_active:
            return
        self.gameplay_active = False
        self.pending_music = None
        self.current_music = None
        pygame.mixer.music.fadeout(max(0, int(fade_ms)))
        for name in tuple(self._loops):
            self.stop_loop(name, fade_ms)

    def play_sfx(self, name: str, category: str = "interaction", volume: float = 1.0,
                 cooldown: float | None = None, max_instances: int | None = None,
                 restart_if_busy: bool = False) -> bool:
        if not self.enabled or not self.gameplay_active:
            return False
        sound = self.sounds.get(name)
        if sound is None:
            if name not in self._warned:
                self._warned.add(name)
                print(f"[AUDIO] Sound unavailable: {name}")
            return False
        cooldown = self.DEFAULT_COOLDOWN.get(name, 0.0) if cooldown is None else max(0.0, cooldown)
        if self._cooldowns.get(name, 0.0) > 0:
            return False
        max_instances = self.DEFAULT_MAX_INSTANCES.get(name, 3) if max_instances is None else max_instances
        active_channels = [
            index for index, use in self._channel_uses.items()
            if use[0] == name and pygame.mixer.Channel(index).get_busy()
        ]
        active_instances = len(active_channels)
        if active_instances >= max_instances:
            if not restart_if_busy:
                return False
            channel_index = active_channels[0]
        else:
            channel_index = self._free_channel(category)
        if channel_index is None:
            return False
        channel = pygame.mixer.Channel(channel_index)
        channel.set_volume(self._effective_volume(name, category, volume))
        channel.play(sound)
        self._channel_uses[channel_index] = (name, category)
        self._cooldowns[name] = cooldown
        return True

    def play_random_sfx(self, names, category: str = "interaction", volume: float = 1.0,
                        **kwargs) -> str | None:
        choices = [name for name in names if name in self.sounds]
        if not choices:
            return None
        name = self.rng.choice(choices)
        return name if self.play_sfx(name, category, volume, **kwargs) else None

    def _free_channel(self, category: str) -> int | None:
        pool = self.CHANNEL_POOLS.get(category, self.CHANNEL_POOLS["interaction"])
        for index in pool:
            if not pygame.mixer.Channel(index).get_busy():
                return index
        return None

    def start_loop(self, name: str, category: str | None = None, volume: float = 1.0,
                   fade_ms: int = 160) -> bool:
        if not self.enabled or not self.gameplay_active:
            return False
        category = category or "interaction"
        sound = self.sounds.get(name)
        channel_index = self.LOOP_CHANNELS.get(category)
        if sound is None or channel_index is None:
            return False
        existing = self._loops.get(category)
        target = self._effective_volume(name, category, volume)
        if existing and existing.name == name and pygame.mixer.Channel(channel_index).get_busy():
            existing.gain = self._clamp(volume)
            existing.target_volume = target
            existing.fade_seconds = max(.001, fade_ms / 1000.0)
            existing.stopping = False
            return True
        channel = pygame.mixer.Channel(channel_index)
        channel.stop()
        initial = 0.0 if fade_ms > 0 else target
        channel.set_volume(initial)
        channel.play(sound, loops=-1)
        self._loops[category] = LoopState(
            name, category, channel_index, self._clamp(volume), initial, target,
            max(.001, fade_ms / 1000.0), False,
        )
        return True

    def stop_loop(self, name: str, fade_ms: int = 0) -> None:
        for category, loop in tuple(self._loops.items()):
            if loop.name != name:
                continue
            channel = pygame.mixer.Channel(loop.channel_index)
            if fade_ms <= 0:
                channel.stop()
                self._loops.pop(category, None)
            else:
                loop.target_volume = 0.0
                loop.fade_seconds = max(.001, fade_ms / 1000.0)
                loop.stopping = True

    def stop_category_loop(self, category: str, fade_ms: int = 0) -> None:
        loop = self._loops.get(category)
        if loop:
            self.stop_loop(loop.name, fade_ms)

    def active_loop(self, category: str) -> str | None:
        loop = self._loops.get(category)
        return loop.name if loop is not None else None

    def switch_music(self, name: str, fade_ms: int = 1000) -> bool:
        if not self.enabled or not self.gameplay_active or name not in self.paths:
            return False
        return self._transition_music(name, fade_ms)

    def play_menu_music(self, fade_ms: int = 1200) -> bool:
        """Start (or keep) the menu soundtrack; False when the asset is missing."""
        if not self.enabled or self.gameplay_active or self.MENU_MUSIC not in self.paths:
            return False
        return self._transition_music(self.MENU_MUSIC, fade_ms)

    def _transition_music(self, name: str, fade_ms: int) -> bool:
        if name == self.current_music and self.pending_music is None and pygame.mixer.music.get_busy():
            return True
        if name == self.pending_music:
            return True
        if self.current_music is None and pygame.mixer.music.get_busy() and fade_ms > 0:
            # A previous track is still fading out: queue instead of cutting it.
            self.pending_music = name
            self._music_transition = fade_ms / 1000.0
            self._music_fade_ms = fade_ms
            return True
        if self.current_music and pygame.mixer.music.get_busy() and fade_ms > 0:
            self.pending_music = name
            self._music_transition = fade_ms / 1000.0
            self._music_fade_ms = fade_ms
            pygame.mixer.music.fadeout(fade_ms)
            return True
        return self._start_music(name, fade_ms)

    def stop_music(self, fade_ms: int = 800) -> None:
        """Fade the current track out without queueing another; safe to repeat."""
        if not self.enabled or (self.current_music is None and self.pending_music is None):
            return
        self.current_music = None
        self.pending_music = None
        self._music_transition = 0.0
        pygame.mixer.music.fadeout(max(0, int(fade_ms)))

    def _start_music(self, name: str, fade_ms: int) -> bool:
        try:
            pygame.mixer.music.load(str(self.paths[name]))
            pygame.mixer.music.set_volume(self._effective_volume(name, "music", 1.0))
            pygame.mixer.music.play(-1, fade_ms=max(0, int(fade_ms)))
        except (pygame.error, OSError) as exc:
            print(f"[AUDIO] Could not play music '{name}': {exc}")
            # Forget the undecodable track so per-frame switch_music calls do not
            # retry the load (and log) every frame.
            self.paths.pop(name, None)
            self.missing_assets.append(name)
            self.current_music = None
            self.pending_music = None
            return False
        self.current_music = name
        self.pending_music = None
        self._music_transition = 0.0
        return True

    def update_creatures(self, dt: float, entities, player_position,
                         hearing_range: float = 15.0) -> None:
        """Advance stable per-entity vocal timers and play at most an organic pair."""
        if not self.enabled or not self.gameplay_active:
            return
        dt = max(0.0, float(dt))
        px, py = player_position
        live_ids = set()
        eligible = []
        for entity_id, kind, x, y, alive in entities:
            if not alive or kind not in self.CREATURE_INTERVALS:
                continue
            entity_id = str(entity_id)
            live_ids.add(entity_id)
            timer = self._creature_timers.get(entity_id)
            if timer is None or timer.kind != kind:
                bounds = self.CREATURE_INTERVALS[kind]
                timer = CreatureTimer(kind, self.rng.uniform(*bounds), self._clock)
                self._creature_timers[entity_id] = timer
            timer.remaining -= dt
            timer.last_seen = self._clock
            distance = ((x - px) ** 2 + (y - py) ** 2) ** .5
            if timer.remaining <= 0 and distance <= hearing_range:
                eligible.append((distance, entity_id, kind))

        # Entity lists are authoritative each call, so removed/dead entries can be
        # discarded immediately. A small grace path also protects intermittent feeds.
        for entity_id, timer in tuple(self._creature_timers.items()):
            if entity_id not in live_ids and self._clock - timer.last_seen > 1.0:
                self._creature_timers.pop(entity_id, None)

        if self._creature_global_cooldown > 0 or not eligible:
            return
        active_creatures = sum(
            pygame.mixer.Channel(index).get_busy()
            for index in self.CHANNEL_POOLS["creature"]
        )
        if active_creatures >= 2:
            return
        distance, entity_id, kind = min(eligible)
        attenuation = self._clamp(1.0 - distance / hearing_range)
        sound_name = self.play_random_sfx(
            self.CREATURE_SOUNDS[kind], "creature", .35 + .65 * attenuation,
            max_instances=1,
        )
        if sound_name:
            bounds = self.CREATURE_INTERVALS[kind]
            self._creature_timers[entity_id].remaining = self.rng.uniform(*bounds)
            self._creature_global_cooldown = 2.0
        else:
            # A full channel or an already-playing identical call should not turn
            # into a new random playback attempt on every rendered frame.
            self._creature_timers[entity_id].remaining = self.rng.uniform(.7, 1.3)
            self._creature_global_cooldown = .35

    def update(self, dt: float) -> None:
        if not self.enabled:
            return
        dt = max(0.0, float(dt))
        self._clock += dt
        self._creature_global_cooldown = max(0.0, self._creature_global_cooldown - dt)
        for name in tuple(self._cooldowns):
            self._cooldowns[name] = max(0.0, self._cooldowns[name] - dt)
            if self._cooldowns[name] <= 0:
                self._cooldowns.pop(name, None)
        for index in tuple(self._channel_uses):
            if not pygame.mixer.Channel(index).get_busy():
                self._channel_uses.pop(index, None)

        for category, loop in tuple(self._loops.items()):
            channel = pygame.mixer.Channel(loop.channel_index)
            if not channel.get_busy():
                self._loops.pop(category, None)
                continue
            difference = loop.target_volume - loop.current_volume
            if abs(difference) <= .001:
                loop.current_volume = loop.target_volume
            else:
                step = dt / loop.fade_seconds
                loop.current_volume += max(-abs(difference), min(abs(difference), difference * step))
            channel.set_volume(self._clamp(loop.current_volume))
            if loop.stopping and loop.current_volume <= .001:
                channel.stop()
                self._loops.pop(category, None)

        if self.pending_music is not None:
            self._music_transition = max(0.0, self._music_transition - dt)
            if self._music_transition <= 0 or not pygame.mixer.music.get_busy():
                pending = self.pending_music
                self._start_music(pending, self._music_fade_ms)

    def stop_all(self) -> None:
        if not self.enabled:
            return
        pygame.mixer.music.stop()
        for index in range(pygame.mixer.get_num_channels()):
            pygame.mixer.Channel(index).stop()
        self._loops.clear()
        self._channel_uses.clear()
        self._cooldowns.clear()
        self.current_music = None
        self.pending_music = None
        self.gameplay_active = False
