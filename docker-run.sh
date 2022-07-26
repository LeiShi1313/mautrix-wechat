#!/bin/bash

# Define functions.
function fixperms {
	chown -R ${UID:-0}:${GID:-0} /data

	# /opt/mautrix-wechat is read-only, so disable file logging if it's pointing there.
	if [[ "$(yq e '.logging.handlers.file.filename' /data/config.yaml)" == "./mautrix-wechat.log" ]]; then
		yq -I4 e -i 'del(.logging.root.handlers[] | select(. == "file"))' /data/config.yaml
		yq -I4 e -i 'del(.logging.handlers.file)' /data/config.yaml
	fi
}

cd /opt/mautrix-wechat

if [ ! -f /data/config.yaml ]; then
	cp example-config.yaml /data/config.yaml
	echo "Didn't find a config file."
	echo "Copied default config file to /data/config.yaml"
	echo "Modify that config file to your liking."
	echo "Start the container again after that to generate the registration file."
	fixperms
	exit
fi

if [ ! -f /data/registration.yaml ]; then
	python3 -m mautrix_wechat -g -c /data/config.yaml -r /data/registration.yaml || exit $?
	echo "Didn't find a registration file."
	echo "Generated one for you."
	echo "See https://docs.mau.fi/bridges/general/registering-appservices.html on how to use it."
	fixperms
	exit
fi

fixperms
exec su-exec ${UID:-0}:${GID:-0} python3 -m mautrix_wechat -c /data/config.yaml