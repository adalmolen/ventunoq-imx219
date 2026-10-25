"""Read and check the sensor-probe DTB, and clone an existing GRUB entry.

No code from the supplied DTS or GRUB configuration is executed by this module.
"""
from __future__ import annotations

import re
import struct

KERNEL = "6.8.0-1080-qcom"
ENTRY_ID = "ventuno-imx219-probe"
ENTRY_TITLE = "Ventuno Q IMX219 Camera0 sensor test"
CCI = "/soc@0/cci@ac13000"
SENSOR = CCI + "/i2c-bus@0/sensor@10"
CAMSS = "/soc@0/isp@ac7a000"


def fdt_nodes(blob: bytes) -> dict[str, dict[str, bytes]]:
    """Parse properties, preserving their exact bytes for the change check."""
    if len(blob) < 40:
        raise ValueError("Missing DTB header")
    header = struct.unpack_from(">10I", blob)
    if header[0] != 0xD00DFEED or header[1] > len(blob):
        raise ValueError("Invalid DTB header")
    pos = header[2]
    strings = blob[header[3]:header[3] + header[8]]
    stack: list[str] = []
    nodes: dict[str, dict[str, bytes]] = {}
    while pos < header[1]:
        token = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if token == 1:
            end = blob.index(b"\0", pos)
            stack.append(blob[pos:end].decode())
            pos = (end + 4) & ~3
            nodes["/" + "/".join(stack[1:])] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, offset = struct.unpack_from(">II", blob, pos)
            pos += 8
            end = strings.index(b"\0", offset)
            key = strings[offset:end].decode()
            nodes["/" + "/".join(stack[1:])][key] = blob[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            if stack:
                raise ValueError("Incomplete DTB tree")
            return nodes
        else:
            raise ValueError(f"Unknown DTB token: {token}")
    raise ValueError("DTB end marker is missing")


def cells(data: bytes) -> tuple[int, ...]:
    return struct.unpack(">" + "I" * (len(data) // 4), data)


def is_temporary_chosen_property(prop: str) -> bool:
    return prop.startswith("linux,uefi-") or prop in {
        "kaslr-seed", "rng-seed", "linux,initrd-start", "linux,initrd-end",
        "bootargs",
    }


def validate_probe(before_blob: bytes, after_blob: bytes,
                   vendor_paths: set[str], *, sanitized: bool = False) -> dict:
    before, after = fdt_nodes(before_blob), fdt_nodes(after_blob)
    if b"arduino,monza" not in before["/"].get("compatible", b"").split(b"\0"):
        raise ValueError("This is not an Arduino Monza/Ventuno Q device tree")
    if CCI in before or SENSOR in before:
        raise ValueError("CCI0/IMX219 already exists; the original boot is required")
    for path, props in before.items():
        if path not in after:
            raise ValueError(f"Unexpectedly removed node: {path}")
        for prop in set(props) | set(after[path]):
            if props.get(prop) == after[path].get(prop):
                continue
            allowed = (
                path in vendor_paths and prop == "status"
                and after[path].get(prop) == b"disabled\0"
            ) or path == "/__symbols__"
            allowed |= (
                sanitized and path == "/chosen"
                and is_temporary_chosen_property(prop)
                and prop not in after[path]
            )
            if not allowed:
                raise ValueError(f"Unexpected change: {path}:{prop}")
    for path in vendor_paths:
        if after[path].get("status") != b"disabled\0":
            raise ValueError(f"Vendor camera node is still active: {path}")
    if after[CAMSS].get("status") != b"disabled\0":
        raise ValueError("CAMSS must remain disabled for the sensor test")
    cci, sensor = after[CCI], after[SENSOR]
    checks = {
        "CCI0-address": cells(cci["reg"]) == (0, 0xAC13000, 0, 0x1000),
        "CCI0-interrupt": cells(cci["interrupts"]) == (0, 460, 1),
        "sensor-address": cells(sensor["reg"]) == (0x10,),
        "sensor-driver": sensor["compatible"] == b"sony,imx219\0",
        "reset-pin": cells(sensor["reset-gpios"])[1:] == (64, 0),
    }
    handles = {cells(n["phandle"])[0]: (path, n)
               for path, n in after.items() if "phandle" in n}
    camcc = after["/__symbols__"]["camcc"].rstrip(b"\0").decode()
    camcc_handle = cells(after[camcc]["phandle"])[0]
    tlmm = after["/__symbols__"]["tlmm"].rstrip(b"\0").decode()
    expected_new_nodes = {
        "/clocks/imx219-camera0-clk", tlmm + "/imx219-camera0-reset-state",
        CCI, CCI + "/i2c-bus@0", SENSOR, SENSOR + "/port",
        SENSOR + "/port/endpoint",
    }
    if set(after) - set(before) != expected_new_nodes:
        raise ValueError("Unexpected nodes added to the test DTB")
    checks["CCI0-clocks"] = cells(cci["clocks"]) == (
        camcc_handle, 13, camcc_handle, 4,
    )
    checks["reset-controller"] = cells(sensor["reset-gpios"])[0] == cells(
        after[tlmm]["phandle"]
    )[0]
    _, clock = handles[cells(sensor["clocks"])[0]]
    checks["sensor-clock"] = cells(clock["clock-frequency"]) == (24000000,)
    endpoint = after[SENSOR + "/port/endpoint"]
    checks["data-lanes"] = cells(endpoint["data-lanes"]) == (1, 2)
    checks["link-frequency"] = struct.unpack(">Q", endpoint["link-frequencies"])[0] == 456000000
    checks["standalone-sensor-test"] = "remote-endpoint" not in endpoint
    for key, ok in checks.items():
        if not ok:
            raise ValueError(f"DTB verification failed: {key}")
    if sanitized and any(is_temporary_chosen_property(p)
                         for p in after.get("/chosen", {})):
        raise ValueError("Temporary data from the previous boot is still present")
    return {"checks": checks, "vendor_nodes_disabled": len(vendor_paths),
            "added_nodes": sorted(set(after) - set(before)),
            "non_camera_existing_properties_preserved": True,
            "camss_disabled": True}


def make_menu(grub: str, *, loader_module: str | None = None) -> str:
    """Copy the Ubuntu stanza, including its actual root search and boot args."""
    lines = grub.splitlines()
    starts = [i for i, line in enumerate(lines)
              if re.match(r"^menuentry\s+['\"]Ubuntu['\"]\s", line)]
    if len(starts) != 1:
        raise ValueError("Expected exactly one original Ubuntu menu entry")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == "}"), None)
    if end is None:
        raise ValueError("End of the Ubuntu menu entry not found")
    body = lines[start + 1:end]
    linux = [i for i, line in enumerate(body) if re.match(r"\s*linux\s", line)]
    initrd = [line for line in body if re.match(r"\s*initrd\s", line)]
    if len(linux) != 1 or len(initrd) != 1:
        raise ValueError("The Ubuntu entry must contain one linux line and one initrd line")
    index = linux[0]
    match = re.match(r"(\s*linux\s+)(\S+)(.*)", body[index])
    kernel_path = match[2]
    if kernel_path not in {f"/boot/vmlinuz-{KERNEL}", f"/vmlinuz-{KERNEL}"}:
        raise ValueError(f"Ubuntu selects a different kernel: {kernel_path}")
    if not initrd[0].split()[-1].endswith(f"initrd.img-{KERNEL}"):
        raise ValueError("The initrd does not match the expected kernel")
    if any(re.match(r"\s*devicetree\s", line) for line in body):
        raise ValueError("Ubuntu already has a devicetree command; manual review is required")
    args = match[3]
    blacklist = re.search(r"(?<!\S)module_blacklist=([^\s]+)", args)
    if blacklist:
        values = blacklist[1].split(",")
        if "camera_qcs8300" not in values:
            values.append("camera_qcs8300")
        args = args[:blacklist.start()] + "module_blacklist=" + ",".join(values) + args[blacklist.end():]
    else:
        args += " module_blacklist=camera_qcs8300"
    args += " ventuno_imx219_probe=1"
    body[index] = match[1] + kernel_path + args
    prefix = "/boot" if kernel_path.startswith("/boot/") else ""
    new_dtb = f"{prefix}/ventuno-imx219-probe/probe-{KERNEL}.dtb"
    insert = [f"\tdevicetree {new_dtb}"]
    if loader_module is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", loader_module):
            raise ValueError("Unexpected GRUB module name")
        insert.insert(0, f"\tinsmod {loader_module}")
    body[index + 1:index + 1] = insert
    # Selecting the test must not become a permanently saved default.
    body = [line for line in body if line.strip() != "savedefault"]
    return (f"menuentry '{ENTRY_TITLE}' --id '{ENTRY_ID}' {{\n"
            + "\n".join(body) + "\n}\n")
