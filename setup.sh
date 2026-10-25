#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
ventuno_package=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$ventuno_package"
[[ $EUID != 0 ]] || { echo 'Start als gewone App Lab-gebruiker: bash setup.sh'; exit 1; }
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
raise SystemExit(0 if any(app.get('name')=='Ventuno IMX219 Objectdetectie' for app in apps) else 1)
PY
  then
    printf 'De app bestaat al; deze wordt niet overschreven.\n'
  else
    arduino-app-cli app import dist/ventuno-imx219-app.zip
  fi
  printf '\nGereed. Open Arduino App Lab en start Ventuno IMX219 Objectdetectie.\n'
elif [[ $# == 0 ]]; then
  [[ ! -e /opt/ventuno-imx219-v2 && ! -e /var/lib/ventuno-imx219-v2 ]] || {
    echo 'Er bestaat al een camera-installatie. Deze wordt niet overschreven; lees README.md.'; exit 1;
  }
  python3 scripts/package.py verify
  sudo bash scripts/install-dependencies.sh
  bash scripts/build.sh
  sudo python3 install.py prepare
  sudo python3 install.py install
  sudo python3 install.py test-boot
  printf '\nEenmalige cameraboot staat klaar. Voer zelf uit: sudo reboot\n'
  printf 'Voer daarna vanuit deze map uit: bash setup.sh --finish\n'
else
  echo 'Gebruik: bash setup.sh [--finish]'; exit 1
fi
