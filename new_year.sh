#!/bin/bash
set -e

if [ -z "$1" ]; then
    echo "Usage: ./new_year.sh <YEAR>"
    exit 1
fi

YEAR=$1

if [ -d "$YEAR" ]; then
    echo "Folder $YEAR already exists."
    exit 1
fi

echo "Creating folder structure for year $YEAR..."
mkdir -p "$YEAR"
touch "$YEAR/expenses.beancount"
touch "$YEAR/mileage.beancount"
touch "$YEAR/invoices.beancount"

echo "Done. Remember to add 'include \"$YEAR/*.beancount\"' to your regnskab.beancount if it's not already using a wildcard include."
