#!/bin/sh
# Run every suite with an interpreter that actually has the bot's packages.
#
#   tests/test.sh            all suites
#   tests/test.sh cashout    only suites whose name contains "cashout"
#
# Homebrew's python3 is first on PATH on this Mac and has none of them, which
# makes every suite fail with ModuleNotFoundError - a broken shell that looks
# like a broken bot. This tries .venv, then /usr/bin/python3, then python3, and
# only builds .venv from requirements.txt when none of them will do.
cd "$(dirname "$0")/.." || exit 1

has_deps() { "$1" -c 'import telebot, telethon, openpyxl' 2>/dev/null; }

for py in .venv/bin/python /usr/bin/python3 python3; do
    if command -v "$py" >/dev/null 2>&1 && has_deps "$py"; then
        exec "$py" tests/run.py "$@"
    fi
done

echo "No python with the bot's packages - building .venv from requirements.txt"
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
exec .venv/bin/python tests/run.py "$@"
