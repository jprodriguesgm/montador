"""Correções de 25/11/2026: duração que falta, transcrição do Premiere (caixa e XML) e Skoopia sobre a master."""
from pathlib import Path  # noqa: F401 (usado no teste do motor)

from mp4falso import mp4_falso

from montador import dia, importar, premiere, server, srt
from montador.srt import Cue

FPS = 30000 / 1001


def _xml(clipes, nome_seq="Master"):
    """clipes: [(arquivo, início na sequência em s, entrada no vídeo em s, duração em s)]."""
    itens = []
    for k, (arq, ini, entra, dur) in enumerate(clipes, 1):
        f = lambda s: round(s * FPS)                     # noqa: E731
        itens.append(f"""<clipitem id="c{k}"><name>{arq}</name><enabled>TRUE</enabled>
          <rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
          <start>{f(ini)}</start><end>{f(ini + dur)}</end><in>{f(entra)}</in><out>{f(entra + dur)}</out>
          <file id="file-{k}"><name>{arq}</name><pathurl>file:///Volumes/SSD/{arq.replace(' ', '%20')}</pathurl></file>
        </clipitem>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE xmeml><xmeml version="4"><sequence id="s1">
      <name>{nome_seq}</name><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
      <media><video><track>{''.join(itens)}</track></video></media></sequence></xmeml>"""


def _dia(tmp_path, sem_duracao=()):
    raiz = tmp_path / "26_714 Professor" / "2026 11 03"
    foot = raiz / "Footage"
    foot.mkdir(parents=True)
    nomes = ["2026-11-03 07-25-21", "2026-11-03 07-34-22", "2026-11-03 07-43-32"]
    durs = [540.8, 548.7, 553.0]
    falas = {}
    for n, d in zip(nomes, durs):
        mp4_falso(foot / f"{n}.mp4", 0 if n in sem_duracao else d)
        falas[n] = [Cue(k + 1, 5 + 30 * k, 12 + 30 * k, f"Assunto {n[-5:]} parte {k}") for k in range(15)]
    return raiz, foot, nomes, durs, falas


def _master(falas, tabela):
    out = []
    for r in tabela:
        out += [Cue(0, c.ini + r["fala"], c.fim + r["fala"], c.texto) for c in falas[r["video"]]
                if r["separador"] <= c.ini + r["fala"]]
    return [Cue(i + 1, c.ini, c.fim, c.texto) for i, c in enumerate(sorted(out, key=lambda c: c.ini))]


def _txt(cues):
    return "\n".join(f"{c.n}\n{srt.fmt(c.ini)} --> {srt.fmt(c.fim)}\n{c.texto}\n" for c in cues)


def test_video_sem_duracao_e_avisado_pelo_nome(tmp_path):
    raiz, _, nomes, _, _ = _dia(tmp_path, sem_duracao=[ "2026-11-03 07-34-22"])
    d = dia.ler(raiz)
    assert any("duração de: 2026-11-03 07-34-22" in a for a in d["avisos"])


def test_xml_da_sequencia_com_espaco_e_ordem_trocada():
    nomes = ["2026-11-03 07-25-21", "2026-11-03 07-34-22", "2026-11-03 07-43-32"]
    x = _xml([(nomes[0] + ".mp4", 0, 0, 540.8), (nomes[2] + ".mp4", 560, 3.0, 550.0),
              (nomes[1] + ".mp4", 1120, 0, 548.7), ("vinheta.mov", 1700, 0, 5)])
    r = premiere.ler(x, nomes)
    tab = {t["video"]: t for t in r["tabela"]}
    assert abs(tab[nomes[2]]["separador"] - 560) < 0.05 and abs(tab[nomes[2]]["fala"] - 557) < 0.05
    assert r["fora"] == ["vinheta"] and not r["faltam"]


def test_xml_de_um_video_so_nao_serve(tmp_path):
    import pytest
    with pytest.raises(premiere.ErroXML):
        premiere.ler(_xml([("2026-11-03 07-25-21.mp4", 0, 0, 100)]), ["2026-11-03 07-25-21", "2026-11-03 07-34-22"])


def test_caixa_premiere_divide_pela_duracao(tmp_path):
    raiz, _, nomes, durs, falas = _dia(tmp_path)
    d = dia.ler(raiz)
    tab = dia.tabela_colada(d["videos"])
    m = _master(falas, tab)
    texto = _txt(m)
    r = importar.classificar([{"nome": "__Master.srt", "conteudo": texto}], nomes, d["videos"], premiere=True)
    assert r["master"] and sorted(r["por_video"]) == nomes
    assert abs(r["por_video"][nomes[1]][0].ini - 5) < 0.01


def test_sem_duracao_o_xml_resolve_e_a_skoopia_se_divide_sozinha(tmp_path, monkeypatch):
    """O caso de 03/11: um vídeo sem duração → master "não reconhecida" e Skoopia pendente. Com o XML, tudo
    se resolve sem importar de novo a master nem a Skoopia."""
    monkeypatch.setenv("MONTADOR_HOME", str(tmp_path / "home"))
    raiz, foot, nomes, durs, falas = _dia(tmp_path, sem_duracao=["2026-11-03 07-43-32"])
    tab_real = [{"video": n, "separador": s, "fala": s} for n, s in zip(nomes, [0, durs[0], durs[0] + durs[1]])]
    master = _master(falas, tab_real)
    srt.escrever(foot / "__Master.srt", master)
    r = server.acao_dia({"caminho": str(raiz)})
    assert any("__Master.srt parece a transcrição" in a for a in r["dia"]["avisos"])
    assert r["dia"]["soltos"] == ["__Master.srt"]
    # Skoopia feita sobre a master: fica pendente, com o motivo
    c = falas[nomes[2]][3]
    cortes = [Cue(1, tab_real[2]["fala"] + c.ini, tab_real[2]["fala"] + c.fim, f'[ERRO] "{c.texto}"')]
    r = server.acao_skoopia({"arquivos": [{"nome": "cortes.srt", "conteudo": _txt(cortes)}]})
    pend = [x for x in r["dia"]["skoopia"] if x["modo"] == "pendente"]
    assert pend and "2026-11-03 07-43-32" in pend[0]["motivo"] and "XML" in pend[0]["motivo"]
    # só o XML da sequência: a master e a Skoopia se dividem
    x = _xml([(n + ".mp4", t["separador"], 0, dd) for n, t, dd in zip(nomes, tab_real, durs)])
    r = server.acao_transcricoes({"arquivos": [{"nome": "Master.xml", "conteudo": x}]})
    assert r["importacao"]["master"] and sorted(r["importacao"]["videos"]) == nomes
    assert set(r["dia"]["transcritos"]) == set(nomes) and not r["dia"]["soltos"]
    assert not any("parece a transcrição" in a for a in r["dia"]["avisos"])
    sk = r["dia"]["skoopia"][0]
    assert sk["modo"] == "dia" and "ATENÇÃO" not in sk["motivo"]
    marca = server.ESTADO.marcas[nomes[2]]["cortes.srt"][0]
    assert abs(marca.ini - c.ini) < 0.05


def test_skoopia_de_outro_dia_avisa(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTADOR_HOME", str(tmp_path / "home"))
    raiz, foot, nomes, durs, falas = _dia(tmp_path)
    tab = dia.tabela_colada(dia.ler(raiz)["videos"])
    srt.escrever(foot / "__Master.srt", _master(falas, tab))
    server.acao_dia({"caminho": str(raiz)})
    cortes = [Cue(k, 600 + 100 * k, 605 + 100 * k, f'[ERRO] "frase que ninguém disse número {k}"') for k in range(1, 6)]
    cortes.append(Cue(9, 5000, 5005, '[ERRO] "outra frase"'))
    r = server.acao_skoopia({"arquivos": [{"nome": "cortes.srt", "conteudo": _txt(cortes)}]})
    sk = r["dia"]["skoopia"][0]
    assert sk["modo"] == "dia" and "ATENÇÃO" in sk["motivo"] and "depois do fim da sequência" in sk["motivo"]


def test_scripts_do_motor_compilam():
    """Os geradores do motor/ rodam como scripts separados: um erro de digitação só aparecia na hora de montar."""
    import py_compile
    motor = Path(__file__).parent.parent / "montador" / "motor"
    for arq in sorted(motor.glob("*.py")):
        py_compile.compile(str(arq), doraise=True)
