"""Self-check for the equalizer's pure logic. Run: python3 test_eq.py"""
import eq

text = eq.conf_text(eq.PRESETS["Bass boost"], "the_headset_sink")
assert text.count("type = builtin") == 10 and text.count("output = ") == 9
assert text.count("bq_lowshelf") == 1 and text.count("bq_highshelf") == 1 and text.count("bq_peaking") == 8
assert 'label = bq_lowshelf control = { "Freq" = 31.0 "Q" = 0.7 "Gain" = 6.0 }' in text
assert 'name = eq_band_10 label = bq_highshelf control = { "Freq" = 16000.0' in text
assert '{ output = "eq_band_9:Out" input = "eq_band_10:In" }' in text
assert 'target.object = "the_headset_sink"' in text and 'node.name   = "ghub_lite_eq"' in text
assert text.count("{") == text.count("}") and text.count("[") == text.count("]")

assert eq.clean([99, -99] + [0] * 8)[:2] == [12.0, -12.0]
for bad in ([0] * 9, [0] * 11, []):
    try:
        eq.clean(bad)
        raise AssertionError(f"accepted {len(bad)} gains")
    except eq.AudioError:
        pass

for name, gains in eq.PRESETS.items():
    assert len(gains) == 10 and all(eq.MIN_GAIN <= g <= eq.MAX_GAIN for g in gains), name
assert eq.PRESETS["Flat"] == (0,) * 10
assert "Cinematic" in eq.PRESETS

assert eq.param_text([1.5] + [0] * 9).startswith('{ params = [ "eq_band_1:Gain" 1.5 "eq_band_2:Gain" 0.0')

print("ok")
