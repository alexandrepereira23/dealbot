import { criarApp } from "./app.js";
import { env } from "./config/env.js";

const app = criarApp();

app.listen(env.port, () => {
  console.log(`API do Dealbot rodando na porta ${env.port}`);
});
