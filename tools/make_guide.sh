#!/usr/bin/env bash
# Rebuild the printed recovery guide from the live page, so the PDF always
# matches what the agent actually says. Needs libreoffice, which is on the
# host but not in the container.
set -euo pipefail
WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
curl -sf -m 30 "http://127.0.0.1:8096/guide/pinebox" -o "$WORK/pinebox-recovery.html"
( cd "$WORK" && libreoffice --headless --convert-to pdf pinebox-recovery.html >/dev/null )
docker cp "$WORK/pinebox-recovery.pdf" spark-agent:/app/data/pinebox-recovery.pdf
echo "rebuilt: $(du -h "$WORK/pinebox-recovery.pdf" | cut -f1) -> /api/pinebox/guide.pdf"
