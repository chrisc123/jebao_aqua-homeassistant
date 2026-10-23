"""MCP150 API, coordinator and platform routing tests without real devices."""

import asyncio
import json
from pathlib import Path
import threading
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.jebao_aqua import GizwitsDataUpdateCoordinator
from custom_components.jebao_aqua.api import AuthenticationError, GizwitsApi
from custom_components.jebao_aqua import local
from custom_components.jebao_aqua.number import JebaoPumpNumber
from custom_components.jebao_aqua.select import JebaoPumpSelect
from custom_components.jebao_aqua.switch import JebaoPumpSwitch


DEVICE_ID = "test_mcp150"
IP = "192.0.2.1"


@pytest.fixture
def model():
    path = Path(__file__).resolve().parents[1] / "custom_components/jebao_aqua/models"
    return json.loads((path / f"{local.PRODUCT_KEY}.json").read_text())


def status():
    raw = bytearray(401)
    raw[:2] = b"\x00\x49"
    raw[2:5] = bytes([75, 50, 15])
    return local.Status(DEVICE_ID, bytes(raw))


def changed_status(model, attributes):
    original = status()
    payload = local.control_payload(original, attributes, model)
    return local.Status(DEVICE_ID, payload[9:] + original.raw[400:])


def device_data(model, snapshot=None):
    snapshot = snapshot or status()
    return {"did": snapshot.device_id, "attr": local.decode_status(snapshot, model)}


def requested_change(model, name):
    attr = next(item for item in model["attrs"] if item["name"] == name)
    current = local.control_values(status(), model)[name]
    if isinstance(current, bool):
        return not current
    if attr["data_type"] == "enum":
        return next(value for value in attr["enum"] if value != current)
    assert isinstance(current, int)
    return current + 1


@pytest.fixture
def api(model):
    client = GizwitsApi(
        login_url="https://example.com/login",
        devices_url="https://example.com/devices",
        device_data_url="https://example.com/devdata/{device_id}",
        control_url="https://example.com/control/{device_id}",
    )
    client.add_attribute_models({local.PRODUCT_KEY: model})
    return client


@pytest.fixture
def coordinator(hass, mock_api, model):
    instance = GizwitsDataUpdateCoordinator(hass, mock_api)
    instance.device_inventory = [{
        "did": DEVICE_ID, "dev_alias": "MCP150", "product_key": local.PRODUCT_KEY,
        "lan_ip": IP,
    }]
    instance.device_data = {DEVICE_ID: device_data(model)}
    mock_api.control_local_device = AsyncMock(return_value=device_data(model))
    return instance


@pytest.mark.asyncio
async def test_api_local_control_uses_worker_and_decodes_cross_byte_linkage(api, model):
    main_thread = threading.get_ident()
    attributes = {"Linkage": next(attr for attr in model["attrs"] if attr["name"] == "Linkage")["enum"][2]}
    expected = changed_status(model, attributes)

    def local_command(*_args):
        assert threading.get_ident() != main_thread
        return expected

    with patch(
        "custom_components.jebao_aqua.api.control_local", side_effect=local_command,
    ) as command, patch.object(api, "_api_request", new_callable=AsyncMock) as http:
        result = await api.control_local_device(IP, local.PRODUCT_KEY, DEVICE_ID, attributes)
    command.assert_called_once_with(IP, DEVICE_ID, attributes, model)
    assert result == device_data(model, expected)
    assert result["attr"]["Linkage"] == attributes["Linkage"]
    http.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_polling_uses_same_status_decoder(api, model):
    attributes = {"Linkage": next(attr for attr in model["attrs"] if attr["name"] == "Linkage")["enum"][2]}
    expected = changed_status(model, attributes)
    with patch("custom_components.jebao_aqua.api.read_local", return_value=expected) as read:
        result = await api.get_local_device_data(IP, local.PRODUCT_KEY, DEVICE_ID)
    read.assert_called_once_with(IP, DEVICE_ID)
    assert result == device_data(model, expected)


@pytest.mark.asyncio
async def test_failed_verified_poll_is_explicit(api, caplog):
    with patch("custom_components.jebao_aqua.api.read_local", side_effect=TimeoutError("offline")):
        assert await api.get_local_device_data(IP, local.PRODUCT_KEY, DEVICE_ID) is None
    assert "Local status failed" in caplog.text


@pytest.mark.asyncio
async def test_invalid_api_command_never_opens_a_socket(api):
    with patch("custom_components.jebao_aqua.local.connect") as connect:
        with pytest.raises(local.InvalidCommand):
            await api.control_local_device(IP, local.PRODUCT_KEY, DEVICE_ID, {"Flow": 0})
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_api_model_never_attempts_lan(api):
    with patch("custom_components.jebao_aqua.api.control_local") as command:
        with pytest.raises(local.ProbeError, match="No verified"):
            await api.control_local_device(IP, "other_product", DEVICE_ID, {"Flow": 50})
    command.assert_not_called()


@pytest.mark.asyncio
async def test_confirmed_local_control_updates_entities_and_resets_backoff(coordinator, model):
    expected = device_data(model, changed_status(model, {"Flow": 76}))
    coordinator.api.control_local_device.return_value = expected
    coordinator._lan_failure_counts[DEVICE_ID] = 3
    await coordinator.async_control_device(DEVICE_ID, {"Flow": 76})
    coordinator.api.control_local_device.assert_awaited_once_with(
        IP, local.PRODUCT_KEY, DEVICE_ID, {"Flow": 76},
    )
    coordinator.api.control_device.assert_not_awaited()
    assert coordinator.device_data[DEVICE_ID] == expected
    assert coordinator.data[DEVICE_ID] == expected
    assert coordinator._lan_failure_counts[DEVICE_ID] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("offline"), local.ProbeError("unconfirmed")])
@pytest.mark.parametrize("name", sorted(local.CONTROL_NAMES))
async def test_local_failure_falls_back_to_identical_cloud_command(coordinator, model, name, error, caplog):
    coordinator.api.control_local_device.side_effect = error
    changes = {name: requested_change(model, name)}
    await coordinator.async_control_device(DEVICE_ID, changes)
    coordinator.api.control_device.assert_awaited_once_with(DEVICE_ID, changes)
    assert "falling back to cloud" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    None, {"did": DEVICE_ID, "attr": {}}, {"did": "other_pump", "attr": {"Flow": 76}},
])
async def test_invalid_local_reply_uses_cloud_instead_of_claiming_success(coordinator, reply):
    coordinator.api.control_local_device.return_value = reply
    await coordinator.async_control_device(DEVICE_ID, {"Flow": 76})
    coordinator.api.control_device.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_value_is_not_retried_through_cloud(coordinator):
    coordinator.api.control_local_device.side_effect = local.InvalidCommand("invalid Flow")
    with pytest.raises(HomeAssistantError, match="invalid Flow"):
        await coordinator.async_control_device(DEVICE_ID, {"Flow": 0})
    coordinator.api.control_device.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [
    ("lan_ip", None), ("product_key", "legacy_product"),
])
async def test_other_models_or_missing_ip_preserve_cloud_control(coordinator, field, value):
    coordinator.device_inventory[0][field] = value
    await coordinator.async_control_device(DEVICE_ID, {"Flow": 76})
    coordinator.api.control_local_device.assert_not_awaited()
    coordinator.api.control_device.assert_awaited_once_with(DEVICE_ID, {"Flow": 76})


@pytest.mark.asyncio
async def test_unverified_attributes_stay_cloud_only(coordinator):
    await coordinator.async_control_device(DEVICE_ID, {"AutoTime00": "unchanged"})
    coordinator.api.control_local_device.assert_not_awaited()
    coordinator.api.control_device.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_cloud_fallback_surfaces_service_error(coordinator):
    coordinator.api.control_local_device.side_effect = TimeoutError("offline")
    coordinator.api.control_device.return_value = None
    with pytest.raises(HomeAssistantError, match="Cloud control failed"):
        await coordinator.async_control_device(DEVICE_ID, {"Flow": 76})


@pytest.mark.asyncio
async def test_cloud_auth_failure_surfaces_service_error(coordinator):
    coordinator.api.control_local_device.side_effect = TimeoutError("offline")
    coordinator.api.control_device.side_effect = AuthenticationError("expired")
    with pytest.raises(HomeAssistantError, match="Cloud authentication failed"):
        await coordinator.async_control_device(DEVICE_ID, {"Flow": 76})


@pytest.mark.asyncio
async def test_empty_cloud_ack_is_still_success(coordinator):
    coordinator.device_inventory[0]["lan_ip"] = None
    coordinator.api.control_device.return_value = {}
    await coordinator.async_control_device(DEVICE_ID, {"Flow": 76})


@pytest.mark.asyncio
async def test_polling_and_commands_share_the_device_lock(coordinator, model):
    started = asyncio.Event()
    release = asyncio.Event()
    events = []

    async def poll(*_args):
        events.append("poll-start")
        started.set()
        await release.wait()
        events.append("poll-end")
        return device_data(model)

    async def command(*_args):
        events.append("command")
        return device_data(model)

    coordinator.api.get_local_device_data.side_effect = poll
    coordinator.api.control_local_device.side_effect = command
    poll_task = asyncio.create_task(coordinator.get_device_data(DEVICE_ID))
    await started.wait()
    command_task = asyncio.create_task(coordinator.async_control_device(DEVICE_ID, {"Flow": 76}))
    await asyncio.sleep(0)
    coordinator.api.control_local_device.assert_not_awaited()
    release.set()
    await asyncio.gather(poll_task, command_task)
    assert events == ["poll-start", "poll-end", "command"]


@pytest.mark.asyncio
async def test_cancellation_keeps_lock_until_socket_worker_finishes(hass, api):
    coordinator = GizwitsDataUpdateCoordinator(hass, api)
    coordinator.device_inventory = [{
        "did": DEVICE_ID, "product_key": local.PRODUCT_KEY, "lan_ip": IP,
    }]
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def blocked_socket(*_args):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise TimeoutError("test worker was not released")
        return status()

    with patch(
        "custom_components.jebao_aqua.api.control_local", side_effect=blocked_socket,
    ), patch.object(api, "control_device", new_callable=AsyncMock) as cloud:
        task = asyncio.create_task(coordinator.async_control_device(DEVICE_ID, {"Flow": 76}))
        await started.wait()
        task.cancel()
        try:
            await asyncio.sleep(0)
            assert coordinator._device_update_locks[DEVICE_ID].locked()
            assert not task.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not coordinator._device_update_locks[DEVICE_ID].locked()
        cloud.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(local.CONTROL_NAMES))
async def test_every_ha_control_routes_through_local_first(coordinator, model, name):
    attr = next(item for item in model["attrs"] if item["name"] == name)
    target = requested_change(model, name)
    if attr["data_type"] == "bool":
        entity = JebaoPumpSwitch(coordinator, coordinator.device_inventory[0], attr)
    elif attr["data_type"] == "enum":
        entity = JebaoPumpSelect(coordinator, coordinator.device_inventory[0], attr)
    else:
        entity = JebaoPumpNumber(coordinator, coordinator.device_inventory[0], attr)
    coordinator.api.control_local_device.return_value = device_data(
        model, changed_status(model, {name: target}),
    )
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock,
    ), patch("custom_components.jebao_aqua.switch.asyncio.sleep", new_callable=AsyncMock):
        if isinstance(entity, JebaoPumpSwitch):
            if target:
                await entity.async_turn_on()
            else:
                await entity.async_turn_off()
            assert entity.is_on == target
        elif isinstance(entity, JebaoPumpSelect):
            option = attr["desc"][attr["enum"].index(target)]
            await entity.async_select_option(option)
            assert entity.current_option == option
        else:
            await entity.async_set_native_value(float(target))
            assert entity.native_value == target
    coordinator.api.control_local_device.assert_awaited_once_with(
        IP, local.PRODUCT_KEY, DEVICE_ID, {name: target},
    )
    coordinator.api.control_device.assert_not_awaited()
