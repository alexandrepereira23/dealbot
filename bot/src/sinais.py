"""Sinais de encerramento que acordam o event loop, inclusive no fallback."""

import asyncio
import signal
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import FrameType


@contextmanager
def sinais_encerramento(parar: asyncio.Event) -> Iterator[None]:
    """Instala SIGINT/SIGTERM na thread principal e restaura ao sair.

    Deve envolver também a drenagem dos recursos, antes de fechar o loop.
    Só a ausência de suporte a add_signal_handler habilita o fallback.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("sinais_exigem_thread_principal")
    loop = asyncio.get_running_loop()

    def avisar(recebido: int, frame: FrameType | None) -> None:
        # Seguro mesmo no handler reentrante; também acorda o seletor do loop.
        loop.call_soon_threadsafe(parar.set)

    with ExitStack() as recursos:
        for sinal in (signal.SIGINT, signal.SIGTERM):
            # Registrar antes da instalação cobre também falhas parciais.
            recursos.callback(signal.signal, sinal, signal.getsignal(sinal))
            try:
                loop.add_signal_handler(sinal, parar.set)
            except NotImplementedError:
                signal.signal(sinal, avisar)
            else:
                recursos.callback(loop.remove_signal_handler, sinal)
        yield
