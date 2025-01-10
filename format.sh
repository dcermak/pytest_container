#!/bin/bash

set -o pipefail

if [ "$1" = "--check" ]; then
    ruff format --check --diff
    format_ret=$?

    ruff check --diff
    exit $([ $? -eq 0 ] && [ $format_ret -eq 0 ])
else
    ruff format
    ruff check --fix
fi
