// Requer psql e banco LOCAL DESCARTÁVEL vazio chamado dealbot_teste (ou dealbot_teste_*).
// Ex.: DEALBOT_TEST_POSTGRES_URL=postgresql://localhost:5432/dealbot_teste npm run test:sql
// Não lê .env. Tudo fica em transações com rollback, inclusive DDL/fixtures sintéticas.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";

const endereco = process.env.DEALBOT_TEST_POSTGRES_URL;
// Alternativa sem servidor: módulo PGlite instalado em pasta temporária, não
// dependência de produção. Instância em memória, sem URL ou acesso a disco real.
const moduloLocal = process.env.DEALBOT_TEST_PGLITE_MODULE;
if ((!endereco && !moduloLocal) || (endereco && moduloLocal)) {
  throw new Error("Defina somente DEALBOT_TEST_POSTGRES_URL local ou DEALBOT_TEST_PGLITE_MODULE absoluto; migração NÃO validada.");
}
const url = endereco ? new URL(endereco) : null;
if (url && (!["postgres:", "postgresql:"].includes(url.protocol)
  || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  || !/^\/dealbot_teste(?:_[a-z0-9_]+)?$/.test(url.pathname)
  || url.search || url.hash)) {
  throw new Error("Teste SQL recusa host remoto, parâmetros e banco que não seja dealbot_teste[_sufixo].");
}
let db;
if (moduloLocal) {
  if (!isAbsolute(moduloLocal)) throw new Error("PGlite deve ser um caminho local absoluto, não URL remota.");
  const { PGlite } = await import(pathToFileURL(moduloLocal).href);
  db = new PGlite();
  console.log((await db.query("select version()")).rows[0].version);
}
const schema = readFileSync(new URL("../../supabase/schema.sql", import.meta.url), "utf8");
const bloco = schema.match(/-- ETAPA 2 FILTROS: início[\s\S]+?-- ETAPA 2 FILTROS: fim\.[^\n]*/)?.[0];
assert.ok(bloco, "Bloco SQL etapa 2 não encontrado");
const tabelaLegada = `create table public.filtros (
  id bigint generated always as identity primary key, nome text not null,
  palavras_chave text[] default '{}', palavras_bloqueio text[] default '{}',
  categoria text, preco_max numeric(10,2), ativo boolean default true,
  criado_em timestamptz default now()
);`;

async function executar(sql) {
  if (db) return db.exec(sql);
  const resultado = spawnSync("psql", ["-X", "-v", "ON_ERROR_STOP=1", "--dbname", endereco],
    { input: sql, encoding: "utf8" });
  if (resultado.error) throw new Error(`psql local indisponível: ${resultado.error.code}; migração NÃO validada.`);
  if (resultado.status !== 0) throw new Error(`Teste SQL falhou (saída ${resultado.status}):\n${resultado.stderr}`);
}

try {
await executar(`begin;
${tabelaLegada}
insert into public.filtros (nome,palavras_chave,palavras_bloqueio,categoria,preco_max,ativo,criado_em)
values ('Legado sintético',array['SSD'],array['usado'],'eletronicos',0,false,'2026-10-23T00:00:00Z');
${bloco}
${bloco}
do $verificar$
declare comando text;
begin
  if not exists (select 1 from public.filtros where id = 1 and nome = 'Legado sintético'
    and palavras_chave = array['SSD'] and palavras_bloqueio = array['usado']
    and categoria = 'eletronicos' and preco_max = 0 and ativo = false
    and criado_em = '2026-10-23T00:00:00Z'::timestamptz
    and tipo_regra = 'interesse' and modo_palavras = 'qualquer') then
      raise exception 'Dados legados alterados';
  end if;
  insert into public.filtros(nome) values ('Defaults novos');
  if not exists (select 1 from public.filtros where nome = 'Defaults novos'
    and tipo_regra = 'interesse' and modo_palavras = 'qualquer' and ativo = true) then
      raise exception 'Defaults incorretos';
  end if;
  insert into public.filtros(nome,tipo_regra,modo_palavras,palavras_bloqueio)
    values ('Global sintético','bloqueio_global','todas',array['usado']);
  foreach comando in array array[
    $q$update public.filtros set tipo_regra = 'errado' where id = 1$q$,
    $q$update public.filtros set modo_palavras = 'errado' where id = 1$q$,
    $q$update public.filtros set tipo_regra = null where id = 1$q$,
    $q$update public.filtros set modo_palavras = null where id = 1$q$,
    $q$update public.filtros set tipo_regra = 'bloqueio_global' where id = 1$q$,
    $q$update public.filtros set palavras_bloqueio = '{}' where nome = 'Global sintético'$q$,
    $q$update public.filtros set palavras_bloqueio = null where nome = 'Global sintético'$q$,
    $q$update public.filtros set palavras_chave = null where nome = 'Global sintético'$q$,
    $q$update public.filtros set palavras_chave = array['SSD'] where nome = 'Global sintético'$q$,
    $q$update public.filtros set categoria = 'casa' where nome = 'Global sintético'$q$,
    $q$update public.filtros set preco_max = 0 where nome = 'Global sintético'$q$
  ] loop
    begin
      execute comando;
      raise exception 'Constraint não rejeitou: %', comando;
    exception when check_violation or not_null_violation then
      null;
    end;
  end loop;
end
$verificar$;
rollback;`);

// Coluna parcialmente existente com dado inválido: nem a nova coluna pode sobreviver à falha.
await executar(`begin;
${tabelaLegada}
alter table public.filtros add column tipo_regra text;
insert into public.filtros(nome,tipo_regra,ativo) values ('Inválido sintético','errado',false);
do $preflight$
begin
  begin
    execute $migracao$${bloco}$migracao$;
    raise exception 'Preflight deveria ter falhado';
  exception when raise_exception then
    if sqlerrm not like 'Etapa 2: filtros incompatíveis%' then raise; end if;
  end;
  if exists (select 1 from information_schema.columns where table_schema = 'public'
    and table_name = 'filtros' and column_name = 'modo_palavras') then
    raise exception 'Bloco não foi atômico';
  end if;
  if not exists (select 1 from public.filtros where id = 1 and tipo_regra = 'errado' and ativo = false) then
    raise exception 'Preflight modificou dados inválidos sem autorização';
  end if;
end
$preflight$;
rollback;`);
console.log("SQL etapa 2: aplicação dupla, preservação, defaults, constraints e preflight aprovados em Postgres local.");
} finally {
  if (db) await db.close();
}
