"""Tests for the standalone MCP150 probe; no real hardware or cloud access."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from scripts import mcp150_local as probe


def make_status(flow=75, device_id="test_mcp150"):
    raw = bytearray(index % 256 for index in range(probe.STATUS_SIZE))
    raw[:2] = b"\x00\x61"
    raw[2] = flow
    raw[3] = 50
    raw[4] = 15
    raw[400] = 0
    return probe.Status(device_id, bytes(raw))


def info_payload():
    return b"00000000" * 6 + b"\x00\x00\x00\x20" + probe.PRODUCT_KEY.encode()


def status_frame(sequence, status):
    did = status.device_id.encode()
    return probe.Frame(
        1, 0x0094,
        sequence.to_bytes(4, "big") + len(did).to_bytes(2, "big")
        + did + b"\x03" + status.raw,
    )


@pytest.mark.parametrize(
    ("length", "expected"), [(3, b"\x03"), (127, b"\x7f"), (128, b"\x80\x01"), (416, b"\xa0\x03")],
)
def test_frame_length_encoding(length, expected):
    packet = probe.encode_frame(0x0093, b"\x00" * (length - 3))
    assert packet == probe.HEADER + expected + b"\x00\x00\x93" + b"\x00" * (length - 3)


def test_read_fragmented_large_frame():
    packet = probe.encode_frame(0x0094, b"x" * 430)
    incoming = bytearray(packet)
    connection = MagicMock()

    def receive(count):
        chunk = bytes(incoming[:min(count, 2)])
        del incoming[:len(chunk)]
        return chunk

    connection.recv.side_effect = receive
    client = probe.MCP150Client(connection)
    frame = client._read_frame(probe.time.monotonic() + 5)
    assert frame == probe.Frame(0, 0x0094, b"x" * 430)
    assert not incoming


@pytest.mark.parametrize("packet", [
    b"bad!", probe.HEADER + b"\x02",
    probe.HEADER + b"\x80\x80\x80\x80",
    probe.HEADER + b"\x81\x20",
])
def test_reject_invalid_frame(packet):
    incoming = bytearray(packet)
    connection = MagicMock()

    def receive(count):
        result = bytes(incoming[:count])
        del incoming[:count]
        return result

    connection.recv.side_effect = receive
    with pytest.raises(probe.ProbeError):
        probe.MCP150Client(connection)._read_frame(probe.time.monotonic() + 5)


def test_reject_eof():
    connection = MagicMock()
    connection.recv.return_value = b""
    with pytest.raises(probe.ProbeError, match="closed"):
        probe.MCP150Client(connection)._read_frame(probe.time.monotonic() + 5)


def test_product_key_guard():
    assert probe.parse_product_key(info_payload()) == probe.PRODUCT_KEY
    with pytest.raises(probe.ProbeError, match="Refusing"):
        probe.parse_product_key(info_payload()[:-32] + b"0" * 32)


@pytest.mark.parametrize("payload", [b"", b"x" * 51, b"x" * 84, info_payload()[:-1]])
def test_reject_malformed_product_info(payload):
    with pytest.raises(probe.ProbeError):
        probe.parse_product_key(payload)


def test_flow_control_golden_mask_and_preserved_values():
    original = make_status()
    control = probe.flow_control(original, 76)
    assert control[:9] == b"\x01\x00\x00\x00\x00\x00\x00\x01\x00"
    assert len(control) == 409
    expected = bytearray(original.raw[:400])
    expected[2] = 76
    assert control[9:] == bytes(expected)
    assert original.flow == 75
    packet = probe.encode_frame(0x0093, b"\x00\x00\x00\x02" + control)
    assert packet[:12] == bytes.fromhex("00000003a003000093000000")
    assert packet[12] == 2


@pytest.mark.parametrize("value", [0, 101, -1, True, 1.5])
def test_reject_invalid_flow(value):
    with pytest.raises(probe.ProbeError, match="Flow must"):
        probe.flow_control(make_status(), value)


def test_summary_uses_big_endian_bit_word():
    raw = bytearray(make_status().raw)
    raw[:2] = (1 | 8 | (3 << 5) | (2 << 7)).to_bytes(2, "big")
    summary = probe.Status("pump", bytes(raw)).summary()
    assert summary["SwitchON"] is True
    assert summary["TimerON"] is True
    assert summary["FeedSwitch"] is False
    assert summary["Mode"] == 3
    assert summary["Linkage"] == 2


def test_login_does_not_expose_or_strip_binding_length(capsys):
    connection = MagicMock()
    client = probe.MCP150Client(connection)
    binding = b"\x00\x0a" + b"secretcode"
    with patch.object(client, "_response", side_effect=[
        probe.Frame(0, 0x14, info_payload()),
        probe.Frame(0, 0x07, binding),
        probe.Frame(0, 0x09, b"\x00"),
    ]):
        client.login()
    assert connection.sendall.call_args_list[2].args[0] == probe.encode_frame(8, binding)
    assert "secretcode" not in capsys.readouterr().out


def test_rejected_login():
    client = probe.MCP150Client(MagicMock())
    with patch.object(client, "_response", side_effect=[
        probe.Frame(0, 0x14, info_payload()),
        probe.Frame(0, 0x07, b"\x00\x01x"),
        probe.Frame(0, 0x09, b"\x01"),
    ]), pytest.raises(probe.ProbeError, match="rejected"):
        client.login()


def test_unknown_product_stops_before_binding():
    connection = MagicMock()
    client = probe.MCP150Client(connection)
    with patch.object(client, "_response", return_value=probe.Frame(
        0, 0x14, info_payload()[:-32] + b"0" * 32,
    )), pytest.raises(probe.ProbeError, match="Refusing"):
        client.login()
    connection.sendall.assert_called_once_with(probe.encode_frame(0x0013))


def test_read_status_ignores_write_ack_and_unsolicited_reports():
    client = probe.MCP150Client(MagicMock())
    expected = make_status()
    with patch.object(client, "_read_frame", side_effect=[
        probe.Frame(0, 0x0094, b"\x00\x00\x00\x00"),
        status_frame(0, make_status(10)),
        status_frame(1, expected),
    ]):
        assert client.read_status() == expected
    assert client.connection.sendall.call_args.args[0] == bytes.fromhex("00000003080000930000000102")


@pytest.mark.parametrize("raw", [b"", b"x" * 400, b"x" * 402])
def test_status_length_guard(raw):
    with pytest.raises(probe.ProbeError):
        probe.Status("pump", raw)


def test_verify_ignores_clock_but_not_schedule_or_mode_changes():
    original = make_status()
    raw = bytearray(original.raw)
    raw[2] += 1
    raw[392:400] = b"newclock"
    probe.verify_unchanged(original, probe.Status(original.device_id, bytes(raw)))
    raw[8] ^= 1
    with pytest.raises(probe.ProbeError, match="offsets"):
        probe.verify_unchanged(original, probe.Status(original.device_id, bytes(raw)))


def test_verify_rejects_different_device():
    with pytest.raises(probe.ProbeError, match="Device ID"):
        probe.verify_unchanged(make_status(), make_status(device_id="another_pump"))


@pytest.fixture
def flow_clients():
    initial = MagicMock(spec=probe.MCP150Client)
    restore = MagicMock(spec=probe.MCP150Client)
    initial.read_status.return_value = make_status()
    initial.wait_for_flow.return_value = make_status(76)
    restore.read_status.return_value = make_status(76)
    restore.wait_for_flow.return_value = make_status()
    with patch.object(probe, "connect", side_effect=[
        nullcontext(initial), nullcontext(restore),
    ]), patch.object(
        probe, "confirm_device",
        side_effect=lambda host, did, changes, model: make_status(changes["Flow"]),
    ), patch.object(probe.time, "sleep"):
        yield initial, restore


def test_flow_test_verifies_change_and_restoration(flow_clients, capsys):
    initial, restore = flow_clients
    probe.run_flow_test("192.0.2.1", 2)
    initial.write_flow.assert_called_once_with(make_status(), 76)
    initial.wait_for_flow.assert_called_once_with(76, "test_mcp150")
    restore.write_flow.assert_called_once_with(make_status(76), 75)
    restore.wait_for_flow.assert_called_once_with(75, "test_mcp150")
    assert "LOCAL WRITE TEST PASSED" in capsys.readouterr().out


def test_maximum_flow_steps_down_and_restores(flow_clients):
    initial, restore = flow_clients
    initial.read_status.return_value = make_status(100)
    initial.wait_for_flow.return_value = make_status(99)
    restore.read_status.return_value = make_status(99)
    restore.wait_for_flow.return_value = make_status(100)
    probe.run_flow_test("192.0.2.1", 2)
    initial.write_flow.assert_called_once_with(make_status(100), 99)
    restore.write_flow.assert_called_once_with(make_status(99), 100)


@pytest.mark.parametrize("error", [OSError("ambiguous send"), KeyboardInterrupt()])
def test_restore_even_when_write_raises(flow_clients, error):
    initial, restore = flow_clients
    initial.write_flow.side_effect = error
    with pytest.raises(type(error)):
        probe.run_flow_test("192.0.2.1", 2)
    restore.write_flow.assert_called_once_with(make_status(76), 75)


def test_restore_after_failed_readback(flow_clients, capsys):
    initial, restore = flow_clients
    initial.wait_for_flow.side_effect = probe.ProbeError("No confirmed change")
    with pytest.raises(probe.ProbeError, match="No confirmed change"):
        probe.run_flow_test("192.0.2.1", 2)
    restore.write_flow.assert_called_once()
    assert "LOCAL WRITE TEST PASSED" not in capsys.readouterr().out


def test_restoration_failure_is_explicit(flow_clients, capsys):
    _, restore = flow_clients
    restore.wait_for_flow.side_effect = TimeoutError("offline")
    with pytest.raises(probe.RestorationError, match="set Flow=75"):
        probe.run_flow_test("192.0.2.1", 2)
    assert "LOCAL WRITE TEST PASSED" not in capsys.readouterr().out


def test_refuse_restoration_to_another_device(flow_clients):
    _, restore = flow_clients
    restore.read_status.return_value = make_status(device_id="another_pump")
    with pytest.raises(probe.RestorationError, match="another pump"):
        probe.run_flow_test("192.0.2.1", 2)
    restore.write_flow.assert_not_called()


def test_default_cli_is_read_only(capsys):
    client = MagicMock(spec=probe.MCP150Client)
    client.wifi_firmware = "test_fw"
    client.read_status.return_value = make_status()
    with patch.object(probe, "connect", return_value=nullcontext(client)):
        assert probe.main(["192.0.2.1"]) == 0
    client.write_flow.assert_not_called()
    assert '"Flow": 75' in capsys.readouterr().out


@pytest.mark.parametrize("hold", ["0", "-1", "61", "nan", "inf"])
def test_invalid_hold_does_not_connect(hold):
    with patch.object(probe, "connect") as connect:
        with pytest.raises(SystemExit):
            probe.main(["192.0.2.1", "--test-flow", "--hold", hold])
        connect.assert_not_called()


@pytest.mark.parametrize(("name", "value"), [
    ("SwitchON", False), ("PulseTide", True), ("FeedSwitch", True), ("TimerON", False),
    ("Mode", probe.MODEL["attrs"][4]["enum"][0]),
    ("Linkage", probe.MODEL["attrs"][5]["enum"][2]),
    ("Flow", 76), ("Frequency", 51.0), ("FeedTime", 16),
])
def test_every_control_encodes_only_its_flag_and_value(name, value):
    original = make_status()
    attrs = {attr["name"]: attr for attr in probe.MODEL["attrs"]}
    payload = probe.protocol.control_payload(original, {name: value}, probe.MODEL)
    assert payload[:9] == b"\x01" + (1 << attrs[name]["id"]).to_bytes(8, "big")
    after = probe.Status(original.device_id, payload[9:] + original.raw[400:])
    current = probe.protocol.control_values(original, probe.MODEL)
    current[name] = value
    assert probe.protocol.control_values(after, probe.MODEL) == current
    assert after.raw[8:] == original.raw[8:]


@pytest.mark.parametrize(("name", "values"), [
    ("Flow", [1, 100]), ("Frequency", [5, 100]), ("FeedTime", [1, 60]),
    ("Mode", probe.MODEL["attrs"][4]["enum"]), ("Linkage", probe.MODEL["attrs"][5]["enum"]),
])
def test_all_enum_options_and_numeric_boundaries(name, values):
    for value in values:
        original = make_status()
        payload = probe.protocol.control_payload(original, {name: value}, probe.MODEL)
        after = probe.Status(original.device_id, payload[9:] + original.raw[400:])
        assert probe.protocol.control_values(after, probe.MODEL)[name] == value


@pytest.mark.parametrize("changes", [
    {}, {"Fault_UART": False}, {"unknown": 1}, {"SwitchON": 1},
    {"Mode": "invalid"}, {"Linkage": 2}, {"Flow": 0}, {"Flow": 101},
    {"Flow": 1.5}, {"Flow": float("nan")}, {"Flow": float("inf")},
    {"Flow": 10 ** 400}, {"Frequency": 4}, {"FeedTime": 61},
])
def test_invalid_commands_rejected_before_connecting(changes):
    with patch.object(probe.protocol, "connect") as connect:
        with pytest.raises(probe.protocol.InvalidCommand):
            probe.protocol.control_device("192.0.2.1", "pump", changes, probe.MODEL)
        connect.assert_not_called()


def test_combined_control_preserves_cross_byte_linkage_and_mode():
    original = make_status()
    changes = {
        "Linkage": probe.MODEL["attrs"][5]["enum"][2],
        "Mode": probe.MODEL["attrs"][4]["enum"][1],
        "SwitchON": False, "Flow": 76,
    }
    payload = probe.protocol.control_payload(original, changes, probe.MODEL)
    after = probe.Status(original.device_id, payload[9:] + original.raw[400:])
    expected = probe.protocol.control_values(original, probe.MODEL)
    expected.update(changes)
    assert probe.protocol.control_values(after, probe.MODEL) == expected
    assert payload[1:9] == ((1 << 6) | (1 << 5) | 1 | (1 << 8)).to_bytes(8, "big")


def test_wrong_device_id_never_receives_a_write():
    client = MagicMock(spec=probe.MCP150Client)
    client.read_status.return_value = make_status(device_id="other_pump")
    with patch.object(probe.protocol, "connect", return_value=nullcontext(client)):
        with pytest.raises(probe.ProbeError, match="no command sent"):
            probe.protocol.control_device("192.0.2.1", "expected", {"Flow": 76}, probe.MODEL)
    client.write_attributes.assert_not_called()


def test_all_command_cases_cover_nine_controls_and_each_enum_option():
    original = make_status()
    current = probe.protocol.control_values(original, probe.MODEL)
    cases = probe.command_cases(original)
    assert len(cases) == 12
    assert {name for case in cases for name in case} == probe.protocol.CONTROL_NAMES
    for name in ("Mode", "Linkage"):
        spec = next(attr for attr in probe.MODEL["attrs"] if attr["name"] == name)
        assert {case[name] for case in cases if name in case} | {current[name]} == set(spec["enum"])


def test_attribute_test_restores_even_after_ambiguous_send(capsys):
    initial = MagicMock(spec=probe.MCP150Client)
    restore = MagicMock(spec=probe.MCP150Client)
    original = make_status()
    initial.read_status.return_value = original
    initial.write_attributes.side_effect = OSError("write may have reached pump")
    restore.read_status.return_value = original
    restore.wait_for_attributes.return_value = original
    with patch.object(
        probe, "connect", side_effect=[nullcontext(initial), nullcontext(restore)],
    ), patch.object(probe, "confirm_device", return_value=original):
        with pytest.raises(OSError, match="may have reached"):
            probe.run_attribute_test("192.0.2.1", {"SwitchON": False}, 2)
    restore.write_attributes.assert_called_once_with(original, {"SwitchON": True}, probe.MODEL)
    assert "PASS" not in capsys.readouterr().out


def test_attribute_test_restores_related_device_side_effects(capsys):
    initial = MagicMock(spec=probe.MCP150Client)
    restore = MagicMock(spec=probe.MCP150Client)
    original = make_status()
    payload = probe.protocol.control_payload(original, {"FeedSwitch": True, "Flow": 50}, probe.MODEL)
    observed = probe.Status(original.device_id, payload[9:] + original.raw[400:])
    initial.read_status.return_value = original
    initial.wait_for_attributes.return_value = observed
    restore.read_status.return_value = observed
    restore.wait_for_attributes.return_value = original
    with patch.object(probe, "connect", side_effect=[
        nullcontext(initial), nullcontext(restore),
    ]), patch.object(
        probe, "confirm_device", side_effect=[observed, original],
    ), patch.object(probe.time, "sleep"):
        probe.run_attribute_test("192.0.2.1", {"FeedSwitch": True}, 2)
    restore.write_attributes.assert_called_once_with(
        observed, {"FeedSwitch": False, "Flow": 75}, probe.MODEL,
    )
    output = capsys.readouterr().out
    assert "Device also updated" in output
    assert "PASS" in output


def test_flow_probe_refuses_an_active_native_timer():
    initial = MagicMock(spec=probe.MCP150Client)
    raw = bytearray(make_status().raw)
    raw[1] |= 8
    initial.read_status.return_value = probe.Status("test_mcp150", bytes(raw))
    with patch.object(probe, "connect", return_value=nullcontext(initial)):
        with pytest.raises(probe.ProbeError, match="Native timer"):
            probe.run_flow_test("192.0.2.1", 2)
    initial.write_flow.assert_not_called()


def test_same_session_echo_is_not_enough_for_command_success():
    client = MagicMock(spec=probe.MCP150Client)
    client.read_status.return_value = make_status()
    client.wait_for_attributes.return_value = make_status(76)
    with patch.object(
        probe.protocol, "connect", return_value=nullcontext(client),
    ), patch.object(
        probe.protocol, "confirm_device", side_effect=probe.ProbeError("independent read still 75"),
    ) as confirm:
        with pytest.raises(probe.ProbeError, match="independent read"):
            probe.protocol.control_device("192.0.2.1", "test_mcp150", {"Flow": 76}, probe.MODEL)
    confirm.assert_called_once_with("192.0.2.1", "test_mcp150", {"Flow": 76}, probe.MODEL)


def test_full_probe_restores_native_timer_after_a_failed_test(capsys):
    baseline = make_status()
    raw = bytearray(baseline.raw)
    raw[1] |= 8
    original = probe.Status(baseline.device_id, bytes(raw))
    first = MagicMock(spec=probe.MCP150Client)
    first.read_status.return_value = original
    second = MagicMock(spec=probe.MCP150Client)
    second.read_status.return_value = baseline
    with patch.object(
        probe, "connect", side_effect=[nullcontext(first), nullcontext(second)],
    ), patch.object(
        probe.protocol, "control_device", side_effect=[baseline, original],
    ) as command, patch.object(
        probe, "run_attribute_test", side_effect=probe.ProbeError("test failed"),
    ):
        with pytest.raises(probe.ProbeError, match="test failed"):
            probe.run_all_tests("192.0.2.1", 0.5)
    assert command.call_args_list[0].args[2] == {"TimerON": False}
    assert command.call_args_list[-1].args[2] == probe.protocol.control_values(original, probe.MODEL)
    assert command.call_args_list[-1].args[2]["TimerON"] is True
    assert "ALL NINE CONTROLS PASSED" not in capsys.readouterr().out
