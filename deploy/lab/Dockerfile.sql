FROM node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS node
FROM postgres:18.6-bookworm@sha256:f1ea2a1a4fb7b68d4836be1fdcb8a6466a89b072158bf9d97663600538c294c5
# Cliente pg_dump/psql da MESMA major do servidor, apenas no laboratório.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
WORKDIR /app
COPY backend/package.json backend/package-lock.json ./
RUN node /usr/local/lib/node_modules/npm/bin/npm-cli.js ci --omit=dev
COPY backend/src ./src
COPY backend/tests ./tests
COPY supabase/schema.sql /supabase/schema.sql
COPY deploy/schema-inventario.sql /inventario.sql
COPY deploy/lab/sql-compose.sh /lab/sql-compose.sh
USER 10002:10000
ENTRYPOINT []
CMD ["sh", "/lab/sql-compose.sh"]
