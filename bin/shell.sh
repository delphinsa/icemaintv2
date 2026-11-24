#!/usr/bin/env bash
# Shell interactif dans l'image, avec la configuration commune chargée.
#
#   bin/shell.sh [fichier.env]
#
# Puis, dans le conteneur :
#   icemaint --help
#   icemaint health -t poc_db.t_ventes
#   icemaint sql "SELECT * FROM poc_db.t_ventes.snapshots"
#
# Interface Spark (mesures) : http://<vm>:4040 pendant qu'une commande tourne
# (port modifiable avec ICEMAINT_SPARK_UI_PORT dans conf/common.env).
set -euo pipefail
# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

load_common
if [[ $# -gt 0 ]]; then
  load_env "$1"
fi
export ICEMAINT_SPARK_UI="${ICEMAINT_SPARK_UI:-true}"
build_docker_args ICEMAINT_SPARK_UI

exec docker run "${DOCKER_ARGS[@]}" -p "${ICEMAINT_SPARK_UI_PORT:-4040}:4040" -it --name "icemaint-shell-${USER:-user}-$$" "$ICEMAINT_IMAGE" bash
