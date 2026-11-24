#!/usr/bin/env bash
# Compaction bin-pack des petits fichiers (rewrite_data_files).
# Usage ($U ou manuel) : bin/compact.sh [fichier.env] [-- options icemaint]
# Paramètres par défaut : conf/compact.env ; codes retour : voir bin/_run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" compact "$@"
