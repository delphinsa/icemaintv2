#!/usr/bin/env bash
# Lanceur non interactif commun, appelé par bin/<commande>.sh.
#
#   bin/<commande>.sh [fichier.env] [-- options icemaint supplémentaires]
#
# Configuration chargée dans cet ordre (la dernière valeur l'emporte) :
#   conf/common.env < conf/secrets.env < conf/<commande>.env < fichier.env passé en argument
#
# Codes retour : 0 OK | 1 table(s) en échec | 2 paramètre ou configuration
#                125 conteneur non lancé (déjà en cours ? image absente ?) | 137 conteneur tué (mémoire)
set -euo pipefail
# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

CMD="${1:?usage : _run.sh <commande> [fichier.env] [-- options]}"
shift
JOB_ENV=""
if [[ $# -gt 0 && "$1" != "--" ]]; then
  JOB_ENV="$1"
  shift
fi
if [[ "${1:-}" == "--" ]]; then
  shift
fi

load_common
if [[ -f "$KIT_DIR/conf/$CMD.env" ]]; then
  load_env "$KIT_DIR/conf/$CMD.env"
fi
if [[ -n "$JOB_ENV" ]]; then
  load_env "$JOB_ENV"
fi
build_docker_args

# Nom de conteneur unique par commande et par cible (table, fichier SQL ou table cible Teradata) :
# deux exécutions simultanées sur la même cible sont refusées par Docker (code 125).
SHOWN="${ICEMAINT_TABLE:-${ICEMAINT_TD_TARGET:-${ICEMAINT_TD_FILE:-sans-cible}}}"
TARGET="$(printf '%s' "$SHOWN" | tr -c 'a-zA-Z0-9_.-' '_' | cut -c1-100)"
NAME="icemaint-${CMD}-${TARGET}"

echo "[$(date '+%F %T')] icemaint ${CMD} | cible=${SHOWN} | image=${ICEMAINT_IMAGE} | conteneur=${NAME}"
set +e
docker run "${DOCKER_ARGS[@]}" --name "$NAME" "$ICEMAINT_IMAGE" icemaint "$CMD" "$@"
rc=$?
set -e

case $rc in
  0)   msg="OK" ;;
  1)   msg="au moins une cible en échec (voir les lignes ERREUR et RESULTAT)" ;;
  2)   msg="paramètre ou configuration invalide" ;;
  125) msg="docker run refusé (voir le message docker ci-dessus : exécution déjà en cours, image absente, option refusée...)" ;;
  137) msg="conteneur tué : mémoire insuffisante (ICEMAINT_DOCKER_MEMORY) ou arrêt forcé" ;;
  *)   msg="erreur inattendue" ;;
esac
echo "[$(date '+%F %T')] icemaint ${CMD} terminé : code ${rc} (${msg})"
exit "$rc"
