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


# ---------------------------------------------------------------- partes da mesma aula

TOL = 6        # quadros: fundos que terminam um pouco antes do fim da câmera ainda são fundos


def _janela(seq: ET.Element) -> tuple[int, int]:
    """Começo e fim da câmera (clipes aninhados) na sequência, em quadros."""
    st, en = [], []
    for tr in seq.findall("media/video/track"):
        for c in tr.findall("clipitem"):
            if c.find("sequence") is not None:
                st.append(int(c.findtext("start")))
                en.append(int(c.findtext("end")))
    if not st:
        raise ValueError("sequência sem câmera")
    return min(st), max(en)


def _eh_camera(c: ET.Element, seq_cam: set[str]) -> bool:
    if c.find("sequence") is not None:
        return True
    f = c.find("file")
    return f is not None and f.get("id") in seq_cam


def _mover(e: ET.Element, d: int, so_fim: bool = False):
    """Desloca um item da timeline em `d` quadros (ou só estica o fim)."""
    for tag in (("end",) if so_fim else ("start", "end")):
        v = e.find(tag)
        if v is not None and v.text and v.text.strip() not in ("-1", ""):
            v.text = str(int(v.text) + d)
    if so_fim:
        for tag, fator in (("out", 1), ("pproTicksOut", 8475667200)):
            v = e.find(tag)
            if v is not None and v.text:
                v.text = str(int(v.text) + d * fator)


def juntar_partes(arquivos: list[Path], saida: Path, nome: str) -> Path:
    """Partes de uma aula (uma por vídeo) viram uma sequência só, uma parte depois da outra.

    Da primeira parte ficam a vinheta e os fundos (esticados até o fim); os créditos vão para o fim;
    das outras partes entram a câmera, o áudio, os slides e os marcadores do trecho delas, com um
    marcador "TROCA DE VÍDEO" na emenda.
    """
    import copy
    tmp = saida.with_name(saida.stem + " (juntando).xml")
    juntar(arquivos, tmp, nome)
    root = ET.parse(tmp).getroot()
    tmp.unlink()
    proj = root.find("project")
    filhos = proj.find("children")
    seqs = filhos.findall("sequence")
    base = seqs[0]
    vb, ab = base.findall("media/video/track"), base.findall("media/audio/track")
    for parte in seqs[1:]:
        cs_a, ce_a = _janela(base)
        cs_b, ce_b = _janela(parte)
        desloc, delta = ce_a - cs_b, ce_b - cs_b
        # os arquivos da câmera da parte (áudio dela fica em clipes de arquivo, não aninhados)
        cam_b = {c.find("file").get("id") for tr in parte.findall("media/audio/track") for c in tr.findall("clipitem")
                 if c.find("file") is not None and cs_b - 1 <= int(c.findtext("start")) and int(c.findtext("end")) <= ce_b + 1
                 and int(c.findtext("end")) - int(c.findtext("start")) > 0
                 and not any(x in (c.findtext("name") or "") for x in ("Final_cima", "tela_creditos"))}
        # 1) a base abre espaço: créditos e o que vem depois da câmera andam; fundos esticam
        for tr in vb + ab:
            for c in tr.findall("clipitem") + tr.findall("transitionitem"):
                st, en = int(c.findtext("start") or -1), int(c.findtext("end") or -1)
                if c.find("sequence") is not None or st < 0:
                    continue
                if st <= cs_a + TOL and en >= ce_a - TOL and not _eh_camera(c, set()):
                    _mover(c, delta, so_fim=True)                   # fundo (HEX, degradê, vinheta, brasão)
                elif st >= ce_a - 60:
                    _mover(c, delta)                               # créditos
        for mk in base.findall("marker"):
            if int(mk.findtext("in") or 0) >= ce_a:
                for tag in ("in", "out"):
                    if mk.find(tag) is not None and mk.findtext(tag) not in ("-1", None):
                        mk.find(tag).text = str(int(mk.findtext(tag)) + delta)
        # 2) o trecho da parte entra logo depois da câmera da base
        for lado, trs_b, trs_a in (("video", parte.findall("media/video/track"), vb),
                                    ("audio", parte.findall("media/audio/track"), ab)):
            for i, tr in enumerate(trs_b):
                if i >= len(trs_a):
                    novo = copy.deepcopy(tr)
                    for c in novo.findall("clipitem") + novo.findall("transitionitem"):
                        novo.remove(c)
                    base.find(f"media/{lado}").append(novo)
                    trs_a.append(novo)
                destino = trs_a[i]
                for c in tr.findall("clipitem") + tr.findall("transitionitem"):
                    st, en = int(c.findtext("start") or -1), int(c.findtext("end") or -1)
                    camera = _eh_camera(c, cam_b)
                    fundo = st <= cs_b + TOL and en >= ce_b - TOL and not camera
                    tarja = (c.findtext("name") or "").lower().startswith("lower third")
                    if st < 0 or fundo or tarja or st < cs_b - 1 or en > ce_b + 1:
                        continue                                    # vinheta, créditos, tarja e fundos da parte ficam de fora
                    novo = copy.deepcopy(c)
                    _mover(novo, desloc)
                    pos = next((k for k, ch in enumerate(list(destino)) if ch.tag in ("enabled", "locked")), len(destino))
                    destino.insert(pos, novo)
        ult = [k for k, ch in enumerate(list(base)) if ch.tag == "marker"]
        pos = (ult[-1] + 1) if ult else len(base)
        cam_nome = next((c.findtext("name") for tr in parte.findall("media/video/track") for c in tr.findall("clipitem")
                         if c.find("sequence") is not None), "")
        troca = ET.Element("marker")
        ET.SubElement(troca, "comment").text = f"A aula continua na gravação {cam_nome}: confira a emenda."
        ET.SubElement(troca, "name").text = "TROCA DE VÍDEO"
        ET.SubElement(troca, "in").text = str(ce_a)
        ET.SubElement(troca, "out").text = str(ce_a + 30)
        ET.SubElement(troca, "pproColor").text = "4294741314"
        novos = [troca]
        for mk in parte.findall("marker"):
            i0 = int(mk.findtext("in") or 0)
            if not (cs_b <= i0 < ce_b) or (mk.findtext("name") or "").lower().startswith("lower third"):
                continue
            m2 = copy.deepcopy(mk)
            for tag in ("in", "out"):
                if m2.find(tag) is not None and m2.findtext(tag) not in ("-1", None):
                    m2.find(tag).text = str(int(m2.findtext(tag)) + desloc)
            novos.append(m2)
        for k, m2 in enumerate(novos):
            base.insert(pos + k, m2)
        dur = base.find("duration")
        if dur is not None and dur.text:
            dur.text = str(int(dur.text) + delta)
        filhos.remove(parte)
    base.find("name").text = nome
    proj.find("name").text = nome
    saida.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
                     + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    return saida
