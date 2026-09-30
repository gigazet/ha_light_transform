"""Exact channel mapping and quantization invariants."""

import pytest

from custom_components.light_transform.model import (
    Level,
    Output,
    decode,
    encode,
    pack_rgb,
    unpack_rgb,
    validate_outputs,
)


@pytest.mark.parametrize("mixing", ["constant_sum", "constant_max"])
@pytest.mark.parametrize("brightness", [1, 2, 64, 128, 254, 255])
@pytest.mark.parametrize("kelvin", [2000, 2100, 3500, 4250, 6000, 6500])
def test_cct_round_trip(mixing, brightness, kelvin):
    output = Output("a", "CCT", "cct", mixing=mixing)
    original = Level(True, brightness, kelvin)
    channels = encode(output, original)
    result = decode(output, channels, Level())
    assert result == original
    b, rgb = pack_rgb(channels)
    actual = unpack_rgb(b, rgb)
    assert all(abs(actual[channel] - value) <= 1 for channel, value in channels.items())
    if mixing == "constant_sum":
        assert sum(channels.values()) == pytest.approx(brightness)
    else:
        assert max(channels.values()) == pytest.approx(brightness)


def test_normalization_does_not_dim_twice():
    brightness, rgb = pack_rgb({"red": 128, "green": 64, "blue": 32})
    assert brightness == 128
    assert rgb == (255, 128, 64)
    assert unpack_rgb(brightness, rgb)["green"] == pytest.approx(64, abs=0.3)


def test_non_normalized_external_rgb_keeps_its_intensity():
    assert unpack_rgb(255, (128, 0, 0)) == {"red": 128, "green": 0, "blue": 0}


def test_zero_and_retained_memory():
    output = Output("a", "Dimmer", "dimmer", ("blue",))
    previous = Level(True, 80, 4000)
    assert decode(output, {"blue": 0}, previous) == Level(False, 80, 4000)
    assert encode(output, Level(False, 80)) == {"blue": 0}
    assert pack_rgb({}) == (0, (0, 0, 0))
    assert unpack_rgb(255, (0, 0, 0)) == {"red": 0, "green": 0, "blue": 0}


def test_disjoint_cct_and_dimmer():
    validate_outputs([Output("a", "CCT", "cct"), Output("b", "Dimmer", "dimmer", ("blue",))], "rgb")


@pytest.mark.parametrize(
    ("outputs", "transport", "error"),
    [
        (
            [Output("a", "CCT", "cct", warm_channel="red", cold_channel="red")],
            "rgb",
            "invalid_channels",
        ),
        (
            [Output("a", "CCT", "cct", min_kelvin=6500, max_kelvin=2000)],
            "rgb",
            "invalid_temperature",
        ),
        ([Output("a", "Dimmer", "dimmer")], "rgb", "invalid_channels"),
        (
            [Output("a", "CCT", "cct"), Output("b", "D", "dimmer", ("red",))],
            "rgb",
            "overlapping_channels",
        ),
        ([Output("a", "D", "dimmer"), Output("b", "D", "dimmer")], "cct", "overlapping_channels"),
        ([Output("a", "CCT", "invalid")], "cct", "invalid_kind"),
        (
            [Output("a", "CCT", "cct", min_kelvin=6500, max_kelvin=2000)],
            "cct",
            "invalid_temperature",
        ),
        ([Output("a", "D", "dimmer", fixed_kelvin=0)], "cct", "invalid_temperature"),
    ],
)
def test_invalid_mapping(outputs, transport, error):
    with pytest.raises(ValueError, match=error):
        validate_outputs(outputs, transport)
