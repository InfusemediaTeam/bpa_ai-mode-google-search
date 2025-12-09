#!/bin/sh
set -e

: "${API_PORT:=4001}"
: "${NOVNC_PORT:=3000}"
: "${WATCHER_PORT:=3101}"
: "${DOMAIN:=eg.instagingserver.com}"

CERT_FULLCHAIN="${CERT_FULLCHAIN:-/etc/letsencrypt/live/${DOMAIN}/fullchain.pem}"
CERT_PRIVKEY="${CERT_PRIVKEY:-/etc/letsencrypt/live/${DOMAIN}/privkey.pem}"

export API_PORT NOVNC_PORT WATCHER_PORT DOMAIN CERT_FULLCHAIN CERT_PRIVKEY

# Render nginx config from template
envsubst '${DOMAIN} ${CERT_FULLCHAIN} ${CERT_PRIVKEY} ${API_PORT} ${NOVNC_PORT} ${WATCHER_PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
