"""Dia real 2026 11 03 (26_714): transcrição master do Premiere + cortes e inserções da Skoopia feitos sobre ela.

Durações reais (afinfo). Mapa certo, conferido pelo JP: cada vídeo é uma aula, na ordem dos .pptx U3_T1_V1 …
U3_T8_V2; descartar 07-24-42 (começo falso), 08-53-41 ("vou parar cinco minutinhos") e 10-37-44 (4 s).
Os arquivos ficam em tests/dados/dia_2026_11_03/ (fora do GitHub público); sem eles, o teste é pulado.
"""
from pathlib import Path

import pytest

from montador import dia, importar, mapa, skoopia, srt

D = Path(__file__).parent / "dados" / "dia_2026_11_03"
pytestmark = pytest.mark.skipif(not (D / "__Master.srt").is_file(), reason="sem os arquivos do dia real")

DUR = [("07-24-42", 14.868), ("07-25-21", 540.799), ("07-34-22", 548.671), ("07-43-32", 552.959),
       ("07-52-46", 866.004), ("08-07-14", 664.511), ("08-18-23", 596.991), ("08-28-22", 716.969),
       ("08-40-21", 799.167), ("08-53-41", 13.972), ("09-04-03", 830.036), ("09-18-02", 609.471),
       ("09-28-13", 637.097), ("09-38-51", 697.129), ("09-50-30", 824.703), ("10-04-17", 636.927),
       ("10-14-57", 1366.377), ("10-37-44", 3.839), ("10-37-49", 586.836)]
DESCARTE = {"07-24-42", "08-53-41", "10-37-44"}
VIDEOS = [{"nome": f"2026-11-03 {n}", "duracao": d} for n, d in DUR]
NOMES = [v["nome"] for v in VIDEOS]
TITULOS = [f"U3_T{k // 2 + 1}_V{k % 2 + 1}" for k in range(16)]


@pytest.fixture(scope="module")
def dividido():
    txt = (D / "__Master.srt").read_text(encoding="utf-8")
    r = importar.classificar([{"nome": "__Master.srt", "conteudo": txt}], NOMES, VIDEOS)
    return r


def test_master_reconhecida_com_as_duracoes_reais(dividido):
    assert dividido["master"] and sorted(dividido["por_video"]) == NOMES


def test_master_sem_uma_duracao_pede_o_xml_e_diz_qual_video():
    txt = (D / "__Master.srt").read_text(encoding="utf-8")
    videos = [dict(v, duracao=None if v["nome"].endswith("09-18-02") else v["duracao"]) for v in VIDEOS]
    r = importar.classificar([{"nome": "__Master.srt", "conteudo": txt}], NOMES, videos, premiere=True)
    assert not r["master"] and "09-18-02" in r["motivos"]["__Master.srt"] and "XML" in r["motivos"]["__Master.srt"]


@pytest.mark.parametrize("nome", ["cortes.srt", "insercoes.srt"])
def test_skoopia_sobre_a_master_divide_sozinha_e_confere(dividido, nome):
    cues = srt.ler_texto((D / nome).read_text(encoding="utf-8"))
    dest = skoopia.ligar(nome, cues, VIDEOS, dividido["por_video"], dividido["tabela"])
    assert dest["modo"] == "dia" and "ATENÇÃO" not in dest["motivo"]


def test_mapa_do_dia_real(dividido):
    marcas = {}
    for nome in ("cortes.srt", "insercoes.srt"):
        cues = srt.ler_texto((D / nome).read_text(encoding="utf-8"))
        for k, v in dia.dividir_unico(cues, dividido["tabela"]).items():
            marcas.setdefault(k, []).extend(c for c in v if skoopia.classe(c) == "insercao")
    for ins in (None, marcas):                       # com e sem as inserções como pista
        m = mapa.sugerir(VIDEOS, dividido["por_video"], TITULOS, None, ins)
        aulas = [n for n, _ in DUR if n not in DESCARTE]
        assert {a["n"]: [t["video"][-8:] for t in a["trechos"]] for a in m["aulas"]} == \
            {k: [aulas[k - 1]] for k in range(1, 17)}
        assert {d["video"][-8:] for d in m["descartados"]} == DESCARTE
        assert any("pausa longa" in x for x in m["aulas"][14]["conferir"])          # 10-14-57
        assert sum(bool(a["conferir"]) for a in m["aulas"]) <= 4                   # pouco "confira"


def test_mapa_do_dia_real_sem_cartao(dividido):
    m = mapa.sugerir(VIDEOS, dividido["por_video"], [])
    assert len([a for a in m["aulas"] if a["trechos"]]) == 16
