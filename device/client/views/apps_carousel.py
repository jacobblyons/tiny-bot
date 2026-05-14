"""Paged app launcher for the home scene.

Each entry is a "mobile-style" tile: a rounded card with a terminal-art
icon glyph centered above its label. The launcher shows a fixed number
of tiles per page (computed from the available width) with `[<]` /
`[>]` arrow buttons on either side. Tapping an arrow advances by one
page; swiping the band horizontally does the same thing (the swipe
direction is interpreted as "where to flick the current page" — swipe
left → next page, swipe right → previous page).

Tapping a tile launches the app or scene it points at.

The strip can be locked via `set_locked(True)` — used while the agent
is mid-turn so the user can't accidentally launch an app on top of a
still-running bot send. Locked tiles and arrows render dim and all
input (tap, swipe) is ignored.

Carousel order: /sd/state/apps_order.json holds a single list of
names that covers BOTH built-in scenes (e.g. `config`, `system`) and
discovered apps from /sd/apps/. Listed names appear first in the
given order; unlisted entries follow in their natural order (built-in
scenes as `build()` got them, then apps alphabetically) so a fresh
install or a newly-added built-in never disappears from the launcher.
The agent reorders via the `reorder_apps` tool.
"""
import json
import os
import sys

import displayio
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.roundrect import RoundRect

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import (
    BG_SURFACE, BORDER, TEXT_PRIMARY, TEXT_DIM, ACCENT, TILE_FILL,
)

APPS_DIR = "/sd/apps"
APPS_ORDER_PATH = "/sd/state/apps_order.json"

# Tile + arrow geometry. Sizes are chosen so that 4 tiles fit evenly
# between the two arrow zones with a single uniform gap (8 px) used
# both between tiles and as the edge margin against the arrows:
#   320 = 2*ARROW_W + 5*TILE_GAP + 4*TILE_W
#       = 2*24    + 5*8        + 4*58
TILE_W = 58
TILE_H = 58
TILE_GAP = 8
ICON_GLYPH_PX = 4  # pixel size of each "char" in an ICON row
ICON_GLYPH_GAP = 1

# Width of the left/right arrow zones on the launcher band. Each
# arrow is centered inside this strip; taps anywhere in the zone
# count as a page nav so the touch target is generously thumb-sized.
ARROW_W = 24

# Horizontal pixel motion required during a touch swipe to count as a
# page nav. Anything smaller is treated as a tap.
SWIPE_THRESHOLD_PX = 24

# Default icons for built-in scenes and apps that don't ship their own.
# 5x5 grids: '#' fills a pixel, anything else leaves it empty.
DEFAULT_ICONS = {
    # speech bubble glyph
    "bot": [
        "#####",
        "# # #",
        "#####",
        "##   ",
        "#    ",
    ],
    # gear glyph
    "config": [
        "# # #",
        "#####",
        "## ##",
        "#####",
        "# # #",
    ],
    # monitor glyph
    "system": [
        "#####",
        "#   #",
        "#####",
        "  #  ",
        " ### ",
    ],
    "_default": [
        " ### ",
        "#   #",
        "# ? #",
        "#   #",
        " ### ",
    ],
}

DEFAULT_LABELS = {
    "bot":    "bot",
    "config": "config",
    "system": "system",
}


def _load_apps_order():
    """Return the persisted app order list (possibly empty).

    The file is a JSON array of app-name strings. Missing/corrupt
    files return an empty list — discovery falls back to alpha.
    """
    try:
        with open(APPS_ORDER_PATH, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for x in data:
        if isinstance(x, str):
            out.append(x)
    return out


def discover_apps():
    """Return a list of (app_name, module_or_none) tuples in alpha
    order. The module is imported lazily so we can read its
    LABEL/ICON. If import fails we still return the entry (with
    module=None) so the user sees the broken tile and knows it exists.

    Order application happens in `AppsCarousel.build()` across the
    combined builtins + apps list, so don't try to apply persistent
    order here — alphabetical is the "natural" default that the
    carousel falls back to for unlisted entries.
    """
    apps = []
    try:
        entries = os.listdir(APPS_DIR)
    except OSError:
        return apps
    if APPS_DIR not in sys.path:
        sys.path.insert(0, APPS_DIR)

    for entry in sorted(entries):
        if entry.endswith(".py") and not entry.startswith("_"):
            name = entry[:-3]
            mod = None
            try:
                if name in sys.modules:
                    mod = sys.modules[name]
                else:
                    mod = __import__(name)
            except Exception as e:
                print("app discover:", name, "import failed:", e)
            apps.append((name, mod))
    return apps


def _apply_carousel_order(raw):
    """Re-order a list of carousel entries by /sd/state/apps_order.json.

    `raw` is a list of (kind, name, label, icon) tuples in natural
    default order (builtins first as given, then apps alpha). Listed
    names move to the front in the order specified; unlisted entries
    keep their original relative position at the tail.
    """
    order = _load_apps_order()
    if not order:
        return list(raw)
    by_name = {}
    for entry in raw:
        by_name[entry[1]] = entry
    out = []
    seen = set()
    for name in order:
        if name in by_name and name not in seen:
            out.append(by_name[name])
            seen.add(name)
    for entry in raw:
        if entry[1] not in seen:
            out.append(entry)
    return out


class AppsCarousel:
    """Renders a horizontal strip of app tiles inside a fixed band."""

    def __init__(self, root_group, x, y, w, h):
        self._root = root_group
        self._x, self._y, self._w, self._h = x, y, w, h
        # Each tile gets its own subgroup so we can move them together
        # (via strip.x for pagination) AND hide them individually so
        # tiles from off-screen pages can't bleed past the arrow chrome
        # (displayio doesn't clip groups to a viewport).
        self._strip = displayio.Group(x=x, y=y)
        # Items: list of (action_kind, target, name, label, tile_x, tile_w)
        self._items = []
        self._tile_groups = []
        self._tile_labels = []
        # Pagination state — computed in build() once tile count is known.
        self._page = 0
        self._tiles_per_page = 1
        self._total_pages = 1
        self._page_pitch_px = 0      # pixels the strip slides per page
        self._content_left_x = x     # screen-x of page 0's strip origin
        # Touch swipe state (signed pixel delta from anchor).
        self._drag_anchor_x = None
        self._drag_total = 0
        # When locked, all input is ignored and labels render dim. Set
        # by the home scene while a bot turn is in flight.
        self._locked = False
        # Arrow button refs (built in build()).
        self._left_bg = None
        self._left_lbl = None
        self._left_rect = None
        self._right_bg = None
        self._right_lbl = None
        self._right_rect = None

    def build(self, builtin_scenes):
        """Build tiles for built-in scenes + discovered apps.

        `builtin_scenes` is an iterable of (scene_name, label). Both
        builtins and discovered apps participate in the same
        /sd/state/apps_order.json ordering — the agent can move
        builtins around just like apps, and unlisted entries fall
        through to the natural default (builtins as given, then apps
        alpha) so a freshly-installed app never goes missing.
        """
        # Backdrop band: subtle surface so the carousel visually separates
        # from the widget area above it.
        self._root.append(Rect(self._x - 0, self._y, self._w, self._h,
                               fill=BG_SURFACE.value, outline=None))
        # Top divider.
        self._root.append(Rect(self._x, self._y, self._w, 1,
                               fill=BORDER.value, outline=None))
        self._root.append(self._strip)

        # Materialize every entry with its full presentation data
        # before applying order — that way the order step works on
        # one unified list regardless of whether each entry came from
        # the builtins or /sd/apps/.
        raw = []
        for scene_name, label in builtin_scenes:
            raw.append((
                "scene", scene_name,
                label or DEFAULT_LABELS.get(scene_name, scene_name),
                DEFAULT_ICONS.get(scene_name, DEFAULT_ICONS["_default"]),
            ))
        for app_name, mod in discover_apps():
            app_label = getattr(mod, "LABEL", None) if mod else None
            app_icon = getattr(mod, "ICON", None) if mod else None
            raw.append((
                "app", app_name,
                app_label or app_name,
                app_icon or DEFAULT_ICONS["_default"],
            ))

        ordered = _apply_carousel_order(raw)

        # Tile layout — tiles live inside `self._strip` at fixed
        # local-x positions. The strip's x is what moves between
        # pages; tiles themselves never need to be re-placed.
        cursor_x = TILE_GAP
        for kind, name, label, icon in ordered:
            self._add_tile(cursor_x,
                           action=(kind, name),
                           name=name,
                           label=label,
                           icon=icon)
            cursor_x += TILE_W + TILE_GAP

        # Pagination math. The visible tile area sits between the two
        # arrow zones (each ARROW_W wide). Fit as many full tiles as
        # we can; partial tiles are always pushed to the next page.
        tile_pitch = TILE_W + TILE_GAP
        usable = self._w - 2 * ARROW_W
        # A row of N tiles spans N*TILE_W + (N-1)*TILE_GAP, which we
        # bound to `usable` and solve for N:
        self._tiles_per_page = max(
            1, (usable + TILE_GAP) // tile_pitch)
        self._page_pitch_px = self._tiles_per_page * tile_pitch
        n_items = len(self._items)
        self._total_pages = max(
            1, (n_items + self._tiles_per_page - 1) // self._tiles_per_page)
        # The strip's screen-x at page 0 — tiles begin just inside the
        # left arrow zone.
        self._content_left_x = self._x + ARROW_W
        self._page = 0

        self._build_arrows()
        self._apply_page()

    # ---- arrow buttons ----------------------------------------------------

    def _build_arrows(self):
        """Always builds the arrow chrome on both sides; _apply_page
        hides whichever side isn't currently navigable. Drawn on the
        root group (not the strip) so they don't scroll with tiles."""
        inner_h = self._h - 8
        mid_y = self._y + 4

        # Left arrow.
        lx = self._x + 2
        self._left_bg = Rect(
            lx, mid_y, ARROW_W - 4, inner_h,
            fill=BG_SURFACE.value, outline=BORDER.value, stroke=1,
        )
        self._root.append(self._left_bg)
        self._left_lbl = Label(
            "<",
            root_group=self._root,
            dimensions=Dimensions(ARROW_W - 4, inner_h),
            position=Position(lx, mid_y),
            default_style=Style(
                font_size=12, font_color=ACCENT,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        self._left_rect = (self._x, self._y, ARROW_W, self._h)

        # Right arrow.
        rx = self._x + self._w - ARROW_W + 2
        self._right_bg = Rect(
            rx, mid_y, ARROW_W - 4, inner_h,
            fill=BG_SURFACE.value, outline=BORDER.value, stroke=1,
        )
        self._root.append(self._right_bg)
        self._right_lbl = Label(
            ">",
            root_group=self._root,
            dimensions=Dimensions(ARROW_W - 4, inner_h),
            position=Position(rx, mid_y),
            default_style=Style(
                font_size=12, font_color=ACCENT,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        self._right_rect = (self._x + self._w - ARROW_W, self._y,
                            ARROW_W, self._h)

    # ---- pagination -------------------------------------------------------

    def _apply_page(self):
        if self._page < 0:
            self._page = 0
        elif self._page > self._total_pages - 1:
            self._page = self._total_pages - 1
        # Slide the strip so the first tile of the current page lands
        # right after the left arrow zone.
        self._strip.x = self._content_left_x - self._page * self._page_pitch_px
        # Hide tiles not on the current page so they can't bleed into
        # view under the arrow chrome — displayio doesn't clip groups
        # so we have to clip manually.
        start = self._page * self._tiles_per_page
        end = start + self._tiles_per_page
        for i, tg in enumerate(self._tile_groups):
            tg.hidden = not (start <= i < end)
        # Show only the arrows that lead somewhere.
        show_left = self._total_pages > 1 and self._page > 0
        show_right = self._total_pages > 1 and self._page < self._total_pages - 1
        self._set_visible(self._left_bg, self._left_lbl, show_left)
        self._set_visible(self._right_bg, self._right_lbl, show_right)

    @staticmethod
    def _set_visible(bg, lbl, visible):
        if bg is not None:
            bg.hidden = not visible
        # Our Label wraps adafruit_display_text.label.Label at
        # `_text_area`; .hidden lives on the inner widget.
        if lbl is not None:
            lbl._text_area.hidden = not visible

    def next_page(self):
        if self._locked:
            return
        if self._page < self._total_pages - 1:
            self._page += 1
            self._apply_page()

    def prev_page(self):
        if self._locked:
            return
        if self._page > 0:
            self._page -= 1
            self._apply_page()

    def _add_tile(self, tile_x, action, name, label, icon):
        kind, target = action
        # Each tile lives in its own sub-Group so we can flip
        # `tile_group.hidden` per page. Children inside still use
        # strip-local coordinates so the parent group can stay at
        # (0, 0) and we don't have to re-parent on page changes.
        tile_group = displayio.Group()

        try:
            card = RoundRect(tile_x, (self._h - TILE_H) // 2,
                             TILE_W, TILE_H, 6,
                             fill=TILE_FILL.value,
                             outline=BORDER.value, stroke=1)
        except Exception:
            card = Rect(tile_x, (self._h - TILE_H) // 2,
                        TILE_W, TILE_H,
                        fill=TILE_FILL.value,
                        outline=BORDER.value, stroke=1)
        tile_group.append(card)

        # Render the icon glyph as a grid of small Rects. Each
        # non-space char in the row becomes one filled square.
        rows = icon[:5]
        glyph_w = ICON_GLYPH_PX
        glyph_total_w = max((len(r) for r in rows), default=5) * \
                        (glyph_w + ICON_GLYPH_GAP) - ICON_GLYPH_GAP
        glyph_origin_x = tile_x + (TILE_W - glyph_total_w) // 2
        glyph_origin_y = (self._h - TILE_H) // 2 + 6
        for ry, row in enumerate(rows):
            for rx, ch in enumerate(row):
                if ch == " " or ch == ".":
                    continue
                px = glyph_origin_x + rx * (glyph_w + ICON_GLYPH_GAP)
                py = glyph_origin_y + ry * (glyph_w + ICON_GLYPH_GAP)
                tile_group.append(Rect(px, py, glyph_w, glyph_w,
                                       fill=ACCENT.value, outline=None))

        text = label if len(label) <= 9 else label[:8] + "."
        lbl = Label(
            text,
            root_group=tile_group,
            dimensions=Dimensions(TILE_W, 12),
            position=Position(tile_x, (self._h - TILE_H) // 2 + TILE_H - 14),
            default_style=Style(
                font_size=12,
                font_color=TEXT_PRIMARY,
                horizontal_align=Align.Center,
                vertical_align=Align.Start,
            ),
        )
        self._tile_labels.append(lbl)
        self._tile_groups.append(tile_group)
        self._items.append((kind, target, name, label, tile_x, TILE_W))
        self._strip.append(tile_group)

    def contains(self, x, y):
        return (self._x <= x < self._x + self._w
                and self._y <= y < self._y + self._h)

    def is_locked(self):
        return self._locked

    def set_locked(self, locked):
        """Lock the launcher against interaction. Used by home while
        the agent is mid-turn so a stray tap doesn't switch scenes on
        top of a still-running send. Dims tile labels AND the arrow
        chrome so the locked state reads clearly."""
        locked = bool(locked)
        if locked == self._locked:
            return
        self._locked = locked
        tile_color = TEXT_DIM if locked else TEXT_PRIMARY
        arrow_color = TEXT_DIM if locked else ACCENT
        for lbl in self._tile_labels:
            lbl.style.font_color = tile_color
            lbl._dirty = True
            lbl.draw()
        for lbl in (self._left_lbl, self._right_lbl):
            if lbl is not None:
                lbl.style.font_color = arrow_color
                lbl._dirty = True
                lbl.draw()
        # Cancel any in-progress swipe so it doesn't resume when we
        # unlock later.
        self._drag_anchor_x = None
        self._drag_total = 0

    # ---- swipe-as-paginate ------------------------------------------------

    def begin_drag(self, x):
        if self._locked:
            return
        self._drag_anchor_x = x
        self._drag_total = 0

    def update_drag(self, x):
        if self._locked or self._drag_anchor_x is None:
            return
        # Signed delta from anchor; we don't move the strip during the
        # drag — pagination is discrete on release.
        self._drag_total = x - self._drag_anchor_x

    def end_drag(self, x):
        if self._locked:
            self._drag_anchor_x = None
            self._drag_total = 0
            return None
        anchor = self._drag_anchor_x
        delta = self._drag_total
        self._drag_anchor_x = None
        self._drag_total = 0
        if anchor is None:
            return None
        # A real swipe paginates; anything smaller is a tap and is
        # handled separately by click_at (the home scene's was_tap
        # check gates which path runs).
        if delta <= -SWIPE_THRESHOLD_PX:
            self.next_page()
        elif delta >= SWIPE_THRESHOLD_PX:
            self.prev_page()
        return None

    # ---- tap dispatch -----------------------------------------------------

    def click_at(self, x, y):
        """Hit-test a tap. Arrows take priority over tiles since they
        overlap the carousel band at the edges."""
        if self._locked or not self.contains(x, y):
            return None
        if self._hit_rect(self._left_rect, x, y):
            if self._page > 0:
                self.prev_page()
            return None
        if self._hit_rect(self._right_rect, x, y):
            if self._page < self._total_pages - 1:
                self.next_page()
            return None
        return self._hit_test_page(x)

    def _hit_test_page(self, screen_x):
        """Return the tile on the current page that contains
        screen_x, or None."""
        start = self._page * self._tiles_per_page
        end = min(len(self._items), start + self._tiles_per_page)
        local_x = screen_x - self._strip.x
        for i in range(start, end):
            item = self._items[i]
            kind, target, name, label, tile_x, tile_w = item
            if tile_x <= local_x < tile_x + tile_w:
                return item
        return None

    @staticmethod
    def _hit_rect(rect, x, y):
        if rect is None or x is None or y is None:
            return False
        rx, ry, rw, rh = rect
        return rx <= x < rx + rw and ry <= y < ry + rh
