"""Ponto de entrada do app empacotado (PyInstaller).

Dois cliques: abre o Montador no navegador; fecha sozinho quando a página é fechada.
Pelo Terminal:
  "Montador.app/Contents/MacOS/Montador" diagnostico [slides.pptx]
  "Montador/montador-terminal.exe" diagnostico [slides.pptx]
"""
from __future__ import annotations

import os
import sys
import time


def _log_em_arquivo():
    """Sem janela de terminal: o que o app escreveria vai para montador.log na pasta de dados do app."""
    from montador import appdata
    try:
        casa = appdata.home()
        casa.mkdir(parents=True, exist_ok=True)
        log = casa / "montador.log"
        if log.is_file() and log.stat().st_size > 2_000_000:
            log.replace(casa / "montador.log.1")
        fh = open(log, "a", encoding="utf-8", buffering=1, errors="replace")
        fh.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} abrindo (pid {os.getpid()})\n")
        sys.stdout = fh
        sys.stderr = fh
    except OSError:
        pass


def diagnostico(pptx: str | None = None) -> int:
    """Confere o que vai dentro do app e, com um .pptx, converte os slides de verdade."""
    import platform
    import subprocess
    import tempfile
    from pathlib import Path
    from montador import __version__, montagem, slides
    print(f"Montador {__version__} · {platform.system()} {platform.machine()} · Python {platform.python_version()}")
    ok = True
    so = slides.embutido() or slides.soffice()
    if so:
        r = subprocess.run([so, "--headless", "--version"], capture_output=True, text=True, timeout=300)
        print(f"{'libreoffice':<12} ok   {((r.stdout or r.stderr).strip().splitlines() or ['?'])[0]}  ({so})"
              + ("" if slides.embutido() else "  [não é o embutido]"))
        ok &= bool(slides.embutido()) or not getattr(sys, "frozen", False)
    else:
        print(f"{'libreoffice':<12} FALTA")
        ok = False
    try:
        import pypdfium2
        print(f"{'pypdfium2':<12} ok   {getattr(pypdfium2, '__version__', '')}")
    except Exception as e:      # noqa: BLE001
        print(f"{'pypdfium2':<12} FALTA {e}")
        ok = False
    f = montagem.fontes()
    n = len(list(Path(f).glob("*.ttf"))) if f else 0
    print(f"{'fontes':<12} {'ok' if n >= 30 else 'FALTA'}  ({n} arquivos em {f})")
    ok &= n >= 30
    modelos = list(montagem.MOTOR.glob("modelos/*.xml"))
    print(f"{'modelos':<12} {'ok' if len(modelos) >= 3 else 'FALTA'}  ({len(modelos)})")
    ok &= len(modelos) >= 3
    ok &= _montagem_teste()
    if pptx:
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="montador_diag_") as t:
            cp = Path(t) / Path(pptx).name
            cp.write_bytes(Path(pptx).read_bytes())
            t0 = time.time()
            try:
                r = slides.converter(cp)
                ims = r["imagens"]
                with Image.open(ims[1]) as im:
                    tam = im.size
                bom = tam == (1920, 1080) and len(ims) == len(slides.ler(cp))
                print(f"{'slides':<12} {'ok' if bom else 'ERRO'} ({len(ims)} JPEG {tam[0]}x{tam[1]} pelo {r['metodo']}, "
                      f"{time.time() - t0:.0f} s)")
                ok &= bom
            except Exception as e:     # noqa: BLE001
                print(f"{'slides':<12} ERRO {e}")
                ok = False
    print("TUDO OK" if ok else "FALTA ALGUMA COISA")
    return 0 if ok else 1


def _montagem_teste() -> bool:
    """Monta um dia inventado nos 4 formatos (confere os geradores dentro do app)."""
    import tempfile
    from pathlib import Path
    from montador import mapa, montagem
    from montador.srt import Cue
    falas = {"2026-01-01 10-00-00": [Cue(1, 5, 9, "Olá, sejam bem-vindos à aula de teste."),
                                     Cue(2, 10, 20, "Hoje vamos falar de filas e pilhas."),
                                     Cue(3, 21, 30, "Na fila o primeiro a entrar é o primeiro a sair."),
                                     Cue(4, 90, 100, "Vejo vocês na próxima aula, obrigado.")]}
    bom = True
    with tempfile.TemporaryDirectory(prefix="montador_diag_") as t:
        raiz = Path(t) / "26_000 Professor Teste" / "2026 01 01"
        (raiz / "Footage").mkdir(parents=True)
        mp4 = raiz / "Footage" / "2026-01-01 10-00-00.mp4"
        mp4.write_bytes(b"")
        videos = [{"nome": "2026-01-01 10-00-00", "arquivo": str(mp4), "duracao": 110.0, "largura": 3840,
                   "altura": 1080, "srt": None}]
        dia = {"raiz": str(raiz), "nome": "2026 01 01", "curso": "26_000 Professor Teste", "videos": videos,
               "material": {"pptx": [], "docx": [], "imagens": []}}
        aulas = mapa.sugerir(videos, falas, ["Teste"])["aulas"]
        for formato in ("TP", "TV", "SCREENCAST"):
            t0 = time.time()
            try:
                r = montagem.montar(dia, falas, aulas, formato, "nenhuma", {}, Path(t) / formato, modo="regras",
                                    juntar=True)
                erro = next((x["erro"] for x in r["resultados"] if x["erro"]), None)
            except Exception as e:     # noqa: BLE001
                erro = str(e)
            print(f"{'XML ' + formato:<12} {'ok' if not erro else 'ERRO ' + erro} ({time.time() - t0:.1f} s)")
            bom &= not erro
    return bom


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]   # o Finder antigo manda "-psn_…"
    if args and args[0] == "diagnostico":
        return diagnostico(args[1] if len(args) > 1 else None)
    if args:
        from montador.__main__ import main as cli
        return cli(args) or 0
    if getattr(sys, "frozen", False):
        _log_em_arquivo()
    from montador import server
    server.serve(fechar_sozinho=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
