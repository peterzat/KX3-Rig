import json

from kx3rig import config


def test_defaults_are_this_station():
    s = config.Settings()
    assert s.callsign == "K1ABC"
    assert s.grid4 == "FN42"
    assert s.license_class == "General"
    assert s.power_w == 5.0


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(str(tmp_path / "nope.json")) == config.Settings()


def test_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    s = config.Settings(power_w=3.0, band_memory={"20m": 14_200_000})
    config.save(s, path)
    assert config.load(path) == s


def test_unknown_keys_ignored_and_values_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"callsign": " k1abc ", "power_w": 99, "bogus": 1, "license_class": "Wizard"}))
    s = config.load(str(path))
    assert s.callsign == "K1ABC"
    assert s.power_w == s.max_power_w == 10.0
    assert s.license_class == "General"


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert config.load(str(path)) == config.Settings()
    path.write_text("[1, 2]")
    assert config.load(str(path)) == config.Settings()
