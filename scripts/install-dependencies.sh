#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Usage: sudo bash scripts/install-dependencies.sh'; exit 1; }
python3 - <<'PY'
import os
from pathlib import Path
assert os.uname().machine == 'aarch64', 'Requires aarch64.'
assert os.uname().release == '6.8.0-1080-qcom', 'Only the tested kernel 6.8.0-1080-qcom is supported.'
c=Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
assert b'arduino,monza' in c and b'qcom,qcs8300' in c, 'Unknown Ventuno Q board variant.'
PY
apt-get update
apt-get install --no-install-recommends build-essential gcc-13 kmod device-tree-compiler \
  v4l-utils psmisc python3-numpy python3-pil python3-yaml linux-headers-6.8.0-1080-qcom
