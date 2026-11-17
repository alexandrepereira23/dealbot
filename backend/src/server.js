import { criarApp } from "./app.js";
import { env } from "./config/env.js";
import { executarLimpeza } from "./services/limpeza.service.js";
import { agendarLimpeza } from "./services/agendamento-limpeza.service.js";

const app = criarApp();

const server = app.listen(env.port, env.host, () => {
  console.log(`API do Dealbot rodando na porta ${env.port}`);
});

const limpeza = agendarLimpeza({ ativa: env.limpezaAtiva,
  intervaloMin: env.limpezaIntervaloMin }, executarLimpeza);

let encerrando = false;
async function encerrar(sinal) {
  if (encerrando) return;
  encerrando = true;
  console.log(`[server] recebido ${sinal}, encerrando...`);
  setTimeout(() => process.exit(1), 25_000).unref();
  await Promise.all([
    new Promise(resolve => server.close(resolve)),
    limpeza.encerrar(),
  ]);
  process.exit(0);
}

process.on("SIGTERM", () => encerrar("SIGTERM"));
process.on("SIGINT", () => encerrar("SIGINT"));
