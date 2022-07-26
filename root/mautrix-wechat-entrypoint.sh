#!/usr/bin/env bash
sudo rm /tmp/.X0-lock

/inj-entrypoint.sh &
sleep 5
mautrix-wechat &
wait