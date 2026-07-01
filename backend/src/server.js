import { criarApp } from "./app.js";
import { env } from "./config/env.js";
import { executarLimpeza } from "./services/limpeza.service.js";

const app = criarApp();

const server = app.listen(env.port, () => {
  console.log(`API do Dealbot rodando na porta ${env.port}`);
});

const bootTimer = setTimeout(executarLimpeza, 10_000);
const intervalTimer = setInterval(
  executarLimpeza,
  env.limpezaIntervaloMin * 60_000,
);
console.log(
  `[limpeza] agendada: retenção=${env.retencaoHoras}h intervalo=${env.limpezaIntervaloMin}min`,
);

function encerrar(sinal) {
  console.log(`[server] recebido ${sinal}, encerrando...`);
  clearTimeout(bootTimer);
  clearInterval(intervalTimer);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000).unref();
}

process.on("SIGTERM", () => encerrar("SIGTERM"));
process.on("SIGINT", () => encerrar("SIGINT"));
