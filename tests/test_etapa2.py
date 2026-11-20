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
    aulas = mapa.montar(fx, ["Um", "Tres", "Quatro"])["aulas"]
    r = montagem.montar(d, falas, aulas, "TV", "nenhuma", {}, tmp / "out", modo="regras")
    nomes = [x["nome"] for x in r["resultados"]]
    assert nomes[:2] == ["01 Um", "01 Um (parte 2)"]
    assert any("2 vídeos" in a for a in r["avisos"])


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
