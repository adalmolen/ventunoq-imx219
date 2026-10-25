#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
ventuno_package=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ventuno_package"
[[ $EUID != 0 ]] || { echo 'Bouw als gewone gebruiker, zonder sudo.'; exit 1; }
python3 scripts/package.py verify
python3 install.py check --build
mkdir -p .build/driver
cp driver/camss/* .build/driver/
make -C /lib/modules/6.8.0-1080-qcom/build M="$ventuno_package/.build/driver" \
  CONFIG_VIDEO_QCOM_CAMSS=m CC=gcc-13 -j2 modules
cc -O3 -std=c11 -shared -fPIC -pthread runtime/picture_native.c -o runtime/picture_native.so
python3 scripts/package.py record-build
python3 scripts/package.py app
printf '\nBouw geslaagd. Er is geen driver geladen en de boot is niet gewijzigd.\n'
