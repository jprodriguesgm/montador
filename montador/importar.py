"""Importar transcrições à mão (quando elas não estão na Footage).

Aceita arquivos soltos (o conteúdo vem da janela, arrastado ou escolhido) ou uma pasta (caminho).
Cada arquivo é reconhecido pelo conteúdo e pelo nome:
  - SRT único do dia: tem separadores [ARQUIVO: ...];
  - tabela do SRT único: linhas "vídeo<TAB>tempo<TAB>tempo";
  - transcrição de um vídeo: o nome do arquivo contém o nome do vídeo (ex.: "2026-10-08 13-17-17.srt");
  - retorno da Skoopia ([ERRO]/[BASTIDORES]): reconhecido, mas só é usado na etapa 2;
  - transcrição master do Premiere (vídeos colados numa sequência): dividida pelo XML da sequência ou
    pela duração de cada vídeo;
  - XML da sequência master (.xml): onde cada vídeo começa na sequência.
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


def _parece_master(cues: list[srt.Cue], info: list[dict] | None) -> bool:
    """Passa do fim do vídeo mais longo (dos que têm duração) e não tem separadores: é de uma sequência."""
    durs = [v.get("duracao") or 0 for v in info or []]
    return bool(cues) and not srt.separadores(cues) and max(c.fim for c in cues) > max(durs, default=0) + 5


def _hms(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def tabela_master(cues: list[srt.Cue], info: list[dict] | None, xml: dict | None = None,
                  premiere: bool = False) -> tuple[list[dict] | None, str]:
    """Tabela para dividir uma transcrição feita sobre a sequência master do Premiere.

    (tabela, explicação) ou (None, motivo de não dar). Ordem: XML da sequência → durações (reconhecida
    sozinha) → durações porque o editor marcou "Transcrição feita no Premiere"."""
    if not cues or srt.separadores(cues):
        return None, ""
    fim = max(c.fim for c in cues)
    if xml and xml.get("tabela"):
        ultimo = max(r.get("fim") or r["separador"] for r in xml["tabela"])
        aviso = "" if fim <= ultimo + 30 else \
            f" — a transcrição vai até {_hms(fim)}, depois do fim da sequência ({_hms(ultimo)}): confira"
        return xml["tabela"], "dividida pelo XML da sequência" + aviso
    info = info or []
    colada = dia.tabela_colada(info) if info else None
    if colada and dia.eh_master(cues, info):
        return colada, "vídeos colados, divididos pela duração de cada um"
    if not premiere:
        return None, ""
    if len(info) < 2:
        return None, "a pasta do dia precisa de pelo menos 2 vídeos"
    sem = [v["nome"] for v in info if not v.get("duracao")]
    if sem:
        return None, ("não consegui ler a duração de " + ", ".join(sem)
                      + " — importe o XML da sequência master para dividir")
    soma = sum(float(v["duracao"]) for v in info)
    aviso = ""
    if fim > soma + 30:
        aviso = (f" — a transcrição vai até {_hms(fim)} e os vídeos somam {_hms(soma)}: talvez haja espaço entre"
                 " eles ou um vídeo de fora; o XML da sequência resolve")
    return colada, "vídeos colados na ordem dos nomes, divididos pela duração de cada um" + aviso


def classificar(arquivos: list[dict], videos: list[str], info: list[dict] | None = None,
                premiere: bool = False) -> dict:
    """arquivos: [{"nome": "x.srt", "conteudo": "..."}]. Devolve o que foi reconhecido.

    `info` (os vídeos com a duração) permite reconhecer a transcrição master do Premiere: todos os vídeos
    do dia colados numa sequência, sem separadores. `premiere` = o editor marcou "Transcrição feita no
    Premiere": a transcrição sem dono é dividida pela duração mesmo quando a conta não fecha certinho.
    Um .xml (Final Cut Pro XML da sequência master) dá o início real de cada vídeo."""
    from . import premiere as premiere_xml
    master = False
    por_video: dict[str, list[srt.Cue]] = {}
    unico: list[srt.Cue] | None = None
    tabela: list[dict] = []
    skoopia, ignorados = [], []
    motivos: dict[str, str] = {}
    soltos: dict[str, str] = {}             # transcrições sem dono que podem ser a master (texto)
    explicacao = ""
    xml = None
    nomes_norm = sorted(((_norm(v), v) for v in videos), key=lambda x: -len(x[0]))
    for a in arquivos:                                    # o XML primeiro: ele decide como dividir a master
        nome, texto = a.get("nome") or "", a.get("conteudo") or ""
        if nome.lower().endswith(".xml"):
            try:
                xml = premiere_xml.ler(texto, videos)
            except premiere_xml.ErroXML as e:
                ignorados.append(nome)
                motivos[nome] = str(e)
    for a in arquivos:
        nome, texto = a.get("nome") or "", a.get("conteudo") or ""
        if nome.lower().endswith(".xml"):
            continue
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
            continue
        tab, expl = tabela_master(cues, info, xml, premiere) if unico is None else (None, "")
        if tab:
            unico, master, tabela, explicacao = cues, True, tab, expl
            continue
        ignorados.append(nome)
        if expl:
            motivos[nome] = expl
        if _parece_master(cues, info):
            soltos[nome] = texto
            motivos.setdefault(nome, "parece a transcrição de uma sequência com todos os vídeos: marque "
                                     "\"Transcrição feita no Premiere\" ou importe o XML da sequência")
    if unico is not None:
        if not tabela:
            tabela = [{"video": n, "separador": t, "fala": t + 2.0} for n, t in srt.separadores(unico)]
        for k, v in dia.dividir_unico(unico, tabela).items():
            if k in videos and k not in por_video:
                por_video[k] = v
    elif xml and not tabela:
        tabela = xml["tabela"]                            # só o XML: serve para dividir a Skoopia e as soltas
    return {"por_video": por_video, "unico": unico is not None, "tabela": tabela, "skoopia": skoopia,
            "ignorados": ignorados, "master": master, "motivos": motivos, "soltos": soltos,
            "explicacao": explicacao, "xml": ({k: xml[k] for k in ("sequencia", "fora", "faltam")} | {"n": len(xml["tabela"])})
            if xml else None}


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
