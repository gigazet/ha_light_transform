"""Standard HA lights with only the capabilities of their connected strips."""

from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode, LightEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LightTransformEntry
from .const import DOMAIN
from .controller import Controller
from .model import Output

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightTransformEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for output in entry.runtime_data.outputs.values():
        async_add_entities(
            [TransformedLight(entry.runtime_data, output)], config_subentry_id=output.id
        )


class TransformedLight(LightEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, controller: Controller, output: Output) -> None:
        self.controller = controller
        self.output = output
        self._attr_unique_id = f"{controller.entry.entry_id}_{output.id}"
        self._attr_name = None
        self._attr_supported_color_modes = {
            ColorMode.COLOR_TEMP if output.kind == "cct" else ColorMode.BRIGHTNESS
        }
        self._attr_color_mode = (
            ColorMode.COLOR_TEMP if output.kind == "cct" else ColorMode.BRIGHTNESS
        )
        self._attr_min_color_temp_kelvin = output.min_kelvin
        self._attr_max_color_temp_kelvin = output.max_kelvin
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller.entry.entry_id}_{output.id}")},
            name=output.name,
            manufacturer="Light Transform",
            model="Transformed light",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.subscribe(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self.controller.available

    @property
    def is_on(self) -> bool:
        return self.controller.levels[self.output.id].on

    @property
    def brightness(self) -> int:
        return self.controller.levels[self.output.id].brightness

    @property
    def color_temp_kelvin(self) -> int | None:
        return self.controller.levels[self.output.id].kelvin if self.output.kind == "cct" else None

    @property
    def supported_features(self) -> LightEntityFeature:
        return (
            LightEntityFeature.TRANSITION
            if self.controller.supports_transition
            else LightEntityFeature(0)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source_entity": self.controller.source,
            "transform": self.output.kind,
            "channels": (
                sorted(self.output.owned_channels) if self.controller.transport == "rgb" else []
            ),
            "approximate_channel_control": self.controller.approximate,
            "delivery_status": self.controller.status,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.command(self.output.id, "on", kwargs, self._context)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.command(self.output.id, "off", kwargs, self._context)

    async def async_toggle(self, **kwargs: Any) -> None:
        await self.controller.command(self.output.id, "toggle", kwargs, self._context)
