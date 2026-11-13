#!/usr/bin/env python3
"""G Hub Lite: settings window for a Logitech G305 mouse and G533 headset."""
import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

import g533  # noqa: E402
import mouse  # noqa: E402

CONFIG = os.path.join(GLib.get_user_config_dir(), "ghub-lite.json")


def load_config():
    try:
        with open(CONFIG) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def bg(work, done):
    """Run work() off the UI thread, then done(result_or_exception) on it."""
    def run():
        try:
            result = work()
        except Exception as e:  # shown to the user by done()
            result = e
        GLib.idle_add(done, result)
    threading.Thread(target=run, daemon=True).start()


class Page(Gtk.Stack):
    """Either a 'device missing' message or the device's controls."""

    def __init__(self, icon, toast):
        super().__init__()
        self.toast = toast
        self.busy = False  # a refresh is in flight; skip the next tick
        self.status = Adw.StatusPage(icon_name=icon)
        self.controls = Adw.PreferencesPage()
        self.add_named(self.status, "status")
        self.add_named(self.controls, "controls")
        self.missing("Looking for the device…")

    def missing(self, text):
        self.status.set_description(GLib.markup_escape_text(text))
        self.set_visible_child_name("status")


class MousePage(Page):
    def __init__(self, toast):
        super().__init__("input-mouse-symbolic", toast)
        self.mouse = None
        self.generation = 0  # bumped whenever what we read may be out of date
        self.groups = []

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
            self.missing(str(result))
            return
        fresh, battery = result
        if self.mouse is None:  # never rebuild while shown: that would wipe unsaved edits
            self.mouse = fresh
            fresh.on_resync(lambda: GLib.idle_add(self._resync))
            self._build()
        self.battery_row.set_subtitle(battery or "Unknown")
        self.set_visible_child_name("controls")

    def _build(self):
        for group in self.groups:
            self.controls.remove(group)
        m = self.mouse

        info = Adw.PreferencesGroup(title="Logitech G305")
        self.battery_row = Adw.ActionRow(title="Battery")
        info.add(self.battery_row)

        dpi = Adw.PreferencesGroup(
            title="DPI steps",
            description="The selected step is the one in use now. "
                        "The DPI button on the mouse cycles through them.")
        self.steps, self.radios = [], []
        # a list, not a free number: the mouse only accepts these exact values
        choices = Gtk.StringList.new([f"{d} DPI" for d in m.allowed])
        for i, value in enumerate(m.dpis):
            row = Adw.ComboRow(title=f"Step {i + 1}", model=choices)
            row.set_selected(m.allowed.index(mouse.snap(value, m.allowed)))
            radio = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=i == m.active)
            radio.update_property([Gtk.AccessibleProperty.LABEL], [f"Use step {i + 1} now"])
            if self.radios:
                radio.set_group(self.radios[0])
            row.add_prefix(radio)
            dpi.add(row)
            self.steps.append(row)
            self.radios.append(radio)

        rate = Adw.PreferencesGroup(title="Polling rate")
        self.rate_row = Adw.ComboRow(
            title="Reports per second",
            model=Gtk.StringList.new([f"{r} Hz" for r in m.rates]))
        if m.rate in m.rates:
            self.rate_row.set_selected(m.rates.index(m.rate))
        rate.add(self.rate_row)

        self.apply_button = Gtk.Button(
            label="Apply to mouse", halign=Gtk.Align.CENTER, margin_top=18,
            css_classes=["suggested-action", "pill"])
        self.apply_button.connect("clicked", self._apply)
        rate.add(self.apply_button)

        self.groups = [info, dpi, rate]
        for group in self.groups:
            self.controls.add(group)

    def _apply(self, _button):
        m = self.mouse
        dpis = [m.allowed[row.get_selected()] for row in self.steps]
        active = next(i for i, radio in enumerate(self.radios) if radio.get_active())
        selected = self.rate_row.get_selected()
        rate = m.rates[selected] if selected < len(m.rates) else m.rate
        self.apply_button.set_sensitive(False)
        bg(lambda: m.apply(dpis, active, rate), self._applied)

    def _applied(self, result):
        if isinstance(result, Exception):
            self.toast(str(result))
        else:
            self.toast("Saved to the mouse")
        self._reload()

    def _resync(self):
        self.toast("The mouse did not accept the last change")
        self._reload()

    def _reload(self):
        """Throw away our snapshot and show what the mouse really holds."""
        self.generation += 1
        self.mouse = None
        self.refresh()


class HeadsetPage(Page):
    def __init__(self, toast):
        super().__init__("audio-headset-symbolic", toast)
        self.config = load_config()
        self.timers = {}

        info = Adw.PreferencesGroup(title="Logitech G533")
        self.battery_row = Adw.ActionRow(title="Battery")
        info.add(self.battery_row)
        self.controls.add(info)

        settings = Adw.PreferencesGroup(
            description="The headset cannot report these, so the values shown are "
                        "the last ones set from this app.")
        for key, title, subtitle, top, send in (
                ("sidetone", "Sidetone", "How much of your own voice you hear", 100, g533.set_sidetone),
                ("auto_off", "Auto power-off", "Minutes of silence, 0 = never", 90, g533.set_auto_off)):
            row = Adw.SpinRow.new_with_range(0, top, 5)
            row.set_title(title)
            row.set_subtitle(subtitle)
            try:
                row.set_value(float(self.config.get(key, 0)))
            except (TypeError, ValueError):
                pass
            row.connect("notify::value", self._changed, key, send)
            settings.add(row)
        self.controls.add(settings)

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        bg(g533.battery, self._loaded)

    def _loaded(self, result):
        self.busy = False
        if isinstance(result, Exception):
            self.missing(str(result))
            return
        level, charging = result
        self.battery_row.set_subtitle(f"{level}%" + (" · charging" if charging else ""))
        self.set_visible_child_name("controls")

    def _changed(self, row, _param, key, send):
        # wait until the value stops changing, so holding + sends one command, not twenty
        if key in self.timers:
            GLib.source_remove(self.timers[key])

        def fire():
            del self.timers[key]
            value = int(row.get_value())
            bg(lambda: send(value), lambda r: self._sent(key, value, r))
        self.timers[key] = GLib.timeout_add(400, fire)

    def _sent(self, key, value, result):
        if isinstance(result, Exception):
            self.toast(str(result))
            return
        self.config[key] = value  # remember only what the headset was actually sent
        try:
            with open(CONFIG, "w") as f:
                json.dump(self.config, f)
        except OSError as e:
            self.toast(f"Could not remember the setting: {e.strerror}")


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="local.ghublite")

    def do_activate(self):
        if self.props.active_window:
            self.props.active_window.present()
            return
        overlay = Adw.ToastOverlay()

        def toast(text):
            overlay.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))

        pages = [MousePage(toast), HeadsetPage(toast)]
        stack = Adw.ViewStack()
        stack.add_titled_with_icon(pages[0], "mouse", "Mouse", "input-mouse-symbolic")
        stack.add_titled_with_icon(pages[1], "headset", "Headset", "audio-headset-symbolic")
        view = Adw.ToolbarView(content=stack)
        view.add_top_bar(Adw.HeaderBar(
            title_widget=Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)))
        overlay.set_child(view)

        def tick():
            for page in pages:
                page.refresh()
            return True

        tick()
        GLib.timeout_add_seconds(10, tick)
        Adw.ApplicationWindow(
            application=self, title="G Hub Lite", content=overlay,
            default_width=460, default_height=640).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
