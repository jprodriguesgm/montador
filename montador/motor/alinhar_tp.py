#!/usr/bin/env python3
"""Casa os blocos de fala do roteiro TP (PPTX) com a transcrição (SRT) de um bruto.
Uso: python3 -I alinhar_tp.py TP-aula-NN.pptx bruto.srt saida.json
Saída: blocos com início/fim (s do bruto), tentativas repetidas e cues (PAUSA, INSERÇÃO EM TELA Cxx)."""
import sys, re, json, unicodedata
from difflib import SequenceMatcher
from pptx import Presentation

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

def le_roteiro(p):
    itens = []
    for i, s in enumerate(Presentation(p).slides, 1):
        txt = [sh.text_frame.text.strip() for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        if not txt or "CAPA" in " ".join(txt):
            continue
        m = re.match(r"\[(ABERTURA|PAUSA|ENCERRAMENTO|INSERÇÃO EM TELA:\s*(C\d+))\]", txt[0])
        if m:
            itens.append({"slide": i, "tipo": m.group(1).split(":")[0].strip(), "cartela": m.group(2)})
        else:
            itens.append({"slide": i, "tipo": "fala", "texto": txt[0]})
    return itens

def main(pptx, srt, saida):
    cues = le_srt(srt); roteiro = le_roteiro(pptx)
    toks, tcue = [], []
    for ci, (a, b, t) in enumerate(cues):
        for w in norm(t):
            toks.append(w); tcue.append(ci)
    falas = [r for r in roteiro if r["tipo"] == "fala"]
    for r in falas:
        bt = norm(r["texto"]); n = len(bt); r["n"] = n
        cand = []
        L = max(3, int(n * 1.15))
        for i in range(0, max(1, len(toks) - n // 2)):
            janela = toks[i:i + L]
            sm = SequenceMatcher(None, bt, janela, autojunk=False)
            sc = sum(x.size for x in sm.get_matching_blocks()) / max(n, 1)
            if sc >= 0.5:
                cand.append((sc, i))
        # máximos locais não sobrepostos
        cand.sort(reverse=True); esc = []
        for sc, i in cand:
            if all(abs(i - j) > n * 0.7 for _, j in esc):
                esc.append((sc, i))
        esc.sort(key=lambda x: x[1])
        r["cand"] = [{"score": round(sc, 2), "ini": cues[tcue[i]][0], "fim": cues[tcue[min(i + L - 1, len(toks) - 1)]][1], "tok": i} for sc, i in esc]
    json.dump({"roteiro": roteiro}, open(saida, "w"), ensure_ascii=False, indent=1)
    for r in roteiro:
        if r["tipo"] == "fala":
            c = r["cand"]
            print(f"s{r['slide']:02d} n={r['n']:3d} cands:", [(x['score'], round(x['ini'], 1)) for x in c])
        else:
            print(f"s{r['slide']:02d} [{r['tipo']} {r.get('cartela') or ''}]")

if __name__ == "__main__":
    main(*sys.argv[1:4])
