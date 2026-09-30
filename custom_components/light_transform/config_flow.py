"""UI-configured controllers and independently named output subentries."""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import CHANNELS, DOMAIN
from .endpoint import source_entity, validate_mapping, validate_source
from .model import Output


def select(
    options: list[str], translation_key: str, *, multiple: bool = False
) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=translation_key,
            multiple=multiple,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def output_schema(transport: str, values: Mapping[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required("name", default=values.get("name", "")): vol.All(
            str, vol.Strip, vol.Length(min=1)
        ),
    }
    if transport == "cct":
        fields[vol.Required("kind", default=values.get("kind", "dimmer"))] = select(
            ["dimmer", "cct"], "kind"
        )
        fields[vol.Required("fixed_kelvin", default=values.get("fixed_kelvin", 2000))] = vol.All(
            vol.Coerce(int), vol.Range(min=1000, max=40000)
        )
    else:
        fields.update(
            {
                vol.Required("kind", default=values.get("kind", "dimmer")): select(
                    ["dimmer", "cct"], "kind"
                ),
                vol.Required("channels", default=values.get("channels", ["red"])): select(
                    list(CHANNELS), "channel", multiple=True
                ),
                vol.Required("warm_channel", default=values.get("warm_channel", "red")): select(
                    list(CHANNELS), "channel"
                ),
                vol.Required("cold_channel", default=values.get("cold_channel", "green")): select(
                    list(CHANNELS), "channel"
                ),
                vol.Required("min_kelvin", default=values.get("min_kelvin", 2000)): vol.All(
                    vol.Coerce(int), vol.Range(min=1000, max=40000)
                ),
                vol.Required("max_kelvin", default=values.get("max_kelvin", 6500)): vol.All(
                    vol.Coerce(int), vol.Range(min=1000, max=40000)
                ),
                vol.Required("mixing", default=values.get("mixing", "constant_sum")): select(
                    ["constant_sum", "constant_max"], "mixing"
                ),
            }
        )
    return vol.Schema(fields)


class LightTransformConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                state = validate_source(self.hass, user_input["source"], user_input["transport"])
                registered = er.async_get(self.hass).async_get(user_input["source"])
                await self.async_set_unique_id(registered.id if registered else state.entity_id)
                self._abort_if_unique_id_configured()
            except ValueError as err:
                errors["base"] = str(err)
            else:
                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        **user_input,
                        "source_registry_id": registered.id if registered else None,
                    },
                )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1)),
                    vol.Required("source"): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light")
                    ),
                    vol.Required("transport", default="rgb"): select(["rgb", "cct"], "transport"),
                }
            ),
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {"output": OutputSubentryFlow}


class OutputSubentryFlow(ConfigSubentryFlow):
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return self._form(user_input, "user")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self._form(user_input, "reconfigure")

    def _form(self, user_input: dict[str, Any] | None, step: str) -> SubentryFlowResult:
        entry = self._get_entry()
        current = self._get_reconfigure_subentry() if step == "reconfigure" else None
        defaults = dict(current.data) if current else {}
        if current:
            defaults["name"] = current.title
        defaults.update(user_input or {})
        errors = {}
        if user_input is not None:
            data = dict(user_input)
            if entry.data["transport"] == "cct":
                data.setdefault("kind", "dimmer")
            try:
                state = validate_source(
                    self.hass,
                    source_entity(self.hass, entry),
                    entry.data["transport"],
                    entry.entry_id,
                )
                if entry.data["transport"] == "cct" and data["kind"] == "cct":
                    data["min_kelvin"] = state.attributes.get("min_color_temp_kelvin")
                    data["max_kelvin"] = state.attributes.get("max_color_temp_kelvin")
                    if data["min_kelvin"] is None or data["max_kelvin"] is None:
                        raise ValueError("unsupported_source")
                outputs = [
                    Output.from_data(sub.subentry_id, sub.title, sub.data)
                    for sub in entry.subentries.values()
                    if current is None or sub.subentry_id != current.subentry_id
                ]
                outputs.append(Output.from_data("new", data["name"], data))
                validate_mapping(state, outputs, entry.data["transport"])
            except ValueError as err:
                errors["base"] = str(err)
            else:
                if current:
                    return self.async_update_and_abort(
                        entry, current, title=data["name"], data=data
                    )
                return self.async_create_entry(title=data["name"], data=data)
        return self.async_show_form(
            step_id=step,
            errors=errors,
            data_schema=output_schema(entry.data["transport"], defaults),
            description_placeholders={"transport": entry.data["transport"].upper()},
        )
