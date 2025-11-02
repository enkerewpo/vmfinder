#!/bin/bash
# pack python package and upload to pypi

# Check for required modules
MISSING_BUILD=0
MISSING_TWINE=0

if ! python -m build --version > /dev/null 2>&1; then
    MISSING_BUILD=1
fi

if ! python -m twine --version > /dev/null 2>&1; then
    MISSING_TWINE=1
fi

if [ "$MISSING_BUILD" -eq 1 ] || [ "$MISSING_TWINE" -eq 1 ]; then
    echo "Missing required dependencies:"
    if [ "$MISSING_BUILD" -eq 1 ]; then
        echo "  - build"
    fi
    if [ "$MISSING_TWINE" -eq 1 ]; then
        echo "  - twine"
    fi
    echo "Please install them with: pip install build twine"
    exit 1
fi

# Clean dist directory (create it if it doesn't exist)
if [ -d "dist" ]; then
    rm -rf dist/*
else
    mkdir -p dist
fi

python -m build
ls -la dist/
python -m twine check dist/*
python -m twine upload dist/*