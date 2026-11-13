"""Read-only snapshot check of a running dashboard; not a soak/accuracy test."""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def check_state(state, node_ids, *, require_config=False, require_audio=False,
                require_sensors=False):
    errors, notes = [], []
    nodes = {n["id"]: n for n in state.get("nodes", [])}
    for node_id in node_ids:
        node = nodes.get(node_id)
        if node is None:
            errors.append(f"Node {node_id}: not seen")
            continue
        prefix = f"Node {node_id}"
        if node.get("status") != "online":
            errors.append(f"{prefix}: {node.get('status', 'unknown')}")
        if node.get("simulated") is not False:
            errors.append(f"{prefix}: not identified as a real LAN node")
        telemetry = node.get("telemetry") or {}
        if not telemetry:
            errors.append(f"{prefix}: no telemetry")
        if require_config:
            config = node.get("config") or {}
            if (config.get("state") != "applied" or not config.get("version") or
                    telemetry.get("config_version") != config.get("version")):
                errors.append(f"{prefix}: requested CONFIG not confirmed in telemetry")
        if require_audio and telemetry.get("audio") is None:
            errors.append(f"{prefix}: no audio window")
        if require_sensors:
            missing = [k for k in ("temperature_c", "humidity_pct", "co2_ppm", "pir_pct")
                       if telemetry.get(k) is None]
            if missing:
                errors.append(f"{prefix}: missing valid sensor values: {', '.join(missing)}")
        notes.append(f"{prefix}: {node.get('ip')} status={node.get('status')} "
                     f"RSSI={telemetry.get('rssi_dbm')} dBm "
                     f"received={node.get('received')} lost={node.get('lost')} "
                     f"reboots={node.get('reboots')} (session totals)")
    return errors, notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8050")
    parser.add_argument("--nodes", type=int, nargs="+", default=[1], choices=range(1, 9))
    parser.add_argument("--require-config", action="store_true")
    parser.add_argument("--require-audio", action="store_true")
    parser.add_argument("--require-sensors", action="store_true")
    parser.add_argument("--save", type=Path, help="save this timestamped snapshot as JSON")
    args = parser.parse_args(argv)
    try:
        with urllib.request.urlopen(args.url.rstrip('/') + '/api/state', timeout=5) as response:
            state = json.load(response)
    except (OSError, urllib.error.URLError, ValueError) as error:
        print(f"Cannot read dashboard: {error}. Start mosaic.dashboard first.", file=sys.stderr)
        return 2
    errors, notes = check_state(state, args.nodes, require_config=args.require_config,
                               require_audio=args.require_audio, require_sensors=args.require_sensors)
    for note in notes:
        print(note)
    for error in errors:
        print("FAIL: " + error)
    print("SNAPSHOT CHECK: " + ("FAIL" if errors else "PASS"))
    print("This does not establish soak loss, reset-free operation, audio timing or accuracy.")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        with args.save.open("x") as output:
            json.dump({"captured_utc": datetime.now(timezone.utc).isoformat(),
                       "errors": errors, "notes": notes, "state": state}, output, indent=2)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
