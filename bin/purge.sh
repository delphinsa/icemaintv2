#!/usr/bin/env bash
# Purge métier de lignes selon ICEMAINT_WHERE (simulation tant que ICEMAINT_DRY_RUN=true).
# Usage ($U ou manuel) : bin/purge.sh [fichier.env] [-- options icemaint]
# Paramètres par défaut : conf/purge.env ; codes retour : voir bin/_run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" purge "$@"
