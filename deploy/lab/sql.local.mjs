// Ensaio PostgreSQL real sem instalar serviço no host; somente cluster NOVO local.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const base = process.env.DEALBOT_LAB_BASE;
const bin = process.env.DEALBOT_LAB_PG_BIN;
const modulo = process.env.DEALBOT_TEST_PG_MODULE;
assert.ok([base, bin, modulo].every(v => path.isAbsolute(v || "")));
const pg = await import(pathToFileURL(modulo));
const { Client } = pg.default || pg;
const raiz = await fs.mkdtemp(path.join(base, "dealbot-pg-"));
const dados = path.join(raiz, "cluster");
const porta = Number(process.env.DEALBOT_LAB_PG_PORT || 55439);
const exe = nome => path.join(bin, nome + (process.platform === "win32" ? ".exe" : ""));
const repo = path.resolve(import.meta.dirname, "../..");
function comando(executavel, args, env = process.env, cwd = repo) {
  const r = spawnSync(executavel, args, { env, cwd, stdio: "inherit", timeout: 180_000 });
  if (r.error) throw r.error;
  assert.equal(r.status, 0, "Comando do ensaio SQL falhou");
}
const conectar = async banco => {
  const c = new Client({ host: "127.0.0.1", port: porta, user: "postgres", database: banco,
    password: "", ssl: false, connectionTimeoutMillis: 5000 });
  await c.connect(); return c;
};
comando(exe("initdb"), ["-D", dados, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"]);
let iniciado = false;
try {
  comando(exe("pg_ctl"), ["-D", dados, "-l", path.join(raiz, "postgres.log"), "-o", `-h 127.0.0.1 -p ${porta}`, "-w", "start"]);
  iniciado = true;
  const admin = await conectar("postgres");
  try {
    for (const nome of ["dealbot_teste_etapa2", "dealbot_teste_etapa3", "dealbot_teste_limpo"]) {
      await admin.query(`create database ${nome}`);
    }
  } finally { await admin.end(); }
  for (const etapa of [2, 3]) {
    comando(process.execPath, [`tests/sql-etapa${etapa}.local.mjs`], {
      ...process.env, DEALBOT_TEST_POSTGRES_URL: `postgresql://postgres@127.0.0.1:${porta}/dealbot_teste_etapa${etapa}`,
      DEALBOT_TEST_POSTGRES_DISPOSABLE: "SIM", DEALBOT_TEST_SQL_ARTIFACTS: raiz,
    }, path.join(repo, "backend"));
  }
  const limpo = await conectar("dealbot_teste_limpo");
  try {
    const bootstrap = await fs.readFile(path.join(repo, "backend/tests/sql-etapa3.local.sql"), "utf8");
    const schema = await fs.readFile(path.join(repo, "supabase/schema.sql"), "utf8");
    await limpo.query(bootstrap);
    await limpo.query(schema);
    await limpo.query(schema);
    const inventario = await fs.readFile(path.join(repo, "deploy/schema-inventario.sql"), "utf8");
    await limpo.query(inventario);
    const grants = await limpo.query(`select count(*)::int n from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname ~ '^(_?oferta_|midia_)'
      and (has_function_privilege('anon',p.oid,'EXECUTE') or has_function_privilege('authenticated',p.oid,'EXECUTE'))`);
    assert.equal(grants.rows[0].n, 0);
    console.log("SQL etapa5: instalação limpa, reaplicação completa, inventário somente leitura e grants aprovados");
  } finally { await limpo.end(); }
} finally {
  if (iniciado) comando(exe("pg_ctl"), ["-D", dados, "-m", "fast", "-w", "stop"]);
  console.log(`SQL: artefatos sintéticos preservados em ${raiz}`);
}
