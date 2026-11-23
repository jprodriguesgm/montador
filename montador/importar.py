"""Importar transcrições à mão (quando elas não estão na Footage).

Aceita arquivos soltos (o conteúdo vem da janela, arrastado ou escolhido) ou uma pasta (caminho).
Cada arquivo é reconhecido pelo conteúdo e pelo nome:
  - SRT único do dia: tem separadores [ARQUIVO: ...];
  - tabela do SRT único: linhas "vídeo<TAB>tempo<TAB>tempo";
  - transcrição de um vídeo: o nome do arquivo contém o nome do vídeo (ex.: "2026-10-08 13-17-17.srt");
  - retorno da Skoopia ([ERRO]/[BASTIDORES]): reconhecido, mas só é usado na etapa 2.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from . import dia, srt

_SKOOPIA = re.compile(r"\[(ERRO|BASTIDORES)\]", re.I)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower()


def _decodifica(dados: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", errors="replace")


def _tabela_texto(texto: str) -> list[dict]:
    out = []
    for linha in texto.splitlines():
        partes = linha.split("\t")
        if len(partes) >= 3:
            try:
                out.append({"video": partes[0].strip(), "separador": srt.tempo(partes[1]), "fala": srt.tempo(partes[2])})
            except ValueError:
                continue
    return out


def classificar(arquivos: list[dict], videos: list[str], info: list[dict] | None = None) -> dict:
    """arquivos: [{"nome": "x.srt", "conteudo": "..."}]. Devolve o que foi reconhecido.

    `info` (os vídeos com a duração) permite reconhecer a transcrição master do Premiere: todos os vídeos
    do dia colados numa sequência, sem separadores."""
    master = False
    por_video: dict[str, list[srt.Cue]] = {}
    unico: list[srt.Cue] | None = None
    tabela: list[dict] = []
    skoopia, ignorados = [], []
    nomes_norm = sorted(((_norm(v), v) for v in videos), key=lambda x: -len(x[0]))
    for a in arquivos:
        nome, texto = a.get("nome") or "", a.get("conteudo") or ""
        if nome.lower().endswith(".txt"):
            t = _tabela_texto(texto)
            if t:
                tabela = t
            else:
                ignorados.append(nome)
            continue
        cues = srt.ler_texto(texto)
        if not cues:
            ignorados.append(nome)
            continue
        if _SKOOPIA.search(texto) and not srt.separadores(cues):
            skoopia.append(nome)
            continue
        if srt.separadores(cues):
            unico = cues
            continue
        alvo = next((orig for n, orig in nomes_norm if n in _norm(nome)), None)
        if alvo:
            por_video[alvo] = [c for c in cues if not srt.SEPARADOR.match(c.texto.strip())]
        elif info and dia.eh_master(cues, info) and dia.tabela_colada(info):
            unico, master = cues, True
            tabela = dia.tabela_colada(info)
        else:
            ignorados.append(nome)
    if unico is not None:
        if not tabela:
            tabela = [{"video": n, "separador": t, "fala": t + 2.0} for n, t in srt.separadores(unico)]
        for k, v in dia.dividir_unico(unico, tabela).items():
            if k in videos and k not in por_video:
                por_video[k] = v
    return {"por_video": por_video, "unico": unico is not None, "tabela": tabela, "skoopia": skoopia,
            "ignorados": ignorados, "master": master}


def ler_pasta(pasta: str | Path, limite: int = 400) -> list[dict]:
    """Lê os .srt e .txt de uma pasta (e subpastas) para `classificar`."""
    out = []
    for raiz, pastas, nomes in os.walk(pasta):
        pastas[:] = [d for d in pastas if not d.startswith(".")]
        for n in sorted(nomes):
            if n.startswith(".") or not n.lower().endswith((".srt", ".txt")):
                continue
            p = Path(raiz) / n
            try:
                if p.stat().st_size > 5_000_000:
                    continue
                out.append({"nome": n, "conteudo": _decodifica(p.read_bytes())})
            except OSError:
                continue
            if len(out) >= limite:
                return out
    return out


def procurar_por_nome(pasta: str | Path, videos: list[str], limite: int = 20000) -> dict[str, str]:
    """Na pasta de transcrições das Configurações: acha o .srt de cada vídeo pelo nome."""
    achados: dict[str, str] = {}
    nomes_norm = sorted(((_norm(v), v) for v in videos), key=lambda x: -len(x[0]))
    vistos = 0
    for raiz, pastas, nomes in os.walk(pasta):
        pastas[:] = [d for d in pastas if not d.startswith(".")]
        for n in nomes:
            vistos += 1
            if not n.lower().endswith(".srt") or n.startswith("."):
                continue
            alvo = next((orig for nn, orig in nomes_norm if nn in _norm(n)), None)
            if alvo and alvo not in achados:
                achados[alvo] = str(Path(raiz) / n)
        if len(achados) == len(videos) or vistos > limite:
            break
    return achados
