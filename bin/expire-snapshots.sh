#!/usr/bin/env bash
# Expiration des anciens snapshots (simulation tant que ICEMAINT_DRY_RUN=true).
# Usage ($U ou manuel) : bin/expire-snapshots.sh [fichier.env] [-- options icemaint]
# Paramètres par défaut : conf/expire-snapshots.env ; codes retour : voir bin/_run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" expire-snapshots "$@"
