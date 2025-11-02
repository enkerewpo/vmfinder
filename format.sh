#!/bin/bash
# format the code under the vmfinder package

# Try to find ruff in common locations or via command
RUFF_CMD=""
if command -v ruff > /dev/null 2>&1; then
    RUFF_CMD="ruff"
elif [ -f "$HOME/miniconda3/bin/ruff" ]; then
    RUFF_CMD="$HOME/miniconda3/bin/ruff"
elif [ -f "$HOME/anaconda3/bin/ruff" ]; then
    RUFF_CMD="$HOME/anaconda3/bin/ruff"
elif python -m ruff --version > /dev/null 2>&1; then
    RUFF_CMD="python -m ruff"
else
    echo "ruff could not be found, please install it with 'pip install ruff'"
    exit 1
fi


if [ -d "vmfinder" ]; then
    echo "Formatting code with ruff..."
    $RUFF_CMD format vmfinder
    echo "Code formatting complete!"
else
    echo "vmfinder directory not found"
    exit 1
fi