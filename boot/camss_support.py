"""Validate the minimal change from the working sensor test to CAMSS."""
from __future__ import annotations

import re
import struct

from probe_support import (
    CAMSS, CCI, SENSOR, KERNEL, cells, fdt_nodes, is_temporary_chosen_property,
    make_menu as make_probe_menu,
)

ENTRY_ID = "ventuno-imx219-camss"
SENSOR_EP = SENSOR + "/port/endpoint"
RECEIVER_EP = CAMSS + "/ports/port@0/endpoint"


def symbol(nodes: dict, name: str) -> tuple[str, int]:
    path = nodes["/__symbols__"][name].rstrip(b"\0").decode()
    return path, cells(nodes[path]["phandle"])[0]


def check_probe_base(nodes: dict, vendor_paths: set[str]) -> None:
    if b"arduino,monza" not in nodes["/"]["compatible"].split(b"\0"):
        raise ValueError("Not a Ventuno Q/Monza")
    if nodes[CAMSS].get("status") != b"disabled\0":
        raise ValueError("Expected the sensor test with CAMSS disabled")
    if nodes[CAMSS]["compatible"] != b"qcom,qcs8300-camss\0":
        raise ValueError("Unexpected CAMSS controller")
    if RECEIVER_EP in nodes or "remote-endpoint" in nodes[SENSOR_EP]:
        raise ValueError("The receiver is already connected; review the existing test first")
    for path in vendor_paths:
        if nodes[path].get("status") != b"disabled\0":
            raise ValueError(f"Vendor camera node is still active: {path}")
    _, camcc = symbol(nodes, "camcc")
    _, tlmm = symbol(nodes, "tlmm")
    cci, sensor, ep = nodes[CCI], nodes[SENSOR], nodes[SENSOR_EP]
    handles = {cells(n["phandle"])[0]: n for n in nodes.values() if "phandle" in n}
    checks = {
        "CCI0-address": cells(cci["reg"]) == (0, 0xAC13000, 0, 0x1000),
        "CCI0-clocks": cells(cci["clocks"]) == (camcc, 13, camcc, 4),
        "sensor": sensor["compatible"] == b"sony,imx219\0" and cells(sensor["reg"]) == (0x10,),
        "reset": cells(sensor["reset-gpios"]) == (tlmm, 64, 0),
        "sensor-clock": cells(handles[cells(sensor["clocks"])[0]]["clock-frequency"]) == (24000000,),
        "sensor-lanes": cells(ep["data-lanes"]) == (1, 2),
        "link-frequency": struct.unpack(">Q", ep["link-frequencies"]) == (456000000,),
        "endpoint-symbol": symbol(nodes, "imx219_camera0_ep")[0] == SENSOR_EP,
    }
    for name, ok in checks.items():
        if not ok:
            raise ValueError(f"The working sensor test differs: {name}")


def validate_camss_delta(before_blob: bytes, after_blob: bytes,
                         vendor_paths: set[str], *, sanitized: bool = False) -> dict:
    before, after = fdt_nodes(before_blob), fdt_nodes(after_blob)
    check_probe_base(before, vendor_paths)
    if set(before) - set(after):
        raise ValueError("Existing nodes were removed")
    if set(after) - set(before) != {RECEIVER_EP}:
        raise ValueError("Expected exactly one new CAMSS endpoint")
    _, camcc = symbol(after, "camcc")
    _, phy = symbol(after, "vreg_l4a")
    _, pll = symbol(after, "vreg_l5a")
    sensor_handle = cells(after[SENSOR_EP]["phandle"])[0]
    receiver_handle = cells(after[RECEIVER_EP]["phandle"])[0]
    handles = [cells(n["phandle"])[0] for n in after.values() if "phandle" in n]
    if not receiver_handle or len(handles) != len(set(handles)):
        raise ValueError("Invalid or duplicate phandle in the camera connection")
    pack = lambda *n: struct.pack(">" + "I" * len(n), *n)
    expected = {
        (CCI, "assigned-clocks"): pack(camcc, 4),
        (CCI, "assigned-clock-rates"): pack(37500000),
        (CAMSS, "status"): b"okay\0",
        (CAMSS, "vdda-phy-supply"): pack(phy),
        (CAMSS, "vdda-pll-supply"): pack(pll),
        (SENSOR_EP, "remote-endpoint"): pack(receiver_handle),
    }
    for path, props in before.items():
        for prop in set(props) | set(after[path]):
            if props.get(prop) == after[path].get(prop):
                continue
            key = (path, prop)
            allowed = key in expected and after[path].get(prop) == expected[key]
            allowed |= (
                path == "/__symbols__" and prop == "imx219_camss_camera0_ep"
                and prop not in props
                and after[path].get(prop) == (RECEIVER_EP + "\0").encode()
            )
            allowed |= (
                sanitized and path == "/chosen"
                and is_temporary_chosen_property(prop) and prop not in after[path]
            )
            if not allowed:
                raise ValueError(f"Unexpected change: {path}:{prop}")
    for (path, prop), value in expected.items():
        if after[path].get(prop) != value:
            raise ValueError(f"Required change is missing: {path}:{prop}")
    receiver = after[RECEIVER_EP]
    if receiver != {
        "phandle": pack(receiver_handle), "data-lanes": pack(0, 1),
        "remote-endpoint": pack(sensor_handle),
    }:
        raise ValueError("Unexpected CAMSS endpoint properties")
    if sanitized and any(is_temporary_chosen_property(p) for p in after.get("/chosen", {})):
        raise ValueError("Temporary data from the previous boot is still present")
    return {
        "camss_enabled": True, "camera0_link_bidirectional": True,
        "sensor_lanes": [1, 2], "receiver_lanes": [0, 1],
        "cci_assigned_rate_hz": 37500000,
        "phy_supply": "vreg_l4a", "pll_supply": "vreg_l5a",
        "existing_camss_resources_preserved": True,
        "non_camera_properties_preserved": True,
        "vendor_nodes_still_disabled": len(vendor_paths),
    }


def make_menu(grub: str, *, loader_module: str) -> str:
    menu = make_probe_menu(grub, loader_module=loader_module)
    replacements = {
        "Ventuno Q IMX219 Camera0 sensor test": "Ventuno Q IMX219 Camera0 CAMSS test",
        "--id 'ventuno-imx219-probe'": f"--id '{ENTRY_ID}'",
        f"/ventuno-imx219-probe/probe-{KERNEL}.dtb": f"/ventuno-imx219-camss/camss-{KERNEL}.dtb",
        "ventuno_imx219_probe=1": "ventuno_imx219_camss=1",
    }
    for old, new in replacements.items():
        if menu.count(old) != 1:
            raise ValueError(f"Unexpected menu structure: {old}")
        menu = menu.replace(old, new)
    return menu


def probe_menu(grub: str) -> str:
    """Preserve the successful sensor-test entry during GRUB regeneration."""
    lines = grub.splitlines()
    starts = [i for i, line in enumerate(lines)
              if re.match(r"^menuentry\s", line) and "--id 'ventuno-imx219-probe'" in line]
    if len(starts) != 1:
        raise ValueError("Expected exactly one existing sensor test entry")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == "}"), None)
    if end is None:
        raise ValueError("Incomplete sensor test entry")
    return "\n".join(lines[start:end + 1])
