"""Window/viewport scaling for the fixed-size logical render surfaces.

The game draws to logical surfaces and the viewport scales that image into the
real window with nearest-neighbour scaling, preserving aspect ratio.  The menu
is a fixed 16:9 (1024x576) painting, centred with its scene dimmed in any bars.
The gameplay surface is sized by ``main.game_view_size`` to the window's own
aspect ratio (at least 1200x780), so it fills widescreen and fullscreen displays
by showing more world rather than stretching or letterboxing.  Every mouse
position is mapped back through the same transform, so clicks land on the same
logical pixel whatever the window size, fullscreen state or display density.
"""
from __future__ import annotations

import math
import sys

import pygame

# Window sizes offered in Settings; only those that fit the desktop are listed.
WINDOW_SIZE_CHOICES = (
    (1024, 576), (1200, 780), (1280, 720), (1366, 768), (1600, 900),
    (1920, 1080), (2560, 1440), (3840, 2160),
)
MIN_WINDOW_SIZE = (640, 360)


def enable_hidpi_awareness():
    """Stop Windows from bitmap-stretching (blurring) the window on scaled displays.

    macOS already reports window, surface and mouse sizes in the same points, so
    no change is needed there.  Must run before the window is created.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # per-monitor aware
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
        return True
    except (AttributeError, OSError):
        return False


def desktop_size():
    """Primary desktop size, or ``None`` when the video driver cannot tell."""
    try:
        sizes = pygame.display.get_desktop_sizes()
    except pygame.error:
        return None
    return tuple(sizes[0]) if sizes and sizes[0][0] > 0 and sizes[0][1] > 0 else None


def window_size_options(desktop=None, current=None):
    """Window sizes that fit on the desktop, plus the currently saved size."""
    sizes = [size for size in WINDOW_SIZE_CHOICES
             if desktop is None or (size[0] <= desktop[0] and size[1] <= desktop[1])]
    if not sizes:
        sizes = [WINDOW_SIZE_CHOICES[0]]
    if current is not None and tuple(current) not in sizes:
        sizes.append(tuple(current))
    return sorted(sizes, key=lambda size: (size[0] * size[1], size))


def fit_window_size(size, desktop=None):
    """Clamp a requested windowed size between the minimum and the desktop."""
    width, height = (max(MIN_WINDOW_SIZE[0], int(size[0])), max(MIN_WINDOW_SIZE[1], int(size[1])))
    if desktop is not None:
        width, height = min(width, desktop[0]), min(height, desktop[1])
    return width, height


class Viewport:
    """Aspect-preserving letterbox transform between window and logical pixels."""

    def __init__(self, logical_size=(1, 1)):
        self.logical_size = tuple(logical_size)
        self.window_size = tuple(logical_size)
        self.surface_size = tuple(logical_size)
        self.scale = 1.0
        self.offset = (0, 0)
        self.target_size = tuple(logical_size)
        self.pixel_perfect = False

    def update(self, surface_size, logical_size, pixel_perfect=False, window_size=None):
        """Recompute the transform.

        ``surface_size`` is the drawable display surface in pixels;
        ``window_size`` is the size mouse events are reported in (they differ
        only for HiDPI-aware windows).
        """
        self.surface_size = (max(1, int(surface_size[0])), max(1, int(surface_size[1])))
        self.window_size = tuple(window_size or self.surface_size)
        self.logical_size = tuple(logical_size)
        self.pixel_perfect = bool(pixel_perfect)
        lw, lh = self.logical_size
        scale = min(self.surface_size[0] / lw, self.surface_size[1] / lh)
        # Whole-number steps keep every art pixel the same size when the
        # window is at least as large as the logical image.
        if self.pixel_perfect and scale >= 1:
            scale = float(math.floor(scale))
        self.scale = max(scale, 1e-3)
        # Round (not truncate) so a fitted side fills the window exactly.
        self.target_size = (max(1, min(self.surface_size[0], round(lw * self.scale))),
                            max(1, min(self.surface_size[1], round(lh * self.scale))))
        self.offset = ((self.surface_size[0] - self.target_size[0]) // 2,
                       (self.surface_size[1] - self.target_size[1]) // 2)
        return self

    def _density(self):
        return (self.surface_size[0] / max(1, self.window_size[0]),
                self.surface_size[1] / max(1, self.window_size[1]))

    def _axis_scale(self):
        # The drawn image is exactly target_size, so map through its true ratio.
        return (self.target_size[0] / self.logical_size[0],
                self.target_size[1] / self.logical_size[1])

    def to_logical(self, pos):
        """Mouse/window position -> logical pixel (may fall outside in the bars)."""
        dx, dy = self._density()
        sx, sy = self._axis_scale()
        return (math.floor((pos[0] * dx - self.offset[0]) / sx),
                math.floor((pos[1] * dy - self.offset[1]) / sy))

    def to_window(self, pos):
        """Logical pixel -> a mouse/window position that displays that pixel.

        Nearest-neighbour scaling shows logical pixel ``p`` in drawn pixels
        ``ceil(p*s) .. ceil((p+1)*s)-1``; the middle of that run is returned.
        """
        dx, dy = self._density()
        sx, sy = self._axis_scale()

        def axis(value, scale, offset, density):
            first = math.ceil(value * scale)
            last = max(first, math.ceil((value + 1) * scale) - 1)
            return math.floor((offset + (first + last) // 2) / density)

        return (axis(pos[0], sx, self.offset[0], dx), axis(pos[1], sy, self.offset[1], dy))

    def contains(self, window_pos):
        x, y = self.to_logical(window_pos)
        return 0 <= x < self.logical_size[0] and 0 <= y < self.logical_size[1]


# Shared by the app (which updates it) and gameplay code that needs the
# current mouse in logical coordinates or must warp the cursor.
VIEWPORT = Viewport()


def logical_mouse_pos():
    return VIEWPORT.to_logical(pygame.mouse.get_pos())
