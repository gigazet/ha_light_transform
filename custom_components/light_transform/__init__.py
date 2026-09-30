"""Light Transform integration lifecycle."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .controller import Controller
from .endpoint import source_entity, validate_mapping, validate_source
from .model import Output

type LightTransformEntry = ConfigEntry[Controller]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: LightTransformEntry) -> bool:
    try:
        source = source_entity(hass, entry)
        state = validate_source(hass, source, entry.data["transport"], entry.entry_id)
        outputs = [
            Output.from_data(sub.subentry_id, sub.title, sub.data)
            for sub in entry.subentries.values()
            if sub.subentry_type == "output"
        ]
        validate_mapping(state, outputs, entry.data["transport"])
    except ValueError as err:
        if str(err) == "source_unavailable":
            raise ConfigEntryNotReady("Waiting for the source light") from err
        raise ConfigEntryError(f"Invalid transform configuration: {err}") from err
    controller = Controller(hass, entry, source, outputs)
    try:
        await controller.initialize()
    except (ValueError, OSError) as err:
        raise ConfigEntryError(f"Cannot load transform memory: {err}") from err
    entry.runtime_data = controller
    controller.start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload))

    @callback
    def registry_changed(event: Event[Any]) -> None:
        if event.data.get("entity_id") == controller.source:
            if event.data["action"] == "remove":
                controller.state = None
                controller._notify()
        if (
            event.data["action"] == "update"
            and event.data.get("changes", {}).get("entity_id") == controller.source
        ):
            hass.async_create_task(async_reload(hass, entry))

    entry.async_on_unload(hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_changed))
    return True


async def async_reload(hass: HomeAssistant, entry: LightTransformEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LightTransformEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.stop()
        return True
    return False


async def async_remove_entry(hass: HomeAssistant, entry: LightTransformEntry) -> None:
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
