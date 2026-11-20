"""MP4 mínimo (só o cabeçalho: ftyp + moov com mvhd e tkhd) para os testes rodarem sem ffmpeg."""
import struct
from pathlib import Path


def _box(tipo: bytes, dados: bytes) -> bytes:
    return struct.pack(">I", 8 + len(dados)) + tipo + dados


def mp4_falso(caminho: Path, duracao: float, largura: int = 64, altura: int = 18, escala: int = 1000):
    mvhd = _box(b"mvhd", bytes(4) + struct.pack(">IIII", 0, 0, escala, round(duracao * escala)) + bytes(80))
    tkhd = _box(b"tkhd", bytes([0, 0, 0, 3]) + struct.pack(">IIII", 0, 0, 1, 0) + struct.pack(">I", round(duracao * 1000))
                + bytes(8) + bytes(8) + bytes(36) + struct.pack(">II", largura << 16, altura << 16))
    trak = _box(b"trak", tkhd)
    moov = _box(b"moov", mvhd + trak)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    Path(caminho).write_bytes(ftyp + moov)
