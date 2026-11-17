// Alternativa a psql quando o laboratório só dispõe do servidor PostgreSQL.
// Cada instância mantém UMA conexão TCP real; nunca usa banco em memória.
import assert from "node:assert/strict";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";

export async function driverPostgres() {
  const modulo = process.env.DEALBOT_TEST_PG_MODULE;
  assert.ok(isAbsolute(modulo || ""), "Driver pg de laboratório deve ter caminho absoluto");
  const pg = await import(pathToFileURL(modulo));
  const { Client } = pg.default || pg;
  return class SessaoPostgres {
    constructor(endereco) {
      const url = new URL(endereco);
      assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(url.hostname));
      assert.match(url.pathname, /^\/dealbot_teste(?:_[a-z0-9_]+)?$/);
      assert.ok(!url.password && !url.search && !url.hash);
      assert.equal(process.env.DEALBOT_TEST_POSTGRES_DISPOSABLE, "SIM");
      this.cliente = new Client({ host: url.hostname.replace(/^\[|\]$/g, ""), port: Number(url.port || 5432),
        user: url.username || "postgres", database: url.pathname.slice(1), password: "", ssl: false,
        application_name: "dealbot_sql_lab", connectionTimeoutMillis: 5000,
        options: "-c statement_timeout=15000 -c lock_timeout=10000 -c timezone=UTC -c client_min_messages=warning" });
      this.pronta = this.cliente.connect();
    }
    async exec(sql) {
      await this.pronta;
      const resposta = await this.cliente.query(sql);
      return (Array.isArray(resposta) ? resposta : [resposta])
        .flatMap(r => r.rows).map(r => Object.values(r).map(v => v ?? "").join("|")).join("\n");
    }
    async rows(sql) {
      return JSON.parse(await this.exec(`select coalesce(json_agg(q),'[]'::json)::text from (${sql}) q;`));
    }
    async close() { await this.pronta; await this.cliente.end(); }
  };
}
