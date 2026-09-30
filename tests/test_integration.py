"""Behavior through Core's actual light services and config entries."""

import asyncio

import pytest
from homeassistant.components.light import ColorMode
from homeassistant.components.light.const import LightEntityFeature
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.light_transform.model import unpack_rgb


def entity_ids(hass, entry):
    return {
        entry.subentries[entity.config_subentry_id].title: entity.entity_id
        for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def command(hass, entity_id, service="turn_on", **kwargs):
    await hass.services.async_call(
        "light", service, {"entity_id": entity_id, **kwargs}, blocking=True
    )
    await hass.async_block_till_done()


async def test_cct_capabilities_and_kelvin(hass, source, setup_transform):
    entry = await setup_transform([{"name": "Strip", "kind": "cct"}])
    light = entity_ids(hass, entry)["Strip"]
    state = hass.states.get(light)
    assert state.attributes["supported_color_modes"] == ["color_temp"]
    assert "effect_list" not in state.attributes
    assert state.attributes["supported_features"] == 32
    assert not source.calls
    await command(hass, light, brightness=200, color_temp_kelvin=4250, transition=1)
    assert source.calls[-1] == (
        "on",
        {"brightness": 100, "rgb_color": (255, 255, 0), "transition": 1},
    )
    assert hass.states.get(light).attributes["brightness"] == 200
    assert hass.states.get(light).attributes["color_temp_kelvin"] == 4250
    await command(hass, light, "turn_off")
    await command(hass, light)
    assert source.calls[-1][1]["brightness"] == 100
    assert source.calls[-1][1]["rgb_color"] == (255, 255, 0)


async def test_independent_channels_concurrent_and_off(hass, source, setup_transform):
    entry = await setup_transform(
        [
            {"name": channel, "kind": "dimmer", "channels": [channel]}
            for channel in ("red", "green", "blue")
        ]
    )
    ids = entity_ids(hass, entry)
    await asyncio.gather(
        command(hass, ids["red"], brightness=200),
        command(hass, ids["green"], brightness=80),
        command(hass, ids["blue"], brightness=40),
    )
    actual = unpack_rgb(source.brightness, source.rgb_color)
    assert actual == pytest.approx({"red": 200, "green": 80, "blue": 40}, abs=1)
    await command(hass, ids["red"], "turn_off")
    assert source.is_on
    actual = unpack_rgb(source.brightness, source.rgb_color)
    assert actual == pytest.approx({"red": 0, "green": 80, "blue": 40}, abs=1)
    await command(hass, ids["green"], "turn_off")
    await command(hass, ids["blue"], "turn_off")
    assert not source.is_on


async def test_pending_writes_preserve_siblings(hass, source, setup_transform):
    entry = await setup_transform(
        [{"name": channel, "kind": "dimmer", "channels": [channel]} for channel in ("red", "green")]
    )
    source.report = False
    ids = entity_ids(hass, entry)
    await command(hass, ids["red"], brightness=200)
    await command(hass, ids["green"], brightness=100)
    assert source.calls[-1][1] == {"brightness": 200, "rgb_color": (255, 128, 0)}
    assert entry.runtime_data.pending
    assert hass.states.get(ids["red"]).attributes["delivery_status"] == "pending"
    source._attr_is_on = True
    source._attr_rgb_color = (255, 128, 0)
    source._attr_brightness = 200
    source.async_write_ha_state()
    await hass.async_block_till_done()
    assert not entry.runtime_data.pending


async def test_feedback_timeout_adopts_actual(hass, source, setup_transform, caplog):
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    source.report = False
    light = next(iter(entity_ids(hass, entry).values()))
    await command(hass, light, brightness=90)
    entry.runtime_data._timeout(None)
    assert hass.states.get(light).state == "off"
    assert hass.states.get(light).attributes["delivery_status"] == "feedback_mismatch"
    assert "did not confirm" in caplog.text


async def test_errors_propagate_and_do_not_claim_success(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    light = next(iter(entity_ids(hass, entry).values()))
    source.fail = True
    with pytest.raises(HomeAssistantError, match="Simulated failure"):
        await command(hass, light, brightness=80)
    assert hass.states.get(light).state == "off"
    assert hass.states.get(light).attributes["delivery_status"] == "command_failed"
    assert not entry.runtime_data.pending


async def test_external_changes_and_unavailability(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    light = next(iter(entity_ids(hass, entry).values()))
    await command(hass, source.entity_id, brightness=77, rgb_color=(255, 0, 0))
    assert hass.states.get(light).state == "on"
    assert hass.states.get(light).attributes["brightness"] == 77
    source._attr_available = False
    source.async_write_ha_state()
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "unavailable"
    source._attr_available = True
    source.async_write_ha_state()
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "on"
    await command(hass, source.entity_id, color_temp_kelvin=3000)
    assert hass.states.get(light).state == "unavailable"
    await command(hass, source.entity_id, "turn_off")
    assert hass.states.get(light).state == "off"


async def test_fixed_cct_applied_on_every_on(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "dimmer", "fixed_kelvin": 2000}], transport="cct")
    light = next(iter(entity_ids(hass, entry).values()))
    await command(hass, light, brightness=120)
    assert source.calls[-1][1] == {"brightness": 120, "color_temp_kelvin": 2000}
    assert hass.states.get(light).attributes["supported_color_modes"] == ["brightness"]
    await command(hass, light, "turn_off")
    await command(hass, light)
    assert source.calls[-1][1] == {"brightness": 120, "color_temp_kelvin": 2000}


async def test_native_cct_passthrough_memory_and_feedback(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "cct", "max_kelvin": 6500}], transport="cct")
    light = next(iter(entity_ids(hass, entry).values()))
    state = hass.states.get(light)
    assert state.attributes["supported_color_modes"] == ["color_temp"]
    assert state.attributes["channels"] == []
    assert not state.attributes["approximate_channel_control"]
    assert state.attributes["supported_features"] == 32
    assert "effect_list" not in state.attributes
    assert not source.calls
    await command(hass, light, brightness=130, color_temp_kelvin=3500, transition=1)
    assert source.calls[-1][1] == {"brightness": 130, "color_temp_kelvin": 3500, "transition": 1}
    assert hass.states.get(light).attributes["color_temp_kelvin"] == 3500
    assert hass.states.get(light).attributes["delivery_status"] == "in_sync"
    await command(hass, source.entity_id, brightness=100, color_temp_kelvin=5000)
    assert hass.states.get(light).attributes["color_temp_kelvin"] == 5000
    await command(hass, light, "turn_off", transition=2)
    assert source.calls[-1] == ("off", {"transition": 2})
    before = len(source.calls)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(source.calls) == before
    assert hass.states.get(light).state == "off"
    await command(hass, light)
    assert source.calls[-1][1] == {"brightness": 100, "color_temp_kelvin": 5000}
    source.report = False
    await command(hass, light, color_temp_kelvin=3000)
    assert entry.runtime_data.pending
    assert hass.states.get(light).attributes["color_temp_kelvin"] == 3000
    entry.runtime_data._timeout(None)
    assert hass.states.get(light).attributes["color_temp_kelvin"] == 5000
    assert hass.states.get(light).attributes["delivery_status"] == "feedback_mismatch"


async def test_native_cct_startup_bounds_and_incompatible_feedback(hass, source, setup_transform):
    await command(hass, source.entity_id, brightness=90, color_temp_kelvin=3200)
    before = len(source.calls)
    entry = await setup_transform([{"kind": "cct"}], transport="cct")
    light = next(iter(entity_ids(hass, entry).values()))
    assert len(source.calls) == before
    assert hass.states.get(light).attributes["color_temp_kelvin"] == 3200
    await command(hass, light, color_temp_kelvin=1000)
    assert source.calls[-1][1]["color_temp_kelvin"] == 2000
    await command(hass, light, color_temp_kelvin=10000)
    assert source.calls[-1][1]["color_temp_kelvin"] == 6500
    await command(hass, source.entity_id, rgb_color=(255, 0, 0))
    assert hass.states.get(light).state == "unavailable"
    await command(hass, source.entity_id, "turn_off")
    assert hass.states.get(light).state == "off"
    await command(hass, light)
    assert source.calls[-1][1]["color_temp_kelvin"] == 6500
    source._attr_color_temp_kelvin = None
    source.async_write_ha_state()
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "unavailable"
    source._attr_is_on = False
    source._attr_max_color_temp_kelvin = 6000
    source.async_write_ha_state()
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "unavailable"


@pytest.mark.parametrize("kelvin", [3000, 3500, 6300])
async def test_native_cct_quantized_feedback(hass, source, setup_transform, kelvin):
    entry = await setup_transform([{"kind": "cct"}], transport="cct")
    light = next(iter(entity_ids(hass, entry).values()))
    source.report = False
    await command(hass, light, brightness=100, color_temp_kelvin=kelvin)
    assert entry.runtime_data.pending
    source._attr_is_on = True
    source._attr_color_mode = ColorMode.COLOR_TEMP
    source._attr_brightness = 100
    source._attr_color_temp_kelvin = round(1_000_000 / round(1_000_000 / kelvin))
    source.async_write_ha_state()
    await hass.async_block_till_done()
    assert not entry.runtime_data.pending
    assert hass.states.get(light).attributes["delivery_status"] == "in_sync"
    assert hass.states.get(light).attributes["color_temp_kelvin"] == source.color_temp_kelvin


@pytest.mark.parametrize("mode", [ColorMode.XY, ColorMode.HS])
async def test_color_conversion_sources(hass, source, setup_transform, mode):
    source._attr_supported_color_modes = {mode, ColorMode.COLOR_TEMP}
    source._attr_color_mode = mode
    source.async_write_ha_state()
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    light = next(iter(entity_ids(hass, entry).values()))
    await command(hass, light, brightness=100)
    assert hass.states.get(light).attributes["approximate_channel_control"]
    assert ("xy_color" if mode == ColorMode.XY else "hs_color") in source.calls[-1][1]
    assert "rgb_color" not in source.calls[-1][1]


async def test_reload_retains_brightness_without_turning_on(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "cct"}])
    light = next(iter(entity_ids(hass, entry).values()))
    await command(hass, light, brightness=150, color_temp_kelvin=6500)
    await command(hass, light, "turn_off")
    before = len(source.calls)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(source.calls) == before
    assert hass.states.get(light).state == "off"
    await command(hass, light)
    assert source.calls[-1][1] == {"brightness": 150, "rgb_color": (0, 255, 0)}


async def test_zero_brightness_and_context(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    light = next(iter(entity_ids(hass, entry).values()))
    context = Context()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": light, "brightness": 111}, blocking=True, context=context
    )
    assert hass.states.get(source.entity_id).context == context
    await command(hass, light, brightness=0)
    assert not source.is_on
    await command(hass, light)
    assert source.brightness == 111


async def test_toggle_serialized(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    light = next(iter(entity_ids(hass, entry).values()))
    await asyncio.gather(command(hass, light, "toggle"), command(hass, light, "toggle"))
    assert [call[0] for call in source.calls] == ["on", "off"]
    assert hass.states.get(light).state == "off"


async def test_cct_plus_dimmer_and_native_scene_restore(hass, source, setup_transform):
    from homeassistant.setup import async_setup_component

    entry = await setup_transform(
        [
            {"name": "CCT", "kind": "cct", "warm_channel": "blue", "cold_channel": "red"},
            {"name": "Dimmer", "kind": "dimmer", "channels": ["green"]},
        ]
    )
    ids = entity_ids(hass, entry)
    await command(hass, ids["CCT"], brightness=160, color_temp_kelvin=4250)
    await command(hass, ids["Dimmer"], brightness_pct=20)
    actual = unpack_rgb(source.brightness, source.rgb_color)
    assert actual == pytest.approx({"red": 80, "green": 51, "blue": 80}, abs=1)
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()
    await hass.services.async_call(
        "scene",
        "create",
        {"scene_id": "before_transform_change", "snapshot_entities": list(ids.values())},
        blocking=True,
    )
    await command(hass, ids["CCT"], "turn_off")
    assert source.is_on
    await command(hass, ids["Dimmer"], brightness_step=40)
    assert source.brightness == 91
    await hass.services.async_call(
        "scene", "turn_on", {"entity_id": "scene.before_transform_change"}, blocking=True
    )
    await hass.async_block_till_done()
    actual = unpack_rgb(source.brightness, source.rgb_color)
    assert actual == pytest.approx({"red": 80, "green": 51, "blue": 80}, abs=1)


async def test_unload_stops_timer_and_rejects_queued_commands(hass, source, setup_transform):
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red"]}])
    controller = entry.runtime_data
    light = next(iter(entity_ids(hass, entry).values()))
    source.report = False
    await command(hass, light, brightness=80)
    assert controller.pending
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not controller.pending
    assert controller._cancel_timeout is None
    calls = len(source.calls)
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await controller.command(next(iter(controller.outputs)), "on", {}, None)
    assert len(source.calls) == calls


async def test_startup_observes_on_source_without_writing(hass, source, setup_transform):
    await command(hass, source.entity_id, brightness=128, rgb_color=(255, 128, 0))
    count = len(source.calls)
    entry = await setup_transform(
        [
            {"name": "Red", "kind": "dimmer", "channels": ["red"]},
            {"name": "Green", "kind": "dimmer", "channels": ["green"]},
        ]
    )
    assert len(source.calls) == count
    ids = entity_ids(hass, entry)
    assert hass.states.get(ids["Red"]).attributes["brightness"] == 128
    assert hass.states.get(ids["Green"]).attributes["brightness"] == 64


async def test_tied_dimmer_channels_and_no_transition_capability(hass, source, setup_transform):
    source._attr_supported_features = LightEntityFeature(0)
    source.async_write_ha_state()
    entry = await setup_transform([{"kind": "dimmer", "channels": ["red", "blue"]}])
    light = next(iter(entity_ids(hass, entry).values()))
    assert hass.states.get(light).attributes["supported_features"] == 0
    await command(hass, light, brightness=90)
    assert source.calls[-1][1] == {"brightness": 90, "rgb_color": (255, 0, 255)}


async def test_source_update_during_storage_load_is_observed(hass, source, monkeypatch):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.light_transform.controller import Controller
    from custom_components.light_transform.model import Output

    entry = MockConfigEntry(domain="light_transform", data={"transport": "rgb"})
    controller = Controller(
        hass, entry, source.entity_id, [Output("red", "Red", "dimmer", ("red",))]
    )

    async def load_with_source_update():
        source._attr_is_on = True
        source._attr_brightness = 53
        source.async_write_ha_state()
        return None

    monkeypatch.setattr(controller._store, "async_load", load_with_source_update)
    await controller.initialize()
    assert controller.levels["red"].on
    assert controller.levels["red"].brightness == 53
    assert not source.calls
