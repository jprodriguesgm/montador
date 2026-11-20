"""Prepara o que vai DENTRO do app (etapa 4).

    python packaging/build_deps.py          # baixa e prepara tudo
    python packaging/build_deps.py check    # confere

Resultado na raiz do repositório (fora do git):
    fontes/   Montserrat, Poppins e Carlito (licença OFL) — para o LibreOffice e para as cartelas de palavra-chave
    bin/      Mac: LibreOffice.app · Windows: libreoffice/ (com as fontes dentro, para os slides saírem iguais)

LibreOffice: a versão "stable" mais nova do site oficial (download.documentfoundation.org), sem instalar nada:
- Mac (Apple Silicon): abre o .dmg e copia o LibreOffice.app; as fontes vão em Contents/Resources/fonts/truetype
  e o app é assinado de novo (assinatura local, como o resto do Montador).
- Windows: extrai o .msi (msiexec /a, instalação administrativa: só copia os arquivos) em bin/libreoffice;
  as fontes vão em share/fonts/truetype.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
FONTES = ROOT / "fontes"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
LO_BASE = "https://download.documentfoundation.org/libreoffice/stable/"

GF = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
MONT = "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/"
FONTS = {
    **{f"Montserrat-{p}.ttf": MONT + f"Montserrat-{p}.ttf" for p in (
        "Thin", "ExtraLight", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black",
        "Italic", "LightItalic", "MediumItalic", "SemiBoldItalic", "BoldItalic", "ExtraBoldItalic", "BlackItalic")},
    **{f"Poppins-{p}.ttf": GF + f"poppins/Poppins-{p}.ttf" for p in (
        "Thin", "ExtraLight", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black",
        "Italic", "LightItalic", "MediumItalic", "SemiBoldItalic", "BoldItalic")},
    **{f"Carlito-{p}.ttf": GF + f"carlito/Carlito-{p}.ttf" for p in ("Regular", "Bold", "Italic", "BoldItalic")},
}


def log(msg: str):
    print(f"\n=== {msg}", flush=True)


def baixar(url: str, destino: Path):
    print("baixando", url, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "montador-build"})
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r, open(destino, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            return
        except OSError as e:
            print("  falhou:", e, flush=True)
            if tentativa == 3:
                raise
            import time
            time.sleep(5 * (tentativa + 1))


def fontes():
    log("fontes")
    FONTES.mkdir(exist_ok=True)
    for nome, url in FONTS.items():
        alvo = FONTES / nome
        if not alvo.is_file() or alvo.stat().st_size < 10000:
            baixar(url, alvo)
    for lic, url in (("OFL-Montserrat.txt", "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/OFL.txt"),
                     ("OFL-Poppins.txt", GF + "poppins/OFL.txt"), ("OFL-Carlito.txt", GF + "carlito/OFL.txt")):
        if not (FONTES / lic).is_file():
            baixar(url, FONTES / lic)


def versao_lo() -> str:
    with urllib.request.urlopen(urllib.request.Request(LO_BASE, headers={"User-Agent": "montador-build"}), timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    vs = sorted({v for v in re.findall(r'href="(\d+\.\d+\.\d+)/"', html)}, key=lambda v: tuple(map(int, v.split("."))))
    if not vs:
        raise SystemExit("não achei a versão do LibreOffice em " + LO_BASE)
    return vs[-1]


def _por_fontes(pasta_fontes: Path):
    pasta_fontes.mkdir(parents=True, exist_ok=True)
    for f in FONTES.glob("*.ttf"):
        shutil.copy2(f, pasta_fontes / f.name)


def libreoffice_mac():
    v = versao_lo()
    log(f"LibreOffice {v} (Mac, Apple Silicon)")
    with tempfile.TemporaryDirectory() as t:
        dmg = Path(t) / "lo.dmg"
        baixar(f"{LO_BASE}{v}/mac/aarch64/LibreOffice_{v}_MacOS_aarch64.dmg", dmg)
        ponto = Path(t) / "montado"
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(ponto), str(dmg)], check=True)
        try:
            alvo = BIN / "LibreOffice.app"
            if alvo.exists():
                shutil.rmtree(alvo)
            BIN.mkdir(exist_ok=True)
            subprocess.run(["ditto", str(ponto / "LibreOffice.app"), str(alvo)], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(ponto), "-force"])
    _por_fontes(alvo / "Contents" / "Resources" / "fonts" / "truetype")
    subprocess.run(["xattr", "-cr", str(alvo)])
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(alvo)], check=True)
    (BIN / "libreoffice-versao.txt").write_text(v)


def libreoffice_windows():
    v = versao_lo()
    log(f"LibreOffice {v} (Windows 64 bits)")
    with tempfile.TemporaryDirectory() as t:
        msi = Path(t) / "lo.msi"
        baixar(f"{LO_BASE}{v}/win/x86_64/LibreOffice_{v}_Win_x86-64.msi", msi)
        ext = Path(t) / "extraido"
        r = subprocess.run(["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={ext}"], capture_output=True, text=True)
        print("msiexec:", r.returncode, r.stdout[-300:], r.stderr[-300:])
        so = next(ext.rglob("soffice.exe"), None)
        if so is None:
            raise SystemExit("não achei o soffice.exe no LibreOffice extraído")
        raiz = so.parent.parent             # .../LibreOffice (com program/ e share/)
        alvo = BIN / "libreoffice"
        if alvo.exists():
            shutil.rmtree(alvo)
        BIN.mkdir(exist_ok=True)
        shutil.copytree(raiz, alvo)
    _por_fontes(alvo / "share" / "fonts" / "truetype")
    (BIN / "libreoffice-versao.txt").write_text(v)


def soffice() -> Path | None:
    for c in (BIN / "LibreOffice.app" / "Contents" / "MacOS" / "soffice", BIN / "libreoffice" / "program" / "soffice.exe"):
        if c.is_file():
            return c
    return None


def check() -> int:
    ok = True
    faltam = [n for n in FONTS if not (FONTES / n).is_file()]
    print(f"fontes       {'ok' if not faltam else 'FALTAM ' + ', '.join(faltam)} ({len(FONTS) - len(faltam)})")
    ok &= not faltam
    if IS_MAC or IS_WIN:
        so = soffice()
        if so:
            r = subprocess.run([str(so), "--headless", "--version"], capture_output=True, text=True, timeout=180)
            print(f"libreoffice  ok   {(r.stdout or r.stderr).strip().splitlines()[:1]}  ({so})")
        else:
            print("libreoffice  FALTA")
            ok = False
    return 0 if ok else 1


def main(args: list[str]) -> int:
    if args and args[0] == "check":
        return check()
    fontes()
    if IS_MAC:
        libreoffice_mac()
    elif IS_WIN:
        libreoffice_windows()
    else:
        print("Linux (testes): sem LibreOffice embutido; usa o do sistema")
    return check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
