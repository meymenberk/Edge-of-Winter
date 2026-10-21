import json

from modules.multiplayer import NetworkClient
from modules.settings import GameSettings, load_settings, save_settings, stable_seed, validate_endpoint
from modules.worldgen import make_world


def test_text_and_integer_seeds_are_stable():
    assert stable_seed("123") == 123
    assert stable_seed("edge of winter") == stable_seed("edge of winter")
    assert stable_seed("edge of winter") != stable_seed("another winter")


def test_settings_round_trip_and_invalid_fallback(tmp_path):
    path = tmp_path / "settings.json"
    value = GameSettings("Kızılkök", "localhost", 6123)
    save_settings(value, path)
    assert load_settings(path) == value
    path.write_text("{broken", encoding="utf-8")
    assert load_settings(path) == GameSettings()


def test_endpoint_validation():
    assert validate_endpoint("127.0.0.1", "5555") == ("127.0.0.1", 5555)
    assert validate_endpoint("game.example.com", 6500) == ("game.example.com", 6500)


def test_offline_client_retains_configured_seed(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr("socket.create_connection", fail)
    client = NetworkClient(offline_seed=98765)
    assert not client.try_connect(timeout=.01)
    assert client.seed == 98765


def test_same_world_seed_repeats_world_layout():
    a, b = make_world(3049), make_world(3049)
    assert a.heights == b.heights
    assert [island.village.center if island.village else None for island in a.islands] == \
        [island.village.center if island.village else None for island in b.islands]


# --- Seed determinism -------------------------------------------------------
import os
import random
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def fingerprint(world):
    return (sum(map(sum, world.heights)), tuple((i.x, i.y, i.name) for i in world.islands),
            tuple(node.id for node in world.nodes), world.boss_island_index, world.boss_portal)


def test_text_seed_is_independent_of_python_hash_randomization():
    code = ("from modules.settings import stable_seed; print(stable_seed('Crimsonroot'), "
            "stable_seed('42'), stable_seed('  edge of winter  '))")
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": seed}, check=True).stdout
               for seed in ("1", "2", "random")}
    assert len(outputs) == 1
    assert stable_seed("  edge of winter  ") == stable_seed("edge of winter")


def test_different_seeds_make_different_worlds_and_text_seeds_repeat():
    a, b = make_world(stable_seed("autumn")), make_world(stable_seed("winter"))
    assert fingerprint(a) != fingerprint(b)
    assert fingerprint(make_world(stable_seed("autumn"))) == fingerprint(a)
    assert a.islands[a.boss_island_index].name == "Crimsonroot Isle"


def test_generation_ignores_other_threads_using_global_random():
    expected = fingerprint(make_world(77))
    stop = threading.Event()

    def menu_particles():
        while not stop.is_set():
            random.uniform(0, 1)
            random.seed()

    noise = threading.Thread(target=menu_particles, daemon=True)
    noise.start()
    try:
        results = []
        worker = threading.Thread(target=lambda: results.append(fingerprint(make_world(77))))
        worker.start()
        worker.join()
    finally:
        stop.set()
        noise.join()
    assert results == [expected]


@pytest.mark.parametrize("host, port", [
    ("300.1.1.1", 5555), ("bad host", 5555), ("", 5555), ("-bad.example", 5555),
    ("a..b", 5555), ("127.0.0.1", 0), ("127.0.0.1", 70000), ("127.0.0.1", "abc"),
])
def test_invalid_endpoints_are_rejected(host, port):
    with pytest.raises(ValueError):
        validate_endpoint(host, port)


def test_ipv6_and_hostnames_are_accepted():
    assert validate_endpoint("[::1]", 1) == ("::1", 1)
    assert validate_endpoint("localhost", "65535") == ("localhost", 65535)
    assert validate_endpoint("192.168.1.20", 5555) == ("192.168.1.20", 5555)


def test_server_cli_accepts_text_seeds_and_rejects_bad_ports():
    from server import parse_args
    args = parse_args(["--host", "0.0.0.0", "--port", "6000", "--seed", "edge of winter"])
    assert (args.host, args.port, args.seed) == ("0.0.0.0", 6000, stable_seed("edge of winter"))
    assert parse_args([]).seed == 42
    with pytest.raises(SystemExit):
        parse_args(["--port", "0"])


def test_online_client_adopts_the_shared_server_seed():
    from server import GameServer
    game = GameServer(make_world(4242))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def accept_one():
        conn, addr = listener.accept()
        game.handle_client(conn, addr, 0)

    threading.Thread(target=accept_one, daemon=True).start()
    client = NetworkClient("127.0.0.1", port, offline_seed=11)
    try:
        assert client.try_connect(timeout=2)
        assert client.seed == 4242
    finally:
        client.close()
        listener.close()


# --- Settings menu flow -------------------------------------------------------
class FakePreloader:
    instances = []

    def __init__(self, host, port, audio, seed):
        self.args = (host, port, seed)
        self.network = NetworkClient(host, port, offline_seed=seed)
        self.game_session = None
        self.cancelled = False
        FakePreloader.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def app(monkeypatch, tmp_path):
    import pygame
    import main
    saved = tmp_path / "settings.json"
    monkeypatch.setattr(main, "save_settings", lambda value: save_settings(value, saved))
    monkeypatch.setattr(main, "BackgroundPreloader", FakePreloader)
    FakePreloader.instances.clear()
    instance = main.AutumnGameApp.__new__(main.AutumnGameApp)
    instance.settings = GameSettings("42", "127.0.0.1", 5555)
    instance.audio = None
    instance.preloader = FakePreloader("127.0.0.1", 5555, None, 42)
    instance.open_settings()
    instance.saved_path = saved
    instance.key = lambda key, text="", mod=0: instance._settings_key(
        pygame.event.Event(pygame.KEYDOWN, key=key, unicode=text, mod=mod))
    return instance


def test_typing_never_regenerates_and_invalid_input_shows_errors(app):
    import pygame
    app.settings_focus = "world_seed"
    for char in "abc":
        app.key(pygame.K_a, char)
    assert app.settings_draft["world_seed"] == "42abc"
    assert len(FakePreloader.instances) == 1
    app.settings_focus = "server_port"
    app.key(pygame.K_x, "x")  # letters are ignored in the port field
    assert app.settings_draft["server_port"] == "5555"
    app.settings_draft["server_address"] = "300.1.1.1"
    app._apply_settings()
    assert "not a valid" in app.settings_error
    assert len(FakePreloader.instances) == 1 and not app.saved_path.exists()


def test_apply_before_any_world_exists_saves_and_restarts_preload(app):
    app.settings_draft.update(world_seed="Crimsonroot", server_address="game.example.com",
                              server_port="6100")
    app._apply_settings()
    assert app.settings_pending is None
    assert load_settings(app.saved_path) == GameSettings("Crimsonroot", "game.example.com", 6100)
    assert FakePreloader.instances[0].cancelled
    assert FakePreloader.instances[-1].args == ("game.example.com", 6100, stable_seed("Crimsonroot"))


def test_existing_world_and_online_session_require_confirmation(app):
    import pygame
    from types import SimpleNamespace
    session = SimpleNamespace(boss_active=False, seed=42, deactivate_audio=lambda: None)
    app.preloader.game_session = session
    app.preloader.network.connected = True
    app.settings_draft["world_seed"] = "99"
    app._apply_settings()
    assert app.settings_pending is not None
    text = " ".join(app.settings_pending[1])
    assert "regenerated" in text and "disconnected" in text
    assert len(FakePreloader.instances) == 1
    app.key(pygame.K_ESCAPE)  # back out of the confirmation: nothing changes
    assert app.settings_pending is None and app.settings.world_seed == "42"
    app._apply_settings()
    app.key(pygame.K_RETURN)  # confirm
    assert app.settings.world_seed == "99" and len(FakePreloader.instances) == 2

    app.preloader.game_session = SimpleNamespace(boss_active=True, seed=99, deactivate_audio=lambda: None)
    app.settings_draft["world_seed"] = "100"
    app._apply_settings()
    assert app.settings_pending is None and "PLATANUS" in app.settings_error
