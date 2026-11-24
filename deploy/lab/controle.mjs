// Comandos manuais exclusivamente para a fixture neste container.
const acao = process.argv[2];
if (process.argv.length !== 3 || !["oferta", "foto"].includes(acao)) {
  console.error("Uso: node /lab/controle.mjs oferta|foto");
  process.exitCode = 2;
} else {
  const resposta = await fetch("http://127.0.0.1:54329/__lab/controle", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-lab-controle": "sintetico" },
    body: JSON.stringify({ acao }),
    signal: AbortSignal.timeout(5000),
  });
  if (!resposta.ok) throw new Error(`controle_sintetico_http_${resposta.status}`);
  console.log(acao === "oferta" ? "Oferta sintética enfileirada." : "Fotos sintéticas pendentes liberadas.");
}
