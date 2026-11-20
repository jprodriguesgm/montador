#!/usr/bin/env python3
"""Alinha o roteiro (DOCX) de um vídeo com a transcrição (SRT) e decide em que parte entra cada slide do PPTX.
Uso: python3 -I alinhar_notas.py ROTEIRO.docx SLIDES.pptx|- bruto.srt saida.json
(SLIDES = "-" quando o vídeo não tem slides)
Os slides de conteúdo (2 até o penúltimo) viram "INSERÇÃO EM TELA"; o slide fica até a "PAUSA" que fecha o trecho.
A fala de cada slide é descoberta comparando o roteiro com as notas do slide (notas = texto lido naquele slide).
Só usa a biblioteca padrão do Python."""
import os, sys, re, json, zipfile, unicodedata
from difflib import SequenceMatcher


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


def texto_xml(x):
    x = re.sub(r"<w:tab/>", " ", x)
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", x)).replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">")


def negritos(par):
    """trechos em negrito de um parágrafo (candidatos a palavra-chave); parágrafo todo em negrito é título e não conta"""
    partes, cur, tudo = [], "", True
    for run in re.findall(r"<w:r[ >].*?</w:r>", par, flags=re.S):
        t = texto_xml(run)
        if not t:
            continue
        rpr = re.search(r"<w:rPr>.*?</w:rPr>", run, flags=re.S)
        b = bool(rpr and re.search(r"<w:b(?:\s+w:val=\"(?:1|true|on)\")?\s*/>", rpr.group(0)))
        if b:
            cur += t
        else:
            if t.strip():
                tudo = False
            if cur.strip():
                partes.append(cur)
            cur = "" if t.strip() else cur + t
    if cur.strip():
        partes.append(cur)
    if tudo:
        return []
    out = []
    for x in partes:
        x = " ".join(x.split()).strip(" .,;:!?()[]\"'“”")
        if x and 1 <= len(norm(x)) <= 8 and x not in out:
            out.append(x)
    return out


def le_docx2(p):
    """Parágrafos do roteiro, na ordem, como {"t": texto, "notas": [...], "slide": n ou None}.
    - Tabela de DUAS COLUNAS: a coluna da esquerda é a fala; o texto da direita é a instrução de inserção daquela linha
      (vira NOTA = marcador para o editor; se citar "slide N", a linha fica ligada a esse slide).
    - NEGRITO_PC=1 (dia de palavra-chave sem pptx): cada trecho em negrito vira NOTA "palavra-chave: ..."."""
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf8")
    com_negrito = os.environ.get("NEGRITO_PC") == "1"
    out = []

    def paragrafos(trecho, notas=None, slide=None):
        primeiro = True
        for par in re.findall(r"<w:p[ >].*?</w:p>", trecho, flags=re.S):
            t = " ".join(texto_xml(par).split())
            if not t or re.match(r"^(roteiro aulas|v[ií]deo \d+)", t.lower()):
                continue
            ns = list(notas or []) if primeiro else []
            if com_negrito:
                ns += [{"tipo": "NOTA", "texto": "palavra-chave: " + x, "palavra": x} for x in negritos(par)]
            out.append({"t": t, "notas": ns, "slide": slide}); primeiro = False
        if primeiro and notas:          # linha com instrução mas sem fala: a instrução vale para a próxima fala
            out.append({"t": "", "notas": list(notas), "slide": slide})

    for parte in re.split(r"(<w:tbl>.*?</w:tbl>)", xml, flags=re.S):
        if not parte.startswith("<w:tbl>"):
            paragrafos(parte); continue
        linhas = [re.findall(r"<w:tc>.*?</w:tc>|<w:tc [^>]*>.*?</w:tc>", l, flags=re.S) for l in re.findall(r"<w:tr[ >].*?</w:tr>", parte, flags=re.S)]
        duas = linhas and sum(1 for c in linhas if len(c) == 2) >= 0.7 * len(linhas)
        for k, cel in enumerate(linhas):
            if not duas or len(cel) != 2:
                paragrafos("".join(cel)); continue
            esq = " ".join(texto_xml(cel[0]).split()); dire = " ".join(" ".join(texto_xml(x).split()) for x in re.findall(r"<w:p[ >].*?</w:p>", cel[1], flags=re.S)).strip()
            if k == 0 and len(norm(esq)) <= 4 and len(norm(dire)) <= 4:
                continue                    # cabeçalho da tabela (ex.: "Fala | Inserção")
            m = re.search(r"\bslides?\s*n?[ºo°.]?\s*(\d+)", dire, flags=re.I)
            paragrafos(cel[0], [{"tipo": "NOTA", "texto": "inserção (roteiro): " + dire[:400]}] if dire else None, int(m.group(1)) if m else None)
    return out


def le_docx(p):
    return [x["t"] for x in le_docx2(p) if x["t"]]


def notas_slides(p):
    z = zipfile.ZipFile(p)
    n = len([x for x in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", x)])
    res = []
    for i in range(1, n + 1):
        nt = ""
        try:
            rel = z.read(f"ppt/slides/_rels/slide{i}.xml.rels").decode()
            m = re.search(r"notesSlides/(notesSlide\d+)\.xml", rel)
            if m:
                nt = " ".join(re.sub(r"<[^>]+>", " ", z.read(f"ppt/notesSlides/{m.group(1)}.xml").decode()).split())
        except KeyError:
            pass
        res.append(nt)
    return res


def bigr(tk):
    return set(zip(tk, tk[1:]))


def main(docx, pptx, srt, saida):
    cues = le_srt(srt)
    itens = le_docx2(docx)
    paras = [x["t"] for x in itens]; notas_par = [x["notas"] for x in itens]
    tab_slides = [x["slide"] or 0 for x in itens] if any(x["slide"] for x in itens) else None
    explicito = None
    if any(re.match(r"^SLIDE \d+\b", p) for p in paras):
        # roteiro com cabeçalhos "SLIDE N título": o slide de cada fala é o do cabeçalho; cabeçalhos e metadados não são falas
        explicito = []; novas = []; nn = []; atual = None
        for p, nt in zip(paras, notas_par):
            m = re.match(r"^SLIDE (\d+)\b", p)
            if m:
                atual = int(m.group(1)); continue
            if atual is None:
                continue
            novas.append(p); explicito.append(atual); nn.append(nt)
        paras = novas; notas_par = nn
    elif tab_slides and pptx != "-":
        explicito = tab_slides              # roteiro em duas colunas citando "slide N" na coluna da direita
    toks, tcue = [], []
    for ci, (a, b, t) in enumerate(cues):
        for w in norm(t):
            toks.append(w); tcue.append(ci)
    falas = []; pend = []
    for t, nt in zip(paras, notas_par):
        pend += nt
        bt = norm(t)
        if len(bt) < 3:
            continue
        falas.append({"tipo": "fala", "texto": t, "n": len(bt), "notas": pend}); pend = []
    # --- slide de cada parágrafo
    slide_de = [1] * len(falas)
    if explicito is not None:
        _ex = [explicito[i] for i, p in enumerate(paras) if len(norm(p)) >= 3]
        slide_de = _ex
    elif pptx != "-":
        notas = notas_slides(pptx)
        total = len(notas)
        bn = [bigr(norm(x)) for x in notas]
        atual = 1
        for i, f in enumerate(falas):
            b = bigr(norm(f["texto"]))
            if not b:
                slide_de[i] = atual; continue
            pont = [len(b & bn[k]) / len(b) for k in range(total)]
            k = max(range(total), key=lambda j: pont[j])
            if pont[k] >= 0.35 and k + 1 >= atual:
                atual = k + 1
            slide_de[i] = atual
    # --- alinhamento com a transcrição
    for f in falas:
        bt = norm(f["texto"]); n = len(bt)
        cand = []
        L = max(3, int(n * 1.15))
        for i in range(0, max(1, len(toks) - n // 2)):
            sm = SequenceMatcher(None, bt, toks[i:i + L], autojunk=False)
            sc = sum(x.size for x in sm.get_matching_blocks()) / max(n, 1)
            if sc >= 0.5:
                cand.append((sc, i))
        cand.sort(reverse=True); esc = []
        for sc, i in cand:
            if all(abs(i - j) > n * 0.7 for _, j in esc):
                esc.append((sc, i))
        esc.sort(key=lambda x: x[1])
        f["cand"] = [{"score": round(sc, 2), "ini": cues[tcue[i]][0], "fim": cues[tcue[min(i + L - 1, len(toks) - 1)]][1], "tok": i} for sc, i in esc]
    # --- monta o roteiro com as inserções (slides 2 .. penúltimo)
    roteiro = []
    ultimo = max(slide_de)
    total = len(notas_slides(pptx)) if pptx != "-" else 1
    for i, f in enumerate(falas):
        s = slide_de[i]
        ant = slide_de[i - 1] if i else 0
        if s != ant and 2 <= s < total:
            roteiro.append({"tipo": "INSERÇÃO EM TELA", "cartela": f"S{s}"})
        roteiro += f.pop("notas", [])          # instruções do roteiro (coluna de inserções / negrito): viram marcadores
        roteiro.append(f)
        if 2 <= s < total and (i + 1 == len(falas) or slide_de[i + 1] != s):
            roteiro.append({"tipo": "PAUSA"})
    json.dump({"roteiro": roteiro}, open(saida, "w"), ensure_ascii=False, indent=1)
    for r in roteiro:
        if r["tipo"] == "fala":
            print(f"n={r['n']:3d} cands:", [(x['score'], round(x['ini'], 1)) for x in r["cand"]], "|", r["texto"][:50])
        else:
            print(f"[{r['tipo']} {r.get('cartela') or r.get('texto', '')[:70]}]")


if __name__ == "__main__":
    main(*sys.argv[1:5])
