"""Etapa 2: montagem do XML (geradores do Fluxo NPD + Skoopia, nomes, cores, sem Lumetri, assets da máquina)."""
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from montador import appdata, dia, mapa, montagem, skoopia, srt
from montador.srt import Cue
from mp4falso import mp4_falso

DADOS = Path(__file__).parent / "dados"
UNICO = DADOS / "SRT unico - exemplo.srt"


@pytest.fixture
def dia_teste(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTADOR_HOME", str(tmp_path / "home"))
    raiz = tmp_path / "26_000 Professor Exemplo" / "2026 10 08"
    foot = raiz / "Footage"
    foot.mkdir(parents=True)
    cues = srt.ler(UNICO)
    por = dia.dividir_unico(cues, [])
    for nome, cs in por.items():
        dur = int(cs[-1].fim + 5)
        mp4_falso(foot / f"{nome}.mp4", dur)
    shutil.copy(UNICO, foot / UNICO.name)
    d = dia.ler(raiz)
    falas = dia.transcricoes(d)
    m = mapa.sugerir(d["videos"], falas, ["Um", "Dois", "Tres", "Quatro"])
    return d, falas, m, tmp_path


def _seq(arquivo, nome):
    root = ET.parse(arquivo).getroot()
    return root, next(s for s in root.iter("sequence") if s.findtext("name") == nome)


@pytest.mark.parametrize("formato", ["TP", "TV", "SCREENCAST"])
def test_monta_os_quatro_xmls_sem_efeitos(dia_teste, formato):
    d, falas, m, tmp = dia_teste
    r = montagem.montar(d, falas, m["aulas"], formato, "nenhuma", {}, tmp / "out", modo="regras")
    assert [x["erro"] for x in r["resultados"]] == [None] * 4
    assert [Path(x["arquivo"]).name for x in r["resultados"]] == ["01 Um.xml", "02 Dois.xml", "03 Tres.xml", "04 Quatro.xml"]
    root, seq = _seq(r["resultados"][0]["arquivo"], "01 Um")
    assert not [e for e in root.iter("effectid") if e.text in ("Lumetri", "Gaussian Blur")]
    assert Path(r["relatorio"]).is_file()


def test_skoopia_vira_marcadores_com_tipo_e_cor(dia_teste):
    d, falas, m, tmp = dia_teste
    v = "2026-10-08 13-50-08"
    c = falas[v]
    marcas = {v: {"cortes.srt": [Cue(1, c[1].ini, c[1].fim, "[BASTIDORES] instrução à professora"),
                                Cue(2, c[3].ini, c[3].fim, "[ERRO] repetiu a frase")]}}
    appdata.salvar({"cores": {"bastidores": "Mango", "erro": "Rose"}})
    r = montagem.montar(d, falas, m["aulas"][3:], "TP", "nenhuma", marcas, tmp / "out", modo="skoopia")
    res = r["resultados"][0]
    assert res["erro"] is None and res["fonte"] == "skoopia"
    _, seq = _seq(res["arquivo"], "04 Quatro")
    nomes = [mk.findtext("name") for mk in seq.findall("marker")]
    assert "ERRO" in nomes and "ERRO a conferir" not in nomes


def test_aula_em_dois_videos_sai_em_duas_partes(dia_teste):
    d, falas, m, tmp = dia_teste
    fx = [dict(f) for f in m["faixas"]]
    fx[2]["aula"] = 1                                  # junta a 2ª gravação à aula 1 (como um final refeito)
    m2 = mapa.montar(fx, ["Um", "Dois", "Tres", "Quatro"])
    # o número da aula é o do título: a aula 2 ficou sem trecho e aparece como não reconhecida (não vira XML)
    assert [a["n"] for a in m2["aulas"] if a.get("nao_reconhecida")] == [2]
    aulas = m2["aulas"]
    r = montagem.montar(d, falas, aulas, "TV", "nenhuma", {}, tmp / "out", modo="regras")
    nomes = [x["nome"] for x in r["resultados"]]
    assert nomes[:2] == ["01 Um", "01 Um (parte 2)"]
    assert any("2 vídeos" in a and "sequência só" in a for a in r["avisos"])
    # as duas partes viram uma sequência só, uma depois da outra
    assert r["resultados"][0]["arquivo"] == r["resultados"][1]["arquivo"]
    root = ET.parse(r["resultados"][0]["arquivo"]).getroot()
    seqs = root.find("project/children").findall("sequence")
    assert [s.findtext("name") for s in seqs] == ["01 Um"]
    seq = seqs[0]
    cam = sorted((int(c.findtext("start")), int(c.findtext("end")), c.findtext("name"))
                 for c in seq.findall("media/video/track")[1].findall("clipitem"))
    assert len({n[:19] for _, _, n in cam}) == 2                       # as duas gravações
    assert all(a[1] == b[0] for a, b in zip(cam, cam[1:]))             # sem buraco na emenda
    nomes_m = [m.findtext("name") for m in seq.findall("marker")]
    assert "TROCA DE VÍDEO" in nomes_m and sum(n.lower().startswith("lower third") for n in nomes_m) == 1
    creditos = [c for t in seq.iter("track") for c in t.findall("clipitem") if "creditos" in (c.findtext("name") or "")]
    assert len(creditos) == 1 and int(creditos[0].findtext("start")) >= cam[-1][1] - 60
    assert sorted(p.name for p in (tmp / "out").glob("*.xml")) == ["01 Um.xml", "03 Tres.xml", "04 Quatro.xml"]


def test_assets_da_maquina(dia_teste):
    d, falas, m, tmp = dia_teste
    base = tmp / "Drive Backup" / "Saida"
    base.mkdir(parents=True)
    for nome in ("Final_cima_v4_mov.mov", "Brasão 2025.png"):
        (base / nome).write_bytes(b"x")
    appdata.salvar({"assets": appdata.procurar_assets(base / "Brasão 2025.png", niveis_acima=1)})
    r = montagem.montar(d, falas, m["aulas"][:1], "TV", "nenhuma", {}, tmp / "out", modo="regras")
    texto = Path(r["resultados"][0]["arquivo"]).read_text(encoding="utf-8")
    assert "Drive%20Backup/Saida/Final_cima_v4_mov.mov" in texto
    assert "SSD%20Ilha%201/assets/Identidade%20visual%20PMV/2025%20-%20Novo%20projeto%20base/Projeto%20vinheta%20PUC%202025/Saida/Final_cima" not in texto


def test_plano_skoopia_junta_sobrepostos_e_acha_silencio():
    cues = [Cue(1, 0, 5, "Olá, bem-vindos à aula de hoje sobre filas."), Cue(2, 6, 10, "Filas organizam o trabalho."),
            Cue(3, 30, 35, "Depois de um silêncio, continuamos."), Cue(4, 36, 40, "Vejo vocês lá.")]
    mk = [Cue(1, 6, 8, "[ERRO] x"), Cue(2, 7, 10, "[BASTIDORES] y"), Cue(3, 1, 2, "Cartela")]
    p = montagem.plano_skoopia(cues, mk, 0, 50)
    erros = [t for t in p["trechos"] if t[2] == "erro"]
    assert erros[0][:2] == [6, 10] and "[ERRO]" in erros[0][3] and "[BASTIDORES]" in erros[0][3]
    assert any("[SILÊNCIO]" in t[3] for t in erros)
    # a aula inteira fica dividida (TV e screencast precisam disso)
    tr = p["trechos"]
    assert tr[0][0] == p["T0"] and tr[-1][1] == p["T1"] and all(a[1] == b[0] for a, b in zip(tr, tr[1:]))



def test_skoopia_com_script_marca_pode_ser_um_erro_em_outra_cor(dia_teste):
    from test_script_skoopia import _cues
    d, falas, m, tmp = dia_teste
    v = m["aulas"][0]["trechos"][0]["video"]
    falas = dict(falas, **{v: _cues()})                  # aula curta com uma tentativa repetida que a Skoopia não marcou
    aulas = [{"n": 1, "nome": "01 Um", "trechos": [{"video": v, "ini": 0.0, "fim": 40.0}]}]
    for formato in ("TP", "TV", "SCREENCAST"):
        r = montagem.montar(d, falas, aulas, formato, "nenhuma", {}, tmp / f"out-{formato}", modo="skoopia",
                            com_script=True)
        x = r["resultados"][0]
        assert x["arquivo"] and x["n_script"] > 0, (formato, x)
        texto = Path(x["arquivo"]).read_text(encoding="utf-8")
        assert "PODE SER UM ERRO" in texto and "Cerulean" in texto, formato
        sem = montagem.montar(d, falas, aulas, formato, "nenhuma", {}, tmp / f"sem-{formato}", modo="skoopia",
                              com_script=False)
        assert sem["resultados"][0]["n_script"] == 0 and "PODE SER UM ERRO" not in Path(
            sem["resultados"][0]["arquivo"]).read_text(encoding="utf-8"), formato
