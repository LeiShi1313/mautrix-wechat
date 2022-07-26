#!/usr/bin/env bash
cd /opt/mautrix-wechat && pip3 install pdm && eval "$(/home/app/.local/bin/pdm --pep582)" && /home/app/.local/bin/pdm install && cd -