"""Standalone MCP150 LAN probe; writes require an explicit test option."""

import argparse
import importlib.util
from ipaddress import IPv4Address
import json
import math
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "jebao_aqua"
if TYPE_CHECKING:
    from custom_components.jebao_aqua import local as protocol
else:
    # Load the dependency-free protocol without importing Home Assistant.
    spec = importlib.util.spec_from_file_location("jebao_aqua_local_probe", COMPONENT / "local.py")
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load the Jebao LAN protocol")
    protocol = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = protocol
    spec.loader.exec_module(protocol)

PRODUCT_KEY = protocol.PRODUCT_KEY
HEADER = protocol.HEADER
STATUS_SIZE = protocol.STATUS_SIZE
Frame = protocol.Frame
Status = protocol.Status
ProbeError = protocol.ProbeError
RestorationError = protocol.RestorationError
MCP150Client = protocol.MCP150Client
encode_frame = protocol.encode_frame
parse_product_key = protocol.parse_product_key
flow_control = protocol.flow_control
verify_unchanged = protocol.verify_unchanged
connect = protocol.connect
confirm_device = protocol.confirm_device
MODEL = json.loads((COMPONENT / "models" / f"{PRODUCT_KEY}.json").read_text())


def run_flow_test(host: str, hold: float) -> None:
    baseline = None
    write_attempted = False
    try:
        with connect(host) as client:
            baseline = client.read_status()
            if not 1 <= baseline.flow <= 100:
                raise ProbeError("Refusing a test with an original Flow outside 1..100")
            if baseline.summary()["TimerON"]:
                raise ProbeError(
                    "Native timer is enabled and can override Flow. Disable it first, "
                    "or use --test-all to temporarily disable and restore it."
                )
            target = baseline.flow + 1 if baseline.flow < 100 else 99
            print(f"Testing Flow: {baseline.flow} -> {target}", flush=True)
            write_attempted = True
            client.write_flow(baseline, target)
            observed = client.wait_for_flow(target, baseline.device_id)
            verify_unchanged(baseline, observed)
            time.sleep(hold)
            observed = confirm_device(host, baseline.device_id, {"Flow": target}, MODEL)
            verify_unchanged(baseline, observed)
            print(f"Independent LAN read confirmed Flow={observed.flow}; other settings unchanged", flush=True)
    finally:
        if write_attempted and baseline is not None:
            print(f"Restoring Flow={baseline.flow} using a fresh connection", flush=True)
            try:
                with connect(host) as client:
                    current = client.read_status()
                    if current.device_id != baseline.device_id:
                        raise ProbeError("Device ID changed; refusing restoration to another pump")
                    client.write_flow(current, baseline.flow)
                    client.wait_for_flow(baseline.flow, baseline.device_id)
                restored = confirm_device(host, baseline.device_id, {"Flow": baseline.flow}, MODEL)
                verify_unchanged(baseline, restored)
                print(f"Independent LAN read confirmed restored Flow={restored.flow}", flush=True)
            except (OSError, ProbeError) as error:
                raise RestorationError(
                    f"Restoration could not be verified on {host}. "
                    f"Check the pump/app immediately and set Flow={baseline.flow}: {error}"
                ) from error
    print("LOCAL WRITE TEST PASSED (change and restoration verified)", flush=True)


def verify_schedules(before: Status, after: Status) -> None:
    if before.device_id != after.device_id:
        raise ProbeError("Device ID changed")
    if before.raw[8:392] != after.raw[8:392]:
        raise ProbeError("Native schedule data changed; check the pump/app")
    if before.raw[400] != after.raw[400]:
        raise ProbeError(f"Fault status changed from {before.raw[400]} to {after.raw[400]}")


def command_cases(status: Status) -> list[dict[str, protocol.ControlValue]]:
    current = protocol.control_values(status, MODEL)
    specs = {attr["name"]: attr for attr in MODEL["attrs"]}
    cases = []
    for name in (
        "Flow", "Frequency", "FeedTime", "PulseTide", "Mode",
        "TimerON", "FeedSwitch", "SwitchON", "Linkage",
    ):
        value = current[name]
        attr = specs[name]
        if attr["data_type"] == "enum":
            cases.extend({name: option} for option in attr["enum"] if option != value)
        elif isinstance(value, bool):
            cases.append({name: not value})
        elif isinstance(value, int):
            limits = attr["uint_spec"]
            target = value + 1 if value < limits["max"] else value - 1
            if not limits["min"] <= value <= limits["max"] or target < limits["min"]:
                raise ProbeError(f"Cannot safely choose a neighboring value for {name}")
            cases.append({name: target})
    return cases


def run_attribute_test(host: str, changes: dict[str, protocol.ControlValue], hold: float) -> None:
    baseline = None
    write_attempted = False
    try:
        with connect(host) as client:
            baseline = client.read_status()
            original = protocol.control_values(baseline, MODEL)
            print(f"TEST {json.dumps(changes, ensure_ascii=False)}", flush=True)
            write_attempted = True
            client.write_attributes(baseline, changes, MODEL)
            observed = client.wait_for_attributes(changes, baseline.device_id, MODEL)
            verify_schedules(baseline, observed)
            time.sleep(hold)
            observed = confirm_device(host, baseline.device_id, changes, MODEL)
            verify_schedules(baseline, observed)
            current = protocol.control_values(observed, MODEL)
            side_effects = {
                name: current[name] for name, value in original.items()
                if name not in changes and current[name] != value
            }
            if side_effects:
                print(f"Device also updated: {json.dumps(side_effects, ensure_ascii=False)}", flush=True)
            print("Independent LAN read confirmed requested values; schedules/faults unchanged", flush=True)
    finally:
        if write_attempted and baseline is not None:
            original = protocol.control_values(baseline, MODEL)
            try:
                with connect(host) as client:
                    current = client.read_status()
                    if current.device_id != baseline.device_id:
                        raise ProbeError("Device ID changed; refusing restoration to another pump")
                    current_values = protocol.control_values(current, MODEL)
                    restore = {
                        name: value for name, value in original.items()
                        if name in changes or current_values[name] != value
                    }
                    client.write_attributes(current, restore, MODEL)
                    client.wait_for_attributes(original, baseline.device_id, MODEL)
                restored = confirm_device(host, baseline.device_id, original, MODEL)
                verify_schedules(baseline, restored)
                print("RESTORED: all nine controls verified on a fresh connection", flush=True)
            except (OSError, ProbeError) as error:
                raise RestorationError(
                    f"Restoration failed on {host}. Check the app immediately. "
                    f"Original settings: {json.dumps(original, ensure_ascii=False)}. {error}"
                ) from error
    print("PASS", flush=True)


def run_all_tests(host: str, hold: float) -> None:
    with connect(host) as client:
        original = client.read_status()
    original_values = protocol.control_values(original, MODEL)
    try:
        if original_values["TimerON"]:
            protocol.control_device(host, original.device_id, {"TimerON": False}, MODEL)
            print("Native timer temporarily disabled to prevent manual settings being overridden", flush=True)
        with connect(host) as client:
            baseline = client.read_status()
        cases = command_cases(baseline)
        for changes in cases:
            run_attribute_test(host, changes, hold)
    finally:
        try:
            final = protocol.control_device(host, original.device_id, original_values, MODEL)
            verify_schedules(original, final)
            print("FINAL RESTORED: original controls, including native timer, independently verified", flush=True)
        except (OSError, ProbeError) as error:
            raise RestorationError(
                f"Final restoration failed. Original settings: "
                f"{json.dumps(original_values, ensure_ascii=False)}. {error}"
            ) from error
    print(f"ALL NINE CONTROLS PASSED ({len(cases)} changes plus restoration after each)", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", type=IPv4Address, help="MCP150 LAN IPv4 address")
    tests = parser.add_mutually_exclusive_group()
    tests.add_argument("--test-flow", action="store_true", help="Reversible one-point Flow test")
    tests.add_argument(
        "--test-all", action="store_true",
        help="Test all nine HA controls, including power, feeding/timer and every enum option",
    )
    parser.add_argument(
        "--hold", type=float, default=2.0, metavar="SECONDS",
        help="Hold each temporary value (0 < seconds <= 60; default: 2)",
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.hold) or not 0 < args.hold <= 60:
        parser.error("--hold must be finite, greater than zero, and at most 60")
    host = str(args.host)
    try:
        if args.test_all:
            run_all_tests(host, args.hold)
        elif args.test_flow:
            run_flow_test(host, args.hold)
        else:
            with connect(host) as client:
                status = client.read_status()
                print(json.dumps({
                    "product_key": PRODUCT_KEY,
                    "wifi_firmware": client.wifi_firmware,
                    "device_id": status.device_id,
                    "state": status.summary(),
                }, indent=2))
    except (OSError, ProbeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; any attempted test has run its restoration handler", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
