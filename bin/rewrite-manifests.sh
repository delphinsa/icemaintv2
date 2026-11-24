#!/usr/bin/env bash
# Regroupement des manifests (rewrite_manifests).
# Usage ($U ou manuel) : bin/rewrite-manifests.sh [fichier.env] [-- options icemaint]
# Paramètres par défaut : conf/rewrite-manifests.env ; codes retour : voir bin/_run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/_run.sh" rewrite-manifests "$@"
