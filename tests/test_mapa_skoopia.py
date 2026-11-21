"""Mapa pela Skoopia/decupagem: onde cada aula começa e termina."""
import math

from montador import mapa, skoopia
from montador.srt import Cue

VIDS = [("v1", 30), ("v2", 2000), ("v3", 120), ("v4", 900), ("v5", 800)]


def _dia():
    videos = [{"nome": n, "duracao": d} for n, d in VIDS]
    tab, ini = [], 0
    for n, d in VIDS:
        fala = ini + 2
        tab.append({"video": n, "separador": ini, "fala": fala})
        ini = math.ceil((fala + d + 30) / 60) * 60
    falas = {n: [Cue(1, 1, d - 1, "fala")] for n, d in VIDS}
    return videos, tab, falas


def _marcas(arquivos, tab):
    marcas = {}
    for nome, cues in arquivos.items():
        for v, lista in skoopia.distribuir(cues, {"modo": "dia", "tabela": tab}, tab).items():
            marcas.setdefault(v, {})[nome] = lista
    return marcas


def test_aulas_pelos_slides_de_titulo(tmp_path):
    videos, tab, falas = _dia()
    f2 = tab[1]["fala"]; f4 = tab[3]["fala"]
    insercoes = [Cue(1, f2 + 300, f2 + 310, "SLIDE 1.01 – Título"), Cue(2, f2 + 900, f2 + 920, "SLIDE 1.02 – Texto"),
                 Cue(3, f2 + 1800, f2 + 1810, "PALAVRA-CHAVE: PRÓXIMA AULA"),
                 Cue(4, f4 + 100, f4 + 110, "SLIDE 2.01 – Título"), Cue(5, f4 + 600, f4 + 610, "SLIDE 2.05 – Algo")]
    cortes = [Cue(1, 0, f2 + 300, "[BASTIDORES]"), Cue(2, f2 + 1820, f4 + 100, "[BASTIDORES]"),
              Cue(3, f4 + 700, f4 + 705, "[BASTIDORES]")]           # curto: não encerra a aula
    r = mapa.pela_skoopia(videos, falas, _marcas({"ins.srt": insercoes, "cor.srt": cortes}, tab), tab, [])
    assert r["fonte"].startswith("slides de título")
    a1, a2 = r["aulas"]
    assert [(t["video"], round(t["ini"]), round(t["fim"])) for t in a1["trechos"]] == [("v2", 300, 1820)]
    assert a2["trechos"][0]["video"] == "v4" and round(a2["trechos"][0]["ini"]) == 100
    assert a2["trechos"][-1]["video"] == "v5"          # sem bastidor longo no fim: vai até o fim do dia


def test_lista_de_aulas_da_decupagem_com_nomes(tmp_path):
    videos, tab, falas = _dia()
    f2, f3 = tab[1]["fala"], tab[2]["fala"]
    aulas = [Cue(1, f2 + 300, f2 + 1200, "Aula 1A – Primeira metade"),
             Cue(2, f2 + 1202, f3 + 100, "Aula 1B – Segunda metade"),
             Cue(3, tab[3]["fala"] + 50, tab[3]["fala"] + 850, "Aula 2 – Outra aula")]
    assert skoopia.tipo(aulas) == "aulas"
    r = mapa.pela_skoopia(videos, falas, _marcas({"AULAS.srt": aulas}, tab), tab, [])
    assert [a["titulo"] for a in r["aulas"]] == ["Primeira metade", "Segunda metade", "Outra aula"]
    assert [t["video"] for t in r["aulas"][1]["trechos"]] == ["v2", "v3"]     # a aula 1B passa para o vídeo seguinte
    # com o cartão na mesma conta, valem os títulos do cartão
    r = mapa.pela_skoopia(videos, falas, _marcas({"AULAS.srt": aulas}, tab), tab, ["A", "B", "C"])
    assert [a["titulo"] for a in r["aulas"]] == ["A", "B", "C"]


def test_sem_marca_de_aula_fica_como_antes():
    videos, tab, falas = _dia()
    assert mapa.pela_skoopia(videos, falas, _marcas({"c.srt": [Cue(1, 10, 20, "[ERRO]")]}, tab), tab, []) is None
