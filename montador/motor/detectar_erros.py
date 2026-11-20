#!/usr/bin/env python3
"""Detecta trechos de ERRO em um bruto de screencast (sem roteiro), a partir da transcrição SRT.
Uso: python3 -I detectar_erros.py bruto.srt saida.json
Saída: {"T0":..,"T1":..,"trechos":[[ini,fim,"ok"|"erro","motivo"],...]}  (segundos do bruto)
Regras (só marcam, nunca apagam):
  - começo: bastidores até a 1ª fala "de aula" (cue longo, que não é conversa com a equipe);
  - fim: depois da última fala de aula;
  - interrupção: conversa com a equipe / pedido de pausa / ruído / silêncio longo;
  - tentativa repetida: bloco que o professor volta a dizer logo depois (vale o último);
  - pausa longa entre falas (> PAUSA_LONGA s)."""
import sys, re, json, unicodedata

PAUSA_LONGA = 3.0
LIMIAR_REPETICAO = 0.60   # sobreposição de palavras de conteúdo
LIMIAR_ABERTURA = 0.45    # sobreposição das primeiras palavras (recomeço do mesmo assunto)
INTERRUPCAO = re.compile(
    r"desculp|pera a[ií]|vou repetir|de novo|vou voltar|posso voltar|[eé] para voltar|pode voltar|pausa|"
    r"parece que eu|arrumar (os )?slide|trot|vou ajustar|deixa eu|um minuto|pode cortar|corta (isso|a[ií])|"
    r"estamos gravando|est[aá] gravando|quer colocar|a tela t[aá]|pode abrir|pode come[cç]ar|vou come[cç]ar|"
    r"gravando\?|t[aá] gravando|j[aá] est[aá] (gravando|rodando)|corrig|perd[aã]o|refaz|recome[cç]|ler de novo|ficou ruim", re.I)
PEDIDO_REFAZER = re.compile(r"corrig|refaz|recome[cç]|ler de novo|ficou ruim|vou repetir|de novo|vou voltar", re.I)
SAUDACAO = re.compile(r"\bol[aá]\b|bom dia|boa tarde|boa noite|meu nome [eé]|nesse v[ií]deo|neste v[ií]deo", re.I)
RUIDO = re.compile(r"^\s*\[[^\]]*\]\s*$")


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
            cues.append([a, b, " ".join(ln[2:]).strip()])
    return tira_alucinacao(cues)


def tira_alucinacao(cues):
    """Whisper inventa falas curtas ("E aí", "Abertura", "Legenda ...") em instantes
    múltiplos de 30 s sobre trechos silenciosos. Elas não são fala de verdade."""
    ok = []
    for a, b, t in cues:
        tk = re.findall(r"\w+", t)
        multiplo30 = abs(a / 30.0 - round(a / 30.0)) < 0.001
        if re.match(r"\s*legenda", t, re.I) or (multiplo30 and len(tk) <= 4 and not SAUDACAO.search(t)):
            continue
        ok.append([a, b, t])
    return ok


def bigr(tk):
    return set(zip(tk, tk[1:]))


def junta_cues(cues, folga=0.8):
    """Whisper (mlx) devolve trechos muito curtos: junta os que estão colados (pausa < folga s) em frases."""
    out = []
    for a, b, t in cues:
        if out and a - out[-1][1] < folga and not RUIDO.match(t) and not RUIDO.match(out[-1][2]):
            out[-1][1] = b; out[-1][2] = (out[-1][2] + " " + t).strip()
        else:
            out.append([a, b, t])
    return out


def divide_pedidos(cues):
    """Se uma fala longa contém 'vou corrigir essa frase' etc., separa a frase errada (a anterior, se curta) e o pedido
    em um cue próprio (marcado como erro), com tempos proporcionais ao tamanho do texto. Devolve (cues, índices_erro)."""
    out, marc = [], set()
    for a, b, t in cues:
        fr = re.split(r"(?<=[.?!])\s+", t)
        k = next((j for j, f in enumerate(fr) if PEDIDO_REFAZER.search(f) and len(norm(f)) <= 14), None)
        if k is None or len(fr) == 1:
            out.append([a, b, t]); continue
        i0 = k - 1 if k > 0 and len(norm(fr[k - 1])) <= 25 else k
        partes = [(fr[:i0], False), (fr[i0:k + 1], True), (fr[k + 1:], False)]
        tot = max(1, len(t)); cur = a
        for pt, erro in partes:
            if not pt:
                continue
            tx = " ".join(pt); d = (b - a) * len(tx) / tot
            if erro:
                marc.add(len(out))
            out.append([cur, cur + d, tx]); cur += d
    return out, marc


def detectar(cues):
    cues, marc = divide_pedidos(junta_cues(cues))
    n = len(cues)
    estado = ["fala"] * n     # fala | erro
    motivo = [""] * n
    for i, (a, b, t) in enumerate(cues):
        if i in marc:
            estado[i], motivo[i] = "erro", "frase errada + pedido de correção"
        elif RUIDO.match(t):
            estado[i], motivo[i] = "erro", "ruído/silêncio"
        elif INTERRUPCAO.search(t) and len(norm(t)) <= 14:
            estado[i], motivo[i] = "erro", "interrupção/conversa com a equipe"
        elif len(norm(t)) <= 3:
            estado[i], motivo[i] = "erro", "fala muito curta (conversa)"
    # início: primeira fala de aula = 1ª fala longa que NÃO é interrupção e vem depois do último erro inicial
    ini = None
    for i in range(n):
        if cues[i][0] > 300:
            break
        if estado[i] == "fala" and SAUDACAO.search(cues[i][2]) \
                    and i + 1 < n and cues[i + 1][0] - cues[i][1] < 60:
            ini = i; break
    if ini is None:
        ini = next((i for i in range(n) if estado[i] == "fala" and len(norm(cues[i][2])) >= 8), 0)
    for i in range(ini):
        if estado[i] == "fala":
            estado[i], motivo[i] = "erro", "bastidor (antes da aula)"
    # blocos (parágrafos) separados por pausas > 1.5 s, para achar repetição
    blocos, cur = [], [0]
    for i in range(1, n):
        if cues[i][0] - cues[i - 1][1] > 1.5 or estado[i] != estado[i - 1]:
            blocos.append(cur); cur = [i]
        else:
            cur.append(i)
    blocos.append(cur)
    info = []
    for bl in blocos:
        tx = " ".join(cues[i][2] for i in bl)
        tk = norm(tx)
        info.append((bl, set(w for w in tk if len(w) >= 5), len(tk), set(tk[:9])))
    for x, (bl, bg, nt, ab) in enumerate(info):
        if estado[bl[0]] == "erro" or nt < 25:
            continue
        for y in range(x + 1, len(info)):
            bl2, bg2, nt2, ab2 = info[y]
            if cues[bl2[0]][0] - cues[bl[-1]][1] > 400:
                break
            if estado[bl2[0]] == "erro" or nt2 < 25 or not bg:
                continue
            comum = len(bg & bg2) / len(bg)
            abert = len(ab & ab2) / max(1, min(len(ab), len(ab2)))
            if (comum >= LIMIAR_REPETICAO or abert >= LIMIAR_ABERTURA) and cues[bl[-1]][1] - cues[bl[0]][0] <= 90:
                for i in bl:
                    estado[i], motivo[i] = "erro", f"tentativa repetida (refeita em {cues[bl2[0]][0]:.0f}s)"
                break
    # fim: depois da última fala de aula "longa" não-erro
    ultimo = max((i for i in range(n) if estado[i] == "fala"), default=n - 1)
    # trechos contíguos entre T0 e T1
    t0 = cues[ini][0]
    t1 = cues[ultimo][1]
    seg = []
    cursor = t0
    for i in range(ini, ultimo + 1):
        a, b, _ = cues[i]
        if a - cursor > PAUSA_LONGA and seg is not None:
            seg.append([cursor, a, "erro", f"pausa longa ({a - cursor:.1f}s)"])
        elif a > cursor:
            pass
        tipo = "erro" if estado[i] == "erro" else "ok"
        ini_s = max(a, cursor) if not (a - cursor > PAUSA_LONGA) else a
        if a - cursor <= PAUSA_LONGA and a > cursor:
            ini_s = cursor           # pequenas pausas ficam coladas ao trecho seguinte
        seg.append([ini_s, b, tipo, motivo[i]])
        cursor = b
    # junta vizinhos do mesmo tipo
    jun = []
    for s in seg:
        if jun and jun[-1][2] == s[2]:
            jun[-1][1] = s[1]
            if s[3] and s[3] not in jun[-1][3]:
                jun[-1][3] = (jun[-1][3] + "; " + s[3]).strip("; ")
        else:
            jun.append(list(s))
    return {"T0": t0, "T1": t1, "trechos": jun}


if __name__ == "__main__":
    r = detectar(le_srt(sys.argv[1]))
    json.dump(r, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    print(f"T0={r['T0']:.1f} T1={r['T1']:.1f}")
    for a, b, t, m in r["trechos"]:
        if t == "erro":
            print(f"  ERRO {a:7.1f}-{b:7.1f} ({b - a:5.1f}s) {m[:80]}")
