"""Confere se o Montador (modo sem IA) monta igual ao Fluxo NPD.

Uso: python3 tools/comparar_fluxo.py <pasta do dia> <pasta "3 Geradores de XML" do Fluxo NPD> <pasta "4 Modelos">

Para cada formato (TP sem inserção, TV e Screencast), gera as sequências pelos dois caminhos com as mesmas
transcrições e compara os XMLs, ignorando só o que o Montador muda de propósito:
nome da sequência, nome do marcador de erro ("ERRO a conferir" → "ERRO"), comentários com o tipo da
marcação, Lumetri removido, identificadores aleatórios (uuid) e caminhos dos arquivos de assets.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from montador import dia as dia_mod, mapa, montagem, srt   # noqa: E402


def normal(caminho: Path) -> list[str]:
    root = ET.parse(caminho).getroot()
    for pai in root.iter():
        for f in list(pai.findall("filter")):
            e = f.find("effect")
            if e is not None and (e.findtext("effectid") or "").lower() == "lumetri":
                pai.remove(f)
        for tag in ("uuid", "comment"):
            for x in list(pai.findall(tag)):
                pai.remove(x)
    out = []
    for el in root.iter():
        txt = (el.text or "").strip()
        if el.tag == "name" and txt in ("ERRO a conferir", "ERRO"):
            txt = "ERRO"
        if el.tag == "pathurl" and "/assets" in txt:
            txt = txt.split("/")[-1]
        out.append(f"{el.tag}|{txt}")
    return out


def main(pasta, ger, modelos):
    d = dia_mod.ler(pasta)
    falas = dia_mod.transcricoes(d)
    m = mapa.sugerir(d["videos"], falas, [])
    tmp = Path(tempfile.mkdtemp(prefix="comparar_"))
    falhas = 0
    for fmt in ("TP", "TV", "SCREENCAST"):
        res = montagem.montar(d, falas, m["aulas"], fmt, "nenhuma", {}, tmp / f"montador_{fmt}", modo="regras")
        for a, r in zip(m["aulas"], res["resultados"]):
            if r["erro"]:
                print(fmt, a["nome"], "montador falhou:", r["erro"]); falhas += 1; continue
            v = next(x for x in d["videos"] if x["nome"] == r["video"])
            s = tmp / f"{fmt}_{a['n']}.srt"; srt.escrever(s, falas[r["video"]])
            nome_mp4 = Path(v["arquivo"]).name
            saida = tmp / f"fluxo_{fmt}_{a['n']:02d}.xml"
            env = dict(os.environ, ANINHADO="1", BINS="1", AULA=str(a["n"]))
            if fmt == "TP":
                al = tmp / f"al_{a['n']}.json"
                subprocess.run([sys.executable, "-I", f"{ger}/alinhar_pptx.py", "-", s, al], check=True, capture_output=True)
                cmd = [sys.executable, "-I", f"{ger}/gerar_xml_tp_slide.py", f"{modelos}/modelo_tp.xml", al, s, d["raiz"],
                       str(a["n"]), nome_mp4, f"{v['duracao']:.6f}", saida, "sem-slides"]
            else:
                det = tmp / f"det_{fmt}_{a['n']}.json"
                subprocess.run([sys.executable, "-I", f"{ger}/detectar_erros.py", s, det], check=True, capture_output=True)
                if fmt == "TV":
                    cmd = [sys.executable, "-I", f"{ger}/gerar_xml_tv.py", f"{modelos}/modelo_tv.xml", det, s, d["raiz"],
                           Path(nome_mp4).stem, f"{v['duracao']:.6f}", saida, a["nome"]]
                else:
                    p = json.load(open(det)); p.update(raw=nome_mp4, dur=v["duracao"], nome=a["nome"])
                    json.dump(p, open(det, "w"))
                    cmd = [sys.executable, "-I", f"{ger}/gerar_xml_screencast.py", f"{modelos}/modelo_screencast.xml", det, d["raiz"], saida]
            g = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if g.returncode:
                print(fmt, a["nome"], "fluxo falhou:", g.stderr[-200:]); falhas += 1; continue
            x, y = normal(saida), normal(Path(r["arquivo"]))
            y = [l if not l.startswith("name|" + a["nome"]) else l.replace(a["nome"], f"{a['n']:02d}" if fmt == "TP" else a["nome"]) for l in y]
            dif = [(i, p, q) for i, (p, q) in enumerate(zip(x, y)) if p != q]
            ok = not dif and len(x) == len(y)
            falhas += not ok
            print(f"{fmt:<10} {a['nome']:<28} {'IGUAL' if ok else f'DIFERENTE ({len(dif)} linhas; {len(x)} x {len(y)})'}")
            for i, p, q in dif[:5]:
                print("     ", i, p[:80], "≠", q[:80])
    print("TUDO IGUAL" if not falhas else f"{falhas} diferença(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
