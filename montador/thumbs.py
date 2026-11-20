"""Thumbs das aulas, no padrão do "Gerador de Thumbnail" da equipe (index.html do colega).

O Montador não leva a fonte (Cronos Pro) nem as artes: lê tudo do index.html do gerador, apontado nas
Configurações — a fonte é licenciada e não pode ir para o repositório público. Daquele arquivo saem:
  - a fonte (@font-face, embutida no HTML);
  - os modelos (Default, Libras...) com a arte de fundo e a área do título de cada um (--w-area, --h-area,
    --translate-w, --translate-h, --font-max).
A tela desenha cada thumb como o gerador (mesma conta de tamanho da letra) e exporta PNG 1920x1080;
aqui só se gravam os arquivos.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from pathlib import Path

_cache: dict = {}

PADRAO_AREA = {"w": "84%", "h": "40%", "tw": "0%", "th": "-10%", "font_max": "90px", "font_min": "1rem"}


def _id(label: str) -> str:
    t = unicodedata.normalize("NFD", label or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()
    t = re.sub(r"[^a-z0-9\s-]", "", t)
    return re.sub(r"[\s-]+", "-", t).strip("-")


def _vars(bloco: str) -> dict:
    out = {}
    for k, chave in (("--w-area", "w"), ("--h-area", "h"), ("--translate-w", "tw"), ("--translate-h", "th"),
                     ("--font-max", "font_max"), ("--font-min", "font_min")):
        m = re.search(re.escape(k) + r"\s*:\s*([^;]+);", bloco)
        if m:
            out[chave] = m.group(1).strip()
    return out


def _regra(css: str, seletor: str) -> str:
    m = re.search(r"(?:^|\})\s*" + re.escape(seletor) + r"\s*\{([^{}]*)\}", css)
    return m.group(1) if m else ""


class ErroThumb(Exception):
    pass


def ler_modelo(html_path: str | Path) -> dict:
    """{fonte_css, familia, opcoes: [{id, label, img, padrao, area}]} lidos do index.html do gerador."""
    p = Path(html_path or "")
    if not p.is_file():
        raise ErroThumb("Aponte o gerador de thumbnail (index.html) em Configurações → Thumbs.")
    chave = (str(p), p.stat().st_mtime)
    if _cache.get("chave") == chave:
        return _cache["modelo"]
    s = p.read_text(encoding="utf-8", errors="replace")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", s, re.S))
    fontes = re.findall(r"@font-face\s*\{.*?\}", css, re.S)
    familia = None
    m = re.search(r"--font-family-thumbnail\s*:\s*([^;]+);", css)
    if m:
        familia = m.group(1).strip().split(",")[0].strip().strip("'\"")
    imgs = dict(re.findall(r'window\.base64\.(\w+)\s*=\s*"(data:image/[^"]+)"', s))
    raiz = _vars(_regra(css, ":root")) or {}
    area_base = {**PADRAO_AREA, **{k: v for k, v in raiz.items()}}
    opcoes = []
    for bloco in re.findall(r"\{[^{}]*?label\s*:\s*[\"'][^\"']+[\"'][^{}]*?\}", s):
        lab = re.search(r"label\s*:\s*[\"']([^\"']+)[\"']", bloco).group(1)
        im = re.search(r"img\s*:\s*window\.base64\.(\w+)", bloco)
        if not im or im.group(1) not in imgs:
            continue
        oid = _id(lab)
        area = {**area_base, **_vars(_regra(css, f".{oid}-container")), **{
            k: v for k, v in _vars(_regra(css, f".{oid}")).items() if k.startswith("font")}}
        opcoes.append({"id": oid, "label": lab, "img": imgs[im.group(1)], "padrao": bool(re.search(r"default\s*:\s*true", bloco)),
                       "area": area})
    if not opcoes:
        raise ErroThumb("Não achei os modelos de thumbnail nesse arquivo (é o index.html do gerador?).")
    if not any(o["padrao"] for o in opcoes):
        opcoes[0]["padrao"] = True
    modelo = {"fonte_css": "\n".join(fontes), "familia": familia or "sans-serif", "opcoes": opcoes,
              "arquivo": str(p)}
    _cache.update(chave=chave, modelo=modelo)
    return modelo


def nome_arquivo(nome: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", nome).strip().rstrip(".") or "thumb"


def salvar(pasta: str | Path, itens: list[dict]) -> list[str]:
    """Grava cada {nome, png (data URL)} como <pasta>/<nome>.png."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    out = []
    for it in itens:
        dados = it.get("png") or ""
        if "," in dados:
            dados = dados.split(",", 1)[1]
        alvo = pasta / (nome_arquivo(it.get("nome") or "thumb") + ".png")
        alvo.write_bytes(base64.b64decode(dados))
        out.append(str(alvo))
    return out
