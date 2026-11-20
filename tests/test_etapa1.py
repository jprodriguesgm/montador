"""Testes da etapa 1: SRT, cartão (títulos grudados), pasta do dia, mapa do dia e configurações."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from montador import appdata, cartao, dia, mapa, mp4info, srt
from montador.srt import Cue

DADOS = Path(__file__).parent / "dados"
UNICO = DADOS / "SRT unico - exemplo.srt"

# Cartão real do Planner (20/11/2026): títulos da Unidade 2, alguns grudados na mesma linha
CARTAO = """Curso: Automação Inteligente: RPA, IA e Hiperautomação

Tipo do curso:  Pós Graduação

Disciplina: Projeto em Hiperautomação

Microfundamento: Não

Início da(s) disciplina(s):  Não sei

Títulos:
Unidade 2

O que o PDD entrega e o que o SDD precisa acrescentar
Da regra de negócio à especificação técnica da solução
Componentes reutilizáveis: por que a automação é montada em partes Exceção de negócio e exceção de sistema: tratamento e retomada Onde um modelo de aprendizado de máquina entra em um fluxo automatizado Chamada de modelo, limiar de confiança e devolução para o humano
O que o processamento de linguagem natural resolve em um fluxo de processo Classificação, extração e roteamento a partir de texto livre
Como um documento vira dado estruturado
Qualidade de imagem, layout variável e conferência do que foi lido Filas e gatilhos: o que dispara cada etapa do fluxo
Pontos de decisão assistida e a passagem do caso para a pessoa Como se testa uma automação que depende de um modelo
Critérios de aceite quando a saída não é sempre a mesma

Está ciente que deverá alocar o material na unidade correspondente? Sim

Deseja ter algum tipo de treinamento? Não

Finalizou as gravações da sua disciplina/UDA? Não
Gravou Pós Graduação? Você finalizou a gravação de alguma unidade? Unidade 2

\\---
"""

ESPERADOS = [
    "O que o PDD entrega e o que o SDD precisa acrescentar",
    "Da regra de negócio à especificação técnica da solução",
    "Componentes reutilizáveis: por que a automação é montada em partes",
    "Exceção de negócio e exceção de sistema: tratamento e retomada",
    "Onde um modelo de aprendizado de máquina entra em um fluxo automatizado",
    "Chamada de modelo, limiar de confiança e devolução para o humano",
    "O que o processamento de linguagem natural resolve em um fluxo de processo",
    "Classificação, extração e roteamento a partir de texto livre",
    "Como um documento vira dado estruturado",
    "Qualidade de imagem, layout variável e conferência do que foi lido",
    "Filas e gatilhos: o que dispara cada etapa do fluxo",
    "Pontos de decisão assistida e a passagem do caso para a pessoa",
    "Como se testa uma automação que depende de um modelo",
    "Critérios de aceite quando a saída não é sempre a mesma",
]


@pytest.fixture(autouse=True)
def home_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTADOR_HOME", str(tmp_path / "home"))


# ------------------------------------------------------------------ SRT

def test_srt_unico_e_separadores():
    cues = srt.ler(UNICO)
    seps = srt.separadores(cues)
    assert [s[0] for s in seps][:2] == ["2026-10-08 13-16-38", "2026-10-08 13-17-17"]
    assert len(seps) == 5
    por_video = dia.dividir_unico(cues, [])
    v = por_video["2026-10-08 13-38-48"]
    assert v[0].texto.startswith("Dá uma respiradinha")
    assert v[0].ini == pytest.approx(2.08, abs=0.01)       # 24:04,08 − 24:02 (fala começa 2 s após o separador)


def test_srt_ida_e_volta(tmp_path):
    c = [Cue(1, 1.5, 3.25, "Olá"), Cue(2, 3.5, 4.0, "mundo")]
    srt.escrever(tmp_path / "a.srt", c)
    lido = srt.ler(tmp_path / "a.srt")
    assert [(x.ini, x.fim, x.texto) for x in lido] == [(1.5, 3.25, "Olá"), (3.5, 4.0, "mundo")]


# ------------------------------------------------------------------ cartão

def test_cartao_le_titulos_e_unidade():
    c = cartao.ler_texto(CARTAO)
    assert c.unidade == "Unidade 2"
    assert len(c.titulos) == 8                     # como vieram (alguns grudados)
    assert c.resumo()["disciplina"] == "Projeto em Hiperautomação"


def test_titulos_grudados_separados_ate_bater_com_as_aulas():
    c = cartao.ler_texto(CARTAO)
    r = cartao.separar_titulos(c.titulos, 14)
    assert r["titulos"] == ESPERADOS
    assert r["separados"] == 6


def test_sem_alvo_nao_separa():
    c = cartao.ler_texto(CARTAO)
    r = cartao.separar_titulos(c.titulos)
    assert len(r["titulos"]) == 8 and r["conferir"]


def test_nome_proprio_nao_vira_titulo():
    linhas = ["A correlação funciona com trace id do OpenTelemetry e com o New Relic Como avaliar plataformas"]
    r = cartao.separar_titulos(linhas, 2)
    assert r["titulos"] == ["A correlação funciona com trace id do OpenTelemetry e com o New Relic",
                            "Como avaliar plataformas"]


def test_formato_e_insercao():
    assert cartao.detectar_formato("1 - Aspectos técnicos: Gravação em TP.") == "TP"
    assert cartao.detectar_formato("Formato: TV Interativa") == "TV"
    assert cartao.detectar_formato("Mesa digitalizadora") == "SCREENCAST"
    c = cartao.ler_texto("3 - Inserções: Slides\n")
    assert c.insercao == "slide"
    c = cartao.ler_texto("3 - Inserções: a critério do editor\n")
    assert c.insercao == "editor"


def test_numerar():
    assert cartao.numerar(["Um", "Dois"]) == ["01 Um", "02 Dois"]


# ------------------------------------------------------------------ mapa do dia

def _videos_do_unico():
    falas = dia.dividir_unico(srt.ler(UNICO), [])
    videos = [{"nome": k, "duracao": (v[-1].fim + 5 if v else 10)} for k, v in falas.items()]
    return videos, falas


def test_mapa_dia_real_descarta_take_e_monta_4_aulas():
    videos, falas = _videos_do_unico()
    m = mapa.sugerir(videos, falas, ["Aula 17", "Aula 18", "Aula 19", "Aula 20"])
    assert [f["aula"] for f in m["faixas"]] == [0, 1, 2, 3, 4]
    assert m["descartados"][0]["video"] == "2026-10-08 13-16-38"
    assert [a["nome"] for a in m["aulas"]] == ["01 Aula 17", "02 Aula 18", "03 Aula 19", "04 Aula 20"]
    assert not m["avisos"]


def test_mapa_sem_titulos_tambem_descarta_o_take_curto():
    videos, falas = _videos_do_unico()
    m = mapa.sugerir(videos, falas, [])
    assert [f["aula"] for f in m["faixas"]] == [0, 1, 2, 3, 4]


def _c(ini, texto, dur=4.0):
    return Cue(0, ini, ini + dur, texto)


def test_final_refeito_em_take_curto_vira_continuacao():
    falas = {
        "A": [_c(0, "Olá, nesta aula vamos falar de filas."), _c(10, "Filas organizam o trabalho do robô."),
              _c(300, "E para fechar, o que vimos hoje."), _c(320, "Desculpa, vou refazer o final.")],
        "B": [_c(0, "Então, para fechar, vimos filas e gatilhos."), _c(20, "Vejo vocês na próxima aula.")],
    }
    videos = [{"nome": "A", "duracao": 330}, {"nome": "B", "duracao": 30}]
    m = mapa.sugerir(videos, falas, ["Filas"])
    assert len(m["aulas"]) == 1
    assert [t["video"] for t in m["aulas"][0]["trechos"]] == ["A", "B"]
    assert m["aulas"][0]["conferir"]               # confira o corte no vídeo anterior


def test_final_refeito_emendando_a_proxima_aula_divide_o_video():
    falas = {
        "A": [_c(0, "Olá, hoje vamos falar de filas."), _c(10, "Filas organizam o trabalho."),
              _c(300, "Para fechar, o que vimos.")],
        "B": [_c(0, "Para fechar, vimos filas e gatilhos."), _c(15, "Vejo vocês na próxima."),
              _c(40, "Olá, nesta aula vamos falar de gatilhos."), _c(60, "Gatilhos disparam o fluxo."),
              _c(400, "Vejo vocês lá.")],
    }
    videos = [{"nome": "A", "duracao": 310}, {"nome": "B", "duracao": 410}]
    m = mapa.sugerir(videos, falas, ["Filas", "Gatilhos"])
    assert [a["nome"] for a in m["aulas"]] == ["01 Filas", "02 Gatilhos"]
    a1, a2 = m["aulas"]
    assert [t["video"] for t in a1["trechos"]] == ["A", "B"]
    assert a1["trechos"][1]["fim"] == pytest.approx(39.0)
    assert a2["trechos"] == [{"video": "B", "ini": 39.0, "fim": 410}]


def test_teste_de_microfone_sai():
    falas = {"T": [_c(0, "Testando, um dois.")], "A": [_c(0, "Olá, bem-vindos à aula."), _c(10, "Conteúdo.")]}
    videos = [{"nome": "T", "duracao": 20}, {"nome": "A", "duracao": 600}]
    m = mapa.sugerir(videos, falas, ["Aula"])
    assert m["faixas"][0]["aula"] == 0 and "teste" in m["faixas"][0]["motivo"]
    assert len(m["aulas"]) == 1


def test_editor_divide_e_troca_aula():
    fx = [{"video": "B", "ini": 0, "fim": 100, "tipo": "abre", "aula": 1, "motivo": ""}]
    fx = mapa.dividir(fx, "B", 40)
    fx[1]["aula"] = 2
    m = mapa.montar(fx, ["X", "Y"])
    assert [a["trechos"] for a in m["aulas"]] == [[{"video": "B", "ini": 0, "fim": 40}],
                                                  [{"video": "B", "ini": 40, "fim": 100}]]


# ------------------------------------------------------------------ pasta do dia e vídeo

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_pasta_do_dia(tmp_path):
    raiz = tmp_path / "26_000 Professor Exemplo" / "2026 10 08"
    foot, ori = raiz / "Footage", raiz / "Originais"
    foot.mkdir(parents=True)
    ori.mkdir()
    for nome in ["2026-10-08 13-16-38", "2026-10-08 13-17-17", "2026-10-08 13-29-42", "2026-10-08 13-38-48",
                 "2026-10-08 13-50-08"]:
        (foot / f"{nome}.mp4").write_bytes(b"")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=3840x1080:d=2", "-c:v",
                    "mpeg4", str(foot / "2026-10-08 13-16-38.mp4")], check=True)
    (foot / "2026-10-08 13-17-17-E.mp4").write_bytes(b"")       # metade antiga: ignorada
    shutil.copy(UNICO, foot / UNICO.name)
    (ori / "cartao.txt").write_text(CARTAO.replace("Títulos:", "Formato: TP\n3 - Inserções: Slides\n\nTítulos:"), encoding="utf-8")
    (ori / "Aula 17.pptx").write_bytes(b"")
    d = dia.ler(foot)                                           # aponta a Footage: acha o dia
    assert d["raiz"] == str(raiz)
    assert [v["nome"] for v in d["videos"]][0] == "2026-10-08 13-16-38"
    assert len(d["videos"]) == 5
    assert d["videos"][0]["largura"] == 3840 and d["videos"][0]["duracao"] == pytest.approx(2, abs=0.1)
    assert d["srt_unico"] and d["cartao"]["formato"] == "TP" and d["cartao"]["insercao"] == "slide"
    assert d["material"]["pptx"]
    falas = dia.transcricoes(d)                                 # sem .srt por vídeo: recorta do SRT único
    assert falas["2026-10-08 13-50-08"][-1].texto.startswith("Obrigado por ter chegado")


# ------------------------------------------------------------------ configurações e "Link Media"

def test_configuracoes_e_procura_de_assets(tmp_path):
    base = tmp_path / "Drive Backup"
    (base / "Identidade" / "Saida").mkdir(parents=True)
    (base / "Fundos" / "PALETA").mkdir(parents=True)
    for p in ["Identidade/Saida/Final_cima_v4_mov.mov", "Identidade/Saida/Brasão 2025.png",
              "Identidade/Saida/tela_creditos_mov_v1.mov", "Fundos/vignette_00000_00000.png", "Fundos/PALETA/HEX.png"]:
        (base / p).write_bytes(b"x")
    achados = appdata.procurar_assets(base / "Identidade/Saida/Final_cima_v4_mov.mov", niveis_acima=2)
    assert {"vinheta", "brasao", "creditos", "vignette", "hex"} <= set(achados)
    cfg = appdata.salvar({"assets": achados, "cores": {"erro": "Red"}})
    assert cfg["cores"] == {"erro": "Red", "bastidores": "Mango", "conferir": "Violet"}
    est = {a["id"]: a["ok"] for a in appdata.estado_assets()}
    assert est["vinheta"] and not est["marinho"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_mp4info(tmp_path):
    p = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=1920x1080:d=3", "-c:v",
                    "mpeg4", "-movflags", "+faststart", str(p)], check=True)
    i = mp4info.info(p)
    assert i["largura"] == 1920 and i["altura"] == 1080 and i["duracao"] == pytest.approx(3, abs=0.1)


def test_sigla_abre_titulo_depois_de_nome_proprio():
    linhas = ["Plataformas comerciais de observabilidade: New Relic e Datadog IA embarcada nas plataformas comerciais"]
    r = cartao.separar_titulos(linhas, 2)
    assert r["titulos"] == ["Plataformas comerciais de observabilidade: New Relic e Datadog",
                            "IA embarcada nas plataformas comerciais"]


# ------------------------------------------------------------------ importar transcrições à mão

from montador import importar


def test_importar_reconhece_cada_arquivo(tmp_path):
    videos = ["2026-10-08 13-16-38", "2026-10-08 13-17-17", "2026-10-08 13-29-42", "2026-10-08 13-38-48",
              "2026-10-08 13-50-08"]
    arquivos = [
        {"nome": "2026-10-08 13-16-38.srt", "conteudo": "1\n00:00:02,000 --> 00:00:04,000\nOlá, teste\n"},
        {"nome": "cortes.srt", "conteudo": "1\n00:00:01,000 --> 00:00:02,000\n[ERRO] repetiu\n"},
        {"nome": "anotacoes.txt", "conteudo": "nada aqui"},
        {"nome": "SRT unico - Footage.srt", "conteudo": UNICO.read_text(encoding="utf-8")},
    ]
    r = importar.classificar(arquivos, videos)
    assert r["unico"] and r["skoopia"] == ["cortes.srt"] and r["ignorados"] == ["anotacoes.txt"]
    assert sorted(r["por_video"]) == sorted(videos)
    assert r["por_video"]["2026-10-08 13-16-38"][0].texto == "Olá, teste"      # o arquivo do vídeo vale mais que o único


def test_importar_pasta_e_procurar_por_nome(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "2026-10-08 13-17-17 - transcrição.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nOlá\n", encoding="utf-8")
    achados = importar.procurar_por_nome(tmp_path, ["2026-10-08 13-17-17", "2026-10-08 13-29-42"])
    assert list(achados) == ["2026-10-08 13-17-17"]
    lidos = importar.ler_pasta(tmp_path)
    assert lidos[0]["nome"].startswith("2026-10-08 13-17-17")


# ------------------------------------------------------------------ retorno da Skoopia

from montador import skoopia


def _dia_exemplo():
    cues = srt.ler(UNICO)
    tab = [{"video": n, "separador": t, "fala": t + 2} for n, t in srt.separadores(cues)]
    falas = dia.dividir_unico(cues, tab)
    videos = [{"nome": k, "duracao": v[-1].fim + 5} for k, v in falas.items()]
    return videos, falas, tab


def test_skoopia_do_dia_inteiro_e_dividida_pela_tabela():
    videos, falas, tab = _dia_exemplo()
    cortes = [Cue(1, 60.0, 61.0, "[BASTIDORES] marcador de arquivo"),
              Cue(2, 2159.0, 2193.0, "[BASTIDORES] intervalo entre gravações ('E aí', 'Obrigado')")]
    d = skoopia.ligar("cortes.srt", cortes, videos, falas, tab)
    assert d["modo"] == "dia" and skoopia.tipo(cortes) == "cortes"
    por = skoopia.distribuir(cortes, d, tab)
    assert "2026-10-08 13-17-17" not in por                      # só o separador: não vira marcação
    assert por["2026-10-08 13-50-08"][0].ini == 0.0


def test_skoopia_de_um_video_pelas_falas_citadas():
    videos, falas, tab = _dia_exemplo()
    v = "2026-10-08 13-38-48"
    c = falas[v][0]
    cortes = [Cue(1, c.ini, c.fim, f"[BASTIDORES] instrução à professora ('{c.texto}')")]
    d = skoopia.ligar("cortes da aula.srt", cortes, videos, falas, tab)
    assert d == {"modo": "video", "video": v, "motivo": "pelas falas citadas"}


def test_skoopia_sem_pista_fica_pendente_e_conta_por_aula():
    videos, falas, tab = _dia_exemplo()
    ins = [Cue(1, 5.0, 9.0, "Cartela sem relação\nTópico")]
    d = skoopia.ligar("insercoes.srt", ins, videos, falas, tab)
    assert d["modo"] == "pendente" and skoopia.tipo(ins) == "insercoes"
    marcas = {"V": {"a.srt": [Cue(1, 10, 12, "[ERRO] x"), Cue(2, 50, 55, "Cartela")]}}
    assert skoopia.contar(marcas, [{"video": "V", "ini": 0, "fim": 40}]) == {"erro": 1, "bastidores": 0, "insercao": 0}
