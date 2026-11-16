export type ResultadoFalhaPolling = { espera: number; compartilhar?: boolean } | null;

export class PortaoPolling {
  private ate = 0;

  bloquear(espera: number, agora = Date.now()) {
    this.ate = Math.max(this.ate, agora + Math.max(0, espera));
  }

  limpar() {
    this.ate = 0;
  }

  restante(agora = Date.now()) {
    return Math.max(0, this.ate - agora);
  }
}

export function atrasoExponencial(tentativa: number, intervalo: number, teto: number) {
  return Math.min(teto, intervalo * 2 ** Math.min(tentativa, 4));
}

type Opcoes<T> = {
  intervalo: number;
  timeout: number;
  executar: (signal: AbortSignal) => Promise<T>;
  antes?: () => void;
  sucesso: (resultado: T) => void;
  falha: (erro: unknown, tentativa: number) => ResultadoFalhaPolling | Promise<ResultadoFalhaPolling>;
  recuo: PortaoPolling;
  compartilhado: PortaoPolling;
  agora?: () => number;
  agendar?: (callback: () => void, espera: number) => number;
  cancelar?: (id: number) => void;
};

/**
 * Um ciclo por endpoint: nunca sobrepõe request/timer e descarta conclusões após
 * parar. O componente recria o ciclo em troca de filtro/sessão/visibilidade, mas
 * conserva os portões de recuo em refs para não burlar Retry-After no retorno.
 */
export class ControladorPolling<T> {
  private ativo = false;
  private timer: number | null = null;
  private timeout: number | null = null;
  private controlador: AbortController | null = null;
  private tentativa = 0;
  private geracao = 0;
  private readonly agora: () => number;
  private readonly agendar: (callback: () => void, espera: number) => number;
  private readonly cancelar: (id: number) => void;

  constructor(private readonly opcoes: Opcoes<T>) {
    this.agora = opcoes.agora ?? Date.now;
    this.agendar = opcoes.agendar ?? ((callback, espera) => window.setTimeout(callback, espera));
    this.cancelar = opcoes.cancelar ?? ((id) => window.clearTimeout(id));
  }

  iniciar() {
    if (this.ativo) return;
    this.ativo = true;
    this.rodarOuAguardar();
  }

  parar() {
    this.ativo = false;
    this.geracao += 1;
    if (this.timer !== null) {
      this.cancelar(this.timer);
      this.timer = null;
    }
    if (this.timeout !== null) {
      this.cancelar(this.timeout);
      this.timeout = null;
    }
    this.controlador?.abort();
    this.controlador = null;
  }

  private proximaEspera() {
    return Math.max(this.opcoes.intervalo, this.opcoes.recuo.restante(this.agora()),
      this.opcoes.compartilhado.restante(this.agora()));
  }

  private agendarProxima(espera = this.proximaEspera()) {
    if (!this.ativo) return;
    this.timer = this.agendar(() => {
      this.timer = null;
      this.rodarOuAguardar();
    }, Math.max(0, espera));
  }

  private rodarOuAguardar() {
    if (!this.ativo || this.controlador) return;
    if (this.opcoes.recuo.restante(this.agora()) || this.opcoes.compartilhado.restante(this.agora())) {
      this.agendarProxima();
      return;
    }
    void this.executar();
  }

  private async executar() {
    const minhaGeracao = this.geracao;
    const controlador = new AbortController();
    this.controlador = controlador;
    let expirou = false;
    const timeout = this.agendar(() => {
      expirou = true;
      controlador.abort();
    }, this.opcoes.timeout);
    this.timeout = timeout;
    this.opcoes.antes?.();
    try {
      const resultado = await this.opcoes.executar(controlador.signal);
      if (!this.ativo || minhaGeracao !== this.geracao) return;
      this.tentativa = 0;
      this.opcoes.recuo.limpar();
      this.opcoes.sucesso(resultado);
    } catch (erro) {
      if (!this.ativo || minhaGeracao !== this.geracao || (!expirou && controlador.signal.aborted)) return;
      const resultado = await this.opcoes.falha(erro, ++this.tentativa);
      if (!this.ativo || minhaGeracao !== this.geracao) return;
      if (resultado === null) {
        this.ativo = false;
        return;
      }
      this.opcoes.recuo.bloquear(resultado.espera, this.agora());
      if (resultado.compartilhar) this.opcoes.compartilhado.bloquear(resultado.espera, this.agora());
    } finally {
      this.cancelar(timeout);
      if (this.timeout === timeout) this.timeout = null;
      if (this.controlador === controlador) this.controlador = null;
      if (this.ativo && minhaGeracao === this.geracao) this.agendarProxima();
    }
  }
}
