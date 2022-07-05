#!/bin/bash

if [ "$1" = "--check" ]; then
    set -e
    args="--check"
fi

black . ${args}
for f in $(git ls-files|grep '.*py$'); do
    reorder-python-imports $f
done
