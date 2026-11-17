#!/bin/sh
set -eu
: "${STATE_HOST_DIR:?}" "${MEDIA_HOST_DIR:?}"
df -h "$STATE_HOST_DIR" "$MEDIA_HOST_DIR"
df -i "$STATE_HOST_DIR" "$MEDIA_HOST_DIR"
du -sh "$STATE_HOST_DIR" "$MEDIA_HOST_DIR"
# Não listar nomes de arquivos nem ler texto, URLs ou SQLite.
