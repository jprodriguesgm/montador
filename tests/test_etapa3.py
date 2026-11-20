"""Etapa 3: slides e inserções."""
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from montador import insercoes, montagem, slides
from montador.srt import Cue

pptx_lib = pytest.importorskip("pptx")
from test_etapa2 import dia_teste  # noqa: E402,F401  (mesma pasta do dia de exemplo)


def _deck(caminho: Path):
    from pptx import Presentation
    from pptx.util import Inches
    p = Presentation()
    p.slide_width, p.slide_height = Inches(13.333), Inches(7.5)
    for titulo, cod, itens, nota in [
        ("Filas e pilhas", "C10", ["Primeiro a entrar", "Último a sair"], "C10 · Cartela. Exibir por 6 a 8 segundos."),
        ("Árvores binárias", "C11", ["Raiz", "Folhas", "Altura"], ""),
        ("Referências", None, ["AUTOR. Livro. 2026."], ""),
    ]:
        s = p.slides.add_slide(p.slide_layouts[5])
        s.shapes.title.text = titulo
        tb = s.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3)).text_frame
        tb.text = itens[0]
        for x in itens[1:]:
            tb.add_paragraph().text = x
        if cod:
            s.shapes.add_textbox(Inches(11), Inches(0.3), Inches(1), Inches(0.5)).text_frame.text = cod
        if nota:
            s.notes_slide.notes_text_frame.text = nota
    p.save(caminho)


def _imagens_prontas(pptx: Path, n=3):
    from PIL import Image
    pasta = pptx.parent / pptx.stem
    pasta.mkdir(exist_ok=True)
    for i in range(1, n + 1):
        Image.new("RGB", (1920, 1080), (40 * i, 80, 160)).save(pasta / f"{pptx.stem}.{i:03d}.jpg", quality=95)


def test_le_texto_codigo_e_tempo_da_nota(tmp_path):
    d = tmp_path / "Aula.pptx"
    _deck(d)
    ss = slides.ler(d)
    assert [s["titulo"] for s in ss] == ["Filas e pilhas", "Árvores binárias", "Referências"]
    assert [s["codigo"] for s in ss] == ["C10", "C11", None]
    assert ss[0]["segundos"] == 8.0 and ss[1]["segundos"] is None
    assert ss[2]["referencias"]


@pytest.mark.skipif(not slides.soffice(), reason="sem LibreOffice")
def test_converte_em_jpeg_1920(tmp_path):
    from PIL import Image
    d = tmp_path / "Aula.pptx"
    _deck(d)
    r = slides.converter(d)
    assert sorted(r["imagens"]) == [1, 2, 3]
    with Image.open(r["imagens"][1]) as im:
        assert im.size == (1920, 1080) and im.format == "JPEG"
    assert slides.converter(d)["metodo"] == "imagens prontas"


def _todos(tmp_path):
    d = tmp_path / "Aula.pptx"
    _deck(d)
    _imagens_prontas(d)
    return insercoes.todos_os_slides([{"pptx": str(d), "slides": slides.ler(d), "imagens": slides.imagens(d)}])


def test_casa_skoopia_por_codigo_titulo_e_sem_slide(tmp_path):
    ss = _todos(tmp_path)
    assert [s["n"] for s in ss] == [1, 2]                 # referências ficam fora
    cues = [Cue(1, 10, 50, "Estruturas de árvore\n\nC11 raiz e folhas"),
            Cue(2, 60, 70, "Filas e pilhas\n\nPrimeiro a entrar"),
            Cue(3, 80, 90, "Grafos dirigidos\n\nVértices e arestas"),
            Cue(4, 95, 99, "[ERRO] repetiu")]
    its = insercoes.casar_skoopia(cues, ss)
    assert [(it["slide"] or {}).get("codigo") for it in its] == ["C11", "C10", None]
    its = insercoes.duracoes(its, 200, 15)
    assert [round(it["fim_tela"] - it["ini"]) for it in its] == [15, 8, 10]


def test_sem_ia_acha_o_slide_pela_fala(tmp_path):
    ss = _todos(tmp_path)
    falas = [Cue(1, 0, 5, "Bom dia, vamos começar."), Cue(2, 30, 36, "Uma árvore binária tem raiz, folhas e altura."),
             Cue(3, 90, 95, "Na fila o primeiro a entrar é o primeiro a sair; na pilha, o último a sair.")]
    its = insercoes.casar_regras(falas, 0, 120, ss)
    assert [(it["slide"]["codigo"], it["ini"]) for it in its] == [("C11", 30), ("C10", 90)]


@pytest.mark.parametrize("formato", ["TP", "TV"])
def test_montagem_com_slides_e_cartela(dia_teste, formato):
    d, falas, m, tmp = dia_teste
    org = Path(d["raiz"]) / "Originais"
    org.mkdir(exist_ok=True)
    deck = org / "Aula 4.pptx"
    _deck(deck)
    _imagens_prontas(deck)
    v = "2026-10-08 13-50-08"
    marcas = {v: {"insercoes.srt": [Cue(1, 200, 260, "Filas e pilhas\n\nPrimeiro a entrar"),
                                    Cue(2, 400, 420, "Algo sem slide\n\nTexto da cartela")]}}
    dd = dict(d, material={"pptx": [str(deck)], "docx": [], "imagens": []})
    r = montagem.montar(dd, falas, m["aulas"][3:], formato, "slide", marcas, tmp / "out", modo="skoopia")
    res = r["resultados"][0]
    assert res["erro"] is None
    root = ET.parse(res["arquivo"]).getroot()
    seq = next(s for s in root.iter("sequence") if s.findtext("name") == "04 Quatro")
    nomes = [mk.findtext("name") for mk in seq.findall("marker")]
    if formato == "TP":
        assert res["n_slides"] == 1 and res["n_cartelas"] == 1
        assert "SLIDE C10" in nomes and "CARTELA" in nomes
        jpg = [x for x in seq.iter("clipitem") if (x.findtext("name") or "").endswith(".001.jpg")]
        assert len(jpg) == 1
        assert int(jpg[0].findtext("end")) - int(jpg[0].findtext("start")) == round(8 * 30000 / 1001)
    else:
        assert res["n_tela"] == 2 and nomes.count("TELA CHEIA") == 2
        topo = seq.findall("media/video/track")[-1]
        assert topo.findtext("enabled") == "TRUE"
        assert all(x.findtext("name").endswith("-D") for x in topo.findall("clipitem"))
    # nenhum clipe sobreposto na mesma faixa
    for tr in seq.findall("media/video/track"):
        cs = sorted((int(x.findtext("start")), int(x.findtext("end"))) for x in tr.findall("clipitem"))
        assert all(a[1] <= b[0] for a, b in zip(cs, cs[1:]))
