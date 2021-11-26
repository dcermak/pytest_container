#!/bin/bash

set -euox pipefail

pytest --cov=pytest_container --cov-report term --cov-report html --cov-report xml -vv $@ tests/base/*py
