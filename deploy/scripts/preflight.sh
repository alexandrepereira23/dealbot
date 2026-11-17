#!/bin/sh
# Somente inspeção local; não sobe serviços, não lê .env e não acessa rede remota.
set -eu
for nome in STATE_HOST_DIR MEDIA_HOST_DIR BACKUP_DIR; do
    eval 'valor=${'"$nome"':?Defina o caminho absoluto}'
    case "$valor" in /*) ;; *) echo "preflight: caminho não absoluto ($nome)" >&2; exit 1;; esac
    test -d "$valor" && test ! -L "$valor" || { echo "preflight: diretório ausente/link ($nome)" >&2; exit 1; }
done
test "$STATE_HOST_DIR" != "$MEDIA_HOST_DIR"
case "$MEDIA_HOST_DIR/" in "$STATE_HOST_DIR/"*) echo 'preflight: mídia dentro do estado' >&2; exit 1;; esac
case "$STATE_HOST_DIR/" in "$MEDIA_HOST_DIR/"*) echo 'preflight: estado dentro da mídia' >&2; exit 1;; esac
uname -sm
docker version --format '{{.Server.Version}}'
docker compose version
printf '%s\n' 'Filesystem/permissões (confirmar local ext4/xfs; rejeitar NFS/SMB):'
findmnt -T "$STATE_HOST_DIR" -o FSTYPE,OPTIONS
findmnt -T "$MEDIA_HOST_DIR" -o FSTYPE,OPTIONS
stat -c '%u:%g %a' "$STATE_HOST_DIR" "$MEDIA_HOST_DIR" "$BACKUP_DIR"
df -h "$STATE_HOST_DIR" "$MEDIA_HOST_DIR" "$BACKUP_DIR"
df -i "$STATE_HOST_DIR" "$MEDIA_HOST_DIR" "$BACKUP_DIR"
printf '%s\n' 'Containers em execução (confirmar também systemd, Railway e outros hosts):'
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
printf '%s\n' 'Pré-checagem local concluída; schema/Auth/ausência de escritores ainda devem ser confirmados.'
