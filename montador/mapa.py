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


# ---------------------------------------------------------------- mapa pela Skoopia / decupagem
_SLIDE_TITULO = re.compile(r"^\s*SLIDE\s+(\d+)\s*[.,]\s*0*1\b", re.I)        # "SLIDE 2.01 – Título" = começo da aula 2
_AULA = re.compile(r"^\s*(aula\b|apresenta[cç][aã]o\b|abertura\b|encerramento\b)", re.I)
_PREFIXO_AULA = re.compile(r"^\s*aula\s+[\w.]+\s*[–—:-]\s*", re.I)
BASTIDOR_LONGO_S = 30.0        # bastidores longos depois da última inserção: fim da aula (conversa, troca de arquivo)


def eh_lista_de_aulas(cues: list[Cue]) -> bool:
    """SRT de aulas da decupagem: uma legenda por aula, com o nome dela ("Aula 1A – ...")."""
    textos = [c.texto.strip() for c in cues if c.texto.strip()]
    return bool(textos) and len(textos) <= 40 and sum(bool(_AULA.match(t)) for t in textos) >= max(1, len(textos) * 0.6)


def nome_da_aula(texto: str) -> str:
    return _PREFIXO_AULA.sub("", texto.strip().split("\n")[0]).strip()


def pela_skoopia(videos: list[dict], falas: dict[str, list[Cue]], marcas: dict, tabela: list[dict],
                 titulos: list[str]) -> dict | None:
    """Mapa a partir do retorno da Skoopia/decupagem, quando ele diz onde cada aula começa.

    - Lista de aulas (SRT de aulas da decupagem): cada legenda é uma aula, com começo, fim e nome.
    - Senão, inserções "SLIDE N.01": começo da aula N; a aula vai até os bastidores que antecedem a próxima.
    O resto do dia (bastidores, testes, conversa entre aulas) fica descartado.
    """
    ordem = [v["nome"] for v in videos]
    dur = {v["nome"]: (v.get("duracao") or ((falas.get(v["nome"]) or [Cue(0, 0, 0, "")])[-1].fim + 1)) for v in videos}
    pos_tab = {r["video"]: r["fala"] for r in (tabela or [])}
    off, acc = {}, 0.0
    for nome in ordem:                                   # tempo contínuo do dia (o do SRT único, se houver)
        off[nome] = pos_tab.get(nome, acc) if len(pos_tab) == len(ordem) else acc
        acc = off[nome] + dur[nome] + 60.0

    lista_aulas, inicios, bastidores, insercoes = [], {}, [], []
    for video, arquivos in (marcas or {}).items():
        if video not in off:
            continue
        for _arq, cues in arquivos.items():
            if eh_lista_de_aulas(cues):
                lista_aulas += [(off[video] + c.ini, off[video] + c.fim, nome_da_aula(c.texto)) for c in cues if c.texto.strip()]
                continue
            for c in cues:
                g0, g1 = off[video] + c.ini, off[video] + c.fim
                m = _SLIDE_TITULO.match(c.texto)
                if m:
                    n = int(m.group(1))
                    inicios[n] = min(inicios.get(n, 1e12), g0)
                if re.match(r"^\s*\[BASTIDORES\]", c.texto, re.I):
                    bastidores.append((g0, g1))
                elif not re.match(r"^\s*(\[|TARJA)", c.texto, re.I):
                    insercoes.append((g0, g1))

    fim_do_dia = max(off[n] + dur[n] for n in ordem) if ordem else 0.0
    intervalos = []                                       # (ini, fim, nome)
    if lista_aulas:
        juntas: dict[str, list] = {}                     # a mesma aula pode vir cortada em dois vídeos
        for a, b, nome in lista_aulas:
            j = juntas.setdefault(nome, [a, b, nome])
            j[0], j[1] = min(j[0], a), max(j[1], b)
        intervalos = sorted(tuple(x) for x in juntas.values())
        fonte = "lista de aulas da decupagem"
    elif inicios:
        bastidores.sort()
        starts = sorted(inicios.items(), key=lambda x: x[1])
        for k, (n, ini) in enumerate(starts):
            prox = starts[k + 1][1] if k + 1 < len(starts) else fim_do_dia
            # a aula vai até o primeiro bastidor longo depois da última inserção dela (conversa entre aulas)
            ult = max([b for a, b in insercoes if ini <= a < prox] or [ini])
            longo = next((a for a, b in bastidores if a >= ult - 0.5 and a < prox and b - a >= BASTIDOR_LONGO_S), None)
            intervalos.append((ini, longo if longo is not None else prox, ""))
        fonte = "slides de título da Skoopia (SLIDE N.01)"
    else:
        return None

    # tempo do dia -> pedaços de cada vídeo
    fx = []
    for nome in ordem:
        a0, a1 = off[nome], off[nome] + dur[nome]
        cortes = sorted({a0, a1, *[x for i, f, _ in intervalos for x in (i, f) if a0 < x < a1]})
        for p, q in zip(cortes, cortes[1:]):
            if q - p < 0.5:
                continue
            meio = (p + q) / 2
            k = next((j for j, (i, f, _) in enumerate(intervalos) if i <= meio < f), None)
            fx.append({"video": nome, "ini": round(p - a0, 3), "fim": round(q - a0, 3),
                       "tipo": "abre" if k is not None and abs(p - intervalos[k][0]) < 1 else "continua",
                       "aula": (k + 1) if k is not None else 0,
                       "motivo": "" if k is not None else "fora das aulas (bastidores/teste, pela Skoopia)",
                       "abre_texto": " ".join(c.texto for c in (falas.get(nome) or []) if p - a0 <= c.ini < q - a0)[:160]})
    nomes = [n for _, _, n in intervalos]
    usar = titulos if titulos and len(titulos) == len(intervalos) else ([n for n in nomes] if any(nomes) else titulos)
    r = {"faixas": fx, **montar(fx, usar or [])}
    r["fonte"] = fonte
    r["titulos_skoopia"] = nomes if any(nomes) else []
    return r
