#!/usr/bin/env bash
# Lanceur non interactif : td-sql (voir conf/td-sql.env). Usage : bin/td-sql.sh [fichier.env] [-- options]
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" td-sql "$@"
