"""Retorno da Skoopia: SRTs de cortes e de inserções, quantos o editor quiser.

Cada arquivo é reconhecido pelo conteúdo (não pelo nome):
  - cortes: marcações [ERRO] / [BASTIDORES];
  - inserções: o resto (título e tópicos da cartela).
E é ligado ao vídeo certo:
  1. o nome do arquivo traz o nome do vídeo;
  2. o tempo passa do maior vídeo → veio do SRT único do dia: é dividido pela tabela (cada vídeo em 0);
  3. senão, as falas citadas/o texto são comparados com a transcrição de cada vídeo naquele tempo.
Sem certeza, o arquivo fica pendente e o editor escolhe o vídeo.
"""
from __future__ import annotations

import math
import re
import unicodedata

from . import dia, srt

_TIPO = re.compile(r"^\s*\[(ERRO|BASTIDORES)\]", re.I)
_CITACAO = re.compile(r"['\"‘“]([^'\"’”]{4,})['\"’”]")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _palavras(t: str) -> set[str]:
    return {w for w in _norm(t).split() if len(w) > 3}


def tipo(cues: list[srt.Cue]) -> str:
    return "cortes" if any(_TIPO.match(c.texto) for c in cues) else "insercoes"


def classe(c: srt.Cue) -> str:
    m = _TIPO.match(c.texto)
    return m.group(1).lower() if m else "insercao"


def _pontuar(cues: list[srt.Cue], falas: list[srt.Cue]) -> float:
    """Quanto as marcações combinam com a transcrição de um vídeo nos mesmos tempos."""
    total = 0.0
    for c in cues:
        cit = _CITACAO.findall(c.texto)
        alvo = _palavras(" ".join(cit)) if cit else _palavras(c.texto.split("\n")[0] if not _TIPO.match(c.texto) else "")
        if not alvo:
            continue
        perto = " ".join(f.texto for f in falas if f.fim >= c.ini - 3 and f.ini <= c.fim + 3)
        total += len(alvo & _palavras(perto)) / len(alvo)
    return total


def _fim_video(v: dict, falas: dict) -> float:
    fs = falas.get(v["nome"]) or []
    return v.get("duracao") or (fs[-1].fim + 1 if fs else 0.0)


def tabelas_candidatas(videos: list[dict], falas: dict) -> list[list[dict]]:
    """Sem a tabela do SRT único, refaz as posições prováveis de cada vídeo dentro dele.

    (a) regra do `transcribe` (duração real do vídeo, próximo minuto cheio com 30 s de folga);
    (b) a mesma conta pela última fala (como o SRT único montado à mão em 20/11).
    """
    ordem = sorted(videos, key=lambda v: v["nome"])
    out = []
    for pelo_video in (True, False):
        tab, ini = [], 0.0
        for v in ordem:
            fs = falas.get(v["nome"]) or []
            fala = ini + 2.0
            tab.append({"video": v["nome"], "separador": ini, "fala": fala})
            fim = (v.get("duracao") if pelo_video else None) or (fs[-1].fim if fs else 0.0)
            ini = math.ceil((fala + fim + 30.0) / 60.0) * 60.0 if pelo_video else \
                ini + math.ceil(((fs[-1].fim if fs else 0.0) + 2.0 + 30.0) / 60.0) * 60.0
        out.append(tab)
    return out


def _nota_tabela(cues: list[srt.Cue], tabela: list[dict], falas: dict) -> float:
    por = dia.dividir_unico(cues, tabela)
    return sum(_pontuar(v, falas.get(k, [])) for k, v in por.items())


def ligar(nome: str, cues: list[srt.Cue], videos: list[dict], falas: dict, tabela: list[dict]) -> dict:
    """Decide o destino de um arquivo: {"modo": "video"|"dia"|"pendente", "video": ..., "motivo": ...}."""
    nn = unicodedata.normalize("NFC", nome).lower()
    for v in sorted(videos, key=lambda x: -len(x["nome"])):
        if unicodedata.normalize("NFC", v["nome"]).lower() in nn:
            return {"modo": "video", "video": v["nome"], "motivo": "pelo nome do arquivo"}
    fim = max((c.fim for c in cues), default=0)
    maior = max((_fim_video(v, falas) for v in videos), default=0)
    if maior and fim > maior + 5:
        if tabela:
            return {"modo": "dia", "video": None, "motivo": "SRT do dia inteiro, dividido pela tabela", "tabela": tabela}
        # sem a tabela: refaz as posições prováveis e fica com a que bate com as falas citadas
        notas = sorted(((_nota_tabela(cues, t, falas), k, t) for k, t in enumerate(tabelas_candidatas(videos, falas))),
                       key=lambda x: (-x[0], x[1]))
        citadas = sum(1 for c in cues if _CITACAO.search(c.texto)) or len(cues)
        if notas and notas[0][0] >= max(1.0, 0.3 * citadas):
            return {"modo": "dia", "video": None, "tabela": notas[0][2],
                    "motivo": "SRT do dia inteiro, dividido pelas posições de cada vídeo (conferidas pelas falas)"}
        return {"modo": "pendente", "video": None,
                "motivo": "é do SRT único do dia: importe o SRT único (ou a tabela) para dividir"}
    notas = sorted(((_pontuar(cues, falas.get(v["nome"], [])), v["nome"]) for v in videos), reverse=True)
    if notas and notas[0][0] >= 1.0 and (len(notas) == 1 or notas[0][0] >= 1.5 * max(notas[1][0], 0.01)):
        return {"modo": "video", "video": notas[0][1], "motivo": "pelas falas citadas"}
    return {"modo": "pendente", "video": None, "motivo": "não deu para saber de qual vídeo é"}


def distribuir(cues: list[srt.Cue], destino: dict, tabela: list[dict]) -> dict[str, list[srt.Cue]]:
    if destino["modo"] == "video":
        return {destino["video"]: cues}
    if destino["modo"] == "dia":
        return {k: v for k, v in dia.dividir_unico(cues, destino.get("tabela") or tabela).items() if v}
    return {}


def contar(marcas: dict, trechos: list[dict]) -> dict:
    """Quantas marcações caem nos trechos de uma aula."""
    out = {"erro": 0, "bastidores": 0, "insercao": 0}
    for t in trechos:
        m = marcas.get(t["video"]) or {}
        for lista in m.values():
            for c in lista:
                if c.ini < t["fim"] and c.fim > t["ini"]:
                    out[classe(c)] += 1
    return out
