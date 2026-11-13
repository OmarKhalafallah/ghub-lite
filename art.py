"""Hand-drawn (cairo) pictures of the two devices and the DPI rail. Original line art."""
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

INK, DECK, RIDGE, CHALK, FOG = (0.067, 0.078, 0.106), (0.098, 0.118, 0.161), (0.165, 0.192, 0.259), (0.914, 0.929, 0.961), (0.545, 0.584, 0.663)
LINE = (0.36, 0.41, 0.52)
ORCHID, MINT = (0.773, 0.545, 1.0), (0.373, 0.890, 0.725)


def rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


class Art(Gtk.DrawingArea):
    """Scales a fixed design box into whatever space it gets."""
    BOX = (200, 330)

    def __init__(self, accent, **kw):
        super().__init__(**kw)
        self.accent = accent
        self.set_draw_func(self._draw)
        self._fit = (1, 0, 0)

    def _draw(self, _area, cr, width, height):
        bw, bh = self.BOX
        scale = min(width / bw, height / bh) * 0.9
        ox, oy = (width - bw * scale) / 2, (height - bh * scale) / 2
        self._fit = (scale, ox, oy)
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        cr.set_line_join(1)
        cr.set_line_cap(1)
        self.paint(cr)

    def to_design(self, x, y):
        scale, ox, oy = self._fit
        return (x - ox) / scale, (y - oy) / scale


class MouseArt(Art):
    """Top view of the mouse. Button `highlight` glows; clicking a button calls on_pick(index)."""
    BOX = (200, 330)
    # index -> (x, y, w, h, radius); 0/1 are the main buttons, clipped to the body
    PARTS = {2: (90, 40, 20, 52, 10), 5: (91, 104, 18, 24, 6), 4: (7, 126, 14, 46, 6), 3: (7, 178, 14, 46, 6),
             0: (18, 8, 80, 134, 0), 1: (102, 8, 80, 134, 0)}

    def __init__(self, accent, on_pick=None, **kw):
        super().__init__(accent, **kw)
        self.highlight = None
        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed, on_pick)
        self.add_controller(click)

    def set_highlight(self, index):
        if index != self.highlight:
            self.highlight = index
            self.queue_draw()

    def _pressed(self, _gesture, _n, x, y, on_pick):
        dx, dy = self.to_design(x, y)
        for index, (px, py, pw, ph, _r) in self.PARTS.items():
            if px <= dx <= px + pw and py <= dy <= py + ph:
                if on_pick:
                    on_pick(index)
                return

    @staticmethod
    def _body(cr):
        cr.move_to(100, 8)
        cr.curve_to(152, 8, 182, 52, 182, 122)
        cr.curve_to(182, 230, 168, 322, 100, 322)
        cr.curve_to(32, 322, 18, 230, 18, 122)
        cr.curve_to(18, 52, 48, 8, 100, 8)
        cr.close_path()

    def paint(self, cr):
        for index in (4, 3):  # side buttons sit behind the body's edge
            self._part(cr, index)
        self._body(cr)
        cr.set_source_rgb(0.125, 0.149, 0.2)
        cr.fill()
        if self.highlight in (0, 1):
            cr.save()
            self._body(cr)
            cr.clip()
            x, y, w, h, _r = self.PARTS[self.highlight]
            cr.rectangle(x, y, w, h)
            cr.set_source_rgba(*self.accent, 0.4)
            cr.fill()
            cr.restore()
        self._body(cr)
        cr.set_source_rgb(*LINE)
        cr.set_line_width(2)
        cr.stroke()
        cr.move_to(100, 9)
        cr.line_to(100, 146)
        cr.move_to(19, 140)
        cr.curve_to(60, 150, 140, 150, 181, 140)
        cr.set_line_width(1.4)
        cr.stroke()
        for index in (2, 5):
            self._part(cr, index)

    def _part(self, cr, index):
        x, y, w, h, r = self.PARTS[index]
        lit = index == self.highlight
        if lit:
            rrect(cr, x - 3, y - 3, w + 6, h + 6, r + 3)
            cr.set_source_rgba(*self.accent, 0.25)
            cr.fill()
        rrect(cr, x, y, w, h, r)
        cr.set_source_rgb(*(self.accent if lit else INK))
        cr.fill_preserve()
        cr.set_source_rgb(*(self.accent if lit else LINE))
        cr.set_line_width(1.6)
        cr.stroke()


class HeadsetArt(Art):
    BOX = (300, 330)

    def paint(self, cr):
        cr.arc(150, 168, 116, math.pi, 2 * math.pi)  # headband
        cr.set_source_rgb(0.125, 0.149, 0.2)
        cr.set_line_width(18)
        cr.stroke()
        cr.arc(150, 168, 116, math.pi, 2 * math.pi)
        cr.set_source_rgb(*LINE)
        cr.set_line_width(2)
        cr.stroke()
        cr.arc(150, 168, 104, math.pi * 1.08, math.pi * 1.92)  # the accent line inside the band
        cr.set_source_rgba(*self.accent, 0.9)
        cr.set_line_width(2)
        cr.stroke()
        cr.move_to(32, 276)  # microphone boom
        cr.curve_to(30, 316, 70, 322, 106, 312)
        cr.set_source_rgb(*LINE)
        cr.set_line_width(4)
        cr.stroke()
        rrect(cr, 102, 304, 24, 15, 7)
        cr.set_source_rgb(*self.accent)
        cr.fill()
        for x, pad in ((12, 58), (242, 228)):  # ear cups and their cushions
            rrect(cr, x, 160, 46, 122, 20)
            cr.set_source_rgb(0.125, 0.149, 0.2)
            cr.fill_preserve()
            cr.set_source_rgb(*LINE)
            cr.set_line_width(2)
            cr.stroke()
            rrect(cr, pad, 174, 14, 94, 7)
            cr.set_source_rgb(*INK)
            cr.fill_preserve()
            cr.set_source_rgb(*LINE)
            cr.set_line_width(1.4)
            cr.stroke()


class DpiRail(Gtk.DrawingArea):
    """Every DPI step on one line, placed by where it sits in the mouse's accepted values."""

    def __init__(self, accent, count, on_pick):
        super().__init__(height_request=96, hexpand=True)
        self.accent, self.count = accent, max(2, count)
        self.steps, self.active, self.default = [], 0, 0  # steps: index into the accepted values
        self.labels = []
        self._xs = []
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, _n, x, _y: self._xs and on_pick(
            min(range(len(self._xs)), key=lambda i: abs(self._xs[i] - x))))
        self.add_controller(click)

    def update(self, steps, labels, active, default):
        self.steps, self.labels, self.active, self.default = steps, labels, active, default
        self.queue_draw()

    def _draw(self, _area, cr, width, _height):
        margin, y = 34, 52
        span = width - 2 * margin
        self._xs = [margin + span * step / (self.count - 1) for step in self.steps]
        cr.set_line_cap(1)
        cr.move_to(margin, y)
        cr.line_to(width - margin, y)
        cr.set_source_rgb(*RIDGE)
        cr.set_line_width(4)
        cr.stroke()
        right_edge = {-1: -999, 1: -999}  # where the last label above (-1) and below (1) ended
        for i, x in sorted(enumerate(self._xs), key=lambda p: p[1]):
            on = i == self.active
            cr.new_path()
            if on:
                cr.arc(x, y, 15, 0, 2 * math.pi)
                cr.set_source_rgba(*self.accent, 0.22)
                cr.fill()
            cr.arc(x, y, 8 if on else 6, 0, 2 * math.pi)
            cr.set_source_rgb(*(self.accent if on else DECK))
            cr.fill_preserve()
            cr.set_source_rgb(*(self.accent if on else FOG))
            cr.set_line_width(2)
            cr.stroke()
            layout = self.create_pango_layout(self.labels[i] + (", start" if i == self.default else ""))
            layout.set_font_description(Pango.FontDescription("Bold 9" if on else "9"))
            text_width, text_height = layout.get_pixel_size()
            left = x - text_width / 2
            side = -1 if left > right_edge[-1] + 8 else 1
            if left <= right_edge[side] + 8 and not on:
                continue  # no room on either side: the row below still shows this step's value
            right_edge[side] = left + text_width
            cr.new_path()
            cr.move_to(x - text_width / 2, y - 18 - text_height if side < 0 else y + 18)
            cr.set_source_rgb(*(CHALK if on else FOG))
            PangoCairo.show_layout(cr, layout)
