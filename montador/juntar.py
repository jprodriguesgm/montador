"""Junta os XMLs das aulas num XML só (uma importação no Premiere).

Cada aula continua sendo uma sequência; o que é igual entre elas entra uma vez só:
vídeos da Footage, sequências aninhadas (E/D) da mesma gravação, vinheta, créditos, fundos, brasão e slides.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_REF_TEXTO = ("linkclipref", "masterclipid")


def _ler(caminho: Path) -> ET.Element:
    return ET.parse(caminho).getroot()


def _renomear(root: ET.Element, sufixo: str):
    """Todos os ids do arquivo ganham um sufixo, para não colidir com os de outra aula."""
    for e in root.iter():
        if e.get("id"):
            e.set("id", e.get("id") + sufixo)
        if e.tag in _REF_TEXTO and e.text and e.text.strip():
            e.text = e.text.strip() + sufixo


def _chave_arquivo(f: ET.Element) -> str | None:
    p = f.findtext("pathurl")
    return p.strip() if p else None


def juntar(arquivos: list[Path], saida: Path, nome_projeto: str) -> Path:
    raizes = []
    for k, a in enumerate(arquivos, 1):
        r = _ler(a)
        _renomear(r, f"-a{k}")
        raizes.append(r)

    # 1) arquivos de mídia: a primeira definição de cada caminho vale para todos
    canon_file: dict[str, str] = {}       # pathurl -> id
    troca_file: dict[str, str] = {}       # id repetido -> id que fica
    for r in raizes:
        for f in r.iter("file"):
            if len(f) == 0:
                continue
            ch = _chave_arquivo(f)
            if not ch:
                continue
            if ch in canon_file:
                troca_file[f.get("id")] = canon_file[ch]
            else:
                canon_file[ch] = f.get("id")
    for r in raizes:
        for f in r.iter("file"):
            novo = troca_file.get(f.get("id"))
            if novo:
                for c in list(f):
                    f.remove(c)
                f.attrib.clear()
                f.set("id", novo)

    # 2) sequências aninhadas e clipes-mestre da Footage: mesmo nome = mesma coisa
    troca_seq: dict[str, str] = {}
    troca_master: dict[str, str] = {}
    vistas_seq: dict[str, str] = {}
    vistos_master: dict[str, str] = {}

    def _nos_bins(r):
        proj = r.find("project")
        return proj if proj is not None else r

    for r in raizes:
        for b in _nos_bins(r).iter("bin"):
            filhos = b.find("children")
            if filhos is None:
                continue
            for c in filhos:
                nome = c.findtext("name") or ""
                if c.tag == "sequence" and len(c):
                    if nome in vistas_seq:
                        troca_seq[c.get("id")] = vistas_seq[nome]
                    else:
                        vistas_seq[nome] = c.get("id")
                elif c.tag == "clip":
                    if nome in vistos_master:
                        troca_master[c.get("id")] = vistos_master[nome]
                    else:
                        vistos_master[nome] = c.get("id")
    for r in raizes:
        for e in r.iter():
            if e.tag == "sequence" and e.get("id") in troca_seq and len(e) == 0:
                e.set("id", troca_seq[e.get("id")])
            if e.tag == "masterclipid" and e.text in troca_master:
                e.text = troca_master[e.text]

    # 3) monta o projeto único: bins juntados por nome, sequências das aulas na ordem
    novo = ET.Element("xmeml", version="4")
    proj = ET.SubElement(novo, "project")
    ET.SubElement(proj, "name").text = nome_projeto
    filhos = ET.SubElement(proj, "children")

    def _juntar_bin(destino: ET.Element, origem: ET.Element):
        """Copia os itens de `origem` (children) para `destino` (children), sem repetir."""
        for c in list(origem):
            if c.tag == "bin":
                nome = c.findtext("name")
                igual = next((b for b in destino.findall("bin") if b.findtext("name") == nome), None)
                if igual is None:
                    igual = ET.SubElement(destino, "bin")
                    ET.SubElement(igual, "name").text = nome
                    ET.SubElement(igual, "children")
                _juntar_bin(igual.find("children"), c.find("children") if c.find("children") is not None else [])
            elif c.tag == "sequence" and c.get("id") in troca_seq:
                continue
            elif c.tag == "clip" and c.get("id") in troca_master:
                continue
            else:
                destino.append(c)

    sequencias = []
    for r in raizes:
        p = _nos_bins(r)
        ch = p.find("children")
        if ch is None:                       # xmeml sem projeto: sequências direto na raiz
            sequencias += [c for c in r if c.tag == "sequence"]
            continue
        for c in list(ch):
            if c.tag == "sequence":
                sequencias.append(c)
                ch.remove(c)
        _juntar_bin(filhos, ch)
    # dentro de cada bin: clipes-mestre (onde a mídia é definida) antes das pastas com as aninhadas
    def _ordenar(ch: ET.Element):
        itens = list(ch)
        for c in itens:
            ch.remove(c)
        for c in sorted(itens, key=lambda x: {"clip": 0, "bin": 2}.get(x.tag, 1)):
            ch.append(c)
            if c.tag == "bin" and c.find("children") is not None:
                _ordenar(c.find("children"))
    _ordenar(filhos)

    # bins primeiro (definições de mídia antes das referências), depois as aulas
    for s in sequencias:
        filhos.append(s)

    saida.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
                     + ET.tostring(novo, encoding="unicode") + "\n", encoding="utf-8")
    return saida
