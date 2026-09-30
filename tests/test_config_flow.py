"""Native setup, subentry editing, ownership, and source identity."""

import json
from pathlib import Path
from string import Formatter

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations

from custom_components.light_transform.config_flow import output_schema
from custom_components.light_transform.const import DOMAIN
from custom_components.light_transform.endpoint import validate_source

from .test_integration import command, entity_ids


async def create_controller(hass, source, transport="rgb"):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"name": "My controller", "source": source.entity_id, "transport": transport},
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    return result["result"]


async def add_output(hass, entry, data):
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "output"), context={"source": "user"}
    )
    return await hass.config_entries.subentries.async_configure(flow["flow_id"], data)


async def test_ui_create_edit_remove_outputs(hass, source):
    entry = await create_controller(hass, source)
    assert not source.calls
    assert not entry.subentries
    result = await add_output(
        hass, entry, {"name": "Red strip", "kind": "dimmer", "channels": ["red"]}
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    result = await add_output(
        hass, entry, {"name": "Blue strip", "kind": "dimmer", "channels": ["blue"]}
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    ids = entity_ids(hass, entry)
    assert set(ids) == {"Red strip", "Blue strip"}
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 2
    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len({entity.config_subentry_id for entity in registered}) == 2
    red = next(sub for sub in entry.subentries.values() if sub.title == "Red strip")
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "output"),
        context={"source": "reconfigure", "subentry_id": red.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {**red.data, "name": "Green strip", "channels": ["green"]}
    )
    assert result["type"] == "abort", result
    await hass.async_block_till_done()
    assert entity_ids(hass, entry)["Green strip"] == ids["Red strip"]
    assert not source.calls
    await command(hass, ids["Red strip"], brightness=80)
    assert source.calls[-1][1]["rgb_color"] == (0, 255, 0)
    calls = len(source.calls)
    hass.config_entries.async_remove_subentry(entry, red.subentry_id)
    await hass.async_block_till_done()
    assert set(entity_ids(hass, entry)) == {"Blue strip"}
    assert len(source.calls) == calls
    await hass.config_entries.async_unload(entry.entry_id)


async def test_overlaps_rejected_and_names_preserved(hass, source):
    entry = await create_controller(hass, source)
    result = await add_output(hass, entry, {"name": "White strip", "kind": "cct"})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    result = await add_output(
        hass, entry, {"name": "Red strip", "kind": "dimmer", "channels": ["red"]}
    )
    assert result["errors"] == {"base": "overlapping_channels"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Blue strip", "kind": "dimmer", "channels": ["blue"]}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_duplicate_controller_rejected(hass, source):
    entry = await create_controller(hass, source)
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Duplicate", "source": source.entity_id, "transport": "rgb"}
    )
    assert result["errors"] == {"base": "already_configured"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cct_bounds_and_second_output_rejected(hass, source):
    entry = await create_controller(hass, source, "cct")
    result = await add_output(hass, entry, {"name": "Dimmer", "fixed_kelvin": 1900})
    assert result["errors"] == {"base": "temperature_out_of_range"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Dimmer", "fixed_kelvin": 2000}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    result = await add_output(hass, entry, {"name": "Another", "fixed_kelvin": 3000})
    assert result["errors"] == {"base": "overlapping_channels"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_source_rename_and_registry_deletion(hass, source):
    entry = await create_controller(hass, source)
    result = await add_output(
        hass, entry, {"name": "Dimmer", "kind": "dimmer", "channels": ["red"]}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    light = entity_ids(hass, entry)["Dimmer"]
    old_id = source.entity_id
    er.async_get(hass).async_update_entity(old_id, new_entity_id="light.renamed_source")
    await hass.async_block_till_done()
    assert entry.runtime_data.source == "light.renamed_source"
    await command(hass, light, brightness=90)
    assert source.brightness == 90
    er.async_get(hass).async_remove("light.renamed_source")
    await hass.async_block_till_done()
    hass.states.async_set("light.renamed_source", "off", {"supported_color_modes": ["rgb"]})
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_bad_sources_rejected(hass, source, setup_transform):
    hass.states.async_set(
        "light.aggregate",
        "off",
        {"supported_color_modes": ["rgb"], "entity_id": [source.entity_id]},
    )
    with pytest.raises(ValueError, match="invalid_source"):
        validate_source(hass, "light.aggregate", "rgb")
    entry = await setup_transform([{"name": "Dimmer", "kind": "dimmer", "channels": ["red"]}])
    with pytest.raises(ValueError, match="invalid_source"):
        validate_source(hass, entity_ids(hass, entry)["Dimmer"], "rgb")
    with pytest.raises(ValueError, match="source_unavailable"):
        validate_source(hass, "light.missing", "rgb")


def test_translations_and_manifest():
    root = Path(__file__).parents[1] / "custom_components" / DOMAIN
    strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((root / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == english
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"]
    assert manifest["dependencies"] == ["light"]


def translation_leaves(data, prefix=""):
    result = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(translation_leaves(value, path))
        else:
            assert isinstance(value, str) and value.strip(), path
            result[path] = value
    return result


def test_ukrainian_translation_keys_and_placeholders():
    root = Path(__file__).parents[1] / "custom_components" / DOMAIN
    english = translation_leaves(json.loads((root / "strings.json").read_text(encoding="utf-8")))
    ukrainian = translation_leaves(
        json.loads((root / "translations" / "uk.json").read_text(encoding="utf-8"))
    )
    assert english.keys() == ukrainian.keys()
    for key, value in english.items():
        expected = [field for _, field, _, _ in Formatter().parse(value) if field is not None]
        actual = [
            field for _, field, _, _ in Formatter().parse(ukrainian[key]) if field is not None
        ]
        assert sorted(actual) == sorted(expected), key
        if key != "title":
            assert ukrainian[key] != value, key


async def test_localized_selector_options_keep_internal_values(hass):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    setup_fields = {key.schema: value for key, value in flow["data_schema"].schema.items()}
    output_fields = {key.schema: value for key, value in output_schema("rgb", {}).schema.items()}
    translations = await async_get_translations(hass, "uk", "selector", {DOMAIN})
    for field, choices in (
        (setup_fields["transport"], ["rgb", "cct"]),
        (output_fields["kind"], ["dimmer", "cct"]),
        (output_fields["channels"], ["red", "green", "blue"]),
        (output_fields["warm_channel"], ["red", "green", "blue"]),
        (output_fields["cold_channel"], ["red", "green", "blue"]),
        (output_fields["mixing"], ["constant_sum", "constant_max"]),
    ):
        assert field.config["options"] == choices
        key = field.config["translation_key"]
        for option in choices:
            assert translations[f"component.{DOMAIN}.selector.{key}.options.{option}"]
    assert output_fields["channels"](["red", "blue"]) == ["red", "blue"]
    assert output_fields["kind"]("cct") == "cct"
    assert output_fields["mixing"]("constant_sum") == "constant_sum"


@pytest.mark.parametrize("category", ["config", "config_subentries"])
async def test_ukrainian_forms_loaded_by_home_assistant(hass, category):
    translations = await async_get_translations(hass, "uk", category, {DOMAIN})
    prefix = f"component.{DOMAIN}.{category}"
    if category == "config":
        assert translations[f"{prefix}.step.user.data.source"] == "Світло-джерело"
    else:
        title = translations[f"{prefix}.output.step.user.title"]
        assert title.format(transport="RGB") == "Додавання виходу для RGB"
