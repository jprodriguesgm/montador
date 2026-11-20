"""Leitura e escrita de legendas SRT (transcrições e retorno da Skoopia)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TEMPO = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


@dataclass
class Cue:
    n: int          # número da legenda no arquivo (a Skoopia cita "cue-000123")
    ini: float      # segundos
    fim: float
    texto: str


def tempo(s: str) -> float:
    m = _TEMPO.search(s)
    if not m:
        raise ValueError(f"tempo inválido: {s!r}")
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")[:3]) / 1000


def fmt(seg: float) -> str:
    ms = int(round(max(0.0, seg) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ler_texto(conteudo: str) -> list[Cue]:
    conteudo = conteudo.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for bloco in re.split(r"\n\s*\n", conteudo.strip()):
        linhas = [l for l in bloco.strip().split("\n")]
        if not linhas:
            continue
        i = 0
        num = None
        if "-->" not in linhas[0]:
            try:
                num = int(linhas[0].strip())
            except ValueError:
                num = None
            i = 1
        if i >= len(linhas) or "-->" not in linhas[i]:
            continue
        a, b = linhas[i].split("-->", 1)
        try:
            ini, fim = tempo(a), tempo(b)
        except ValueError:
            continue
        texto = "\n".join(linhas[i + 1:]).strip()
        cues.append(Cue(num if num is not None else len(cues) + 1, ini, max(ini, fim), texto))
    return cues


def ler(caminho: str | Path) -> list[Cue]:
    dados = Path(caminho).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return ler_texto(dados.decode(enc))
        except UnicodeDecodeError:
            continue
    return ler_texto(dados.decode("utf-8", errors="replace"))


def escrever(caminho: str | Path, cues: list[Cue]) -> None:
    linhas = []
    for k, c in enumerate(cues, 1):
        linhas += [str(k), f"{fmt(c.ini)} --> {fmt(c.fim)}", c.texto, ""]
    Path(caminho).write_text("\n".join(linhas), encoding="utf-8")


SEPARADOR = re.compile(r"^\[ARQUIVO:\s*(.+?)\s*\]$")


def separadores(cues: list[Cue]) -> list[tuple[str, float]]:
    """No SRT único: (nome do vídeo, tempo do separador) de cada [ARQUIVO: ...]."""
    out = []
    for c in cues:
        m = SEPARADOR.match(c.texto.strip())
        if m:
            out.append((m.group(1), c.ini))
    return out
