"""Volume of the G533's speaker and microphone, through PipeWire's own tools."""
import json
import subprocess

EQ_NODE = "ghub_lite_eq"  # the equalizer's virtual sink; never mistake it for the headset


class AudioError(Exception):
    pass


def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True).stdout
    except FileNotFoundError:
        raise AudioError(f"{cmd[0]} is not installed.")
    except subprocess.TimeoutExpired:
        raise AudioError("The sound system did not answer.")
    except subprocess.CalledProcessError as e:
        raise AudioError((e.stderr or "").strip() or f"{cmd[0]} failed.")


def headset_nodes(dump):
    """pw-dump JSON text -> {'sink': (id, node.name), 'source': (id, node.name)} for the G533."""
    found = {}
    for obj in json.loads(dump):
        props = (obj.get("info") or {}).get("props") or {}
        name = props.get("node.name") or ""
        kind = {"Audio/Sink": "sink", "Audio/Source": "source"}.get(props.get("media.class"))
        if kind and "G533" in name + (props.get("node.description") or "") and not name.startswith(EQ_NODE):
            found.setdefault(kind, (obj["id"], name))
    return found


def nodes():
    return headset_nodes(_run("pw-dump"))


def parse_volume(text):
    """'Volume: 0.76 [MUTED]' -> (76, True)."""
    parts = text.split()
    return round(float(parts[1]) * 100), "[MUTED]" in parts


def volumes():
    """{'sink': 76, 'source': 100} for whichever of the two exist."""
    return {kind: parse_volume(_run("wpctl", "get-volume", str(node)))[0]
            for kind, (node, _name) in nodes().items()}


def set_volume(kind, percent):
    found = nodes()
    if kind not in found:
        raise AudioError("The headset's sound device is not available.")
    level = max(0, min(100, int(percent))) / 100
    _run("wpctl", "set-volume", str(found[kind][0]), f"{level:.2f}")
