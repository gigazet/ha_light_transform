"""Exercise real HA Core with local simulated lights, never household devices."""

from types import MappingProxyType

import pytest
from homeassistant import loader
from homeassistant.components.light import ColorMode, LightEntity, LightEntityFeature
from homeassistant.components.light.const import DATA_COMPONENT
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import frame
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_test_home_assistant

from custom_components.light_transform.const import DOMAIN


@pytest.fixture
async def hass(tmp_path):
    # The full upstream pytest plugin imports a Unix-only process runner.
    async with async_test_home_assistant(config_dir=str(tmp_path)) as instance:
        frame.async_setup(instance)
        instance.data.pop(loader.DATA_CUSTOM_COMPONENTS)
        yield instance
        await instance.async_stop(force=True)


class PhysicalLight(LightEntity):
    _attr_name = "Physical controller"
    _attr_unique_id = "physical_controller"
    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
    _attr_color_mode = ColorMode.RGB
    _attr_rgb_color = (255, 0, 0)
    _attr_brightness = 255
    _attr_is_on = False
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500
    _attr_color_temp_kelvin = 2000
    _attr_should_poll = False
    _attr_supported_features = LightEntityFeature.TRANSITION | LightEntityFeature.EFFECT
    _attr_effect_list = ["rainbow"]

    def __init__(self):
        self.calls = []
        self.report = True
        self.fail = False
        self.gate = None

    async def async_turn_on(self, **kwargs):
        self.calls.append(("on", kwargs))
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise HomeAssistantError("Simulated failure")
        if self.report:
            self._attr_is_on = True
            self._attr_brightness = kwargs.get("brightness", self.brightness)
            for key, mode in (
                ("rgb_color", ColorMode.RGB),
                ("xy_color", ColorMode.XY),
                ("hs_color", ColorMode.HS),
                ("color_temp_kelvin", ColorMode.COLOR_TEMP),
            ):
                if key in kwargs:
                    setattr(self, f"_attr_{key}", kwargs[key])
                    self._attr_color_mode = mode
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self.calls.append(("off", kwargs))
        if self.fail:
            raise HomeAssistantError("Simulated failure")
        if self.report:
            self._attr_is_on = False
            self.async_write_ha_state()


@pytest.fixture
async def source(hass):
    assert await async_setup_component(hass, "light", {})
    light = PhysicalLight()
    await hass.data[DATA_COMPONENT].async_add_entities([light])
    await hass.async_block_till_done()
    return light


@pytest.fixture
async def setup_transform(hass, source):
    entries = []

    async def setup(outputs, transport="rgb"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test transform",
            data={"source": source.entity_id, "transport": transport},
        )
        entry.add_to_hass(hass)
        for data in outputs:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    title=data.get("name", "Output"),
                    subentry_type="output",
                    unique_id=None,
                    data=MappingProxyType(data),
                ),
            )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entries.append(entry)
        return entry

    yield setup
    for entry in entries:
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
