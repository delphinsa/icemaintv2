#!/usr/bin/env bash
# Suppression des fichiers orphelins (simulation tant que ICEMAINT_DRY_RUN=true).
# Usage ($U ou manuel) : bin/remove-orphans.sh [fichier.env] [-- options icemaint]
# Paramètres par défaut : conf/remove-orphans.env ; codes retour : voir bin/_run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" remove-orphans "$@"
