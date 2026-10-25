#!/usr/bin/env bash
set -euo pipefail
ventuno_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ventuno_root"
if [[ $(uname -s) == Darwin ]]; then
  cc -O3 -std=c11 -dynamiclib -pthread runtime/picture_native.c -o runtime/picture_native.so
else
  cc -O3 -std=c11 -shared -fPIC -pthread runtime/picture_native.c -o runtime/picture_native.so
fi
python3 -m unittest discover -s tests -v
if command -v node >/dev/null; then node --check app/assets/app.js; fi
python3 scripts/package.py verify
