#!/usr/bin/env bash
set -e

# Determine directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "Error: Not a git repository root."
    exit 1
fi

LINK="$HOOKS_DIR/pre-commit"
TARGET="$PROJECT_ROOT/hooks/pre-commit"

if [ ! -e "$LINK" ]; then
    echo "No pre-commit hook found to remove."
    exit 0
fi

if [ -L "$LINK" ]; then
    RESOLVED="$(readlink "$LINK")"
    if [ "$RESOLVED" != "$TARGET" ]; then
        echo "Warning: '$LINK' is a symlink to '$RESOLVED', not CLaRA."
        read -p "Remove anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 0
        fi
    fi
else
    echo "Warning: '$LINK' is not a symlink."
    read -p "Remove anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

rm "$LINK"
echo "Hook removed successfully."
