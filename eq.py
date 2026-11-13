"""10-band equalizer for the G533: a PipeWire filter-chain sink in front of the headset.

Uses the filter-chain user service PipeWire already ships and runs: we only add or remove
one drop-in file and restart that service (never PipeWire itself, so other audio keeps playing).
"""
import os
import subprocess
import time

import audio
from audio import AudioError, EQ_NODE

BANDS = (31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)  # Hz
MIN_GAIN, MAX_GAIN = -12.0, 12.0  # dB
PRESETS = {
    "Flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "Bass boost": (6, 5, 4, 2, 0, 0, 0, 0, 0, 0),
    "Footsteps": (-4, -3, -2, 0, 1, 3, 5, 5, 3, 1),
    "Voice": (-4, -3, -1, 1, 3, 4, 4, 2, 0, -1),
    "Treble boost": (0, 0, 0, 0, 0, 1, 2, 4, 5, 6),
    # films: rumble and impact down low, less boxiness around 250-500, speech lifted at 2-4 k
    "Cinematic": (5, 4, 2, -1, -2, 0, 2, 3, 2, 1),
}
SERVICE = "filter-chain.service"
CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                    "pipewire", "filter-chain.conf.d", "ghub-lite-eq.conf")


def clean(gains):
    gains = list(gains)
    if len(gains) != len(BANDS):
        raise AudioError(f"The equalizer needs {len(BANDS)} gains, got {len(gains)}.")
    return [max(MIN_GAIN, min(MAX_GAIN, float(g))) for g in gains]


def conf_text(gains, target):
    """The whole drop-in: ten filters in series, playing into the sink named `target`."""
    gains = clean(gains)
    last = len(BANDS) - 1
    nodes, links = [], []
    for i, (freq, gain) in enumerate(zip(BANDS, gains)):
        label = "bq_lowshelf" if i == 0 else "bq_highshelf" if i == last else "bq_peaking"
        q = 0.7 if i in (0, last) else 1.41  # 1.41 = one octave wide, matching the band spacing
        nodes.append(f'                    {{ type = builtin name = eq_band_{i + 1} label = {label} '
                     f'control = {{ "Freq" = {float(freq)} "Q" = {q} "Gain" = {gain} }} }}')
        if i:
            links.append(f'                    {{ output = "eq_band_{i}:Out" input = "eq_band_{i + 1}:In" }}')
    return f"""# Written by G Hub Lite. Delete this file to remove the equalizer.
context.modules = [
    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = "G533 Equalizer"
            media.name       = "G533 Equalizer"
            filter.graph = {{
                nodes = [
{chr(10).join(nodes)}
                ]
                links = [
{chr(10).join(links)}
                ]
            }}
            audio.channels = 2
            audio.position = [ FL FR ]
            capture.props = {{
                node.name   = "{EQ_NODE}"
                media.class = Audio/Sink
            }}
            playback.props = {{
                node.name     = "{EQ_NODE}.output"
                node.passive  = true
                target.object = "{target}"
            }}
        }}
    }}
]
"""


def param_text(gains):
    """The Props value pw-cli needs to change every band's gain while audio plays."""
    pairs = " ".join(f'"eq_band_{i + 1}:Gain" {g}' for i, g in enumerate(clean(gains)))
    return f"{{ params = [ {pairs} ] }}"


def _node_id():
    for obj in audio.json.loads(audio._run("pw-dump")):
        props = (obj.get("info") or {}).get("props") or {}
        if props.get("node.name") == EQ_NODE:
            return obj["id"]
    return None


def is_enabled():
    return _node_id() is not None


def _headset_sink():
    sink = audio.nodes().get("sink")
    if not sink:
        raise AudioError("The headset's sound device is not available. Is its receiver plugged in?")
    return sink


def _restart_service():
    try:
        subprocess.run(["systemctl", "--user", "restart", SERVICE],
                       capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        raise AudioError("Could not restart PipeWire's filter service.")


def _write_conf(gains, target):
    try:
        os.makedirs(os.path.dirname(CONF), exist_ok=True)
        with open(CONF, "w") as f:
            f.write(conf_text(gains, target))
    except OSError as e:
        raise AudioError(f"Could not save the equalizer settings: {e.strerror}")


def enable(gains):
    """Start the equalizer and send all sound through it. Stays on after logging in again."""
    _write_conf(gains, _headset_sink()[1])
    _restart_service()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        node = _node_id()
        if node is not None:
            audio._run("wpctl", "set-default", str(node))
            return
        time.sleep(0.2)
    raise AudioError("The equalizer did not start.")


def set_gains(gains):
    """Change gains while audio plays, and keep them for the next start."""
    node = _node_id()
    if node is None:
        return
    audio._run("pw-cli", "set-param", str(node), "Props", param_text(gains))
    _write_conf(gains, _headset_sink()[1])


def disable():
    """Remove the equalizer and send sound straight to the headset again."""
    try:
        os.remove(CONF)
    except FileNotFoundError:
        return  # was not on: leave the user's output choice alone
    except OSError as e:
        raise AudioError(f"Could not remove the equalizer: {e.strerror}")
    _restart_service()
    sink = audio.nodes().get("sink")
    if sink:
        audio._run("wpctl", "set-default", str(sink[0]))


if __name__ == "__main__":
    import sys
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "on":
        enable(PRESETS["Flat"])
    elif command == "off":
        disable()
    elif command == "preset":
        set_gains(PRESETS[sys.argv[2]])
    print("equalizer is", "on" if is_enabled() else "off")
