"""Duração e tamanho de um vídeo MP4/MOV lendo só o cabeçalho (sem ffprobe).

Lê a caixa "moov" (mvhd = duração; tkhd = largura e altura de cada trilha). Funciona com o
moov no começo ou no fim do arquivo.

MP4 fragmentado (o OBS grava assim): o moov não traz a duração útil. Ela sai dos fragmentos
(moof → traf → tfdt + trun): onde começa o último fragmento + quanto ele dura. Só o fim do arquivo é
lido; se não der, os fragmentos são percorridos do começo.

`duracao()` junta tudo, na ordem: cabeçalho → fragmentos → afinfo (Mac) → ffprobe. Para outros
formatos (mkv), só afinfo/ffprobe.
"""
from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

_TAIL = (8 << 20, 64 << 20)          # quanto do fim do arquivo procurar o último fragmento (8 MB, depois 64 MB)


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


def _ler(f, a: int, b: int, maximo: int = 4096) -> bytes:
    f.seek(a)
    return f.read(min(b - a, maximo))


def info(caminho: str | Path) -> dict | None:
    """{"duracao": segundos, "largura": px, "altura": px} ou None."""
    p = Path(caminho)
    try:
        tamanho = p.stat().st_size
        with open(p, "rb") as f:
            for tipo, ini, fim in _boxes(f, 0, tamanho):
                if tipo == b"moov":
                    out = _moov(f, ini, fim)
                    if not out["duracao"] and out["_frag"]:
                        out["duracao"] = _duracao_fragmentos(f, tamanho, out["_trilhas"], out["_trex"])
                    out.pop("_frag"), out.pop("_trilhas"), out.pop("_trex")
                    return out if out["duracao"] else None
    except (OSError, struct.error):
        return None
    return None


def _moov(f, ini: int, fim: int) -> dict:
    out = {"duracao": None, "largura": 0, "altura": 0, "_frag": False, "_trilhas": {}, "_trex": {}}
    escala_mv, mehd = 0, None
    for tipo, a, b in _boxes(f, ini, fim):
        if tipo == b"mvex":                      # MP4 fragmentado
            out["_frag"] = True
            for t2, a2, b2 in _boxes(f, a, b):
                d = _ler(f, a2, b2, 32)
                if t2 == b"mehd" and len(d) >= 8:
                    mehd = struct.unpack(">Q", d[4:12])[0] if d[0] == 1 and len(d) >= 12 else struct.unpack(">I", d[4:8])[0]
                elif t2 == b"trex" and len(d) >= 16:
                    tid, _desc, dur = struct.unpack(">III", d[4:16])
                    out["_trex"][tid] = dur
        elif tipo == b"mvhd":
            d = _ler(f, a, b, 32)
            if d[0] == 1:
                escala, dur = struct.unpack(">IQ", d[20:32])
            else:
                escala, dur = struct.unpack(">II", d[12:20])
            if escala:
                escala_mv = escala
                out["duracao"] = dur / escala if dur else None
        elif tipo == b"trak":
            _trak(f, a, b, out)
    if not out["duracao"] and mehd and escala_mv:
        out["duracao"] = mehd / escala_mv
    return out


def _trak(f, a: int, b: int, out: dict):
    tid, escala, handler = None, 0, b""
    for t2, a2, b2 in _boxes(f, a, b):
        if t2 == b"tkhd":
            d = _ler(f, a2, b2, 128)
            if len(d) >= 24:
                tid = struct.unpack(">I", d[20:24] if d[0] == 1 else d[12:16])[0]
            if len(d) >= 8:
                w, h = struct.unpack(">II", d[-8:])
                w, h = w >> 16, h >> 16
                if w * h > out["largura"] * out["altura"]:
                    out["largura"], out["altura"] = w, h
        elif t2 == b"mdia":
            for t3, a3, b3 in _boxes(f, a2, b2):
                d = _ler(f, a3, b3, 32)
                if t3 == b"mdhd" and len(d) >= (24 if d[:1] == b"\x01" else 16):
                    escala = struct.unpack(">I", d[20:24] if d[0] == 1 else d[12:16])[0]
                elif t3 == b"hdlr" and len(d) >= 12:
                    handler = d[8:12]
    if tid is not None and escala:
        out["_trilhas"][tid] = {"escala": escala, "video": handler == b"vide"}


def _moof(f, a: int, b: int, trex: dict) -> list[tuple[int, int | None, int]]:
    """[(trilha, início do fragmento ou None, duração)] — tudo na escala da trilha."""
    out = []
    for t, ta, tb in _boxes(f, a, b):
        if t != b"traf":
            continue
        tid, padrao, ini, dur = None, None, None, 0
        for t2, a2, b2 in _boxes(f, ta, tb):
            if t2 == b"tfhd":
                d = _ler(f, a2, b2, 64)
                flags = int.from_bytes(d[1:4], "big")
                tid = struct.unpack(">I", d[4:8])[0]
                pos = 8 + (8 if flags & 0x01 else 0) + (4 if flags & 0x02 else 0)
                if flags & 0x08:
                    padrao = struct.unpack(">I", d[pos:pos + 4])[0]
            elif t2 == b"tfdt":
                d = _ler(f, a2, b2, 16)
                ini = struct.unpack(">Q", d[4:12])[0] if d[0] == 1 else struct.unpack(">I", d[4:8])[0]
            elif t2 == b"trun":
                d = _ler(f, a2, b2, 16 << 20)
                flags = int.from_bytes(d[1:4], "big")
                n = struct.unpack(">I", d[4:8])[0]
                pos = 8 + (4 if flags & 0x01 else 0) + (4 if flags & 0x04 else 0)
                if flags & 0x100:
                    passo = 4 * sum(1 for bit in (0x100, 0x200, 0x400, 0x800) if flags & bit)
                    for k in range(n):
                        p = pos + k * passo
                        if p + 4 > len(d):
                            break
                        dur += struct.unpack(">I", d[p:p + 4])[0]
                else:
                    dur += n * (padrao if padrao is not None else trex.get(tid, 0))
        if tid is not None:
            out.append((tid, ini, dur))
    return out


def _duracao_fragmentos(f, tamanho: int, trilhas: dict, trex: dict) -> float | None:
    if not trilhas:
        return None

    def em_segundos(fim_por_trilha: dict) -> float | None:
        vals = {t: v / trilhas[t]["escala"] for t, v in fim_por_trilha.items() if t in trilhas and v}
        if not vals:
            return None
        video = [v for t, v in vals.items() if trilhas[t]["video"]]
        return max(video) if video else max(vals.values())

    # 1) só o fim do arquivo: o último moof de cada trilha, com tfdt (onde ele começa)
    for tail in _TAIL:
        ini = max(0, tamanho - tail)
        f.seek(ini)
        bloco = f.read(tamanho - ini)
        fins: dict = {}
        pos = len(bloco)
        while True:
            pos = bloco.rfind(b"moof", 0, pos)
            if pos < 4:
                break
            tam = struct.unpack(">I", bloco[pos - 4:pos])[0]
            abs_ini = ini + pos - 4
            if 16 <= tam <= 64 << 20 and abs_ini + tam <= tamanho and bloco[pos + 8:pos + 12] == b"mfhd":
                frags = _moof(f, abs_ini + 8, abs_ini + tam, trex)
                for tid, comeco, dur in frags:
                    if comeco is not None and tid not in fins:
                        fins[tid] = comeco + dur
                if fins and all(t in fins for t in trilhas):
                    break
            pos -= 1
        if fins:
            return em_segundos(fins)
        if ini == 0:
            break
    # 2) sem tfdt: soma todos os fragmentos, do começo
    somas: dict = {}
    for tipo, a, b in _boxes(f, 0, tamanho):
        if tipo == b"moof":
            for tid, comeco, dur in _moof(f, a, b, trex):
                somas[tid] = (comeco + dur) if comeco is not None else somas.get(tid, 0) + dur
    return em_segundos(somas)


def afinfo(caminho: str | Path) -> float | None:
    """Duração pelo afinfo, que já vem no macOS."""
    if sys.platform != "darwin" or not Path("/usr/bin/afinfo").is_file():
        return None
    try:
        r = subprocess.run(["/usr/bin/afinfo", str(caminho)], capture_output=True, text=True, timeout=30)
        m = re.search(r"estimated duration:\s*([\d.]+)", r.stdout)
        return float(m.group(1)) if m and float(m.group(1)) > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ffprobe(caminho: str | Path) -> float | None:
    """Duração pelo ffprobe, se estiver instalado (último recurso)."""
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


def duracao(caminho: str | Path, inf: dict | None = None) -> tuple[float | None, str]:
    """(segundos, de onde veio). Cabeçalho/fragmentos → afinfo (Mac) → ffprobe. (None, "") se nada achar."""
    inf = info(caminho) if inf is None else inf
    if inf and inf.get("duracao"):
        return float(inf["duracao"]), "cabeçalho"
    for nome, fn in (("afinfo", afinfo), ("ffprobe", ffprobe)):
        d = fn(caminho)
        if d:
            return d, nome
    return None, ""
