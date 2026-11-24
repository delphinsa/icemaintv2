# shellcheck shell=bash
# Fonctions communes aux lanceurs (fichier sourcé, ne pas exécuter directement).

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KIT_VARS=()   # variables définies dans les fichiers conf chargés : seules celles-ci vont au conteneur

# Charge un fichier VARIABLE=valeur ; tolère les fins de ligne Windows.
load_env() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "ERREUR : fichier de configuration introuvable : $file" >&2
    exit 2
  fi
  set -a
  # shellcheck disable=SC1090
  source <(tr -d '\r' < "$file")
  set +a
  local name
  while IFS= read -r name; do
    KIT_VARS+=("$name")
  done < <(tr -d '\r' < "$file" | sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/p')
}

# Charge conf/common.env puis conf/secrets.env (obligatoires).
load_common() {
  load_env "$KIT_DIR/conf/common.env"
  load_env "$KIT_DIR/conf/secrets.env"
  : "${ICEMAINT_IMAGE:?ICEMAINT_IMAGE non défini dans conf/common.env}"
}

# Construit DOCKER_ARGS : ressources, réseau, truststore, variables transmises.
# Les valeurs passent par l'environnement (-e NOM), jamais sur la ligne de commande.
# Arguments : noms de variables supplémentaires à transmettre.
# shellcheck disable=SC2120
build_docker_args() {
  DOCKER_ARGS=(--rm --init
    --network "${ICEMAINT_DOCKER_NETWORK:-host}"
    --cpus "${ICEMAINT_DOCKER_CPUS:-2}"
    --memory "${ICEMAINT_DOCKER_MEMORY:-4g}")
  if [[ -n "${ICEMAINT_TLS_DIR:-}" ]]; then
    DOCKER_ARGS+=(-v "${ICEMAINT_TLS_DIR}:/opt/icemaint/tls:ro")
  fi
  # Scripts SQL Teradata : dossier monté en lecture seule (par défaut conf/sql, s'il existe)
  local sql_dir="${ICEMAINT_SQL_DIR:-$KIT_DIR/conf/sql}"
  if [[ -d "$sql_dir" ]]; then
    DOCKER_ARGS+=(-v "${sql_dir}:/opt/icemaint/sql:ro")
  fi
  local name
  while IFS= read -r name; do
    DOCKER_ARGS+=(-e "$name")
  done < <(printf '%s\n' ${KIT_VARS[@]+"${KIT_VARS[@]}"} "$@" | sort -u \
             | grep -E '^[A-Za-z_]' | grep -vE '^ICEMAINT_(IMAGE|DOCKER_.*|TLS_DIR|SQL_DIR)$')
}
