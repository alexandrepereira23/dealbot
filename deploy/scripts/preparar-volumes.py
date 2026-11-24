"""Inicializador de volumes Docker dedicados; altera só as raízes montadas."""
import argparse
import os
import stat


def preparar(caminho, uid, gid, modo, ajustar, montagens):
    if caminho not in montagens:
        raise SystemExit(f"{caminho}: esperado um volume dedicado")
    fd = os.open(caminho, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        atual = os.fstat(fd)
        if (atual.st_uid, atual.st_gid, stat.S_IMODE(atual.st_mode)) == (uid, gid, modo):
            return
        if os.listdir(fd) and not ajustar:
            raise SystemExit(f"{caminho}: volume não vazio com permissões divergentes; faça backup e revise os IDs antes de usar --ajustar-raizes")
        os.fchown(fd, uid, gid)
        os.fchmod(fd, modo)
        print(f"{caminho}: pronto ({uid}:{gid} {modo:04o}); conteúdo não alterado")
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-uid", type=int, required=True)
    parser.add_argument("--media-gid", type=int, required=True)
    parser.add_argument("--laboratorio", action="store_true")
    parser.add_argument("--ajustar-raizes", action="store_true")
    args = parser.parse_args()
    if not 0 < args.bot_uid < 2**32 - 1 or not 0 < args.media_gid < 2**32 - 1:
        parser.error("UID/GID devem ser não root e válidos no Linux")
    volumes = [
        ("/state", args.bot_uid, args.media_gid, 0o700),
        ("/media", args.bot_uid, args.media_gid, 0o2770),
        ("/backup", args.bot_uid, args.media_gid, 0o700),
        ("/caddy-data", 10004, 10004, 0o700),
    ]
    if args.laboratorio:
        volumes.append(("/sintetico", 10005, 10005, 0o700))
    # Detecta também bind mounts sobre o mesmo filesystem (ismount não detecta).
    with open("/proc/self/mountinfo", encoding="utf-8") as info:
        montagens = {linha.split()[4] for linha in info}
    for caminho, uid, gid, modo in volumes:
        preparar(caminho, uid, gid, modo, args.ajustar_raizes, montagens)


if __name__ == "__main__":
    main()
