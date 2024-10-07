#!/bin/sh

mkdir -p /var/volume
touch /var/volume/cleanup_confirmed

trap "echo '1' > /var/volume/cleanup_confirmed" SIGTERM

while true; do
    sleep 5
done
