#!/bin/sh
set -eu

PORT="${1:-8878}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
URL="http://127.0.0.1:${PORT}/viewer-bnw.html?garden_debug=1"

printf 'Serving accepted Garden at %s\n' "$URL"
(sleep 0.5; open -a "Google Chrome" "$URL") &
cd "$ROOT"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
