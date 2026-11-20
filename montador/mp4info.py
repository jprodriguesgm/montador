"""Duração e tamanho de um vídeo MP4/MOV lendo só o cabeçalho (sem ffprobe).

Lê a caixa "moov" (mvhd = duração; tkhd = largura e altura de cada trilha). Funciona com o
moov no começo ou no fim do arquivo. Para outros formatos (mkv), devolve None.
"""
from __future__ import annotations

import struct
from pathlib import Path

_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta"}


def _boxes(f, inicio: int, fim: int):
    pos = inicio
    while pos + 8 <= fim:
        f.seek(pos)
        cab = f.read(8)
        if len(cab) < 8:
            return
        tam, tipo = struct.unpack(">I4s", cab)
        cab_len = 8
        if tam == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            tam = struct.unpack(">Q", ext)[0]
            cab_len = 16
        elif tam == 0:
            tam = fim - pos
        if tam < cab_len:
            return
        yield tipo, pos + cab_len, pos + tam
        pos += tam


def info(caminho: str | Path) -> dict | None:
    """{"duracao": segundos, "largura": px, "altura": px} ou None."""
    p = Path(caminho)
    try:
        tamanho = p.stat().st_size
        with open(p, "rb") as f:
            for tipo, ini, fim in _boxes(f, 0, tamanho):
                if tipo == b"moov":
                    return _moov(f, ini, fim)
    except OSError:
        return None
    return None


def _moov(f, ini: int, fim: int) -> dict | None:
    out = {"duracao": None, "largura": 0, "altura": 0}
    escala_mv, frag = 0, None
    for tipo, a, b in _boxes(f, ini, fim):
        if tipo == b"mvex":          # MP4 fragmentado (OBS): a duração fica em mvex/mehd
            for t2, a2, b2 in _boxes(f, a, b):
                if t2 == b"mehd":
                    f.seek(a2)
                    dados = f.read(min(b2 - a2, 12))
                    if len(dados) >= 8:
                        frag = struct.unpack(">Q", dados[4:12])[0] if dados[0] == 1 and len(dados) >= 12 \
                            else struct.unpack(">I", dados[4:8])[0]
        if tipo == b"mvhd":
            f.seek(a)
            dados = f.read(min(b - a, 32))
            versao = dados[0]
            if versao == 1:
                escala, dur = struct.unpack(">IQ", dados[20:32])
            else:
                escala, dur = struct.unpack(">II", dados[12:20])
            if escala:
                escala_mv = escala
                out["duracao"] = dur / escala
        elif tipo == b"trak":
            for t2, a2, b2 in _boxes(f, a, b):
                if t2 == b"tkhd":
                    f.seek(a2)
                    dados = f.read(b2 - a2)
                    if len(dados) >= 8:
                        w, h = struct.unpack(">II", dados[-8:])
                        w, h = w >> 16, h >> 16
                        if w * h > out["largura"] * out["altura"]:
                            out["largura"], out["altura"] = w, h
    if not out["duracao"] and frag and escala_mv:
        out["duracao"] = frag / escala_mv
    return out if out["duracao"] is not None else None


def ffprobe(caminho: str | Path) -> float | None:
    """Duração pelo ffprobe, se estiver instalado (último recurso)."""
    import shutil
    import subprocess
    exe = shutil.which("ffprobe") or next((x for x in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe")
                                            if Path(x).is_file()), None)
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(caminho)],
                           capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip()) or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
