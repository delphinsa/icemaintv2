#!/usr/bin/env bash
# État d'une table (lecture seule) : petits fichiers, snapshots, historique.
# Usage ($U ou manuel) : bin/health.sh [fichier.env] [-- options icemaint]
# Paramètres par défaut : conf/health.env ; codes retour : voir bin/_run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" health "$@"
