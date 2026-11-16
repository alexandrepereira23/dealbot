// Controlador usado pela página real: relógio/rede falsos, sem Next/Supabase/env.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const arquivo = path.resolve(__dirname, "../lib/polling.ts");
const compilado = ts.transpileModule(fs.readFileSync(arquivo, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const modulo = { exports: {} };
vm.runInThisContext(`(function(require,module,exports){${compilado}\n})`, { filename: arquivo })(require, modulo, modulo.exports);
const { atrasoExponencial, ControladorPolling, PortaoPolling } = modulo.exports;

function relogio() {
  let agora = 0;
  let proximo = 1;
  const timers = new Map();
  const agendar = (callback, espera) => {
    const id = proximo++;
    timers.set(id, { quando: agora + espera, callback });
    return id;
  };
  const cancelar = (id) => timers.delete(id);
  const drenar = async () => {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
  };
  return {
    agora: () => agora,
    agendar,
    cancelar,
    async avancar(ms) {
      const fim = agora + ms;
      while (true) {
        const proximoTimer = [...timers.entries()]
          .filter(([, timer]) => timer.quando <= fim)
          .sort((a, b) => a[1].quando - b[1].quando)[0];
        if (!proximoTimer) break;
        const [id, timer] = proximoTimer;
        timers.delete(id);
        agora = timer.quando;
        timer.callback();
        await drenar();
      }
      agora = fim;
      await drenar();
    },
    async estabilizar() { await drenar(); },
  };
}

test("controlador não sobrepõe request, descarta resultado após parar e preserva cadência", async () => {
  const tempo = relogio();
  const recuo = new PortaoPolling();
  const compartilhado = new PortaoPolling();
  let chamadas = 0;
  let resolver;
  let abortou = false;
  const resultados = [];
  const controlador = new ControladorPolling({
    intervalo: 5000,
    timeout: 10000,
    recuo,
    compartilhado,
    agora: tempo.agora,
    agendar: tempo.agendar,
    cancelar: tempo.cancelar,
    executar: (signal) => new Promise((resolve) => {
      chamadas += 1;
      resolver = resolve;
      signal.addEventListener("abort", () => { abortou = true; });
    }),
    sucesso: (valor) => resultados.push(valor),
    falha: () => ({ espera: 5000 }),
  });

  controlador.iniciar();
  await tempo.estabilizar();
  assert.equal(chamadas, 1);
  await tempo.avancar(5000);
  assert.equal(chamadas, 1, "request lenta não deve abrir segundo poll");
  controlador.parar();
  assert.equal(abortou, true);
  resolver("resposta-antiga");
  await tempo.estabilizar();
  await tempo.avancar(10000);
  assert.deepEqual(resultados, [], "resposta pós-parada não muda snapshot");
});

test("429 compartilha Retry-After e retorno só reinicia após o portão", async () => {
  const tempo = relogio();
  const recuoLista = new PortaoPolling();
  const compartilhado = new PortaoPolling();
  let chamadas = 0;
  const controlador = new ControladorPolling({
    intervalo: 5000,
    timeout: 10000,
    recuo: recuoLista,
    compartilhado,
    agora: tempo.agora,
    agendar: tempo.agendar,
    cancelar: tempo.cancelar,
    executar: async () => {
      chamadas += 1;
      throw new Error("429");
    },
    sucesso: () => assert.fail("não deveria haver sucesso"),
    falha: (_erro, tentativa) => ({ espera: Math.max(atrasoExponencial(tentativa, 5000, 60000), 125000), compartilhar: true }),
  });

  controlador.iniciar();
  await tempo.estabilizar();
  assert.equal(chamadas, 1);
  assert.equal(compartilhado.restante(tempo.agora()), 125000);
  await tempo.avancar(124999);
  assert.equal(chamadas, 1, "não pode burlar Retry-After maior que teto normal");
  await tempo.avancar(1);
  assert.equal(chamadas, 2);
  controlador.parar();
});

test("sucesso limpa apenas recuo próprio e mantém portão compartilhado", () => {
  const recuo = new PortaoPolling();
  const compartilhado = new PortaoPolling();
  recuo.bloquear(1000, 0);
  compartilhado.bloquear(2000, 0);
  recuo.limpar();
  assert.equal(recuo.restante(0), 0);
  assert.equal(compartilhado.restante(0), 2000);
  assert.equal(atrasoExponencial(20, 5000, 60000), 60000);
});
