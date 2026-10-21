"""Terrain must stay tile-aligned through fishing zoom, combat shake and finishers."""
import copy
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import numpy as np
import pygame

import main
from modules.terrain_render import TerrainRenderer, TileAtlas, prepare_terrain
from modules.worldgen import make_world

TILE = main.LOCAL_TILE_SIZE
MARK = 201  # Blue channel reserved for coded terrain pixels.


def coded_chunk(renderer, cx, cy):
    """Flat chunk whose red/green channels name each world tile."""
    size = renderer.CHUNK
    pixels = np.zeros((size * TILE, size * TILE, 3), np.uint8)
    for i in range(size):
        for j in range(size):
            pixels[i * TILE:(i + 1) * TILE, j * TILE:(j + 1) * TILE] = (
                (cx * size + i) % 256, (cy * size + j) % 256, MARK)
    return pygame.surfarray.make_surface(pixels)


def tile_runs(surface, y):
    """(tile id, start, width) of each complete terrain tile along row ``y``."""
    row = pygame.surfarray.array3d(surface)[:, y]
    ids = np.where(row[:, 2] == MARK, row[:, 0].astype(int), -1)
    runs, start = [], 0
    for x in range(1, len(ids) + 1):
        if x == len(ids) or ids[x] != ids[start]:
            if ids[start] >= 0 and start > 0 and x < len(ids) and ids[start - 1] >= 0 and ids[x] >= 0:
                runs.append((int(ids[start]), start, x - start))
            start = x
    return runs


class TerrainStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1200, 780))
        main.set_game_view_size((main.BASE_GAME_WIDTH, main.BASE_GAME_HEIGHT))
        cls.world = make_world(42)
        prepare_terrain(cls.world)
        cls.atlas = TileAtlas(main.find_tileset_file())
        cls.tiles = pygame.image.frombuffer(main.compute_tile_pixels(cls.world),
                                            (main.COLS, main.ROWS), "RGB").convert()
        cls.original_chunk = TerrainRenderer._chunk
        TerrainRenderer._chunk = coded_chunk

    @classmethod
    def tearDownClass(cls):
        TerrainRenderer._chunk = cls.original_chunk

    def session(self):
        world = copy.deepcopy(self.world)
        session = main.GameSession(world, world.ports, main.find_spawn(world), self.tiles,
                                   None, 42, {}, self.atlas)
        session.ambient_leaves_enabled = lambda: False
        return session

    def assert_uniform_tiles(self, surface, width=None):
        rows = (surface.get_height() // 5, surface.get_height() // 3)
        widths = {run[2] for y in rows for run in tile_runs(surface, y)}
        self.assertEqual(len(widths), 1, f"tiles of unequal width {sorted(widths)}")
        if width is not None:
            self.assertEqual(widths, {width})

    def test_magnify_is_world_anchored_while_camera_moves(self):
        for zoom in (1.02, 1.3, 1.6, 1.42):
            span = round(TILE * zoom)
            for camera_x in range(15000, 15000 + 2 * TILE, 7):
                frame = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
                renderer = TerrainRenderer.__new__(TerrainRenderer)
                renderer.CHUNK = 8
                for x in range(camera_x // 384, (camera_x + main.GAME_WIDTH) // 384 + 1):
                    for y in range(6720 // 384, (6720 + main.GAME_HEIGHT) // 384 + 1):
                        frame.blit(coded_chunk(renderer, x, y), (x * 384 - camera_x, y * 384 - 6720))
                origin = (main.GAME_WIDTH / 2 * (1 - 1 / main.snapped_world_zoom(zoom)), 0)
                main.magnify_world(frame, (camera_x, 6720), zoom, origin)
                runs = tile_runs(frame, 300)
                self.assertTrue(runs)
                self.assertEqual({run[2] for run in runs}, {span})
                # Each tile starts where the single world->screen transform puts it.
                offset = round((camera_x + origin[0]) * span / TILE)
                for tile_id, start, _ in runs:
                    world_tile = next(t for t in range(camera_x // TILE - 1, camera_x // TILE + 60)
                                      if t % 256 == tile_id)
                    self.assertEqual(start, world_tile * span - offset)

    def test_fishing_zoom_keeps_every_tile_identical(self):
        session = self.session()
        port = session.ports[0]
        session.player.x, session.player.y = port.x + .5, port.y + .5
        session.cam_x, session.cam_y = main.get_local_camera(session.player)
        session.fishing.open(port, session.player)
        canvas = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        center = (main.GAME_WIDTH // 2, main.GAME_HEIGHT // 2)
        for step in range(90):
            if step > 60:
                session.fishing.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1))
            session.update(1 / 60, center)
            session.render(canvas, center)
            if step % 6 == 0:
                expected = round(TILE * session.fishing.zoom_level)
                self.assert_uniform_tiles(canvas, max(TILE, expected))
        session.fishing.close()
        # Step off the dock, otherwise the port trigger re-opens fishing.
        session.player.x, session.player.y = main.find_spawn(session.world)
        for _ in range(240):
            session.update(1 / 60, center)
        session.render(canvas, center)
        self.assert_uniform_tiles(canvas, TILE)

    def test_combat_shake_is_render_only_and_shared_by_terrain(self):
        session = self.session()
        canvas = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        camera = (session.cam_x, session.cam_y)
        session.combat.combo_step = 3
        for step in range(12):
            session.game_time = step * .37
            session.combat.impact_pulse = .16
            session.render(canvas, (0, 0))
            self.assertEqual((session.cam_x, session.cam_y), camera)
            self.assert_uniform_tiles(canvas, TILE)

    def test_execution_finisher_keeps_tiles_uniform(self):
        session = self.session()
        canvas = pygame.Surface((main.GAME_WIDTH, main.GAME_HEIGHT))
        for timer in (.05, .2, .39, .55, .7):
            session.execution = {"x": session.player.x + .4, "y": session.player.y + .8, "angle": 0.0,
                                 "timer": timer, "duration": .78, "variant": 0, "kind": "wolf"}
            session.combat.impact_pulse = .1
            session.game_time += .13
            session.render(canvas, (0, 0))
            self.assert_uniform_tiles(canvas)


if __name__ == "__main__":
    unittest.main()
