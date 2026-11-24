#!/usr/bin/env bash
# Exporte l'image dans une archive à copier sur la VM, puis à charger avec docker load.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)"
IMAGE="${IMAGE:-icemaint:${VERSION}}"
mkdir -p out
FILE="out/icemaint-${VERSION}.tar.gz"

docker save "$IMAGE" | gzip > "$FILE"
(cd out && sha256sum "$(basename "$FILE")" > "$(basename "$FILE").sha256")
echo "Archive : $FILE ($(du -h "$FILE" | cut -f1))"
echo "Sur la VM : sha256sum -c $(basename "$FILE").sha256 && gunzip -c $(basename "$FILE") | docker load"
