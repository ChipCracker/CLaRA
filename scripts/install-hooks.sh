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

echo "Installing CLaRA pre-commit hook..."

# Symlink the hook from hooks/pre-commit to .git/hooks/pre-commit
# We use relative path for symlink if possible, or absolute.
# Absolute is safer across OS.
TARGET="$PROJECT_ROOT/hooks/pre-commit"
LINK="$HOOKS_DIR/pre-commit"

if [ -e "$LINK" ]; then
    echo "Warning: '$LINK' already exists."
    read -p "Overwrite? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    rm "$LINK"
fi

ln -s "$TARGET" "$LINK"
chmod +x "$TARGET"

echo "✅ Hook installed successfully."
