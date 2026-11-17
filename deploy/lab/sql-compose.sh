#!/bin/sh
set -eu
# Este runner só existe na rede do serviço PostgreSQL descartável, por loopback.
export PGHOST=127.0.0.1 PGUSER=postgres PGDATABASE=postgres
export PGPASSFILE=/dev/null PGSSLMODE=disable
export DEALBOT_TEST_POSTGRES_DISPOSABLE=SIM
psql --version
for nome in dealbot_teste_etapa2 dealbot_teste_etapa3 dealbot_teste_limpo dealbot_teste_restore; do
    createdb "$nome"  # Falha se já existir: não apagar/reutilizar banco.
done
DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1/dealbot_teste_etapa2 node tests/sql-etapa2.local.mjs
DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1/dealbot_teste_etapa3 node tests/sql-etapa3.local.mjs
psql -X -v ON_ERROR_STOP=1 -d dealbot_teste_limpo -f tests/sql-etapa3.local.sql
psql -X -v ON_ERROR_STOP=1 -d dealbot_teste_limpo -f /supabase/schema.sql
psql -X -v ON_ERROR_STOP=1 -d dealbot_teste_limpo -f /supabase/schema.sql
psql -X -v ON_ERROR_STOP=1 -d dealbot_teste_limpo -f /inventario.sql
# Dump lógico real de uma base sintética com dados; Auth/Storage não são objetos.
pg_dump --format=custom --no-owner --no-privileges -d dealbot_teste_etapa3 -f /tmp/dealbot.dump
pg_restore --exit-on-error --no-owner --no-privileges -d dealbot_teste_restore /tmp/dealbot.dump
for tabela in produtos produto_aparicoes filtros canais oferta_eventos oferta_midias oferta_controle; do
    origem=$(psql -X -At -d dealbot_teste_etapa3 -c "select md5(coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t))::text,'')) from public.$tabela t")
    destino=$(psql -X -At -d dealbot_teste_restore -c "select md5(coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t))::text,'')) from public.$tabela t")
    test "$origem" = "$destino"
done
printf '%s\n' 'SQL laboratório: instalação/reaplicação e dump/restauração lógica verificados'
