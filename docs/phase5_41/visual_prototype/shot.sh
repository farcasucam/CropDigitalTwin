#!/bin/bash
# usage: shot.sh name "hash-params" [width] [height]
E="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
D="$(cd "$(dirname "$0")" && pwd)"
"$E" --headless=new --disable-gpu --hide-scrollbars --window-size=${3:-1400},${4:-820} --virtual-time-budget=4000 \
  --screenshot="$(cygpath -w "$D")/$1.png" "file:///$(cygpath -m "$D")/demo-${THEME:-light}.html#$2" >/dev/null 2>&1
ls -la "$D/$1.png" | awk '{print $5, $9}'
