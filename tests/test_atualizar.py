"""Botão Atualizar: qual versão oferecer e a troca do app no Mac (o script roda de verdade num app de mentira)."""
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from montador import atualizar


def _rel(tag, nome=None, pre=False):
    pac = atualizar.nome_do_pacote() or "Montador-mac.zip"
    return {"tag_name": tag, "name": nome or tag, "prerelease": pre, "draft": False, "html_url": "https://x",
            "assets": [{"name": pac, "browser_download_url": f"https://x/{tag}/{pac}"}]}


@pytest.fixture
def github(monkeypatch):
    resp = {}
    monkeypatch.setattr(atualizar, "_baixar", lambda url, destino=None, timeout=30: json.dumps(resp[url.rsplit("/", 1)[-1]]).encode())
    monkeypatch.setattr(atualizar, "nome_do_pacote", lambda: "Montador-mac.zip")
    return resp


def test_oferece_so_versao_oficial_mais_nova(github, monkeypatch):
    monkeypatch.setattr(atualizar, "__version__", "1.0.1")
    monkeypatch.setattr(atualizar, "__build__", "")
    github["latest"] = _rel("v1.0.1")
    assert not atualizar.verificar()["tem"]
    github["latest"] = _rel("v1.1.0", "Montador 1.1.0")
    r = atualizar.verificar()
    assert r["tem"] and r["versao"] == "Montador 1.1.0" and r["url"].endswith("Montador-mac.zip")
    github["latest"] = _rel("v1.0.0")
    assert not atualizar.verificar()["tem"]


def test_canal_de_teste(github, monkeypatch):
    monkeypatch.setattr(atualizar, "__version__", "1.0.1")
    monkeypatch.setattr(atualizar, "__build__", "montagem-12")
    github["releases?per_page=15"] = [_rel("montagem-12", pre=True), _rel("v1.0.1")]
    assert not atualizar.verificar(testes=True)["tem"]           # já é a montagem mais nova
    github["releases?per_page=15"] = [_rel("montagem-13", "Montagem 13 (teste)", pre=True), _rel("montagem-12", pre=True)]
    assert atualizar.verificar(testes=True)["versao"] == "Montagem 13 (teste)"


@pytest.mark.skipif(os.name == "nt", reason="script do Mac")
def test_troca_no_mac_com_o_script(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    velho = apps / "Montador.app" / "Contents" / "MacOS"
    velho.mkdir(parents=True)
    (velho / "Montador").write_text("velho")
    zip_ = tmp_path / "Montador-mac.zip"
    with zipfile.ZipFile(zip_, "w") as z:
        z.writestr("Montador.app/Contents/MacOS/Montador", "novo")
    feito = {}

    def run(cmd, **kw):                                    # o ditto do Mac, aqui pelo zipfile
        zipfile.ZipFile(cmd[3]).extractall(cmd[4])
        return subprocess.CompletedProcess(cmd, 0)

    def popen(cmd, **kw):
        feito["script"] = cmd[1]
        return None
    monkeypatch.setattr(atualizar.subprocess, "run", run)
    monkeypatch.setattr(atualizar.subprocess, "Popen", popen)
    monkeypatch.setattr(atualizar.os, "getpid", lambda: 999999)     # "processo que já fechou"
    r = atualizar._instalar_mac(apps / "Montador.app", zip_)
    assert r["pasta"] == str(apps) and not r["aviso"]
    monkeypatch.undo()
    texto = Path(feito["script"]).read_text()
    texto = texto.replace('open "$DEST"', 'true')
    Path(feito["script"]).write_text(texto)
    subprocess.run(["/bin/sh", feito["script"]], check=True, timeout=30)          # o pid 999999 já não existe
    assert (apps / "Montador.app" / "Contents" / "MacOS" / "Montador").read_text() == "novo"
    assert sorted(p.name for p in apps.iterdir()) == ["Montador.app"]          # sem sobras
