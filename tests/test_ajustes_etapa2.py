"""Ajustes pedidos depois da etapa 2: SRT único da Skoopia sem tabela, teleprompter, MP4 do OBS."""
import shutil
import subprocess
from pathlib import Path

import pytest

from montador import dia, mp4info, server, skoopia, srt
from montador.srt import Cue

UNICO = Path(__file__).parent / "dados" / "SRT unico - exemplo.srt"


def _falas_e_tabela():
    cues = srt.ler(UNICO)
    tab = [{"video": n, "separador": t, "fala": t + 2} for n, t in srt.separadores(cues)]
    return dia.dividir_unico(cues, tab), tab


def test_divide_cortes_do_srt_unico_sem_tabela():
    falas, tab = _falas_e_tabela()
    videos = [{"nome": k, "duracao": None} for k in falas]      # como no Mac: duração desconhecida
    # marcações no tempo do SRT único, citando a fala de cada vídeo
    marcas = []
    for i, r in enumerate(tab):
        f = falas[r["video"]][0]
        marcas.append(Cue(i + 1, r["fala"] + f.ini, r["fala"] + f.fim, f'[ERRO] "{f.texto}"'))
    d = skoopia.ligar("cortes.srt", marcas, videos, falas, [])
    assert d["modo"] == "dia"
    por = skoopia.distribuir(marcas, d, [])
    assert sorted(por) == sorted(falas)
    for r in tab:
        assert abs(por[r["video"]][0].ini - falas[r["video"]][0].ini) < 0.01


def test_teleprompter_fica_fora_e_pode_voltar(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTADOR_HOME", str(tmp_path / "home"))
    raiz = tmp_path / "Curso" / "2026 10 08"
    (raiz / "Footage").mkdir(parents=True)
    org = raiz / "Originais"
    org.mkdir()
    for n in ("TP-aula-17.pptx", "Aula 17.pptx", "TP_aula 3.pptx", "Tpicos.pptx"):
        (org / n).write_bytes(b"x")
    server.ESTADO.limpar_dia(str(raiz))
    server.ESTADO.dia = dia.ler(raiz)
    m = server._material(server.ESTADO.dia)
    nomes = sorted(Path(p).name for p in m["pptx"])
    assert nomes == ["Aula 17.pptx", "Tpicos.pptx"]
    assert sorted(Path(f["arquivo"]).name for f in m["fora"]) == ["TP-aula-17.pptx", "TP_aula 3.pptx"]
    tp = str(org / "TP-aula-17.pptx")
    server.acao_material({"usar": tp})
    assert tp in server._material(server.ESTADO.dia)["pptx"]
    aula = str(org / "Aula 17.pptx")
    server.acao_material({"remover": aula})
    m = server._material(server.ESTADO.dia)
    assert aula not in m["pptx"] and {"arquivo": aula, "motivo": "tirado"} in m["fora"]
    server.acao_material({"adicionar": [aula, str(org / "TP_aula 3.pptx")]})
    m = server._material(server.ESTADO.dia)
    assert aula in m["pptx"] and str(org / "TP_aula 3.pptx") in m["pptx"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_duracao_de_mp4_fragmentado(tmp_path):
    arq = tmp_path / "obs.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=64x36:d=7:r=10",
                    "-c:v", "mpeg4", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                    "-frag_duration", "1000000", str(arq)], check=True)
    # o OBS grava fragmentado; aqui o mehd pode faltar, então vale o ffprobe
    d = (mp4info.info(arq) or {}).get("duracao") or mp4info.ffprobe(arq)
    assert d and abs(d - 7) < 0.5
