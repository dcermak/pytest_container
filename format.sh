#!/bin/bash

if [ "$1" = "--check" ]; then
    set -e
    args="--check"
fi

black . ${args}
for f in $(fd '.*py$'); do
    reorder-python-imports $f
done
