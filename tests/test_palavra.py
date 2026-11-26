"""TP com palavra-chave (gerar_xml_pk.py): monta de verdade com um .pptx."""
import shutil
from pathlib import Path

import pytest

from montador import mapa, montagem
from test_etapa2 import dia_teste  # noqa: F401
from test_etapa3 import _deck


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_monta_tp_com_palavra_chave(dia_teste, tmp_path):   # noqa: F811
    d, falas, m, tmp = dia_teste
    deck = tmp_path / "aula.pptx"
    _deck(deck)
    d = dict(d, material={"pptx": [str(deck)], "docx": [], "imagens": []})
    aulas = mapa.montar(m["faixas"], ["Um", "Dois", "Tres", "Quatro"])["aulas"][:1]
    r = montagem.montar(d, falas, aulas, "TP", "palavra", {}, tmp / "pk", modo="regras", juntar=False)
    assert r["resultados"] and not [x["erro"] for x in r["resultados"] if x["erro"]], r["resultados"]
    assert all(Path(x["arquivo"]).stat().st_size > 1000 for x in r["resultados"])
