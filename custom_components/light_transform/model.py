"""Pure channel transforms; levels are electrical drive requests, not sRGB luminance."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import CHANNELS


@dataclass(frozen=True)
class Output:
    id: str
    name: str
    kind: str
    channels: tuple[str, ...] = ()
    warm_channel: str = "red"
    cold_channel: str = "green"
    min_kelvin: int = 2000
    max_kelvin: int = 6500
    mixing: str = "constant_sum"
    fixed_kelvin: int = 2000

    @classmethod
    def from_data(cls, id: str, name: str, data: Mapping[str, Any]) -> Output:
        return cls(
            id=id,
            name=name,
            kind=data["kind"],
            channels=tuple(data.get("channels", [])),
            warm_channel=data.get("warm_channel", "red"),
            cold_channel=data.get("cold_channel", "green"),
            min_kelvin=data.get("min_kelvin", 2000),
            max_kelvin=data.get("max_kelvin", 6500),
            mixing=data.get("mixing", "constant_sum"),
            fixed_kelvin=data.get("fixed_kelvin", 2000),
        )

    @property
    def temperature_range(self) -> tuple[int, int]:
        if self.kind == "cct":
            return self.min_kelvin, self.max_kelvin
        return self.fixed_kelvin, self.fixed_kelvin

    @property
    def owned_channels(self) -> set[str]:
        return {self.warm_channel, self.cold_channel} if self.kind == "cct" else set(self.channels)


@dataclass(frozen=True)
class Level:
    on: bool = False
    brightness: int = 255
    kelvin: int = 4000


def validate_outputs(outputs: list[Output], transport: str) -> None:
    used: set[str] = set()
    if transport not in {"rgb", "cct"}:
        raise ValueError("unsupported_source")
    if transport == "cct" and len(outputs) > 1:
        raise ValueError("overlapping_channels")
    for output in outputs:
        if output.kind not in {"dimmer", "cct"}:
            raise ValueError("invalid_kind")
        if transport == "cct":
            minimum, maximum = output.temperature_range
            if not 1000 <= minimum <= maximum <= 40000 or (
                output.kind == "cct" and minimum == maximum
            ):
                raise ValueError("invalid_temperature")
            continue
        channels = output.owned_channels
        if not channels or not channels <= set(CHANNELS):
            raise ValueError("invalid_channels")
        if output.kind == "cct":
            if output.warm_channel == output.cold_channel:
                raise ValueError("invalid_channels")
            if not 1000 <= output.min_kelvin < output.max_kelvin <= 40000:
                raise ValueError("invalid_temperature")
            if output.mixing not in {"constant_sum", "constant_max"}:
                raise ValueError("invalid_mixing")
        if channels & used:
            raise ValueError("overlapping_channels")
        used |= channels


def encode(output: Output, level: Level) -> dict[str, float]:
    if not level.on:
        return dict.fromkeys(output.owned_channels, 0.0)
    brightness = max(0, min(255, level.brightness))
    if output.kind == "dimmer":
        return dict.fromkeys(output.channels, float(brightness))
    fraction = max(
        0.0, min(1.0, (level.kelvin - output.min_kelvin) / (output.max_kelvin - output.min_kelvin))
    )
    warm, cold = 1 - fraction, fraction
    scale = max(warm, cold) if output.mixing == "constant_max" else 1
    return {
        output.warm_channel: brightness * warm / scale,
        output.cold_channel: brightness * cold / scale,
    }


def decode(output: Output, channels: Mapping[str, float], previous: Level) -> Level:
    if output.kind == "dimmer":
        brightness = round(max(channels[channel] for channel in output.channels))
        kelvin = previous.kelvin
    else:
        warm, cold = channels[output.warm_channel], channels[output.cold_channel]
        brightness = round(max(warm, cold) if output.mixing == "constant_max" else warm + cold)
        kelvin = (
            round(
                output.min_kelvin + (output.max_kelvin - output.min_kelvin) * cold / (warm + cold)
            )
            if warm + cold > 0
            else previous.kelvin
        )
    if brightness <= 0:
        return Level(False, previous.brightness, previous.kelvin)
    return Level(True, min(255, brightness), kelvin)


def pack_rgb(channels: Mapping[str, float]) -> tuple[int, tuple[int, int, int]]:
    """Separate global brightness from normalized channel ratios exactly once."""
    values = [channels.get(channel, 0.0) for channel in CHANNELS]
    peak = max(values)
    if peak <= 0:
        return 0, (0, 0, 0)
    rgb = [round(value * 255 / peak) for value in values]
    return max(1, round(peak)), (rgb[0], rgb[1], rgb[2])


def unpack_rgb(brightness: int, rgb: tuple[int, int, int]) -> dict[str, float]:
    return {channel: value * brightness / 255 for channel, value in zip(CHANNELS, rgb, strict=True)}
