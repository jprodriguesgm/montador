"""Transcrição master do Premiere: todos os vídeos do dia colados numa sequência, sem separadores."""
from pathlib import Path

from mp4falso import mp4_falso

from montador import dia, importar, server, skoopia, srt
from montador.srt import Cue

UNICO = Path(__file__).parent / "dados" / "SRT unico - exemplo.srt"


def _dia_master(tmp_path, master_na_footage=True):
    raiz = tmp_path / "26_000 Professor Exemplo" / "2026 10 08"
    foot = raiz / "Footage"
    foot.mkdir(parents=True)
    por = dia.dividir_unico(srt.ler(UNICO), [])
    master, ini, durs = [], 0.0, {}
    for nome in sorted(por):
        dur = round(por[nome][-1].fim + 7.3, 3)
        durs[nome] = dur
        mp4_falso(foot / f"{nome}.mp4", dur)
        master += [Cue(0, ini + c.ini, ini + c.fim, c.texto) for c in por[nome]]
        ini += dur
    master = [Cue(i + 1, c.ini, c.fim, c.texto) for i, c in enumerate(master)]
    if master_na_footage:
        srt.escrever(foot / "Transcrição sequência master.srt", master)
    return raiz, por, master, durs


def _confere(falas, por):
    assert sorted(falas) == sorted(por)
    for nome, cs in por.items():
        assert len(falas[nome]) == len(cs)
        assert abs(falas[nome][0].ini - cs[0].ini) < 0.01 and abs(falas[nome][-1].fim - cs[-1].fim) < 0.01


def test_master_na_footage_e_dividida_pela_duracao(tmp_path):
    raiz, por, _, _ = _dia_master(tmp_path)
    d = dia.ler(raiz)
    assert d["master"] and not any("Sem transcrição" in a for a in d["avisos"])
    _confere(dia.transcricoes(d), por)


def test_master_importada_a_mao(tmp_path):
    raiz, por, master, _ = _dia_master(tmp_path, master_na_footage=False)
    d = dia.ler(raiz)
    texto = (tmp_path / "m.srt")
    srt.escrever(texto, master)
    r = importar.classificar([{"nome": "transcricao.srt", "conteudo": texto.read_text(encoding="utf-8")}],
                             [v["nome"] for v in d["videos"]], d["videos"])
    assert r["master"] and not r["ignorados"]
    _confere(r["por_video"], por)


def test_skoopia_feita_sobre_a_master(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTADOR_HOME", str(tmp_path / "home"))
    raiz, por, master, durs = _dia_master(tmp_path)
    server.acao_dia({"caminho": str(raiz)})
    nomes = sorted(por)
    ini2 = durs[nomes[0]]                                  # o 2º vídeo começa onde o 1º termina
    c = por[nomes[1]][1]
    cortes = [Cue(1, ini2 + c.ini, ini2 + c.fim, f'[ERRO] "{c.texto}"')]
    tmp = tmp_path / "cortes.srt"
    srt.escrever(tmp, cortes)
    server.acao_skoopia({"arquivos": [{"nome": "cortes.srt", "conteudo": tmp.read_text(encoding="utf-8")}]})
    assert not server.ESTADO.pendentes
    marca = server.ESTADO.marcas[nomes[1]]["cortes.srt"][0]
    assert abs(marca.ini - c.ini) < 0.01


def test_sem_tabela_a_skoopia_tambem_tenta_os_videos_colados(tmp_path):
    raiz, por, master, durs = _dia_master(tmp_path)
    videos = dia.ler(raiz)["videos"]
    nomes = sorted(por)
    ini3 = durs[nomes[0]] + durs[nomes[1]]
    c = por[nomes[2]][1]
    d = skoopia.ligar("cortes.srt", [Cue(1, ini3 + c.ini, ini3 + c.fim, f'[ERRO] "{c.texto}"')], videos, por, [])
    assert d["modo"] == "dia" and d["tabela"][2]["fala"] == ini3
