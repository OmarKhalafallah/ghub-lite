#!/usr/bin/env python3
"""G Hub Lite: settings window for a Logitech G305 mouse and G533 headset."""
import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

import art  # noqa: E402
import audio  # noqa: E402
import eq  # noqa: E402
import g533  # noqa: E402
import macros  # noqa: E402
import mouse  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(GLib.get_user_config_dir(), "ghub-lite.json")
EQ_LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
KEY_ITEM, MACRO_ITEM, OFF_ITEM, ASIS_ITEM = range(len(mouse.ACTIONS), len(mouse.ACTIONS) + 4)
# Built-in headset profiles: equalizer preset, sidetone, minutes of silence before it switches off.
# Cinematic: no sidetone (the room stays out of the film), and a long pause does not switch it off.
PROFILES = {"Cinematic": ("Cinematic", 0, 30)}


def load_config():
    try:
        with open(CONFIG) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def known(mapping):
    """Can the Buttons page show this mapping?"""
    return (mapping[0] in (mouse.KEYS, macros.MACRO, mouse.OFF, mouse.UNKNOWN)
            or any(mapping == action for _label, action in mouse.ACTIONS))


def maps_from_json(data, count):
    """The custom button set kept in the settings file, or None when it is missing or damaged."""
    try:
        # lists when read from the file, tuples when still in memory from this run
        maps = [(int(kind), tuple(tuple(e) if isinstance(e, (list, tuple)) else int(e) for e in value)
                 if isinstance(value, (list, tuple)) else int(value)) for kind, value in data]
    except (TypeError, ValueError):
        return None
    return maps if len(maps) == count and all(known(m) for m in maps) else None


def macro_label(events):
    """((1, 35), (2, 35), (1, 23), (2, 23)) -> 'H, I'."""
    return ", ".join(mouse.key_label((code,)) for kind, code in events if kind == macros.PRESS)


def bg(work, done):
    """Run work() off the UI thread, then done(result_or_exception) on it."""
    def run():
        try:
            result = work()
        except Exception as e:  # shown to the user by done()
            result = e
        GLib.idle_add(done, result)
    threading.Thread(target=run, daemon=True).start()


def name_for(widget, text):
    """What a screen reader calls a control that has no visible label of its own."""
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])


def no_scroll(widget):
    """The wheel scrolls the page, never a value that happens to be under the pointer."""
    for controller in widget.observe_controllers():
        if isinstance(controller, Gtk.EventControllerScroll):
            controller.set_propagation_phase(Gtk.PropagationPhase.NONE)
    child = widget.get_first_child()
    while child:  # a spin row keeps its wheel handling on an inner widget
        no_scroll(child)
        child = child.get_next_sibling()


def slider_row(title, subtitle, top, value):
    row = Adw.ActionRow(title=title, subtitle=subtitle, title_lines=1)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, top, 1)
    scale.set_value(value)
    no_scroll(scale)
    scale.set_size_request(180, -1)
    scale.set_hexpand(True)
    scale.set_valign(Gtk.Align.CENTER)
    name_for(scale, title)
    number = Gtk.Label(label=str(int(value)), width_chars=4, xalign=1, css_classes=["dim", "numeric"])
    scale.connect("value-changed", lambda s: number.set_label(str(int(s.get_value()))))
    row.add_suffix(scale)
    row.add_suffix(number)
    return row, scale


class DevicePage(Adw.NavigationPage):
    """One device: its stage on the home screen, and the page behind it."""
    KIND, NAME, ICON, ACCENT, ART = "", "", "", art.ORCHID, art.Art

    def __init__(self, toast, nav, config):
        super().__init__(title=self.NAME, tag=self.KIND)
        self.toast, self.nav, self.config = toast, nav, config  # config: one dict shared by both pages
        self.busy = False  # a refresh is in flight; skip the next tick
        self.narrow_hides = []  # the side picture on the device page goes when the window gets narrow
        self.add_css_class(self.KIND)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.status = Adw.StatusPage(icon_name=self.ICON, title=self.NAME)
        self.stack.add_named(self.status, "status")
        self.view = Adw.ToolbarView(content=self.stack)
        self.header = Adw.HeaderBar()
        self.view.add_top_bar(self.header)
        self.set_child(self.view)

        # the stage on the home screen
        self.card_status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim"])
        self.card_battery = Gtk.LevelBar(css_classes=["battery"], visible=False)
        name_for(self.card_battery, f"{self.NAME} battery")
        picture = self.ART(self.ACCENT, vexpand=True, can_target=False)
        picture.set_content_height(160)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for child in (picture, Gtk.Label(label=self.NAME, xalign=0, css_classes=["device-name"]),
                      self.card_status, self.card_battery):
            box.append(child)
        self.card = Gtk.Button(child=box, hexpand=True, vexpand=True, css_classes=["stage", self.KIND])
        self.card.connect("clicked", lambda _b: nav.push(self))
        self.missing("Looking for it…")

    def art_pane(self, picture):
        picture.set_size_request(300, -1)
        pane = Gtk.Box(css_classes=["art-pane"])
        pane.append(picture)
        self.narrow_hides.append(pane)
        return pane

    def missing(self, text):
        self.status.set_description(GLib.markup_escape_text(text))
        self.stack.set_visible_child_name("status")
        self.card_status.set_label(text.split(". ")[0].rstrip("."))
        self.card_battery.set_visible(False)

    def save(self):
        try:
            with open(CONFIG, "w") as f:
                json.dump(self.config, f)
        except OSError as e:
            self.toast(f"Could not remember the setting: {e.strerror}")

    def ready(self, summary, fraction):
        self.stack.set_visible_child_name("controls")
        self.card_status.set_label(summary)
        self.card_battery.set_visible(fraction is not None)
        self.card_battery.set_value(fraction or 0)


class MousePage(DevicePage):
    KIND, NAME, ICON, ACCENT, ART = "mouse", "G305", "input-mouse-symbolic", art.ORCHID, art.MouseArt

    def __init__(self, toast, nav, config):
        super().__init__(toast, nav, config)
        self.mouse = None
        self.generation = 0  # bumped whenever what we read may be out of date
        self.loading = False

        self.picture = art.MouseArt(self.ACCENT, on_pick=self._picked)
        self.tabs = Adw.ViewStack(hexpand=True)
        body = Gtk.Box()
        body.append(self.art_pane(self.picture))
        body.append(self.tabs)
        self.stack.add_named(body, "controls")
        self.header.set_title_widget(Adw.ViewSwitcher(stack=self.tabs, policy=Adw.ViewSwitcherPolicy.WIDE))

        # appears only while there is something to save
        self.apply_button = Gtk.Button(label="Apply to mouse", css_classes=["suggested-action", "pill"])
        self.apply_button.connect("clicked", self._apply)
        discard = Gtk.Button(label="Discard", css_classes=["pill"])
        discard.connect("clicked", lambda _b: self._reload())
        bar = Gtk.Box(spacing=12, css_classes=["apply-bar"])
        bar.append(Gtk.Label(label="Changes are saved in the mouse itself.", xalign=0, hexpand=True,
                             wrap=True, css_classes=["dim"]))
        bar.append(discard)
        bar.append(self.apply_button)
        self.view.add_bottom_bar(bar)
        self.view.set_reveal_bottom_bars(False)

    # ---- reading the mouse
    def refresh(self):
        if self.busy:
            return
        self.busy = True
        generation = self.generation
        bg(lambda: (mouse.Mouse(), mouse.battery()), lambda r: self._loaded(r, generation))

    def _loaded(self, result, generation):
        self.busy = False
        if generation != self.generation:  # read started before an apply finished
            self.refresh()
            return
        if isinstance(result, Exception):
            self.mouse = None
            self.view.set_reveal_bottom_bars(False)
            self.missing(str(result))
            return
        fresh, battery = result
        if self.mouse is None:  # never rebuild while shown: that would wipe unsaved edits
            self.mouse = fresh
            fresh.on_resync(lambda: GLib.idle_add(self._resync))
            self._build()
        if battery == "Unknown":  # what the kernel says while the mouse sleeps
            battery = None
        self.battery_row.set_subtitle(battery or "Not reported while the mouse sleeps")
        dpi = f"{self.mouse.dpis[self.mouse.active]} DPI"  # what the mouse holds, not unsaved edits
        self.ready(f"{dpi}, battery {battery.lower()}" if battery else dpi, mouse.battery_fraction(battery))

    # ---- building the controls from a fresh snapshot
    def _build(self):
        m = self.mouse
        self.loading = True
        shown = self.tabs.get_visible_child_name()  # stay on the tab the user was on, e.g. after Apply
        for name in ("sensitivity", "buttons"):
            old = self.tabs.get_child_by_name(name)
            if old:
                self.tabs.remove(old)
        held = [b if known(b) else (mouse.UNKNOWN, 0) for b in macros.decode(m.buttons, self.config.get("macros"))]
        # the switch is not stored anywhere: it is on when the mouse holds anything but the normal set
        self.custom_on = held != mouse.DEFAULT_BUTTONS[:len(held)]
        kept = maps_from_json(self.config.get("buttons"), len(held))
        self.maps = held if self.custom_on or not kept else kept
        self.tabs.add_titled_with_icon(self._sensitivity(m), "sensitivity", "Sensitivity",
                                       "preferences-desktop-display-symbolic")
        self.tabs.add_titled_with_icon(self._buttons(m), "buttons", "Buttons", "input-mouse-symbolic")
        self.tabs.set_visible_child_name(shown or "sensitivity")
        self.loading = False
        self.saved = self._state(), list(self.maps)
        self._touched()

    def _sensitivity(self, m):
        page = Adw.PreferencesPage()
        top = Adw.PreferencesGroup(title="DPI steps", description="The DPI button on the mouse moves through these.")
        self.rail = art.DpiRail(self.ACCENT, len(m.allowed), lambda i: self.radios[i].set_active(True))
        frame = Gtk.Box(css_classes=["rail"])
        frame.append(self.rail)
        top.add(frame)
        page.add(top)

        steps = Adw.PreferencesGroup()
        self.scales, self.radios = [], []
        for i, value in enumerate(m.dpis):
            row = Adw.ActionRow(title=f"Step {i + 1}", title_lines=1)
            radio = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=i == m.active,
                                    tooltip_text="Use this step now")
            name_for(radio, f"Use step {i + 1} now")
            if self.radios:
                radio.set_group(self.radios[0])
            radio.connect("toggled", lambda r: r.get_active() and self._touched())
            # the scale moves through the exact values the mouse accepts, not through raw numbers
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, len(m.allowed) - 1, 1)
            scale.set_value(m.allowed.index(mouse.snap(value, m.allowed)))
            no_scroll(scale)
            scale.set_size_request(180, -1)
            scale.set_hexpand(True)
            scale.set_valign(Gtk.Align.CENTER)
            name_for(scale, f"Step {i + 1} DPI")
            number = Gtk.Label(xalign=1, css_classes=["dpi-value"])
            scale.connect("value-changed", self._dpi_moved, number)
            self._dpi_moved(scale, number)
            row.add_prefix(radio)
            row.add_suffix(scale)
            row.add_suffix(number)
            steps.add(row)
            self.scales.append(scale)
            self.radios.append(radio)
        self.default_row = Adw.ComboRow(
            title="Step when the mouse switches on",
            model=Gtk.StringList.new([f"Step {i + 1}" for i in range(len(m.dpis))]))
        self.default_row.set_selected(m.default)
        self.default_row.connect("notify::selected", lambda *_: self._touched())
        steps.add(self.default_row)
        page.add(steps)

        rate = Adw.PreferencesGroup(
            title="Polling rate",
            description="How often the mouse reports its position. Higher feels smoother and uses more battery.")
        row = Adw.ActionRow(title="Rate", title_lines=1)
        linked = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        self.rate_buttons = []
        for value in m.rates:
            button = Gtk.ToggleButton(label=f"{value} Hz", active=value == m.rate)
            if self.rate_buttons:
                button.set_group(self.rate_buttons[0])
            button.connect("toggled", lambda b: b.get_active() and self._touched())
            linked.append(button)
            self.rate_buttons.append(button)
        row.add_suffix(linked)
        rate.add(row)
        page.add(rate)

        info = Adw.PreferencesGroup()
        self.battery_row = Adw.ActionRow(title="Battery")
        info.add(self.battery_row)
        page.add(info)
        return page

    def _buttons(self, _m):
        page = Adw.PreferencesPage()
        self.custom = Gtk.Switch(valign=Gtk.Align.CENTER, active=self.custom_on)
        name_for(self.custom, "Custom buttons")
        self.custom.connect("notify::active", self._custom_toggled)
        group = Adw.PreferencesGroup(
            title="Custom buttons", header_suffix=self.custom,
            description="Off: every button does its normal job. On: the buttons do what you choose here. "
                        "Your choices are kept while it is off.")
        self.rows, self.key_buttons = [], []
        for i, name in enumerate(mouse.PHYSICAL[:len(self.maps)]):
            labels = [label for label, _a in mouse.ACTIONS] + ["Keyboard key…", "Macro…", "Off"]
            if self.maps[i][0] == mouse.UNKNOWN:
                labels.append("As it is now")
            row = Adw.ComboRow(title=name, model=Gtk.StringList.new(labels), subtitle_lines=1,
                               sensitive=self.custom_on)
            again = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Choose other keys", css_classes=["flat"])
            again.connect("clicked", lambda _b, i=i: self._ask_keys(i, self.maps[i][0]))
            row.add_suffix(again)
            hover = Gtk.EventControllerMotion()
            hover.connect("enter", lambda _c, _x, _y, i=i: self.picture.set_highlight(i))
            hover.connect("leave", lambda _c: self.picture.set_highlight(None))
            row.add_controller(hover)
            focus = Gtk.EventControllerFocus()
            focus.connect("enter", lambda _c, i=i: self.picture.set_highlight(i))
            row.add_controller(focus)
            row.connect("notify::selected", self._action_chosen, i)
            group.add(row)
            self.rows.append(row)
            self.key_buttons.append(again)
            self._show_map(i)
        page.add(group)
        return page

    # ---- editing
    def _dpi_moved(self, scale, number):
        number.set_label(str(self.mouse.allowed[int(scale.get_value())]))
        self._touched()

    def _picked(self, index):
        if self.mouse and index < len(self.rows):
            self.tabs.set_visible_child_name("buttons")
            self.rows[index].grab_focus()

    def _show_map(self, i):
        kind, value = self.maps[i]
        was, self.loading = self.loading, True
        if kind == mouse.KEYS:
            self.rows[i].set_selected(KEY_ITEM)
        elif kind == macros.MACRO:
            self.rows[i].set_selected(MACRO_ITEM)
        elif kind == mouse.OFF:
            self.rows[i].set_selected(OFF_ITEM)
        elif kind == mouse.UNKNOWN:
            self.rows[i].set_selected(ASIS_ITEM)
        else:
            self.rows[i].set_selected(next(n for n, (_l, a) in enumerate(mouse.ACTIONS) if a == (kind, value)))
        self.rows[i].set_subtitle(mouse.key_label(value) if kind == mouse.KEYS
                                  else macro_label(value) if kind == macros.MACRO else "")
        self.key_buttons[i].set_visible(kind in (mouse.KEYS, macros.MACRO))
        self.loading = was

    def _action_chosen(self, row, _param, i):
        if self.loading:
            return
        chosen = row.get_selected()
        if chosen in (KEY_ITEM, MACRO_ITEM):
            self._ask_keys(i, macros.MACRO if chosen == MACRO_ITEM else mouse.KEYS)
            return
        self.maps[i] = (mouse.ACTIONS[chosen][1] if chosen < KEY_ITEM
                        else (mouse.OFF, 0) if chosen == OFF_ITEM else (mouse.UNKNOWN, 0))
        self._show_map(i)
        self._touched()

    def _custom_toggled(self, switch, _param):
        for row in self.rows:
            row.set_sensitive(switch.get_active())
        self._touched()

    def _ask_keys(self, i, kind):
        (self._record if kind == macros.MACRO else self._capture)(i)

    def _record(self, i):
        """Records key presses and releases in order. Esc ends it, so the keyboard can reach Save."""
        events, recording = [], [True]
        shown = Gtk.Label(label="Nothing typed yet", wrap=True, css_classes=["dim"])
        dialog = Adw.AlertDialog(
            heading="Record a macro", extra_child=shown,
            body="Type the keys in order. Press Esc when you are finished, then choose Save.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("save", False)

        def key(_controller, _keyval, keycode, _state, kind):
            if not recording[0]:
                return False
            if keycode - 8 == 1:  # Esc
                recording[0] = False
                dialog.set_body("Recording finished. Choose Save, or Cancel to keep the button as it was.")
                return True
            events.append((kind, keycode - 8))
            text = macro_label(macros.clean(events))
            shown.set_label(text or "Nothing typed yet")
            dialog.set_response_enabled("save", bool(text))
            return True

        def response(_dialog, name):
            if name == "save":
                self.maps[i] = (macros.MACRO, macros.clean(events))
                self._touched()
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", key, macros.PRESS)
        keys.connect("key-released", key, macros.RELEASE)
        dialog.add_controller(keys)
        dialog.connect("response", response)
        dialog.connect("closed", lambda _d: self._show_map(i))  # shows the macro, or puts the old choice back
        dialog.present(self)
        self.recorder = dialog, keys

    def _capture(self, i):
        dialog = Adw.AlertDialog(heading="Press a key",
                                 body="Hold Ctrl, Shift, Alt or Super with it to make a shortcut.")
        dialog.add_response("cancel", "Cancel")
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key_pressed, i, dialog)
        dialog.add_controller(keys)
        dialog.connect("closed", lambda _d: self._show_map(i))  # shows the new key, or puts the old choice back
        dialog.present(self)

    def _key_pressed(self, _controller, _keyval, keycode, state, i, dialog):
        code = keycode - 8  # X11/Wayland key codes are the kernel's plus 8
        if code in mouse.MODIFIERS:
            return True  # wait for the real key
        held = [c for mask, c in ((Gdk.ModifierType.CONTROL_MASK, 29), (Gdk.ModifierType.SHIFT_MASK, 42),
                                  (Gdk.ModifierType.ALT_MASK, 56), (Gdk.ModifierType.SUPER_MASK, 125))
                if state & mask]
        self.maps[i] = (mouse.KEYS, tuple(held + [code]))
        self._touched()
        dialog.close()
        return True

    def _state(self):
        m = self.mouse
        return ([m.allowed[int(s.get_value())] for s in self.scales],
                next((i for i, r in enumerate(self.radios) if r.get_active()), m.active),
                self.default_row.get_selected(),
                next((v for v, b in zip(m.rates, self.rate_buttons) if b.get_active()), m.rate),
                list(self.maps) if self.custom.get_active() else mouse.DEFAULT_BUTTONS[:len(self.maps)])

    def _touched(self):
        if self.loading or not self.mouse:
            return
        dpis, active, default, _rate, _maps = state = self._state()
        self.rail.update([self.mouse.allowed.index(d) for d in dpis], [str(d) for d in dpis], active, default)
        self.view.set_reveal_bottom_bars((state, list(self.maps)) != self.saved)

    # ---- saving
    def _apply(self, _button):
        m, state = self.mouse, self._state()
        buttons, table = macros.encode(state[4])  # a macro goes into the mouse as a spare key
        try:
            mouse.check_buttons(buttons)  # nothing has been written yet, so keep the edits on screen
        except mouse.MouseError as e:
            self.toast(str(e))
            return
        self.apply_button.set_sensitive(False)
        chosen = list(self.maps)

        def work():
            m.apply(*state[:4], buttons)
            return not table or macros.helper_running()
        bg(work, lambda result: self._applied(result, chosen, table))

    def _applied(self, result, chosen, table):
        self.apply_button.set_sensitive(True)
        if isinstance(result, Exception):
            self.toast(str(result))
        else:
            self.config["buttons"], self.config["macros"] = chosen, table
            self.save()
            self.toast("Saved to the mouse" if result else
                       "Saved, but macros need their helper. Run install.sh once more.")
        self._reload()

    def _resync(self):
        self.toast("The mouse did not accept the last change")
        self._reload()

    def _reload(self):
        """Throw away our snapshot and show what the mouse really holds."""
        self.generation += 1
        self.mouse = None
        self.view.set_reveal_bottom_bars(False)
        self.refresh()


class HeadsetPage(DevicePage):
    KIND, NAME, ICON, ACCENT, ART = "headset", "G533", "audio-headset-symbolic", art.MINT, art.HeadsetArt

    def __init__(self, toast, nav, config):
        super().__init__(toast, nav, config)
        self.timers = {}
        self.loading = False
        self.eq_switching = False  # an on/off is in flight: refresh must not flip the switch back
        page = Adw.PreferencesPage(hexpand=True)

        self.profiles = ["My settings"] + list(PROFILES)
        self.profile_row = Adw.ComboRow(
            title="Profile", subtitle="Cinematic is tuned for films: deep bass, clear speech, no sidetone",
            model=Gtk.StringList.new(self.profiles))
        if self.config.get("profile") in PROFILES:
            self.profile_row.set_selected(self.profiles.index(self.config["profile"]))
        self.profile_row.connect("notify::selected", self._profile_chosen)
        profile = Adw.PreferencesGroup()
        profile.add(self.profile_row)
        page.add(profile)

        sound = Adw.PreferencesGroup(title="Sound")
        self.sliders = {}
        for key, title, subtitle, send in (
                ("sink", "Volume", "", lambda v: audio.set_volume("sink", v)),
                ("source", "Microphone", "How loud others hear you", lambda v: audio.set_volume("source", v)),
                ("sidetone", "Sidetone", "Your own voice in your ears", g533.set_sidetone)):
            row, scale = slider_row(title, subtitle, 100, self._number("sidetone") if key == "sidetone" else 0)
            scale.connect("value-changed", self._changed, key, send)
            sound.add(row)
            self.sliders[key] = scale
        page.add(sound)

        self.eq_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        name_for(self.eq_switch, "Equalizer")
        self.eq_switch.connect("notify::active", self._eq_toggled)
        equalizer = Adw.PreferencesGroup(
            title="Equalizer", header_suffix=self.eq_switch,
            description="Shapes the sound on this computer before it reaches the headset.")
        self.presets = list(eq.PRESETS) + ["Custom"]
        self.preset_row = Adw.ComboRow(title="Preset", model=Gtk.StringList.new(self.presets))
        self.preset_row.connect("notify::selected", self._preset_chosen)
        equalizer.add(self.preset_row)
        bands = Gtk.Box(homogeneous=True, css_classes=["eq-bands"], margin_top=12)
        self.bands = []
        gains = self.config.get("eq")
        gains = gains if isinstance(gains, list) and len(gains) == len(eq.BANDS) else [0] * len(eq.BANDS)
        for label, gain in zip(EQ_LABELS, eq.clean(gains)):
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, eq.MIN_GAIN, eq.MAX_GAIN, 1)
            scale.set_inverted(True)
            no_scroll(scale)
            scale.set_has_origin(False)  # a fill from the bottom would read as 'boost' even at 0 dB
            scale.set_size_request(-1, 150)
            scale.set_value(gain)
            name_for(scale, f"{label} hertz, decibels")
            scale.connect("value-changed", self._band_moved)
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            column.append(scale)
            column.append(Gtk.Label(label=label))
            bands.append(column)
            self.bands.append(scale)
        equalizer.add(bands)
        page.add(equalizer)
        self._show_preset()

        power = Adw.PreferencesGroup(title="Power")
        self.battery_row = Adw.ActionRow(title="Battery")
        self.battery_bar = Gtk.LevelBar(css_classes=["battery"], valign=Gtk.Align.CENTER)
        self.battery_bar.set_size_request(140, -1)
        name_for(self.battery_bar, "Headset battery")
        self.battery_row.add_suffix(self.battery_bar)
        power.add(self.battery_row)
        self.auto_off = Adw.SpinRow.new_with_range(0, 90, 5)
        self.auto_off.set_title("Switch off when silent")
        self.auto_off.set_subtitle("Minutes, 0 means never")
        self.auto_off.set_value(self._number("auto_off"))
        self.auto_off.connect("notify::value", lambda r, _p: self._changed(r, "auto_off", g533.set_auto_off))
        no_scroll(self.auto_off)
        power.add(self.auto_off)
        page.add(power)
        note = Adw.PreferencesGroup(description="The headset cannot report its sidetone or switch-off time, "
                                                "so those show the last values set here.")
        page.add(note)

        body = Gtk.Box()
        body.append(self.art_pane(art.HeadsetArt(self.ACCENT)))
        body.append(page)
        self.stack.add_named(body, "controls")

    def _number(self, key):
        try:
            return float(self.config.get(key, 0))
        except (TypeError, ValueError):
            return 0

    # ---- reading the headset
    def refresh(self):
        if self.busy:
            return
        self.busy = True

        def read():
            level = g533.battery()  # raises when the headset is off: then nothing else matters
            try:
                return level, audio.volumes(), eq.is_enabled()
            except audio.AudioError:
                return level, {}, False
        bg(read, self._loaded)

    def _loaded(self, result):
        self.busy = False
        if isinstance(result, Exception):
            self.missing(str(result))
            return
        (level, charging), volumes, eq_on = result
        text = f"{level}%" + (", charging" if charging else "")
        self.battery_row.set_subtitle(text)
        self.battery_bar.set_value(level / 100)
        self.loading = True  # these come from the system, not from the user's hand
        for kind, value in volumes.items():
            if kind not in self.timers:  # not while the user is dragging it
                self.sliders[kind].set_value(value)
        if not self.eq_switching:
            self.eq_switch.set_active(eq_on)
        self.loading = False
        profile = self.config.get("profile")
        self.ready(f"{profile}, battery {text}" if profile in PROFILES else f"Battery {text}", level / 100)

    # ---- sending changes
    def _later(self, key, work, done):
        """Run work() once the control has stopped moving, so a drag sends one command, not fifty."""
        if key in self.timers:
            GLib.source_remove(self.timers[key])

        def fire():
            self.timers.pop(key, None)
            bg(work, done)
        self.timers[key] = GLib.timeout_add(350, fire)

    def _changed(self, control, key, send):
        if self.loading:
            return
        value = int(control.get_value())
        self._later(key, lambda: send(value), lambda r: self._sent(key, value, r))

    def _sent(self, key, value, result):
        if isinstance(result, Exception):
            self.toast(str(result))
        elif key in ("sidetone", "auto_off", "eq"):
            self._remember(key, value)  # only what the headset was actually sent

    def _remember(self, key, value):
        self.config[key] = value
        self.save()

    # ---- profiles
    def _profile_chosen(self, row, _param):
        name = self.profiles[row.get_selected()]
        mine = {"sidetone": int(self.sliders["sidetone"].get_value()), "auto_off": int(self.auto_off.get_value()),
                "eq": self._gains(), "eq_on": self.eq_switch.get_active()}
        if name in PROFILES:
            if self.config.get("profile") not in PROFILES:
                self.config["mine"] = mine  # leaving your own settings: keep them to come back to
            preset, sidetone, minutes = PROFILES[name]
            gains, eq_on = list(eq.PRESETS[preset]), True
        else:
            kept = self.config.get("mine")
            mine.update(kept if isinstance(kept, dict) else {})
            try:
                gains, sidetone, minutes = eq.clean(mine["eq"]), int(mine["sidetone"]), int(mine["auto_off"])
            except (audio.AudioError, TypeError, ValueError):
                return  # damaged settings file: leave everything as it is
            eq_on = bool(mine["eq_on"])
        self.config["eq"] = gains
        self._remember("profile", name)
        self.sliders["sidetone"].set_value(sidetone)  # these two send themselves when the value changes
        self.auto_off.set_value(minutes)
        self.loading = True
        for scale, gain in zip(self.bands, gains):
            scale.set_value(gain)
        self.loading = False
        self._show_preset()
        if eq_on != self.eq_switch.get_active():
            self.eq_switch.set_active(eq_on)  # starts it with these gains, or stops it
        elif eq_on:
            self._send_gains()

    # ---- equalizer
    def _gains(self):
        return [s.get_value() for s in self.bands]

    def _show_preset(self):
        gains = tuple(self._gains())
        name = next((n for n, g in eq.PRESETS.items() if tuple(map(float, g)) == gains), "Custom")
        was, self.loading = self.loading, True
        self.preset_row.set_selected(self.presets.index(name))
        self.loading = was

    def _preset_chosen(self, row, _param):
        name = self.presets[row.get_selected()]
        if self.loading or name not in eq.PRESETS:
            return
        self.loading = True
        for scale, gain in zip(self.bands, eq.PRESETS[name]):
            scale.set_value(gain)
        self.loading = False
        self._send_gains()

    def _band_moved(self, _scale):
        if not self.loading:
            self._show_preset()
            self._send_gains()

    def _send_gains(self):
        gains = self._gains()
        self._later("eq", lambda: eq.set_gains(gains), lambda r: self._sent("eq", gains, r))

    def _eq_toggled(self, switch, _param):
        if self.loading:
            return
        on, gains = switch.get_active(), self._gains()
        switch.set_sensitive(False)
        self.eq_switching = True

        def done(result):
            self.eq_switching = False
            switch.set_sensitive(True)
            if isinstance(result, Exception):
                self.toast(str(result))
                self.loading = True
                switch.set_active(not on)
                self.loading = False
            else:
                self.toast("Equalizer on. Sound now plays through it." if on else "Equalizer off")
        bg(lambda: eq.enable(gains) if on else eq.disable(), done)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="local.ghublite")

    def do_activate(self):
        if self.props.active_window:
            self.props.active_window.present()
            return
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        # above USER priority: Zorin loads its theme colours there, and this app keeps its own look
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        overlay = Adw.ToastOverlay()

        def toast(text):
            overlay.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))

        nav = Adw.NavigationView()
        config = load_config()
        pages = [MousePage(toast, nav, config), HeadsetPage(toast, nav, config)]
        stages = Gtk.Box(spacing=18, homogeneous=True, margin_top=12, margin_bottom=24,
                         margin_start=24, margin_end=24)
        for page in pages:
            stages.append(page.card)
        home = Adw.ToolbarView(content=stages)
        home.add_top_bar(Adw.HeaderBar())
        nav.add(Adw.NavigationPage(title="G Hub Lite", tag="home", child=home))
        overlay.set_child(nav)

        window = Adw.ApplicationWindow(application=self, title="G Hub Lite", content=overlay,
                                       default_width=980, default_height=700)
        window.set_size_request(360, 480)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        narrow.add_setter(stages, "orientation", Gtk.Orientation.VERTICAL)
        for page in pages:
            for widget in page.narrow_hides:
                narrow.add_setter(widget, "visible", False)
        window.add_breakpoint(narrow)

        def tick():
            for page in pages:
                page.refresh()
            return True

        tick()
        GLib.timeout_add_seconds(10, tick)
        window.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
