#!/bin/bash
sourcedir="$(dirname "$0")"
set -a
source "$sourcedir/.envjdr"
set +a
$sourcedir/.venv/bin/python3 "$sourcedir/jds_discord_threads.py"