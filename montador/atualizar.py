"""Atualizar o app pelo GitHub (Releases do jprodriguesgm/montador).

Duas camadas:
  - Baixar: baixa o .zip da versão nova para a pasta Downloads e abre a pasta (funciona em qualquer máquina;
    o editor troca o app como sempre fez);
  - Atualizar: baixa, troca o app e abre a versão nova, sozinho.
      Mac: na mesma pasta do app, se der para escrever nela; senão em ~/Applications (sem administrador).
           Baixado pelo próprio app, o arquivo não ganha a "quarentena" do Mac (o comando xattr não é mais
           preciso); por garantia, ela é tirada de novo depois da troca.
      Windows: o app fecha, um .cmd espera ele sair, troca a pasta e abre o novo (os arquivos de um programa
           aberto não podem ser trocados).
    Se esbarrar em permissão, avisa o que fazer e deixa o .zip baixado.

Versões de teste ("Montagem N") só aparecem para quem marcar isso nas Configurações.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from . import __build__, __version__

REPO = "jprodriguesgm/montador"
API = f"https://api.github.com/repos/{REPO}"


class ErroAtualizar(Exception):
    pass


def _ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:      # noqa: BLE001 — sem certifi: certificados do sistema
        return ssl.create_default_context()


def _curl() -> str | None:
    return shutil.which("curl") or next((x for x in ("/usr/bin/curl", r"C:\Windows\System32\curl.exe")
                                         if Path(x).is_file()), None)


def _baixar(url: str, destino: Path | None = None, timeout: int = 30) -> bytes | None:
    """Baixa pelo Python; se o certificado/conexão falhar, tenta o curl do sistema (Mac e Windows têm)."""
    import urllib.error
    import urllib.request
    cab = {"User-Agent": f"Montador/{__version__}", "Accept": "application/vnd.github+json"}
    try:
        req = urllib.request.Request(url, headers=cab)
        with urllib.request.urlopen(req, timeout=timeout if destino is None else 600, context=_ctx()) as r:
            if destino is None:
                return r.read()
            with open(destino, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            return None
    except urllib.error.HTTPError as e:
        raise ErroAtualizar(f"o GitHub respondeu {e.code}")
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        exe = _curl()
        if not exe:
            raise ErroAtualizar(f"sem conexão com o GitHub ({e})")
        cmd = [exe, "-fsSL", "--max-time", str(timeout if destino is None else 900), "-H", f"User-Agent: {cab['User-Agent']}",
               "-H", f"Accept: {cab['Accept']}", url]
        if destino is not None:
            cmd[1:1] = ["-o", str(destino)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=(timeout if destino is None else 900) + 10)
        except (OSError, subprocess.SubprocessError) as e2:
            raise ErroAtualizar(f"sem conexão com o GitHub ({e2})")
        if r.returncode != 0:
            raise ErroAtualizar("sem conexão com o GitHub (" + (r.stderr.decode("utf-8", "replace").strip()[:200] or
                                                                 f"curl {r.returncode}") + ")")
        return r.stdout if destino is None else None


def _num(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def nome_do_pacote() -> str | None:
    if sys.platform == "darwin":
        return "Montador-mac.zip"
    if os.name == "nt":
        return "Montador-windows.zip"
    return None


def atual() -> str:
    """Etiqueta da versão aberta: v1.2.3 (oficial) ou montagem-N (teste)."""
    return __build__ or f"v{__version__}"


def verificar(testes: bool = False) -> dict:
    """{"tem": bool, "versao": "1.2.0" | "Montagem 12 (teste)", "etiqueta", "url", "pagina", "automatico": bool}."""
    pacote = nome_do_pacote()
    if testes:
        lista = json.loads(_baixar(f"{API}/releases?per_page=15") or b"[]")
        rel = next((r for r in lista if not r.get("draft")), None)
    else:
        rel = json.loads(_baixar(f"{API}/releases/latest") or b"{}")
    if not rel or not rel.get("tag_name"):
        return {"tem": False}
    tag = rel["tag_name"]
    oficial = tag.startswith("v")
    if tag == atual():
        tem = False
    elif oficial and not __build__:
        tem = _num(tag) > _num(__version__)
    else:
        tem = True                                     # teste ↔ oficial ou outra montagem de teste: oferece
    asset = next((a for a in rel.get("assets", []) if a.get("name") == pacote), None)
    return {"tem": bool(tem and asset), "etiqueta": tag, "versao": rel.get("name") or tag,
            "url": asset and asset.get("browser_download_url"), "pagina": rel.get("html_url"),
            "automatico": bool(getattr(sys, "frozen", False) and pacote)}


def pasta_downloads() -> Path:
    p = Path.home() / "Downloads"
    return p if p.is_dir() else Path(tempfile.gettempdir())


def baixar(info: dict) -> Path:
    if not info.get("url"):
        raise ErroAtualizar("não achei o arquivo da versão nova para este computador")
    destino = pasta_downloads() / f"Montador {info.get('etiqueta', '')} {nome_do_pacote()}".replace("  ", " ")
    parcial = destino.with_suffix(".parcial")
    _baixar(info["url"], parcial)
    if not zipfile.is_zipfile(parcial):
        parcial.unlink(missing_ok=True)
        raise ErroAtualizar("o arquivo baixado veio incompleto — tente de novo")
    parcial.replace(destino)
    return destino


# ------------------------------------------------------------------ trocar o app

def _app_atual() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        app = exe.parents[2]                             # Montador.app/Contents/MacOS/Montador
        return app if app.suffix == ".app" else None
    return exe.parent                                    # pasta Montador\ com o Montador.exe


def _pode_escrever(p: Path) -> bool:
    try:
        teste = p / f".montador-teste-{os.getpid()}"
        teste.write_bytes(b"")
        teste.unlink()
        return True
    except OSError:
        return False


def instalar(zip_: Path) -> dict:
    """Prepara a troca. Devolve {"pasta": onde o novo vai ficar, "aviso": ...}. Quem chama fecha o app depois."""
    app = _app_atual()
    if app is None:
        raise ErroAtualizar("a troca automática só funciona no app instalado — use Baixar")
    if sys.platform == "darwin":
        return _instalar_mac(app, zip_)
    if os.name == "nt":
        return _instalar_windows(app, zip_)
    raise ErroAtualizar("sistema não suportado")


def _instalar_mac(app: Path, zip_: Path) -> dict:
    pasta = app.parent
    aviso = ""
    if not (_pode_escrever(pasta) and os.access(app, os.W_OK)):
        pasta = Path.home() / "Applications"
        pasta.mkdir(exist_ok=True)
        aviso = (f"Sem permissão para trocar o app em {app.parent}: a versão nova foi para {pasta}. "
                 "Use o Montador de lá (pode apagar o antigo quando quiser).")
    tmp = Path(tempfile.mkdtemp(prefix="montador_novo_", dir=pasta if _pode_escrever(pasta) else None))
    r = subprocess.run(["/usr/bin/ditto", "-x", "-k", str(zip_), str(tmp)], capture_output=True, timeout=600)
    novo = tmp / "Montador.app"
    if r.returncode != 0 or not novo.is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        raise ErroAtualizar("não consegui abrir o .zip baixado — ele ficou em Downloads para trocar à mão")
    destino = pasta / "Montador.app"
    script = tmp / "trocar.sh"
    script.write_text(f"""#!/bin/sh
# Montador: espera a versão aberta fechar, troca o app e abre a nova
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
DEST={_sh(destino)}
VELHO={_sh(destino.with_name("Montador.app.antigo"))}
rm -rf "$VELHO"
[ -e "$DEST" ] && mv "$DEST" "$VELHO"
if mv {_sh(novo)} "$DEST"; then
  xattr -dr com.apple.quarantine "$DEST" 2>/dev/null
  rm -rf "$VELHO"
else
  [ -e "$VELHO" ] && mv "$VELHO" "$DEST"
fi
open "$DEST"
rm -rf {_sh(tmp)}
""", encoding="utf-8")
    script.chmod(0o755)
    subprocess.Popen(["/bin/sh", str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return {"pasta": str(pasta), "aviso": aviso}


def _sh(p: Path) -> str:
    return "'" + str(p).replace("'", "'\\''") + "'"


def _instalar_windows(app: Path, zip_: Path) -> dict:
    pasta = app.parent
    aviso = ""
    if not (_pode_escrever(pasta) and _pode_escrever(app)):
        pasta = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs"
        pasta.mkdir(parents=True, exist_ok=True)
        aviso = (f"Sem permissão para trocar o app em {app}: a versão nova foi para {pasta / 'Montador'}. "
                 "Troque o atalho para o Montador.exe de lá.")
    tmp = Path(tempfile.mkdtemp(prefix="montador_novo_", dir=pasta))
    try:
        with zipfile.ZipFile(zip_) as z:
            z.extractall(tmp)
    except (OSError, zipfile.BadZipFile):
        shutil.rmtree(tmp, ignore_errors=True)
        raise ErroAtualizar("não consegui abrir o .zip baixado — ele ficou em Downloads para trocar à mão")
    novo = tmp / "Montador"
    if not (novo / "Montador.exe").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise ErroAtualizar("o .zip baixado não tem o Montador.exe — ele ficou em Downloads para trocar à mão")
    destino = pasta / "Montador" if pasta != app.parent else app
    velho = destino.with_name(destino.name + ".antigo")
    script = tmp / "trocar.cmd"
    velho, destino, novo, tmp_q = (Path(str(x).replace("%", "%%")) for x in (velho, destino, novo, tmp))
    script.write_text(f"""@echo off
rem Montador: espera a versao aberta fechar, troca a pasta e abre a nova
:espera
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find "{os.getpid()}" >NUL && (timeout /t 1 /nobreak >NUL & goto espera)
timeout /t 1 /nobreak >NUL
if exist "{velho}" rmdir /s /q "{velho}"
if exist "{destino}" move "{destino}" "{velho}" >NUL
move "{novo}" "{destino}" >NUL
if errorlevel 1 (
  if exist "{velho}" move "{velho}" "{destino}" >NUL
)
start "" "{destino}\\Montador.exe"
if exist "{velho}" rmdir /s /q "{velho}"
(goto) 2>NUL & rmdir /s /q "{tmp_q}"
""", encoding="cp1252", errors="replace")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    return {"pasta": str(destino.parent), "aviso": aviso}
