#!/usr/bin/env bash
# Lanceur non interactif : td-load (voir conf/td-load.env). Usage : bin/td-load.sh [fichier.env] [-- options]
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" td-load "$@"
