#!/bin/bash
sourcedir="$(dirname "$0")"
set -a
source "$sourcedir/.env"
set +a
$sourcedir/.venv/bin/python3 "$sourcedir/helloasso_discord_sync.py"