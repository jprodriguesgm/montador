"""Mapa do dia: quais trechos de quais vídeos formam cada aula.

Uma aula é um ou mais trechos de vídeo:
  - normal: um vídeo inteiro;
  - take descartado: o vídeo sai inteiro (o primeiro take de uma aula regravada);
  - final refeito em take curto: vídeo A + vídeo B (B começa sem "Olá": é continuação);
  - final refeito emendando a próxima aula: B é dividido no "Olá" da aula seguinte.

Pistas: abertura e fechamento na fala, contagem de títulos do cartão e (etapa 2) os cortes da
Skoopia. O editor confere no mapa e pode trocar a aula de um trecho, descartar ou dividir.
"""
from __future__ import annotations

import re
import unicodedata

from .srt import Cue

_ABRE = re.compile(r"^(e ai\s+)?(ola|oi|bom dia|boa tarde|boa noite|sejam? bem[- ]vindos?)\b")
_FECHA = re.compile(r"(vejo (voce|voces|vcs)|nos vemos|ate a proxima|ate logo|ate mais|obrigad[oa] por)")
TESTE_MAX_S = 90.0          # gravação curta e quase sem fala no começo do dia: teste de vídeo e microfone
TESTE_MAX_PALAVRAS = 15
TAKE_CURTO_S = 150.0        # take que se repete no vídeo seguinte costuma ser curto


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def _palavras(t: str) -> list[str]:
    return [w for w in _norm(t).split() if len(w) > 2]


def _abertura(c: Cue) -> bool:
    return bool(_ABRE.match(_norm(c.texto)))


def _fechamento(c: Cue) -> bool:
    return bool(_FECHA.search(_norm(c.texto)))


def _semelhanca(a: list[Cue], b: list[Cue]) -> float:
    """Quanto o começo de dois trechos se parece (palavras em comum nos primeiros ~25)."""
    pa = set(w for c in a for w in _palavras(c.texto)[:40])
    pb = set(w for c in b for w in _palavras(c.texto)[:40])
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / min(len(pa), len(pb))


def _fala(cues: list[Cue]) -> list[Cue]:
    return [c for c in cues if c.texto.strip() and not c.texto.strip().startswith("[")]


def faixas(videos: list[dict], falas: dict[str, list[Cue]]) -> list[dict]:
    """Divide cada vídeo em pedaços, cada um com tipo: abre | continua | teste."""
    out = []
    for v in videos:
        cues = _fala(falas.get(v["nome"], []))
        dur = v.get("duracao") or (cues[-1].fim if cues else 0.0)
        npal = sum(len(_palavras(c.texto)) for c in cues)
        antes_da_aula = not any(f["tipo"] != "teste" for f in out)    # teste só no começo do dia
        if dur and dur <= TESTE_MAX_S and (npal == 0 or (antes_da_aula and npal <= TESTE_MAX_PALAVRAS)):
            out.append({"video": v["nome"], "ini": 0.0, "fim": dur, "tipo": "teste", "abre_texto": ""})
            continue
        # aberturas que começam aula: nas primeiras falas do vídeo, ou logo depois de um fechamento
        cortes = []
        for k, c in enumerate(cues):
            if not _abertura(c) or k == 0:
                continue
            antes = cues[max(0, k - 4):k]
            pausa = c.ini - cues[k - 1].fim
            fechou = any(_fechamento(x) for x in antes)
            if k <= 2 and not fechou:
                continue                                   # começo do vídeo: o pedaço já começa em 0
            if fechou or pausa >= 20.0:
                cortes.append(max(0.0, c.ini - 1.0))
        inicios = [0.0] + cortes
        abre0 = any(_abertura(c) for c in cues[:3] if not cortes or c.ini < cortes[0])
        for j, ini in enumerate(inicios):
            fim = inicios[j + 1] if j + 1 < len(inicios) else dur
            pedaco = [c for c in cues if ini <= c.ini < fim]
            tipo = "abre" if (j > 0 or abre0) else "continua"
            out.append({"video": v["nome"], "ini": ini, "fim": fim, "tipo": tipo,
                        "abre_texto": " ".join(c.texto for c in pedaco[:3])[:160],
                        "_cues": pedaco})
    return out


def sugerir(videos: list[dict], falas: dict[str, list[Cue]], titulos: list[str]) -> dict:
    """Primeira sugestão do mapa: cada pedaço recebe o número da aula (0 = descartado)."""
    fx = faixas(videos, falas)
    for f in fx:
        f["aula"] = None
        f["motivo"] = ""
        if f["tipo"] == "teste":
            f["aula"] = 0
            f["motivo"] = "teste de vídeo e microfone"

    def blocos():
        """Aulas provisórias: listas de índices de pedaços (um "abre" seguido de "continua")."""
        bl = []
        for i, f in enumerate(fx):
            if f["aula"] == 0:
                continue
            if f["tipo"] == "abre" or not bl:
                bl.append([i])
            else:
                bl[-1].append(i)
        return bl

    # takes descartados: aula de um pedaço só, curta, cujo começo se repete na aula seguinte
    def candidatos(bl):
        out = []
        for a, b in zip(bl, bl[1:]):
            if len(a) != 1:
                continue
            fa, fb = fx[a[0]], fx[b[0]]
            dur = fa["fim"] - fa["ini"]
            sem = _semelhanca(fa.get("_cues", []), fb.get("_cues", []))
            nota = sem + (0.5 if dur < TAKE_CURTO_S else 0.0) + (0.0 if any(_fechamento(c) for c in fa.get("_cues", [])) else 0.2)
            out.append((nota, sem, dur, a[0]))
        return sorted(out, reverse=True)

    bl = blocos()
    for nota, sem, dur, i in candidatos(bl):          # sem cartão: só os casos claros
        if sem >= 0.35 and dur < TAKE_CURTO_S:
            fx[i]["aula"] = 0
            fx[i]["motivo"] = "take descartado (o começo se repete no vídeo seguinte)"
    bl = blocos()
    if titulos:
        while len(bl) > len(titulos):                  # com cartão: a conta tem de fechar
            cand = candidatos(bl)
            if not cand:
                break
            fx[cand[0][3]]["aula"] = 0
            fx[cand[0][3]]["motivo"] = "take descartado (sobrou vídeo em relação aos títulos)"
            bl = blocos()

    for n, b in enumerate(bl, 1):
        for i in b:
            fx[i]["aula"] = n
            if fx[i]["tipo"] == "continua" and i != b[0]:
                fx[i]["motivo"] = "continuação: o professor refez um trecho — confira o corte no vídeo anterior"
    for f in fx:
        f.pop("_cues", None)
    return {"faixas": fx, **montar(fx, titulos)}


def montar(fx: list[dict], titulos: list[str]) -> dict:
    """Aulas a partir das faixas (já ajustadas pelo editor ou sugeridas)."""
    nums = sorted({f["aula"] for f in fx if f.get("aula")})
    aulas = []
    for k, n in enumerate(nums, 1):
        trechos = [{"video": f["video"], "ini": f["ini"], "fim": f["fim"]} for f in fx if f.get("aula") == n]
        titulo = titulos[k - 1] if k - 1 < len(titulos) else ""
        conferir = [f["motivo"] for f in fx if f.get("aula") == n and f.get("motivo")]
        aulas.append({"n": k, "titulo": titulo, "nome": f"{k:02d} {titulo}".strip(),
                      "trechos": trechos, "conferir": conferir})
    descartados = [{"video": f["video"], "ini": f["ini"], "fim": f["fim"], "motivo": f.get("motivo", "")}
                   for f in fx if f.get("aula") == 0]
    avisos = []
    if titulos and len(titulos) != len(aulas):
        avisos.append(f"{len(aulas)} aulas no mapa e {len(titulos)} títulos no cartão — confira a divisão")
    if not titulos:
        avisos.append("Sem títulos: as sequências saem só com o número")
    return {"aulas": aulas, "descartados": descartados, "avisos": avisos}


def dividir(fx: list[dict], video: str, tempo: float) -> list[dict]:
    """O editor divide um pedaço num ponto (ex.: final refeito emendando a próxima aula)."""
    out = []
    for f in fx:
        if f["video"] == video and f["ini"] + 1 < tempo < f["fim"] - 1:
            a = dict(f, fim=tempo)
            b = dict(f, ini=tempo, tipo="abre", motivo="dividido pelo editor")
            out += [a, b]
        else:
            out.append(f)
    return out
