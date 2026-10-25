#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
ventuno_package=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$ventuno_package"
[[ $EUID != 0 ]] || { echo 'Run as your regular App Lab user: bash setup.sh'; exit 1; }
if [[ ${1:-} == --finish && $# == 1 ]]; then
  sudo python3 install.py verify
  sudo python3 install.py make-default
  python3 scripts/package.py app
  arduino-app-cli app list --format json > .build/apps-before.json
  if python3 - <<'PY'
import json
from pathlib import Path
value=json.loads(Path('.build/apps-before.json').read_text())
apps=value.get('apps',[]) if isinstance(value,dict) else value
raise SystemExit(0 if any(app.get('name')=='Ventuno IMX219 Object Detection' for app in apps) else 1)
PY
  then
    printf 'The app already exists and will be preserved.\n'
  else
    arduino-app-cli app import dist/ventuno-imx219-app.zip
  fi
  printf '\nReady. Open Arduino App Lab and start Ventuno IMX219 Object Detection.\n'
elif [[ $# == 0 ]]; then
  [[ ! -e /opt/ventuno-imx219-v2 && ! -e /var/lib/ventuno-imx219-v2 ]] || {
    echo 'A camera installation already exists. It will be preserved; see README.md.'; exit 1;
  }
  python3 scripts/package.py verify
  sudo bash scripts/install-dependencies.sh
  bash scripts/build.sh
  sudo python3 install.py prepare
  sudo python3 install.py install
  sudo python3 install.py test-boot
  printf '\nThe one-time camera boot is ready. Reboot manually: sudo reboot\n'
  printf 'After rebooting, run from this directory: bash setup.sh --finish\n'
else
  echo 'Usage: bash setup.sh [--finish]'; exit 1
fi
