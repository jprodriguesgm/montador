#!/usr/bin/env python3
"""Alinhamento do TP COM SLIDE quando NÃO há roteiro em .docx: decide, só com o .pptx e a transcrição, onde entra cada slide.
Uso: python3 -I alinhar_pptx.py SLIDES.pptx bruto.srt saida.json
A saída tem o mesmo formato do alinhar_notas.py (lista "roteiro" com fala / INSERÇÃO EM TELA / PAUSA), para o gerar_xml_tp_slide.py.

Dois casos, escolhidos sozinho (variável ALINHAR_MODO=A ou B força um deles, para teste):
 A) ROTEIRO DENTRO DO PPTX: o professor intercala um slide só de texto (o que ele lê no TP, em geral começando por
    "[Slide N - título]") e, em seguida, o slide visual. O slide visual entra quando ele começa a ler o texto do slide anterior.
    Só os slides visuais são inseridos; o primeiro (capa) e o último (referências/encerramento) ficam de fora.
 B) SEM ROTEIRO NENHUM: cada slide (do 2º ao penúltimo) entra no trecho da fala em que o ASSUNTO do slide aparece
    (palavras do slide x palavras ditas), respeitando a ordem dos slides. Slide sem trecho parecido não é inserido.
Quanto tempo o slide fica na tela é decidido pelo gerador (SLIDE_DUR). Só biblioteca padrão."""
import html, json, math, os, re, sys, unicodedata, zipfile
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # com -I a pasta do script não entra sozinha

DUR_B = 15.0          # no caso B o trecho "falado" de cada slide é só um ponto de entrada; a duração real vem do gerador
LIM_A = 0.20          # caso A: fração mínima das palavras próprias do texto que precisam ter sido ditas no trecho
LIM_B = 0.18          # caso B: idem, para o texto do próprio slide (o slide tem poucas palavras; as posições saem marcadas para conferir)
STOP = set("""para pelo pela pelos pelas com como mais mas que nao uma uns umas dos das nos nas aos este esta esse essa isso isto
aquele aquela ser sao foi era tem ter seu sua seus suas ele ela eles elas voce voces nosso nossa muito muita entre sobre
que uma dos das nos nas aos por com sem mas nao pra ela ele nem ou the and for meu minha ter tem vao vai ver bem
tambem quando onde porque por qual quais cada todo toda todos todas ate sem sob apos entao assim ainda aqui la ja so
vamos vai pode podem deve devem temos estamos esta estao sendo sera forma parte vez vezes dia hoje aula slide""".split())


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", t)


def ts(s):
    h, m, r = s.split(":"); sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def le_srt(p):
    cues = []
    for bloco in re.split(r"\n\s*\n", open(p, encoding="utf-8").read().strip()):
        ln = bloco.strip().split("\n")
        if len(ln) >= 3 and "-->" in ln[1]:
            a, b = [ts(x.strip()) for x in ln[1].split("-->")]
            cues.append((a, b, " ".join(ln[2:])))
    return cues


def bigr(tk):
    return set(zip(tk, tk[1:]))


RE_CAB = re.compile(r"^\s*\[?\s*slide\s*\d+\s*[-–—:]", re.I)


def tira_cabecalho(t):
    """'[Slide 3 - Título] texto...' -> 'texto...' (o cabeçalho não é falado)"""
    if not RE_CAB.match(t):
        return t
    m = re.match(r"^\s*\[?\s*slide\s*\d+[^\]\n]{0,160}\]\s*", t, flags=re.I)
    if m:
        return t[m.end():]
    return re.sub(r"^\s*\[?\s*slide\s*\d+\s*[-–—:]\s*", "", t, flags=re.I)


def le_pptx(p):
    """slides na ORDEM DA APRESENTAÇÃO (a mesma numeração dos PNGs exportados): n, parágrafos, texto, imagens"""
    z = zipfile.ZipFile(p)
    rel = z.read("ppt/_rels/presentation.xml.rels").decode("utf8")
    alvo = {}
    for tag in re.findall(r"<Relationship\b[^>]*>", rel):
        i = re.search(r'\bId="([^"]+)"', tag); t = re.search(r'\bTarget="([^"]+)"', tag)
        if i and t:
            alvo[i.group(1)] = t.group(1)
    ids = re.findall(r'<p:sldId\b[^>]*r:id="([^"]+)"', z.read("ppt/presentation.xml").decode("utf8"))
    out = []
    for n, r in enumerate(ids, 1):
        nome = "ppt/" + alvo.get(r, "").lstrip("/").replace("ppt/", "", 1) if alvo.get(r) else ""
        try:
            x = z.read(nome).decode("utf8")
        except KeyError:
            x = ""
        paras = []
        for par in re.findall(r"<a:p>.*?</a:p>|<a:p [^>]*>.*?</a:p>", x, flags=re.S):
            t = " ".join(html.unescape("".join(re.findall(r"<a:t>([^<]*)</a:t>", par))).split())
            if t:
                paras.append(t)
        out.append({"n": n, "paras": paras, "texto": " ".join(paras), "imgs": len(re.findall(r"<p:pic>", x))})
    return out


def blocos_de_fala(paras):
    """parágrafos do slide de texto -> blocos de 8 a ~70 palavras (bons para achar na transcrição)"""
    txt = [tira_cabecalho(p) if i == 0 else p for i, p in enumerate(paras)]
    txt = [t.strip() for t in txt if t.strip()]
    partes = []
    for t in txt:
        if len(norm(t)) <= 70:
            partes.append(t); continue
        cur = ""
        for fr in re.split(r"(?<=[.!?])\s+", t):
            if cur and len(norm(cur)) + len(norm(fr)) > 55:
                partes.append(cur); cur = fr
            else:
                cur = (cur + " " + fr).strip()
        if cur:
            partes.append(cur)
    out = []
    for t in partes:                       # bloco curto demais junta com o anterior
        if out and (len(norm(t)) < 8 or len(norm(out[-1])) < 8):
            out[-1] = out[-1] + " " + t
        else:
            out.append(t)
    return out


def acha_na_fala(texto, toks, tcue, cues):
    """candidatos (score, início, fim) do bloco de texto na transcrição (igual ao alinhar_notas, com um filtro rápido antes)"""
    bt = norm(texto); n = len(bt)
    if n < 3:
        return []
    L = max(3, int(n * 1.15)); sb = set(bt); cand = []
    passo = 1 if n < 40 else 2
    for i in range(0, max(1, len(toks) - n // 2), passo):
        jan = toks[i:i + L]
        if len(sb & set(jan)) < 0.4 * len(sb):
            continue
        sm = SequenceMatcher(None, bt, jan, autojunk=False)
        sc = sum(x.size for x in sm.get_matching_blocks()) / max(n, 1)
        if sc >= 0.5:
            cand.append((sc, i))
    cand.sort(reverse=True); esc = []
    for sc, i in cand:
        if all(abs(i - j) > n * 0.7 for _, j in esc):
            esc.append((sc, i))
    esc.sort(key=lambda x: x[1])
    return [{"score": round(sc, 2), "ini": cues[tcue[i]][0], "fim": cues[tcue[min(i + L - 1, len(toks) - 1)]][1], "tok": i} for sc, i in esc]


def limites_da_aula(cues):
    """(T0, T1, cues úteis): começo e fim da aula pela transcrição (mesma regra do screencast/TV)"""
    from detectar_erros import detectar, tira_alucinacao
    limpos = tira_alucinacao([list(c) for c in cues])
    try:
        d = detectar([list(c) for c in limpos]); T0, T1 = d["T0"], d["T1"]
    except Exception:      # noqa: BLE001 - transcrição estranha: usa a fala inteira
        T0, T1 = (limpos[0][0], limpos[-1][1]) if limpos else (0.0, 0.0)
    return T0, T1, [c for c in limpos if c[0] >= T0 - 0.01 and c[1] <= T1 + 0.01]


def segmenta(itens, uteis):
    """Divide a fala, NA ORDEM, em um trecho para cada item (texto de slide): cada frase da transcrição vai para o item
    com que mais se parece, sem voltar atrás. Devolve {id: (segundo em que o trecho começa, força, nº de frases)}.
    Parecido = palavras em comum, pesando mais as que só aquele item tem (palavra que aparece em todos quase não conta).
    Funciona mesmo quando o professor fala com as próprias palavras em vez de ler igual."""
    N, M = len(itens), len(uteis)
    if not N or not M:
        return {}
    pal = [set(w for w in norm(t) if len(w) >= 3 and w not in STOP) for _, t in itens]
    df = {}
    for p in pal:
        for w in p:
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log((N + 1) / v) for w, v in df.items()}
    wc = [set(w for w in norm(c[2]) if len(w) >= 3) for c in uteis]
    cru = [[sum(idf[w] for w in wc[i] & pal[k]) for i in range(M)] for k in range(N)]
    # cada frase também "puxa" um pouco as vizinhas: frase de ligação (sem palavra própria) acompanha o assunto ao redor
    af = [[cru[k][i] + 0.5 * ((cru[k][i - 1] if i else 0.0) + (cru[k][i + 1] if i + 1 < M else 0.0)) for i in range(M)] for k in range(N)]
    NEG = -1e18
    f = [[NEG] * (M + 1) for _ in range(N + 1)]          # f[k][i]: melhor soma com as i primeiras frases repartidas entre os k primeiros itens
    f[0][0] = 0.0
    for k in range(1, N + 1):
        f[k][0] = 0.0
        for i in range(1, M + 1):
            f[k][i] = max(f[k - 1][i], f[k][i - 1] + af[k - 1][i - 1])
    ini = [M] * N; k, i = N, M
    while k > 0 and i > 0:
        if f[k][i] == f[k - 1][i]:            # empate: a frase fica com o item anterior (o slide só entra quando o assunto começa)
            k -= 1
        else:
            i -= 1; ini[k - 1] = i
    res = {}
    for k in range(N):
        fim = min([x for x in ini[k + 1:] if x < M] + [M])
        if ini[k] >= fim:
            continue
        ditas = set().union(*wc[ini[k]:fim]) & pal[k]
        topo = sorted(pal[k], key=lambda w: -idf[w])[:16]
        tot = sum(idf[w] for w in topo)
        forca = sum(idf[w] for w in topo if w in ditas) / tot if tot else 0.0
        res[itens[k][0]] = (uteis[ini[k]][0], forca, fim - ini[k])
    return res


def ancora(texto, a, b):
    return {"tipo": "fala", "texto": texto, "n": 8, "cand": [{"score": 1.0, "ini": a, "fim": b, "tok": 0}]}


def modo_a(slides, cues, eh_texto):
    T0, T1, uteis = limites_da_aula(cues)
    toks, tcue = [], []
    for ci, (a, b, t) in enumerate(cues):
        for w in norm(t):
            toks.append(w); tcue.append(ci)
    visuais = [s for s in slides if not eh_texto[s["n"]] and (s["texto"] or s["imgs"])]
    fora = set()
    if visuais:
        fora.add(visuais[0]["n"]); fora.add(visuais[-1]["n"])          # capa e encerramento
    for s in visuais:
        if re.match(r"\s*(refer[eê]ncias?|cr[eé]ditos?|bibliografia|obrigad[oa]|d[uú]vidas?)\b", s["texto"], flags=re.I):
            fora.add(s["n"])
    grupos, pend, sem_texto = [], [], []                               # (slide visual ou None, [slides de texto lidos antes dele])
    for s in slides:
        if eh_texto[s["n"]]:
            pend.append(s); continue
        if not (s["texto"] or s["imgs"]):
            continue                                                   # slide vazio
        if not pend and s["n"] not in fora:
            sem_texto.append(s["n"])
        grupos.append((s, pend)); pend = []
    if pend:
        grupos.append((None, pend))
    # onde começa a leitura de cada texto: pelo ASSUNTO (o professor costuma falar com as próprias palavras, não ler igual)
    itens = []
    for k, (s, txts) in enumerate(grupos):
        ini = " ".join(" ".join(blocos_de_fala(t["paras"])) for t in txts)
        if ini:
            itens.append((k, ini))
    onde = {k: v for k, v in segmenta(itens, uteis).items() if v[1] >= LIM_A}
    roteiro = []; ult_entrada = -10.0
    todos = segmenta(itens, uteis)
    for k, (s, txts) in enumerate(grupos):
        fs = []
        for t in txts:
            for bl in blocos_de_fala(t["paras"]):
                fs.append({"tipo": "fala", "texto": bl, "n": len(norm(bl)), "cand": acha_na_fala(bl, toks, tcue, cues)})
        if s is None or s["n"] in fora or not txts:
            roteiro += fs; continue
        if k in onde:
            t, q, _ = onde[k]; como = "assunto"
            # se o começo do texto foi lido quase igual, esse instante é mais exato que o do assunto
            exatos = [c["ini"] for c in (fs[0]["cand"] if fs else []) if t - 75 <= c["ini"] <= t + 6 and c["ini"] >= ult_entrada + 2]
            if exatos:
                t = exatos[-1]; como = "leitura"
            t = max(t, ult_entrada + 2); ult_entrada = t
            roteiro.append({"tipo": "INSERÇÃO EM TELA", "cartela": f"S{s['n']}"})
            roteiro.append(ancora(f"(entrada do slide {s['n']})", t, t + 2.0))
            print(f"slide {s['n']:2d}: entra em {t:7.1f}s (semelhança {q:.2f}) | {como} | {s['texto'][:50]}")
            roteiro += fs
            roteiro.append({"tipo": "PAUSA"})
        elif any(f["cand"] for f in fs):
            roteiro.append({"tipo": "INSERÇÃO EM TELA", "cartela": f"S{s['n']}"}); roteiro += fs; roteiro.append({"tipo": "PAUSA"})
            print(f"slide {s['n']:2d}: entra no primeiro trecho lido igual ao texto | {s['texto'][:50]}")
        else:
            roteiro += fs
            print(f"slide {s['n']:2d}: não achei na fala o texto correspondente (não inserido; força {todos.get(k, (0, 0, 0))[1]:.2f}) | {s['texto'][:50]}")
    if sem_texto:
        print("aviso: slides visuais sem slide de texto antes (não inseridos): " + ", ".join(map(str, sem_texto)))
    # começo e fim da aula garantidos mesmo se o primeiro/último texto não for achado
    if not any(f["tipo"] == "fala" and f["cand"] and f["cand"][0]["ini"] <= T0 + 20 for f in roteiro[:4]):
        roteiro.insert(0, ancora("(início da aula)", T0, min(T1, T0 + 3.0)))
    roteiro.append(ancora("(fim da aula)", max(T0, T1 - 3.0), T1))
    return roteiro


def modo_b(slides, cues):
    T0, T1, uteis = limites_da_aula(cues)
    com_texto = [s for s in slides if s["texto"]]
    cont = [s for s in slides[1:-1] if s["texto"]]
    onde = {k: v for k, v in segmenta([(s["n"], s["texto"]) for s in com_texto], uteis).items() if v[1] >= LIM_B and v[2] >= 2}
    roteiro = [ancora("(início da aula)", T0, min(T1, T0 + 3.0))]
    for s in cont:
        if s["n"] not in onde:
            print(f"slide {s['n']:2d}: sem trecho parecido na fala (não inserido) | {s['texto'][:50]}"); continue
        t, q, _ = onde[s["n"]]
        roteiro.append({"tipo": "INSERÇÃO EM TELA", "cartela": f"S{s['n']}"})
        roteiro.append(ancora(s["texto"][:120], t, min(T1, t + DUR_B)))
        roteiro.append({"tipo": "PAUSA"})
        print(f"slide {s['n']:2d}: entra em {t:7.1f}s (semelhança {q:.2f}) | {s['texto'][:50]}")
    roteiro.append(ancora("(fim da aula)", max(T0, T1 - 3.0), T1))
    return roteiro


def main(pptx, srt, saida):
    cues = le_srt(srt)
    if pptx == "-":      # sem slides: só o começo e o fim da aula, nenhuma inserção
        T0, T1, _ = limites_da_aula(cues)
        print("SEM INSERÇÃO: só a sequência montada")
        json.dump({"roteiro": [ancora("(início da aula)", T0, min(T1, T0 + 3.0)), ancora("(fim da aula)", max(T0, T1 - 3.0), T1)], "modo": "-"}, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    slides = le_pptx(pptx)
    bt = bigr(norm(" ".join(c[2] for c in cues)))
    eh_texto, marc = {}, 0
    for s in slides:
        tk = norm(s["texto"]); b = bigr(tk)
        lido = (len(b & bt) / len(b)) if b else 0.0                 # quanto do slide foi dito palavra por palavra
        m = bool(RE_CAB.match(s["texto"])); marc += m
        eh_texto[s["n"]] = m or (len(tk) >= 25 and lido >= 0.5 and s["imgs"] == 0)
    n_txt = sum(eh_texto.values())
    seguidos = sum(1 for a, b in zip(slides, slides[1:]) if eh_texto[a["n"]] and not eh_texto[b["n"]])
    # roteiro dentro do pptx: pelos cabecalhos "[Slide N - ...]" ou, sem eles, so se os slides de texto forem quase metade e alternarem com os visuais
    # (slide comum que o professor leu quase igual NAO e slide de roteiro)
    modo = "A" if (marc >= 3 or (n_txt >= 4 and n_txt >= 0.45 * len(slides) and seguidos >= 0.8 * n_txt)) else "B"
    modo = os.environ.get("ALINHAR_MODO") or modo
    if modo == "A":
        print(f"MODO A: roteiro dentro do pptx ({n_txt} slides de texto, {len(slides) - n_txt} visuais)")
        roteiro = modo_a(slides, cues, eh_texto)
    else:
        print("MODO B: sem roteiro; cada slide entra onde o assunto dele aparece na fala (conferir as posições)")
        roteiro = modo_b(slides, cues)
    json.dump({"roteiro": roteiro, "modo": modo}, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in roteiro:
        if r["tipo"] == "fala":
            print(f"n={r['n']:3d} cands:", [(x['score'], round(x['ini'], 1)) for x in r["cand"]], "|", r["texto"][:50])
        else:
            print(f"[{r['tipo']} {r.get('cartela') or ''}]")


if __name__ == "__main__":
    main(*sys.argv[1:4])
