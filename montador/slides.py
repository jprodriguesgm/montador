"""Slides do professor (.pptx): texto de cada slide e conversão em JPEG 1920x1080.

Conversão, nesta ordem:
  1. imagens já prontas em Originais/<nome do pptx>/ (feitas pelo editor ou numa rodada anterior);
  2. LibreOffice -> PDF -> JPEG (pdftoppm, ou PyMuPDF se estiver instalado);
  3. no Mac sem LibreOffice: Keynote (exporta as imagens) -> JPEG.
As imagens ficam em Originais/<nome do pptx>/<nome do pptx>.001.jpg, .002.jpg ...
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

LARG, ALT, QUALIDADE = 1920, 1080, 95
_IMAGENS = (".jpg", ".jpeg", ".png")
_CODIGO = re.compile(r"^\s*(C\d{1,4})\s*$", re.I)
_CODIGO_NOTA = re.compile(r"^\s*(C\d{1,4})\b", re.I)
_SEGUNDOS = re.compile(r"exibir\s+por\s+(\d+)(?:\s*(?:a|-|–)\s*(\d+))?\s*segundo", re.I)


class ErroSlides(Exception):
    pass


_ULTIMO_ERRO: dict = {}


# ------------------------------------------------------------------ texto

def _textos_xml(xml: str) -> list[str]:
    """Um texto por caixa (parágrafos juntos com quebra de linha)."""
    out = []
    for caixa in re.findall(r"<p:txBody>(.*?)</p:txBody>", xml, re.S):
        pars = []
        for p in re.findall(r"<a:p(?:\s[^>]*)?>(.*?)</a:p>", caixa, re.S):
            pars.append(html.unescape("".join(re.findall(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>", p))))
        txt = "\n".join(x for x in pars if x.strip())
        if txt.strip():
            out.append(txt.strip())
    return out


def ler(pptx: str | Path) -> list[dict]:
    """[{n, titulo, textos, codigo, notas, segundos, referencias}] na ordem dos slides."""
    pptx = Path(pptx)
    try:
        z = zipfile.ZipFile(pptx)
    except (OSError, zipfile.BadZipFile):
        raise ErroSlides(f"não consegui abrir {pptx.name}")
    with z:
        nomes = set(z.namelist())
        rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8", "replace")
        alvo = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
        alvo.update({a: b for b, a in re.findall(r'Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
        pres = z.read("ppt/presentation.xml").decode("utf-8", "replace")
        ordem = [alvo.get(r) for r in re.findall(r'<p:sldId [^>]*r:id="([^"]+)"', pres)]
        out = []
        for n, rel in enumerate([x for x in ordem if x], 1):
            arq = "ppt/" + rel.lstrip("/").replace("../", "")
            if arq not in nomes:
                continue
            textos = _textos_xml(z.read(arq).decode("utf-8", "replace"))
            notas = ""
            srels = f"ppt/slides/_rels/{Path(arq).name}.rels"
            if srels in nomes:
                m = re.search(r'Target="\.\./notesSlides/([^"]+)"', z.read(srels).decode("utf-8", "replace"))
                if m and f"ppt/notesSlides/{m.group(1)}" in nomes:
                    nt = _textos_xml(z.read(f"ppt/notesSlides/{m.group(1)}").decode("utf-8", "replace"))
                    notas = "\n".join(t for t in nt if not re.fullmatch(r"\d+", t.strip()))
            codigo = next((_CODIGO.match(t).group(1).upper() for t in textos if _CODIGO.match(t)), None)
            if not codigo and _CODIGO_NOTA.match(notas):
                codigo = _CODIGO_NOTA.match(notas).group(1).upper()
            seg = _SEGUNDOS.search(notas)
            visiveis = [t for t in textos if not _CODIGO.match(t) and not t.lower().startswith("fonte")]
            titulo = visiveis[0].split("\n")[0] if visiveis else ""
            out.append({"n": n, "titulo": titulo, "textos": visiveis, "codigo": codigo, "notas": notas,
                        "segundos": float(seg.group(2) or seg.group(1)) if seg else None,
                        "referencias": bool(re.match(r"^\s*refer[eê]ncias", titulo, re.I))})
        return out


# ------------------------------------------------------------------ conversão

def _acha(nomes: list[str], extras: list[str]) -> str | None:
    for n in nomes:
        w = shutil.which(n)
        if w:
            return w
    return next((e for e in extras if Path(e).exists()), None)


def soffice(cfg: dict | None = None) -> str | None:
    p = (cfg or {}).get("libreoffice")
    if p and Path(p).exists():
        return p
    return _acha(["soffice", "libreoffice"], [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),   # instalado sem senha de administrador
        str(Path.home() / "Downloads/LibreOffice.app/Contents/MacOS/soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ])


def pasta_imagens(pptx: str | Path) -> Path:
    pptx = Path(pptx)
    return pptx.parent / pptx.stem


def imagens(pptx: str | Path) -> dict[int, str]:
    """{número do slide: imagem} já prontas em Originais/<nome>/ (aceita 001.png, Slide1.PNG, nome.003.jpg...)."""
    pasta = pasta_imagens(pptx)
    if not pasta.is_dir():
        return {}
    out = {}
    for f in sorted(pasta.iterdir()):
        if f.suffix.lower() in _IMAGENS and not f.name.startswith("."):
            m = re.search(r"(\d+)$", f.stem)
            if m:
                n = int(m.group(1))
                if n not in out or f.suffix.lower() in (".jpg", ".jpeg"):
                    out[n] = str(f)
    return out


def _sem_fontes(src: Path, dst: Path):
    """Cópia do pptx sem fontes embutidas (o LibreOffice do Mac se confunde com elas e troca a fonte)."""
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            if it.filename.startswith("ppt/fonts/"):
                continue
            d = zi.read(it.filename)
            if it.filename == "ppt/presentation.xml":
                d = re.sub(rb"<p:embeddedFontLst>.*?</p:embeddedFontLst>", b"", d, flags=re.S)
            elif it.filename == "ppt/_rels/presentation.xml.rels":
                d = re.sub(rb'<Relationship [^>]*Target="fonts/[^>]*/>', b"", d)
            elif it.filename == "[Content_Types].xml":
                d = re.sub(rb'<Default Extension="fntdata"[^>]*/>', b"", d)
            zo.writestr(it, d)


def _jpeg(origem: Path, destino: Path):
    from PIL import Image
    with Image.open(origem) as im:
        im = im.convert("RGB")
        if im.size != (LARG, ALT):
            im = im.resize((LARG, ALT), Image.LANCZOS)
        im.save(destino, "JPEG", quality=QUALIDADE, subsampling=0)


def _pdf_para_jpeg(pdf: Path, tmp: Path) -> list[Path]:
    exe = _acha(["pdftoppm"], ["/opt/homebrew/bin/pdftoppm", "/usr/local/bin/pdftoppm"])
    if exe:
        subprocess.run([exe, "-png", "-r", "200", str(pdf), str(tmp / "p")], capture_output=True, timeout=900)
        return sorted(tmp.glob("p*.png"), key=lambda f: int(re.search(r"(\d+)$", f.stem).group(1)))
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    out = []
    with fitz.open(str(pdf)) as doc:
        for i, pg in enumerate(doc, 1):
            z = LARG / pg.rect.width
            f = tmp / f"p-{i}.png"
            pg.get_pixmap(matrix=fitz.Matrix(z, z)).save(str(f))
            out.append(f)
    return out


def _keynote(pptx: Path, tmp: Path) -> list[Path]:
    if sys.platform != "darwin" or not Path("/Applications/Keynote.app").exists():
        return []
    script = Path(__file__).with_name("keynote_exportar.applescript")
    saida = tmp / "keynote"
    r = subprocess.run(["osascript", str(script), str(pptx), str(saida)], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        _ULTIMO_ERRO["keynote"] = (r.stderr or "").strip()[-200:]
        return []
    fs = [f for f in saida.iterdir() if f.suffix.lower() in _IMAGENS] if saida.is_dir() else []
    return sorted(fs, key=lambda f: int((re.search(r"(\d+)$", f.stem) or re.search(r"(\d+)", "0")).group(1)))


def converter(pptx: str | Path, cfg: dict | None = None) -> dict:
    """Garante as imagens do pptx. {"pasta", "imagens": {n: caminho}, "metodo"}."""
    pptx = Path(pptx)
    prontas = imagens(pptx)
    if prontas and all(Path(p).stat().st_mtime >= pptx.stat().st_mtime for p in prontas.values()):
        return {"pasta": str(pasta_imagens(pptx)), "imagens": prontas, "metodo": "imagens prontas"}
    with tempfile.TemporaryDirectory(prefix="montador_slides_") as t:
        tmp = Path(t)
        paginas, metodo = [], ""
        exe = soffice(cfg)
        if exe:
            limpo = tmp / (pptx.stem + ".pptx")
            try:
                _sem_fontes(pptx, limpo)
            except (OSError, zipfile.BadZipFile):
                shutil.copy(pptx, limpo)
            perfil = (tmp / "perfil").as_uri()
            subprocess.run([exe, "--headless", f"-env:UserInstallation={perfil}", "--convert-to", "pdf",
                            "--outdir", str(tmp), str(limpo)], capture_output=True, timeout=900)
            pdf = tmp / (pptx.stem + ".pdf")
            if pdf.is_file():
                (tmp / "pg").mkdir()
                paginas = _pdf_para_jpeg(pdf, tmp / "pg")
                metodo = "LibreOffice"
        if not paginas:
            paginas = _keynote(pptx, tmp)
            metodo = "Keynote" if paginas else metodo
        if not paginas:
            if prontas:
                return {"pasta": str(pasta_imagens(pptx)), "imagens": prontas, "metodo": "imagens prontas (antigas)"}
            kn = _ULTIMO_ERRO.pop("keynote", "")
            raise ErroSlides("não consegui converter os slides: o LibreOffice não foi encontrado"
                             + (f" e o Keynote recusou ({kn})" if kn else "")
                             + ". Exporte os slides como JPEG em Originais/" + pptx.stem
                             + " ou instale o LibreOffice (libreoffice.org) até sair a versão empacotada")
        pasta = pasta_imagens(pptx)
        pasta.mkdir(exist_ok=True)
        out = {}
        for i, f in enumerate(paginas, 1):
            alvo = pasta / f"{pptx.stem}.{i:03d}.jpg"
            _jpeg(f, alvo)
            out[i] = str(alvo)
    return {"pasta": str(pasta), "imagens": out, "metodo": metodo}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")
