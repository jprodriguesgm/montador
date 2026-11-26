"""XML da sequência master do Premiere (Final Cut Pro XML): onde cada vídeo do dia começa nela.

Quando o editor cola os vídeos do dia numa sequência e transcreve a sequência no Premiere, a transcrição
sai no tempo da sequência. O XML exportado dessa sequência diz o início real de cada vídeo (aguenta espaço
entre eles, ordem diferente da dos nomes, vídeo de fora e vídeo cortado no começo).

Devolve a mesma "tabela" do SRT único: vídeo, separador (onde o clipe começa na sequência) e fala (onde
ficaria o 0:00 do vídeo), que `dia.dividir_unico` já sabe usar.
"""
from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import unquote

TICKS = 254016000000        # "pproTicks" por segundo


class ErroXML(Exception):
    pass


def _n(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").strip().lower()


def _base(nome: str) -> str:
    nome = unquote(nome or "")
    nome = PureWindowsPath(nome).name if "\\" in nome else PurePosixPath(nome).name
    return nome.rsplit(".", 1)[0] if "." in nome else nome


def _fps(rate) -> float | None:
    if rate is None:
        return None
    try:
        tb = float(rate.findtext("timebase") or 0)
    except ValueError:
        return None
    if not tb:
        return None
    ntsc = (rate.findtext("ntsc") or "").strip().upper() == "TRUE"
    return tb * 1000 / 1001 if ntsc else tb


def _int(el, tag: str) -> int | None:
    try:
        return int(float(el.findtext(tag)))
    except (TypeError, ValueError):
        return None


def ler(texto: str, videos: list[str]) -> dict:
    """{"tabela": [...], "sequencia": nome, "fora": [clipes que não são vídeos do dia], "faltam": [vídeos do dia
    que não estão na sequência]}. Levanta ErroXML se não for um XML do Premiere ou não tiver vídeo do dia."""
    try:
        raiz = ET.fromstring(texto.encode("utf-8") if isinstance(texto, str) else texto)
    except ET.ParseError:
        raise ErroXML("o arquivo não é um XML válido")
    if raiz.tag != "xmeml":
        raise ErroXML("não é um XML do Premiere (Final Cut Pro XML)")
    alvo = {_n(v): v for v in videos}
    melhor = None
    for seq in raiz.iter("sequence"):
        r = _sequencia(seq, alvo)
        if r and (melhor is None or len(r["tabela"]) > len(melhor["tabela"])):
            melhor = r
    if not melhor or not melhor["tabela"]:
        raise ErroXML("nenhum vídeo desta pasta do dia aparece nas sequências do XML")
    usados = {r["video"] for r in melhor["tabela"]}
    if len(usados) < 2 and len(videos) > 1:
        raise ErroXML("a sequência deste XML tem só um vídeo do dia — exporte o XML da sequência master "
                      "(a que tem todos os vídeos colados)")
    melhor["faltam"] = [v for v in videos if v not in usados]
    return melhor


def _sequencia(seq, alvo: dict) -> dict | None:
    fps_seq = _fps(seq.find("rate"))
    media = seq.find("media")
    if media is None or not fps_seq:
        return None
    nomes_arquivo: dict[str, str] = {}
    for f in seq.iter("file"):
        fid = f.get("id")
        nome = f.findtext("name") or _base(f.findtext("pathurl") or "")
        if fid and nome and fid not in nomes_arquivo:
            nomes_arquivo[fid] = nome
    candidatas = []
    for grupo in ("video", "audio"):
        g = media.find(grupo)
        if g is None:
            continue
        for trilha in g.findall("track"):
            linhas, fora = [], []
            for c in trilha.findall("clipitem"):
                if (c.findtext("enabled") or "TRUE").strip().upper() == "FALSE":
                    continue
                f = c.find("file")
                nome = ""
                if f is not None:
                    nome = f.findtext("name") or _base(f.findtext("pathurl") or "") or nomes_arquivo.get(f.get("id") or "", "")
                nome = _base(nome) or _base(c.findtext("name") or "")
                video = alvo.get(_n(nome))
                fps = _fps(c.find("rate")) or fps_seq
                ini, fim, entra, sai = (_int(c, t) for t in ("start", "end", "in", "out"))
                if ini is None or fim is None or entra is None:
                    continue
                if ini < 0 and sai is not None:          # começo encoberto por transição
                    ini = fim - (sai - entra)
                ticks = c.findtext("pproTicksIn")
                try:
                    entra_s = int(ticks) / TICKS if ticks else entra / fps
                except ValueError:
                    entra_s = entra / fps
                ini_s = ini / fps_seq
                if video:
                    linhas.append({"video": video, "separador": round(ini_s, 3), "fala": round(ini_s - entra_s, 3),
                                   "fim": round(fim / fps_seq, 3)})
                elif nome:
                    fora.append(nome)
            if linhas:
                candidatas.append({"tabela": sorted(linhas, key=lambda r: r["separador"]), "fora": fora,
                                   "sequencia": seq.findtext("name") or ""})
        if candidatas:
            break                                # vídeo tem prioridade sobre áudio
    return max(candidatas, key=lambda r: len(r["tabela"])) if candidatas else None
