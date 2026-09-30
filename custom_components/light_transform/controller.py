"""One serialized writer and feedback stream for every output of a source."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from homeassistant.components.light.const import LightEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store

from .const import ACK_TIMEOUT, CHANNELS, DOMAIN, RGB_MODES
from .model import Level, Output, decode, encode, pack_rgb, unpack_rgb

_LOGGER = logging.getLogger(__name__)


class Controller:
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: str, outputs: list[Output]
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.source = source
        self.transport: str = entry.data["transport"]
        self.outputs = {output.id: output for output in outputs}
        self.levels = {
            output.id: Level(kelvin=max(output.min_kelvin, min(4000, output.max_kelvin)))
            for output in outputs
        }
        self.state: State | None = hass.states.get(source)
        self.pending = False
        self.status = "in_sync"
        self._lock = asyncio.Lock()
        self._sending = False
        self._stopped = False
        self._listeners: set[Callable[[], None]] = set()
        self._unsubscribe: Callable[[], None] | None = None
        self._cancel_timeout: Callable[[], None] | None = None
        self._store = Store[dict[str, Any]](hass, 1, f"{DOMAIN}.{entry.entry_id}")

    async def initialize(self) -> None:
        if stored := await self._store.async_load():
            for id, values in stored.items():
                if id in self.outputs:
                    output = self.outputs[id]
                    brightness, kelvin = values.get("brightness"), values.get("kelvin")
                    if (
                        not isinstance(brightness, int)
                        or not 1 <= brightness <= 255
                        or not isinstance(kelvin, int)
                        or not 1000 <= kelvin <= 40000
                    ):
                        raise ValueError("Invalid saved output memory")
                    self.levels[id] = Level(
                        False, brightness, max(output.min_kelvin, min(output.max_kelvin, kelvin))
                    )
        self.state = self.hass.states.get(self.source)
        self._adopt()
        if not self.available:
            self.status = "source_unavailable_or_incompatible"

    @callback
    def start(self) -> None:
        self._unsubscribe = async_track_state_change_event(
            self.hass, self.source, self._source_changed
        )

    async def stop(self) -> None:
        self._stopped = True
        if self._unsubscribe:
            self._unsubscribe()
        self._clear_pending()
        async with self._lock:
            await self._store.async_save(self._memory())

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @property
    def available(self) -> bool:
        if self._stopped or self.state is None or self.state.state not in {"on", "off"}:
            return False
        if registry_id := self.entry.data.get("source_registry_id"):
            registered = er.async_get(self.hass).async_get(registry_id)
            if registered is None or registered.entity_id != self.source:
                return False
        modes = set(self.state.attributes.get("supported_color_modes", []))
        if self.transport == "rgb":
            if not modes & RGB_MODES:
                return False
            if self.state.state == "on":
                return (
                    self.state.attributes.get("color_mode") in RGB_MODES
                    and self.state.attributes.get("brightness") is not None
                    and self.state.attributes.get("rgb_color") is not None
                )
            return True
        minimum = self.state.attributes.get("min_color_temp_kelvin")
        maximum = self.state.attributes.get("max_color_temp_kelvin")
        return (
            "color_temp" in modes
            and minimum is not None
            and maximum is not None
            and all(
                minimum <= output.temperature_range[0] <= output.temperature_range[1] <= maximum
                for output in self.outputs.values()
            )
            and (
                self.state.state == "off"
                or (
                    self.state.attributes.get("color_mode") == "color_temp"
                    and self.state.attributes.get("brightness") is not None
                    and (
                        not any(output.kind == "cct" for output in self.outputs.values())
                        or isinstance(self.state.attributes.get("color_temp_kelvin"), (int, float))
                    )
                )
            )
        )

    @property
    def supports_transition(self) -> bool:
        return bool(
            self.state
            and self.state.attributes.get("supported_features", 0) & LightEntityFeature.TRANSITION
        )

    @property
    def approximate(self) -> bool:
        return self.transport == "rgb" and (
            self.state is None
            or "rgb" not in self.state.attributes.get("supported_color_modes", [])
        )

    def _memory(self) -> dict[str, Any]:
        return {
            id: {"brightness": level.brightness, "kelvin": level.kelvin}
            for id, level in self.levels.items()
        }

    @callback
    def _save_memory(self) -> None:
        self._store.async_delay_save(self._memory, 1)

    def _observed_channels(self) -> dict[str, float]:
        if self.state is None or self.state.state != "on":
            return dict.fromkeys(CHANNELS, 0.0)
        rgb = self.state.attributes["rgb_color"]
        return unpack_rgb(self.state.attributes["brightness"], (rgb[0], rgb[1], rgb[2]))

    def _desired_channels(self, levels: dict[str, Level]) -> dict[str, float]:
        channels = dict.fromkeys(CHANNELS, 0.0)
        for id, output in self.outputs.items():
            channels.update(encode(output, levels[id]))
        return channels

    @callback
    def _adopt(self) -> None:
        if not self.available:
            return
        assert self.state is not None
        if self.transport == "rgb":
            channels = self._observed_channels()
            for id, output in self.outputs.items():
                self.levels[id] = decode(output, channels, self.levels[id])
        else:
            on = self.state.state == "on"
            for id, level in self.levels.items():
                output = self.outputs[id]
                brightness = self.state.attributes.get("brightness") if on else None
                kelvin = (
                    max(
                        output.min_kelvin,
                        min(output.max_kelvin, self.state.attributes["color_temp_kelvin"]),
                    )
                    if on and output.kind == "cct"
                    else level.kelvin
                )
                self.levels[id] = replace(
                    level,
                    on=on and bool(brightness),
                    brightness=brightness or level.brightness,
                    kelvin=round(kelvin),
                )

    def _matches(self) -> bool:
        if not self.available:
            return False
        assert self.state is not None
        if self.transport == "rgb":
            desired = self._desired_channels(self.levels)
            if (self.state.state == "on") != (max(desired.values()) > 0):
                return False
            observed = self._observed_channels()
            return all(abs(desired[channel] - observed[channel]) <= 2 for channel in CHANNELS)
        for id, output in self.outputs.items():
            level = self.levels[id]
            if (self.state.state == "on") != level.on:
                return False
            if level.on:
                observed_kelvin = self.state.attributes.get("color_temp_kelvin") or 0
                target = level.kelvin if output.kind == "cct" else output.fixed_kelvin
                temperature_matches = abs(observed_kelvin - target) <= 2
                if output.kind == "cct" and observed_kelvin > 0:
                    # Zigbee controllers often quantize Kelvin requests to whole mireds.
                    temperature_matches |= (
                        abs(1_000_000 / observed_kelvin - 1_000_000 / target) <= 1
                    )
                if (
                    abs(self.state.attributes["brightness"] - level.brightness) > 1
                    or not temperature_matches
                ):
                    return False
        return True

    @callback
    def _clear_pending(self) -> None:
        self.pending = False
        if self._cancel_timeout:
            self._cancel_timeout()
            self._cancel_timeout = None

    @callback
    def _source_changed(self, event: Event[EventStateChangedData]) -> None:
        self.state = event.data["new_state"]
        if self._sending:
            return
        if self.pending:
            if self._matches():
                self._clear_pending()
                self.status = "in_sync"
                self._adopt()
                self._save_memory()
            elif not self.available:
                self._clear_pending()
                self.status = "source_unavailable_or_incompatible"
        else:
            self._adopt()
            self.status = "in_sync" if self.available else "source_unavailable_or_incompatible"
            if self.available:
                self._save_memory()
        self._notify()

    @callback
    def _timeout(self, _: Any) -> None:
        self._clear_pending()
        self._adopt()
        self.status = "feedback_mismatch"
        _LOGGER.warning(
            "Source %s did not confirm its transformed channel request; adopted reported state",
            self.source,
        )
        self._save_memory()
        self._notify()

    async def command(
        self, id: str, action: str, data: dict[str, Any], context: Context | None
    ) -> None:
        async with self._lock:
            if not self.available:
                raise ServiceValidationError(
                    "Transform source is unavailable or in an incompatible mode"
                )
            unsupported = set(data) - {"brightness", "color_temp_kelvin", "transition"}
            if unsupported:
                raise ServiceValidationError(
                    f"Unsupported transform parameters: {sorted(unsupported)}"
                )
            output = self.outputs[id]
            if "color_temp_kelvin" in data and output.kind != "cct":
                raise ServiceValidationError("This output supports brightness only")
            if "transition" in data and not self.supports_transition:
                raise ServiceValidationError("The source does not support transitions")
            before = self.levels[id]
            on = not before.on if action == "toggle" else action == "on"
            brightness = max(0, min(255, int(data.get("brightness", before.brightness))))
            kelvin = max(
                output.min_kelvin,
                min(output.max_kelvin, int(data.get("color_temp_kelvin", before.kelvin))),
            )
            requested = replace(
                before,
                on=on and brightness > 0,
                brightness=brightness or before.brightness,
                kelvin=kelvin,
            )
            next_levels = {**self.levels, id: requested}
            call: dict[str, Any] = {"entity_id": self.source}
            if self.transport == "rgb":
                source_brightness, rgb = pack_rgb(self._desired_channels(next_levels))
                service = "turn_on" if source_brightness else "turn_off"
                if source_brightness:
                    call.update(brightness=source_brightness, rgb_color=rgb)
            else:
                service = "turn_on" if requested.on else "turn_off"
                if requested.on:
                    call.update(
                        brightness=requested.brightness,
                        color_temp_kelvin=(
                            requested.kelvin if output.kind == "cct" else output.fixed_kelvin
                        ),
                    )
            if "transition" in data:
                call["transition"] = data["transition"]
            self._clear_pending()
            self._sending = True
            try:
                await self.hass.services.async_call(
                    "light", service, call, blocking=True, context=context
                )
            except HomeAssistantError, asyncio.CancelledError:
                self.state = self.hass.states.get(self.source)
                self._adopt()
                self.status = "command_failed"
                self._notify()
                raise
            finally:
                self._sending = False
            if self._stopped:
                return
            self.levels = next_levels
            self.state = self.hass.states.get(self.source)
            self.pending = not self._matches()
            self.status = "pending" if self.pending else "in_sync"
            if self.pending:
                self._cancel_timeout = async_call_later(
                    self.hass, ACK_TIMEOUT + float(data.get("transition", 0)), self._timeout
                )
            else:
                self._adopt()
            self._save_memory()
            self._notify()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "transport": self.transport,
            "approximate_channel_control": self.approximate,
            "available": self.available,
            "delivery_status": self.status,
            "pending": self.pending,
            "outputs": [asdict(output) for output in self.outputs.values()],
            "levels": {id: asdict(level) for id, level in self.levels.items()},
        }
