#!/bin/bash
set -e

echo "Setting up Danish Beancount System with uv..."

# 1. Initialize project if pyproject.toml does not exist
if [ ! -f "pyproject.toml" ]; then
    echo "Initializing new uv project..."
    uv init
    # Remove .python-version to prevent mise/version managers from shouting
    rm -f .python-version
fi

# 2. Add dependencies
echo "Installing dependencies..."
uv add beancount fava beangulp jinja2 weasyprint

echo "========================================"
echo "Installation complete!"
echo "To run Fava, execute:"
echo "uv run fava regnskab.beancount"
echo "========================================"
