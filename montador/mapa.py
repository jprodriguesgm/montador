"""Mapa do dia: quais trechos de quais vídeos formam cada aula.

Uma aula é um ou mais trechos de vídeo:
  - normal: um vídeo inteiro;
  - take descartado: o vídeo sai inteiro (o primeiro take de uma aula regravada);
  - final refeito em take curto: vídeo A + vídeo B (B começa sem "Olá": é continuação);
  - final refeito emendando a próxima aula: B é dividido no "Olá" da aula seguinte.

Os títulos do cartão mandam: cada título é uma aula, na ordem do dia. O app procura o trecho de cada uma
somando pistas — nenhuma decide sozinha:
  - abertura ("Olá", "bom dia"...) e fechamento ("vejo vocês", "nos vemos"...) na fala;
  - contagem de títulos do cartão (a conta tem de fechar, para mais e para menos);
  - abertura de aula sem cumprimento ("neste vídeo", "nesta aula", "hoje vamos") e síntese no fim, com peso
    pequeno;
  - conteúdo: as palavras do título, do texto dos slides (.pptx de cada aula) e das inserções da Skoopia
    comparadas com o que é falado em cada trecho;
  - duração (um arquivo curto quase sempre é continuação ou take).
O título que não acha trecho com segurança aparece como "aula não reconhecida": o editor escolhe. Nada é
juntado numa aula só por falta de pista.
"""
from __future__ import annotations

import math
import re
import unicodedata

from .srt import Cue

_ABRE = re.compile(r"^(e ai\s+)?(ola|oi|bom dia|boa tarde|boa noite|sejam? bem[- ]vindos?)\b")
_FECHA = re.compile(r"(vejo (voce|voces|vcs)|nos vemos|ate a proxima|ate logo|ate mais|obrigad[oa] por)")
# abertura de aula sem cumprimento: só reforça (peso pequeno), nunca divide um vídeo
_ABRE_AULA = re.compile(r"\b(neste video|nesse video|nesta aula|nessa aula|neste (modulo|topico|bloco|tema)|"
                        r"nesta (unidade|parte|etapa)|hoje (vamos|eu vou|a gente vai)|"
                        r"vamos (comecar|iniciar) (a|nossa|esta|essa)|nesta videoaula|nessa videoaula)\b")
_SINTESE = re.compile(r"\b(em sintese|sintetizando|resumindo|recapitulando|para (finalizar|concluir|encerrar)|"
                      r"concluindo|chegamos ao (fim|final)|finalizamos|na proxima aula|no proximo (video|tema))\b")
_CONTINUA = re.compile(r"^(entao|continuando|retomando|voltando|como eu (estava|dizia)|bom,? continuando)\b")
TESTE_MAX_S = 90.0          # gravação curta e quase sem fala no começo do dia: teste de vídeo e microfone
TESTE_MAX_PALAVRAS = 15
SOLTO_MAX_S = 30.0          # arquivo minúsculo no meio do dia, sem abertura nem fechamento ("vou parar 5 minutinhos")
TAKE_CURTO_S = 150.0        # take que se repete no vídeo seguinte costuma ser curto
PISTAS_FORTES = 3.0         # nota a partir da qual uma aula nova sem cumprimento não precisa ser conferida
PAUSA_LONGA_S = 300.0       # 5 min sem fala no meio de um trecho: pode ter um começo de aula descartado antes

_STOP = set("""para pelo pela pelos pelas com como mais mas que nao uma uns umas dos das nos nas aos este esta esse essa
isso isto aquele aquela ser sao foi era tem ter seu sua seus suas ele ela eles elas voce voces nosso nossa muito
muita entre sobre por sem pra nem the and for meu minha vao vai ver bem tambem quando onde porque qual quais cada
todo toda todos todas ate sob apos entao assim ainda aqui ja so vamos pode podem deve devem temos estamos estao
sendo sera forma parte vez vezes dia hoje aula aulas video videos slide slides fonte texto imagem elaborado
elaborada autor autora gente coisa coisas fazer feito sempre agora tudo nada isso dessa desse desta deste numa
num pois porque esse essas esses estas estes outro outra outros outras mesmo mesma vou vamos estou""".split())


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def _palavras(t: str) -> list[str]:
    return [w for w in _norm(t).split() if len(w) > 2]


def _termos(t: str) -> set[str]:
    """Palavras que dizem o assunto (sem as comuns), com um "radical" simples (plural)."""
    out = set()
    for w in _norm(t).split():
        if len(w) > 3 and w not in _STOP and not w.isdigit():
            out.add(w[:-1] if w.endswith("s") and len(w) > 5 else w)
    return out


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
    """Divide cada vídeo em pedaços, cada um com tipo: abre | continua | teste | solto."""
    out = []
    for v in videos:
        cues = _fala(falas.get(v["nome"], []))
        dur = v.get("duracao") or (cues[-1].fim if cues else 0.0)
        npal = sum(len(_palavras(c.texto)) for c in cues)
        antes_da_aula = not any(f["tipo"] not in ("teste", "solto") for f in out)    # teste só no começo do dia
        if dur and dur <= TESTE_MAX_S and (npal == 0 or (antes_da_aula and npal <= TESTE_MAX_PALAVRAS)):
            out.append({"video": v["nome"], "ini": 0.0, "fim": dur, "tipo": "teste", "abre_texto": ""})
            continue
        if (dur and dur <= SOLTO_MAX_S and npal <= TESTE_MAX_PALAVRAS and cues
                and not any(_abertura(c) or _fechamento(c) for c in cues)):
            out.append({"video": v["nome"], "ini": 0.0, "fim": dur, "tipo": "solto",
                        "abre_texto": " ".join(c.texto for c in cues)[:160]})
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
            pausas = [(a.fim, b.ini) for a, b in zip(pedaco, pedaco[1:]) if b.ini - a.fim >= PAUSA_LONGA_S]
            out.append({"video": v["nome"], "ini": ini, "fim": fim, "tipo": tipo,
                        "abre_texto": " ".join(c.texto for c in pedaco[:3])[:160],
                        "pausas": pausas, "_cues": pedaco})
    return out


# ------------------------------------------------------------------ conteúdo (títulos, slides, inserções)

def _assinaturas(titulos: list[str], slides: list[str] | None) -> list[dict[str, float]]:
    """Peso de cada termo por título: o título vale mais, o texto dos slides completa. Termos que aparecem em
    quase todas as aulas (o tema da disciplina) valem pouco."""
    brutos = []
    for k, t in enumerate(titulos):
        tt = _termos(t)
        ss = _termos(slides[k]) if slides and k < len(slides) and slides[k] else set()
        brutos.append({w: (2.0 if w in tt else 1.0) for w in tt | ss})
    n = len(brutos)
    df: dict[str, int] = {}
    for b in brutos:
        for w in b:
            df[w] = df.get(w, 0) + 1
    return [{w: p * math.log(1 + n / df[w]) for w, p in b.items()} for b in brutos]


def _nota(assin: dict[str, float], termos: set[str]) -> float:
    total = sum(assin.values())
    return sum(p for w, p in assin.items() if w in termos) / total if total else 0.0


def _texto_bloco(fx: list[dict], bloco: list[int], insercoes: dict | None) -> set[str]:
    out = set()
    for i in bloco:
        f = fx[i]
        out |= _termos(" ".join(c.texto for c in f.get("_cues", [])))
        for c in (insercoes or {}).get(f["video"], []):
            if f["ini"] - 1 <= c.ini < f["fim"]:
                out |= _termos(c.texto)
    return out


def _alinhar(notas: list[list[float]], n_titulos: int) -> list[int]:
    """Cada bloco (na ordem) recebe um título (na ordem, sem repetir): a combinação de maior nota.
    Empate: o título mais cedo (a ordem do dia)."""
    m = len(notas)
    neg = -1e9
    melhor = [[neg] * (n_titulos + 1) for _ in range(m + 1)]
    de = [[0] * (n_titulos + 1) for _ in range(m + 1)]
    for k in range(n_titulos + 1):
        melhor[0][k] = 0.0
    for j in range(1, m + 1):
        for k in range(j, n_titulos + 1):
            # bloco j-1 recebe o título k-1; o anterior recebeu algum título antes de k-1
            ant = max(range(j - 1, k), key=lambda x: (melhor[j - 1][x], -x))
            v = melhor[j - 1][ant] + notas[j - 1][k - 1] - 1e-6 * (k - j)
            if v > melhor[j][k]:
                melhor[j][k], de[j][k] = v, ant
    k = max(range(m, n_titulos + 1), key=lambda x: (melhor[m][x], -x))
    out = []
    for j in range(m, 0, -1):
        out.append(k - 1)
        k = de[j][k]
    return out[::-1]


# ------------------------------------------------------------------ sugestão

def sugerir(videos: list[dict], falas: dict[str, list[Cue]], titulos: list[str],
            slides: list[str] | None = None, insercoes: dict | None = None) -> dict:
    """Primeira sugestão do mapa: cada pedaço recebe o número do título (0 = descartado).

    `slides`: texto dos slides de cada título (mesma ordem; "" quando não se sabe).
    `insercoes`: inserções da Skoopia por vídeo (cues no tempo do vídeo), com o texto do slide."""
    fx = faixas(videos, falas)
    for f in fx:
        f["aula"] = None
        f["motivo"] = ""
        if f["tipo"] == "teste":
            f["aula"] = 0
            f["motivo"] = "teste de vídeo e microfone"
        elif f["tipo"] == "solto":
            f["aula"] = 0
            f["motivo"] = "trecho curto sem aula (pausa ou aviso) — confira"

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
    assin = _assinaturas(titulos, slides) if titulos else []
    if titulos:
        while len(bl) > len(titulos):                  # com cartão: a conta tem de fechar
            cand = candidatos(bl)
            if not cand:
                break
            fx[cand[0][3]]["aula"] = 0
            fx[cand[0][3]]["motivo"] = "take descartado (sobrou vídeo em relação aos títulos)"
            bl = blocos()
        # faltou aula: um arquivo que começou sem "Olá" pode ser uma aula nova (o professor não cumprimenta)
        while len(bl) < len(titulos):
            melhor = _melhor_promocao(fx, bl, assin, insercoes)
            if melhor is None:
                break
            i, fx[i]["_promovido"] = melhor
            fx[i]["tipo"] = "abre"
            bl = blocos()
    else:
        # sem cartão não há conta a fechar: só vira aula nova o arquivo com pistas fortes (pelo menos duas)
        while True:
            melhor = _melhor_promocao(fx, bl, [], insercoes, minimo=2.0)
            if melhor is None:
                break
            i, fx[i]["_promovido"] = melhor
            fx[i]["tipo"] = "abre"
            bl = blocos()

    # cada bloco recebe um título: na ordem; com menos blocos que títulos, o conteúdo decide quais faltam
    if titulos and len(bl) < len(titulos):
        notas = [[_nota(a, _texto_bloco(fx, b, insercoes)) for a in assin] for b in bl]
        numeros = [k + 1 for k in _alinhar(notas, len(titulos))]
    else:
        numeros = list(range(1, len(bl) + 1))
    for n, b in zip(numeros, bl):
        for i in b:
            fx[i]["aula"] = n
            if fx[i]["tipo"] == "continua" and i != b[0]:
                fx[i]["motivo"] = "continuação: o professor refez um trecho — confira o corte no vídeo anterior"
            if fx[i].get("_promovido"):
                pistas, nota = fx[i]["_promovido"]
                fx[i]["pista"] = "aula nova (sem cumprimento): " + pistas
                if nota < PISTAS_FORTES:                   # pista fraca: o editor confere
                    fx[i]["motivo"] = fx[i]["pista"] + " — confira"
            if fx[i].get("pausas"):
                a, z = fx[i]["pausas"][0]
                fx[i]["motivo"] = (fx[i]["motivo"] + " · " if fx[i]["motivo"] else "") + \
                    f"pausa longa de {_mmss(a)} a {_mmss(z)} — confira se o começo é um take descartado"
    # conteúdo que discorda do título recebido (só com pistas de slides/inserções, para não errar por pouco)
    if titulos and (slides and any(slides) or insercoes):
        for n, b in zip(numeros, bl):
            termos = _texto_bloco(fx, b, insercoes)
            ns = [_nota(a, termos) for a in assin]
            proprio = ns[n - 1]
            outro = max(range(len(ns)), key=lambda k: ns[k])
            if outro != n - 1 and ns[outro] >= 0.15 and ns[outro] > 2 * max(proprio, 0.02):
                fx[b[0]]["motivo"] = (fx[b[0]]["motivo"] + " · " if fx[b[0]]["motivo"] else "") + \
                    f"o conteúdo parece mais com a aula {outro + 1} ({titulos[outro][:40]}) — confira"
    for f in fx:
        f.pop("_cues", None)
        f.pop("_promovido", None)
    return {"faixas": fx, **montar(fx, titulos)}


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def _melhor_promocao(fx: list[dict], bl: list[list[int]], assin: list[dict], insercoes: dict | None,
                     minimo: float = 0.0):
    """O pedaço "continua" (começo de arquivo) com mais pistas de ser aula nova. None se nenhum tiver."""
    opcoes = []
    for k, b in enumerate(bl):
        for pos, i in enumerate(b):
            if pos == 0:
                continue
            f = fx[i]
            if f["tipo"] != "continua" or f["ini"] > 0:
                continue
            cues = f.get("_cues", [])
            ant = fx[b[pos - 1]].get("_cues", [])
            dur = f["fim"] - f["ini"]
            nota, pistas = 0.0, []
            if any(_fechamento(c) for c in ant[-4:]):
                nota += 2.0
                pistas.append("o vídeo anterior fecha a aula")
            if any(_SINTESE.search(_norm(c.texto)) for c in ant[-8:]):
                nota += 1.0
                pistas.append("síntese no fim do anterior")
            if any(_ABRE_AULA.search(_norm(c.texto)) for c in cues[:3]):
                nota += 1.0
                pistas.append("abre a aula (\"neste vídeo\"/\"nesta aula\")")
            if dur >= TAKE_CURTO_S:
                nota += 1.0
                pistas.append("vídeo longo")
            elif dur < 60:
                nota -= 1.5
            if cues and _CONTINUA.match(_norm(cues[0].texto)):
                nota -= 1.0
            if assin and k + 1 < len(assin):
                # o conteúdo parece mais com o próximo título do que com o da aula em que está?
                termos = _texto_bloco(fx, b[pos:], insercoes)
                atual, prox = _nota(assin[min(k, len(assin) - 1)], termos), _nota(assin[k + 1], termos)
                if prox > atual * 1.3 and prox >= 0.05:
                    nota += 1.5
                    pistas.append("conteúdo do título seguinte")
                elif atual > prox * 1.3 and atual >= 0.05:
                    nota -= 1.5
            if nota > minimo or (minimo and nota >= minimo):
                opcoes.append((nota, -i, i, ", ".join(pistas)))
    if not opcoes:
        return None
    nota, _, i, motivo = max(opcoes)
    return i, (motivo, nota)


def _ordem_natural(nome: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", _norm(nome))]


def slides_dos_titulos(decks: list[tuple[str, str]], titulos: list[str]) -> list[str]:
    """Texto dos slides de cada título. decks: [(nome do arquivo, texto de todos os slides)].

    Mesmo número de .pptx e de títulos: um para cada, na ordem dos nomes (U3_T1_V1, U3_T1_V2...).
    Senão, cada .pptx vai para o título com que mais se parece (só se parecer de verdade)."""
    if not decks or not titulos:
        return []
    decks = sorted(decks, key=lambda d: _ordem_natural(d[0]))
    if len(decks) == len(titulos):
        return [t for _, t in decks]
    assin = _assinaturas(titulos, None)
    pares = sorted(((_nota(a, _termos(nome + " " + texto)), k, j)
                    for j, (nome, texto) in enumerate(decks) for k, a in enumerate(assin)), reverse=True)
    out, usados = [""] * len(titulos), set()
    for nota, k, j in pares:
        if nota < 0.25:
            break
        if out[k] or j in usados:
            continue
        out[k], usados = decks[j][1], usados | {j}
    return out


def montar(fx: list[dict], titulos: list[str]) -> dict:
    """Aulas a partir das faixas (já ajustadas pelo editor ou sugeridas).

    O número da aula de um trecho é o número do título no cartão (aula 3 = 3º título). Título sem trecho
    aparece como "aula não reconhecida" para o editor escolher."""
    nums = sorted({f["aula"] for f in fx if f.get("aula")})
    total = max([len(titulos)] + nums) if (titulos or nums) else 0
    aulas, faltam = [], []
    for n in range(1, total + 1):
        trechos = [{"video": f["video"], "ini": f["ini"], "fim": f["fim"]} for f in fx if f.get("aula") == n]
        titulo = titulos[n - 1] if n - 1 < len(titulos) else ""
        if not trechos and n > len(titulos):
            continue
        conferir = [f["motivo"] for f in fx if f.get("aula") == n and f.get("motivo")]
        a = {"n": n, "titulo": titulo, "nome": f"{n:02d} {titulo}".strip(), "trechos": trechos, "conferir": conferir}
        if not trechos:
            a["nao_reconhecida"] = True
            a["conferir"] = ["aula não reconhecida — clique no trecho certo do mapa e escolha esta aula"]
            faltam.append(n)
        aulas.append(a)
    descartados = [{"video": f["video"], "ini": f["ini"], "fim": f["fim"], "motivo": f.get("motivo", "")}
                   for f in fx if f.get("aula") == 0]
    avisos = []
    com_trecho = [a for a in aulas if a["trechos"]]
    if faltam:
        avisos.append(f"{len(faltam)} aula(s) não reconhecida(s): " + ", ".join(f"{n:02d}" for n in faltam)
                      + " — escolha o trecho de cada uma no mapa")
    if titulos and len(com_trecho) > len(titulos):
        avisos.append(f"{len(com_trecho)} aulas no mapa e {len(titulos)} títulos no cartão — confira a divisão")
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
