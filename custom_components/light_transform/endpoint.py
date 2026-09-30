"""Source identity and capability validation."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, RGB_MODES
from .model import Output, validate_outputs


def source_entity(hass: HomeAssistant, entry: ConfigEntry) -> str:
    if registry_id := entry.data.get("source_registry_id"):
        registered = er.async_get(hass).async_get(registry_id)
        if registered is None:
            raise ValueError("source_removed")
        return registered.entity_id
    return str(entry.data["source"])


def validate_source(
    hass: HomeAssistant, entity_id: str, transport: str, entry_id: str | None = None
) -> State:
    registered = er.async_get(hass).async_get(entity_id)
    state = hass.states.get(entity_id)
    if not entity_id.startswith("light.") or (
        registered is not None and registered.platform == DOMAIN
    ):
        raise ValueError("invalid_source")
    if state is None or state.state in {"unknown", "unavailable"}:
        raise ValueError("source_unavailable")
    # Aggregates and intent layers cannot guarantee exclusive electrical channel ownership.
    if state.attributes.get("entity_id") or (
        registered is not None and registered.platform in {"group", "light_masks"}
    ):
        raise ValueError("invalid_source")
    modes = set(state.attributes.get("supported_color_modes", []))
    if (
        (transport == "rgb" and not modes & RGB_MODES)
        or (transport == "cct" and "color_temp" not in modes)
        or transport not in {"rgb", "cct"}
    ):
        raise ValueError("unsupported_source")
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id == entry_id:
            continue
        identity = other.data.get("source_registry_id")
        if (registered is not None and identity == registered.id) or (
            not identity and other.data["source"] == entity_id
        ):
            raise ValueError("already_configured")
    return state


def validate_mapping(state: State, outputs: list[Output], transport: str) -> None:
    validate_outputs(outputs, transport)
    if transport == "cct":
        minimum = state.attributes.get("min_color_temp_kelvin")
        maximum = state.attributes.get("max_color_temp_kelvin")
        if minimum is None or maximum is None:
            raise ValueError("unsupported_source")
        if any(not minimum <= output.fixed_kelvin <= maximum for output in outputs):
            raise ValueError("temperature_out_of_range")
