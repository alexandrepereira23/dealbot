// Controle de ciclo de vida; não altera a elegibilidade/reserva de nenhuma mídia.
export function agendarLimpeza({ ativa, intervaloMin }, executar, log = console) {
  let emCurso = null;
  let encerrando = false;
  let boot;
  let intervalo;
  const disparar = () => {
    if (encerrando || emCurso) return;
    emCurso = Promise.resolve().then(executar)
      .catch(() => log.error("[limpeza] ciclo interrompido; pendências preservadas"))
      .finally(() => { emCurso = null; });
  };
  if (ativa) {
    boot = setTimeout(disparar, 10_000);
    intervalo = setInterval(disparar, intervaloMin * 60_000);
    log.log(`[limpeza] agendada: intervalo=${intervaloMin}min`);
  } else {
    log.log("[limpeza] suspensa por configuração");
  }
  return {
    async encerrar() {
      encerrando = true;
      clearTimeout(boot);
      clearInterval(intervalo);
      await emCurso;
    },
  };
}
