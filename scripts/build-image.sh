#!/usr/bin/env bash
# Construit l'image icemaint. À lancer sur une machine ayant accès à Docker Hub, PyPI et
# Maven Central, ou à leurs miroirs internes :
#   PIP_INDEX_URL=https://<nexus>/repository/pypi/simple \
#   MAVEN_REPO=https://<nexus>/repository/maven-central \
#   ./scripts/build-image.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)"
IMAGE="${IMAGE:-icemaint:${VERSION}}"

args=()
if [[ -n "${PIP_INDEX_URL:-}" ]]; then args+=(--build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}"); fi
if [[ -n "${MAVEN_REPO:-}" ]]; then args+=(--build-arg "MAVEN_REPO=${MAVEN_REPO}"); fi

docker build ${args[@]+"${args[@]}"} -t "$IMAGE" .
docker run --rm "$IMAGE" icemaint --version
echo "Image construite : $IMAGE"
echo "Pour la transférer sur une VM sans registre : ./scripts/export-image.sh"
