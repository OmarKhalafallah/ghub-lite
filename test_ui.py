"""Drives the whole window with stand-in devices and checks what it sends. No hardware touched.

Run it with ./test_ui.sh (a headless display, so it also works with the screen locked).
    ./test_ui.sh                 behaviour checks
    ./test_ui.sh pictures/       also save a picture of each screen there
    ./test_ui.sh pictures/ narrow    pictures of the narrow-window layout instead
"""
import os
import sys
import tempfile

out = sys.argv[1] if len(sys.argv) > 1 else None
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # never the real settings
import ghub, g533, mouse, audio, eq, macros
macros.helper_running = lambda: True
from gi.repository import GLib, Gtk, Gio, Gdk, Graphene

log, checks, result = [], [], [1]
def check(name, ok): checks.append((name, bool(ok)))

class FakeMouse:
    state = dict(dpis=[400, 800, 1600, 3200], active=1, default=1, rate=1000,
                 buttons=[(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), mouse.ACTIONS[5][1]])
    def __init__(self):
        s = FakeMouse.state
        self.dpis, self.active, self.default, self.rate = list(s["dpis"]), s["active"], s["default"], s["rate"]
        self.buttons = list(s["buttons"]); self.rates = [125, 250, 500, 1000]
        self.allowed = sorted(set(list(range(200, 1001, 50)) + list(range(1100, 2601, 100)) + list(range(2800, 5001, 200)) + list(range(5500, 12001, 500))))
    def on_resync(self, cb): pass
    def apply(self, dpis, active, default, rate, buttons):
        mouse.check_buttons(buttons)
        log.append(("apply", dpis, active, default, rate, buttons))
        FakeMouse.state = dict(dpis=dpis, active=active, default=default, rate=rate, buttons=buttons)
mouse.Mouse = FakeMouse
mouse.battery = lambda: "Normal"
g533.battery = lambda: (64, False)
g533.set_sidetone = lambda v: log.append(("sidetone", v))
g533.set_auto_off = lambda v: log.append(("auto_off", v))
audio.volumes = lambda: {"sink": 76, "source": 100}
audio.set_volume = lambda kind, v: log.append(("volume", kind, v))
eq_on = [False]
eq.is_enabled = lambda: eq_on[0]
eq.enable = lambda g: (log.append(("eq.enable", list(g))), eq_on.__setitem__(0, True))
eq.disable = lambda: (log.append(("eq.disable",)), eq_on.__setitem__(0, False))
eq.set_gains = lambda g: log.append(("eq.set_gains", list(g)))

NARROW = len(sys.argv) > 2
if NARROW:  # open the window narrow from the start, to see the small-window layout
    _present = ghub.Adw.ApplicationWindow.present
    def present(win):
        win.set_default_size(520, 760); _present(win)
    ghub.Adw.ApplicationWindow.present = present
app = ghub.App(); app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.connect('startup', lambda a: Gtk.Settings.get_default().set_property('gtk-xft-dpi', 96 * 1024))
toasts = []
def find(widget, kind, found):
    if isinstance(widget, kind): found.append(widget)
    child = widget.get_first_child()
    while child:
        find(child, kind, found); child = child.get_next_sibling()
    return found
tries = {}
def shot(name, w=None):
    if not out:
        return
    win = app.props.active_window
    content = win.get_content()
    while content.get_parent() is not win:  # the outermost child also holds open dialogs
        content = content.get_parent()
    probe = Gtk.Snapshot()
    content.get_parent().snapshot_child(content, probe)
    if probe.to_node() is None:  # layout still pending in the headless display: try again next tick
        tries[name] = tries.get(name, 0) + 1
        if tries[name] < 15:
            win.queue_resize(); steps.insert(0, lambda: shot(name))
        return
    snap = Gtk.Snapshot()
    ink = Gdk.RGBA(); ink.parse("#11141b")
    snap.append_color(ink, Graphene.Rect().init(0, 0, win.get_width(), win.get_height()))
    content.get_parent().snapshot_child(content, snap)
    win.get_native().get_renderer().render_texture(snap.to_node(), None).save_to_png(os.path.join(out, name + ".png"))
steps = []
def run():
    if not steps:
        app.quit(); return False
    try: steps.pop(0)()
    except Exception:
        import traceback; traceback.print_exc(); result[0] = 1; app.quit(); return False
    return True
def setup():
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
    win = app.props.active_window
    nav = find(win, ghub.Adw.NavigationView, [])[0]
    overlay = find(win, ghub.Adw.ToastOverlay, [])[0]
    mp = next(b for b in find(win, Gtk.Button, []) if b.has_css_class("stage") and b.has_css_class("mouse"))
    hp = next(b for b in find(win, Gtk.Button, []) if b.has_css_class("stage") and b.has_css_class("headset"))
    P = {}
    def open_mouse():
        mp.emit("clicked"); P["m"] = nav.get_visible_page()
    def edit_mouse():
        m = P["m"]
        check("apply bar hidden before edits", not m.view.get_reveal_bottom_bars())
        def wheel(w):
            n = sum(1 for c in w.observe_controllers() if isinstance(c, Gtk.EventControllerScroll) and c.get_propagation_phase() != Gtk.PropagationPhase.NONE)
            child = w.get_first_child()
            while child: n += wheel(child); child = child.get_next_sibling()
            return n
        P["wheel"] = wheel
        check("the wheel cannot move a DPI slider", wheel(Gtk.Scale()) > 0 and not any(wheel(s) for s in m.scales))
        m.scales[0].set_value(m.mouse.allowed.index(450)); m.radios[2].set_active(True)
        m.default_row.set_selected(0); m.rate_buttons[2].set_active(True)
        check("apply bar shown after edits", m.view.get_reveal_bottom_bars())
    def buttons_tab():
        m = P["m"]; m.tabs.set_visible_child_name("buttons")
        check("custom switch off on a stock mouse, rows locked", not m.custom.get_active() and not m.rows[3].get_sensitive())
        m.custom.set_active(True)
        check("switch alone sends nothing", not any(e[0] == "apply" for e in log) and m.rows[3].get_sensitive())
        m.rows[3].set_selected(6)            # Back side button -> DPI up
        m._key_pressed(None, 0, 46 + 8, Gdk.ModifierType.CONTROL_MASK, 4, ghub.Adw.AlertDialog()); m._show_map(4)  # Forward -> Ctrl+C
        m.picture.set_highlight(4)
        check("key shown on row", m.rows[4].get_subtitle() == "Ctrl + C" and m.rows[4].get_selected() == ghub.KEY_ITEM)
    def bad_apply():
        m = P["m"]; keep = m.maps[0]
        m.rows[0].set_selected(1)            # left button -> right click: no left click left
        n = len(log); m.apply_button.emit("clicked")
        check("refuses to drop left click", len(log) == n and m.mouse is not None and m.maps[3] == mouse.ACTIONS[6][1])
        m.rows[0].set_selected(0)
    def good_apply(): P["m"].apply_button.emit("clicked")
    def after_apply():
        m = P["m"]; a = [e for e in log if e[0] == "apply"]
        check("apply sent once with all edits", len(a) == 1 and a[0][1:5] == ([450, 800, 1600, 3200], 2, 0, 500)
              and a[0][5][3] == mouse.ACTIONS[6][1] and a[0][5][4] == (mouse.KEYS, (29, 46)))
        check("page reloaded with saved values", m.mouse is not None and m.mouse.dpis[0] == 450 and not m.view.get_reveal_bottom_bars()
              and m.rows[4].get_subtitle() == "Ctrl + C" and m.radios[2].get_active())
        check("still on the Buttons tab after saving", m.tabs.get_visible_child_name() == "buttons")
    def record():
        m = P["m"]; m._record(5); dialog, keys = m.recorder
        check("home card shows the DPI the mouse holds", m.card_status.get_label() == "1600 DPI, battery normal")
        for sig, code in (("key-pressed", 35), ("key-pressed", 35), ("key-released", 35), ("key-pressed", 23), ("key-released", 23),
                          ("key-pressed", 1), ("key-pressed", 30)):   # H (held, repeating), I, Esc, then A after the end
            keys.emit(sig, 0, code + 8, 0)
        P["dialog"] = dialog
    def save_macro():
        m = P["m"]; P["dialog"].emit("response", "save"); P["dialog"].close(); m._show_map(5)
        check("macro recorded and shown", m.maps[5] == (macros.MACRO, ((1, 35), (2, 35), (1, 23), (2, 23))) and m.rows[5].get_subtitle() == "H, I"
              and m.rows[5].get_selected() == ghub.MACRO_ITEM and m.view.get_reveal_bottom_bars())
        m.apply_button.emit("clicked")
    def after_macro():
        m = P["m"]; a = [e for e in log if e[0] == "apply"]
        check("macro saved as a spare key plus a table for the helper", a[-1][5][5] == (mouse.KEYS, (189,))
              and m.config["macros"] == {"189": [[1, 35], [2, 35], [1, 23], [2, 23]]})
        check("macro shown again after reload", m.maps[5][0] == macros.MACRO and m.rows[5].get_subtitle() == "H, I")
        m.custom.set_active(False)
        check("switching off asks to save", m.view.get_reveal_bottom_bars())
        m.apply_button.emit("clicked")
    def after_off():
        m = P["m"]; a = [e for e in log if e[0] == "apply"]
        check("off puts the normal buttons in the mouse", a[-1][5] == mouse.DEFAULT_BUTTONS and m.config["macros"] == {})
        check("custom set kept while off", not m.custom.get_active() and m.maps[5][0] == macros.MACRO
              and m.maps[4] == (mouse.KEYS, (29, 46)) and not m.rows[4].get_sensitive())
        m.custom.set_active(True); m.apply_button.emit("clicked")
    def after_on():
        m = P["m"]; a = [e for e in log if e[0] == "apply"]
        check("on brings the custom set back", a[-1][5][4] == (mouse.KEYS, (29, 46)) and a[-1][5][5] == (mouse.KEYS, (189,))
              and m.custom.get_active() and "189" in m.config["macros"])
        shot("f3c-buttons-macro")
        m.tabs.set_visible_child_name("sensitivity")
    def discard():
        m = P["m"]; m.scales[1].set_value(0)
        check("bar back after new edit", m.view.get_reveal_bottom_bars())
        m._reload()
    def after_discard():
        m = P["m"]; check("discard restores", m.mouse.allowed[int(m.scales[1].get_value())] == 800 and not m.view.get_reveal_bottom_bars())
        m.scales[3].set_value(m.mouse.allowed.index(2400))   # leave an edit so the bar is in the picture
    def open_headset():
        nav.pop(); hp.emit("clicked"); P["h"] = nav.get_visible_page()
    def edit_headset():
        h = P["h"]
        check("the wheel cannot move a headset control", not any(P["wheel"](w) for w in list(h.sliders.values()) + h.bands + [h.auto_off]))
        check("volumes shown from system", h.sliders["sink"].get_value() == 76 and h.sliders["source"].get_value() == 100)
        check("showing system values sent nothing", not [e for e in log if e[0] in ("volume", "sidetone", "eq.set_gains", "eq.enable")])
        for v in (30, 40, 50): h.sliders["sink"].set_value(v)
        h.sliders["sidetone"].set_value(35)
        h.preset_row.set_selected(h.presets.index("Bass boost"))
        h.eq_switch.set_active(True)
    def after_headset():
        h = P["h"]
        check("one volume command after a drag", [e for e in log if e[0] == "volume"] == [("volume", "sink", 50)])
        check("sidetone sent and remembered", ("sidetone", 35) in log and h.config.get("sidetone") == 35)
        check("preset sent gains", ("eq.set_gains", [6.0, 5.0, 4.0, 2.0, 0, 0, 0, 0, 0, 0]) in log)
        check("switch enabled equalizer with those gains", ("eq.enable", [6.0, 5.0, 4.0, 2.0, 0, 0, 0, 0, 0, 0]) in log and h.eq_switch.get_active() and h.eq_switch.get_sensitive())
        h.bands[9].set_value(3)
        check("moving a band shows Custom", h.presets[h.preset_row.get_selected()] == "Custom")
    def cinematic():
        del log[:]; P["h"].profile_row.set_selected(1)
    def after_cinematic():
        h = P["h"]; film = [float(g) for g in eq.PRESETS["Cinematic"]]
        check("Cinematic sends its sound, no sidetone, long switch-off", ("eq.set_gains", film) in log and ("sidetone", 0) in log and ("auto_off", 30) in log
              and h.presets[h.preset_row.get_selected()] == "Cinematic")
        check("own settings kept aside", h.config["profile"] == "Cinematic" and h.config["mine"]["sidetone"] == 35 and h.config["mine"]["eq"][9] == 3)
        del log[:]; h.profile_row.set_selected(0)
    def after_mine():
        h = P["h"]
        check("My settings puts everything back", ("sidetone", 35) in log and h.bands[0].get_value() == 6 and h.bands[9].get_value() == 3
              and ("eq.set_gains", [6.0, 5.0, 4.0, 2.0, 0, 0, 0, 0, 0, 3.0]) in log and h.config["profile"] == "My settings")
        h.profile_row.set_selected(1)   # leave Cinematic on for the picture
        h.busy = False; h.refresh()
    def card():
        check("home card names the profile", P["h"].card_status.get_label() == "Cinematic, battery 64%")
    def narrow():
        win.set_default_size(560, 700)
    def report():
        for name, ok in checks: print("PASS" if ok else "FAIL", name)
        failed = sum(1 for _n, ok in checks if not ok)
        print("failed:", failed, "of", len(checks))
        result[0] = 1 if failed else 0
    wait = lambda: None
    if NARROW:
        steps.extend([lambda: shot("n1-home"), open_mouse, wait, lambda: shot("n2-mouse"),
                      lambda: P["m"].tabs.set_visible_child_name("buttons"), wait, lambda: shot("n3-buttons"),
                      open_headset, wait, wait, lambda: shot("n4-headset")])
        GLib.timeout_add(700, run)
        return False
    steps.extend([lambda: shot("f1-home"), open_mouse, wait, edit_mouse, lambda: shot("f2-sensitivity"), buttons_tab, wait, wait, lambda: shot("f3-buttons"),
                  bad_apply, good_apply, wait, after_apply, record, wait, lambda: shot("f3b-macro"), save_macro, wait, after_macro, wait, after_off, wait, after_on, discard, wait, after_discard, open_headset, wait, edit_headset, wait,
                  after_headset, wait, cinematic, wait, after_cinematic, wait, after_mine, wait, card, lambda: shot("f4-headset"), narrow, wait, lambda: shot("f5-narrow-headset"),
                  lambda: nav.pop(), wait, lambda: shot("f6-narrow-home"), report])
    GLib.timeout_add(700, run)
    return False
GLib.timeout_add(3000, setup)
app.run([])
sys.exit(0 if NARROW else result[0])
