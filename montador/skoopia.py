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
    colada = dia.tabela_colada(videos)          # sequência master do Premiere: vídeos colados, sem espaço
    if colada:
        out.append(colada)
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
            return {"modo": "dia", "video": None, "tabela": tabela,
                    "motivo": "SRT do dia inteiro, dividido pela tabela" + conferir(cues, tabela, videos, falas)}
        # sem a tabela: refaz as posições prováveis e fica com a que bate com as falas citadas
        notas = sorted(((_nota_tabela(cues, t, falas), k, t) for k, t in enumerate(tabelas_candidatas(videos, falas))),
                       key=lambda x: (-x[0], x[1]))
        citadas = sum(1 for c in cues if _CITACAO.search(c.texto)) or len(cues)
        if notas and notas[0][0] >= max(1.0, 0.3 * citadas):
            return {"modo": "dia", "video": None, "tabela": notas[0][2],
                    "motivo": "SRT do dia inteiro, dividido pelas posições de cada vídeo (conferidas pelas falas)"}
        sem = [v["nome"] for v in videos if not v.get("duracao")]
        return {"modo": "pendente", "video": None,
                "motivo": f"é do dia inteiro (vai até {_hms(fim)}; o maior vídeo tem {_hms(maior)}) e falta saber onde "
                          "cada vídeo começa: " + (f"não consegui ler a duração de {', '.join(sem)} — importe o XML "
                                                   "da sequência master" if sem else
                                                   "importe a transcrição do dia (SRT único ou master do Premiere) "
                                                   "ou o XML da sequência")}
    notas = sorted(((_pontuar(cues, falas.get(v["nome"], [])), v["nome"]) for v in videos), reverse=True)
    # cabe num vídeo só, mas pode ser do dia inteiro (SRT único ou sequência master) que só tem marcas no começo
    candidatas = [tabela] if tabela else tabelas_candidatas(videos, falas)
    dia_nota, dia_tab = max(((_nota_tabela(cues, t, falas), t) for t in candidatas), key=lambda x: x[0],
                            default=(0.0, None))
    melhor_video = notas[0][0] if notas else 0.0
    if dia_tab and dia_nota >= 1.0 and dia_nota > 1.2 * melhor_video:
        return {"modo": "dia", "video": None, "tabela": dia_tab,
                "motivo": "SRT do dia inteiro, dividido pelas posições de cada vídeo (conferidas pelas falas)"}
    if notas and notas[0][0] >= 1.0 and (len(notas) == 1 or notas[0][0] >= 1.5 * max(notas[1][0], 0.01)):
        return {"modo": "video", "video": notas[0][1], "motivo": "pelas falas citadas"}
    if not any(falas.get(v["nome"]) for v in videos):
        motivo = "os vídeos ainda não têm transcrição para comparar as falas citadas — importe as transcrições"
    elif not any(_CITACAO.search(c.texto) for c in cues) and tipo(cues) == "cortes":
        motivo = "o arquivo não traz o nome do vídeo nem falas citadas para comparar"
    elif notas and notas[0][0] >= 1.0:
        motivo = f"as falas citadas combinam com mais de um vídeo ({notas[0][1]} e {notas[1][1]})"
    else:
        motivo = "as falas citadas não aparecem em nenhuma transcrição do dia (pode ser de outro dia)"
    return {"modo": "pendente", "video": None, "motivo": "não deu para saber de qual vídeo é: " + motivo}


def _hms(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def conferir(cues: list[srt.Cue], tabela: list[dict], videos: list[dict], falas: dict) -> str:
    """Depois de dividir pela tabela: as falas citadas batem com a transcrição de cada vídeo? ("" = tudo certo)."""
    avisos = []
    fim = max((c.fim for c in cues), default=0)
    durs = {v["nome"]: v.get("duracao") for v in videos}
    ult = max(tabela, key=lambda r: r["separador"])
    fim_seq = ult.get("fim") or (ult["fala"] + durs[ult["video"]] if durs.get(ult["video"]) else None)
    if fim_seq and fim > fim_seq + 30:
        avisos.append(f"vai até {_hms(fim)}, depois do fim da sequência ({_hms(fim_seq)}) — confira se é deste dia")
    citadas = [c for c in cues if _CITACAO.search(c.texto)]
    if len(citadas) >= 3 and any(falas.get(v["nome"]) for v in videos):
        por = dia.dividir_unico(citadas, tabela)
        nota = sum(_pontuar(v, falas.get(k, [])) for k, v in por.items())
        if nota < 0.3 * len(citadas):
            avisos.append("as falas citadas não batem com a transcrição nesses tempos — confira se a "
                          "transcrição/XML usados para dividir são deste dia")
    return (" · ATENÇÃO: " + "; ".join(avisos)) if avisos else ""


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
