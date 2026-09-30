"""Downloadable transform configuration and delivery status."""

from typing import Any

from homeassistant.core import HomeAssistant

from . import LightTransformEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LightTransformEntry
) -> dict[str, Any]:
    return entry.runtime_data.diagnostics()
