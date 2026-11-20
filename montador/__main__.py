"""Abrir o Montador: python3 -m montador   (abre a janela no navegador)

Linha de comando para testes:
  python3 -m montador mapa <pasta do dia>     mostra o mapa do dia sugerido
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="montador")
    sub = ap.add_subparsers(dest="cmd")
    ab = sub.add_parser("abrir", help="abre a janela (padrão)")
    ab.add_argument("--porta", type=int, default=None)
    ab.add_argument("--sem-navegador", action="store_true")
    ab.add_argument("--fechar-sozinho", action="store_true")
    mp = sub.add_parser("mapa", help="mostra o mapa do dia sugerido para uma pasta")
    mp.add_argument("pasta")
    args = ap.parse_args(argv)

    if args.cmd in (None, "abrir"):
        from . import server
        server.serve(porta=getattr(args, "porta", None), abrir_navegador=not getattr(args, "sem_navegador", False),
                     fechar_sozinho=getattr(args, "fechar_sozinho", False))
        return 0
    if args.cmd == "mapa":
        from . import server
        r = server.acao_dia({"caminho": args.pasta})
        d, m = r["dia"], r["mapa"]
        print(f"{d['curso']} / {d['nome']}: {len(d['videos'])} vídeo(s)")
        for a in d["avisos"] + m["avisos"]:
            print("  aviso:", a)
        if r["titulos"]["motivo"]:
            print("  títulos:", r["titulos"]["motivo"])
        for f in m["faixas"]:
            aula = "descartado" if f["aula"] == 0 else f"aula {f['aula']}"
            print(f"  {f['video']}  {f['ini']:7.1f}–{f['fim']:7.1f}s  {aula}  {f['motivo']}")
        for a in m["aulas"]:
            print(f"  → {a['nome']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
