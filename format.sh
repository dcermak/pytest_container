#!/bin/bash

if [ "$1" = "--check" ]; then
    set -e
    args="--check"
fi

black . pytest_container ${args}
for f in $(ls pytest_container/*py); do
    reorder-python-imports $f
done
