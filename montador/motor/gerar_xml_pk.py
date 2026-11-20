#!/usr/bin/env python3
"""Gera o XML (xmeml v4) do formato TP com palavra-chave a partir de um XML modelo exportado do Premiere.

Uso:
  python3 -I gerar_xml_pk.py MODELO.xml SRT PPTX PASTA_DIA BASE_BRUTO DURACAO_BRUTO_SEG JANELA_INI JANELA_FIM PASTA_SLIDES_PNG PASTA_CARTOES SAIDA.xml [NOME_SEQUENCIA]

  JANELA_INI/FIM = trecho do bruto (s) que pertence a esta aula (o bruto pode ter varias aulas / ser dividido ao meio)
  PASTA_SLIDES_PNG = pasta com os slides em PNG (nome.001.png ...)
  PASTA_CARTOES    = onde gravar os PNGs de texto (palavras-chave / itens) gerados aqui
O que faz (nada e apagado):
  V5 camera E cortada nos trechos (suspeitos: rotulo Rose + marcador "ERRO a conferir"); sem animacoes de zoom
  V9 itens curtos do slide (negrito do pptx destacado) como cartao de texto a esquerda; slides longos (artigos) como imagem do slide
  V10 palavra-chave do slide (caixa de titulo em negrito)
  V1/V2 fundo, V6 vinheta, V7 brasao, V8 intro/Lower Third/creditos, A1/A2 audio, A3/A4 audio da intro (como no modelo)
O texto do Lower Third e as transicoes ficam para o editor."""
import copy, json, os, re, sys, unicodedata, uuid, zipfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from urllib.parse import quote

(modelo, srt, pptx, pasta_dia, base, dur_s, j_ini, j_fim, pasta_png, pasta_cart, saida) = sys.argv[1:12]
nome_seq = sys.argv[12] if len(sys.argv) > 12 else "TP palavra-chave - TESTE montagem"
dur_s, j_ini, j_fim = float(dur_s), float(j_ini), float(j_fim)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detectar_erros as DET

FPS = 30000 / 1001
TICKS = 8475667200
OFFS = 148
ROTULO_ERRO = "Rose"
LIM_LONGO = 22          # palavras: acima disso o paragrafo vira imagem do slide (artigo); abaixo, cartao de texto
CARD_MIN, CARD_MAX = 3.0, 15.0


def fr(s):
    return round(s * FPS)


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", t)


def url_local(caminho):
    return "file://localhost" + quote(unicodedata.normalize("NFD", caminho), safe="/")


# ---------------------------------------------------------------- pptx (so biblioteca padrao)
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main", "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def le_pptx(p):
    z = zipfile.ZipFile(p)
    pres = ET.fromstring(z.read("ppt/presentation.xml"))
    rels = ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    alvo = {r.get("Id"): r.get("Target") for r in rels}
    slides = []
    for sid in pres.find("p:sldIdLst", NS):
        t = alvo[sid.get("{%s}id" % NS["r"])]
        x = ET.fromstring(z.read("ppt/" + t.lstrip("/").replace("ppt/", "")))
        shapes = []
        for sp in x.iter("{%s}sp" % NS["p"]):
            nome = sp.find("p:nvSpPr/p:cNvPr", NS).get("name", "")
            if "SlideNo" in nome or "Slide Number" in nome:
                continue
            paras = []
            for pa in sp.iter("{%s}p" % NS["a"]):
                runs = []
                for r in pa.findall("a:r", NS):
                    t_ = r.findtext("a:t", "", NS)
                    rp = r.find("a:rPr", NS)
                    runs.append((t_, bool(rp is not None and rp.get("b") == "1")))
                txt = "".join(t for t, _ in runs).strip()
                if txt:
                    paras.append(runs)
            if paras:
                shapes.append(paras)
        slides.append(shapes)
    return slides


def texto(runs):
    return " ".join("".join(t for t, _ in runs).split())


def palavras_neg(runs):
    """[(palavra, negrito)] preservando o negrito de cada palavra."""
    out = []
    for t, b in runs:
        for w in t.split():
            out.append((w, b))
    return out


def classifica(slides):
    """itens por slide: ('palavra'|'cartao'|'slide', slide_idx(1..), runs)"""
    itens = []
    for si, shapes in enumerate(slides, 1):
        for sh in shapes:
            todos_neg = all(b for pa in sh for _, b in pa if _.strip())
            nw = sum(len(norm(texto(pa))) for pa in sh)
            if todos_neg and nw <= 8:
                itens.append(("palavra", si, [r for pa in sh for r in pa])); continue
            for pa in sh:
                t = texto(pa); n = len(norm(t))
                if n < 3 or (t.isupper() and not any(b for _, b in pa)):
                    continue
                itens.append(("slide" if n >= LIM_LONGO else "cartao", si, pa))
    return itens


# ---------------------------------------------------------------- SRT e alinhamento
def ts(s):
    h, m, r = s.split(":"); sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def le_srt(p):
    cues = []
    for b in re.split(r"\n\s*\n", open(p, encoding="utf-8-sig").read().strip()):
        ln = b.strip().split("\n")
        if len(ln) >= 3 and "-->" in ln[1]:
            a, z = [ts(x.strip()) for x in ln[1].split("-->")]
            cues.append([a, z, " ".join(ln[2:]).strip()])
    return cues


cues_all = le_srt(srt)
cues = [c for c in cues_all if c[0] >= j_ini - 15 and c[1] <= j_fim + 1]
toks, tcue = [], []
for ci, (a, b, t) in enumerate(cues):
    for w in norm(t):
        toks.append(w); tcue.append(ci)


def acha(texto_item, apos):
    bt = norm(texto_item); n = len(bt)
    L = max(3, int(n * 1.2))
    cand = []
    for i in range(0, max(1, len(toks) - n // 2)):
        if cues[tcue[i]][0] < j_ini - 5 or cues[tcue[i]][0] > j_fim:
            continue
        sm = SequenceMatcher(None, bt, toks[i:i + L], autojunk=False)
        mb = [m for m in sm.get_matching_blocks() if m.size]
        sc = sum(m.size for m in mb) / n
        if sc >= 0.55 and mb:
            i0 = i + mb[0].b; i1 = i + mb[-1].b + mb[-1].size - 1
            cand.append((sc, cues[tcue[i0]][0], cues[tcue[min(i1, len(toks) - 1)]][1]))
    if not cand:
        return None
    pos = [c for c in cand if c[1] >= apos - 3] or cand
    m = max(c[0] for c in pos)
    return min((c for c in pos if c[0] >= m - 0.05), key=lambda c: c[1])


itens = classifica(le_pptx(pptx))
achados = []        # dicts
prev = j_ini
for tipo, si, runs in itens:
    if tipo == "palavra":
        continue
    r = acha(texto(runs), prev)
    if r:
        sc, a, b = r
        achados.append({"tipo": tipo, "slide": si, "runs": runs, "ini": a, "fim": b, "score": sc})
        prev = a
    else:
        print(f"  (nao localizado) slide {si} [{tipo}] {texto(runs)[:60]}")
# remove itens repetidos (o mesmo texto aparece em dois slides: vale o primeiro slide)
vistos, unicos = [], []
for x in achados:
    if any(abs(x["ini"] - y["ini"]) < 3 and x["tipo"] == y["tipo"] for y in unicos):
        continue
    unicos.append(x)
achados = unicos
# palavra-chave: quando o professor diz a palavra (perto do inicio do slide); senao, no inicio do slide
for tipo, si, runs in itens:
    if tipo != "palavra":
        continue
    do_slide = [x for x in achados if x["slide"] == si]
    if not do_slide:
        r = acha(texto(runs), j_ini) if len(norm(texto(runs))) >= 2 else None
        if r and r[0] >= 0.75:
            achados.append({"tipo": "palavra", "slide": si, "runs": runs, "ini": r[1], "fim": r[1] + 5.0, "score": r[0]})
        else:
            print(f"  (palavra sem slide localizado) slide {si} {texto(runs)}")
        continue
    s0, s1 = min(x["ini"] for x in do_slide), max(x["fim"] for x in do_slide)
    alvo = [w for w in norm(texto(runs)) if len(w) >= 5] or norm(texto(runs))
    ini = s0
    for a, b, t in cues:
        if s0 - 8 <= a <= s1 and any(w in norm(t) for w in alvo):
            ini = a; break
    achados.append({"tipo": "palavra", "slide": si, "runs": runs, "ini": ini, "fim": ini + 5.0, "score": 1.0})
# palavra-chave repetida (mesmo texto em dois slides, mesmo instante): fica uma so
_v, _u = [], []
for x in achados:
    if x["tipo"] == "palavra" and any(y["tipo"] == "palavra" and norm(texto(y["runs"])) == norm(texto(x["runs"])) and abs(y["ini"] - x["ini"]) < 3 for y in _u):
        continue
    _u.append(x)
achados = _u
# cartao curto (<6 palavras) do mesmo slide da palavra-chave e redundante (ex.: INSS / Instituto Nacional do Seguro Social)
pal_slides = {x["slide"] for x in achados if x["tipo"] == "palavra"}
achados = [x for x in achados if not (x["tipo"] == "cartao" and x["slide"] in pal_slides and len(norm(texto(x["runs"]))) < 6)]
achados.sort(key=lambda x: x["ini"])
# duracoes
for k, x in enumerate(achados):
    if x["tipo"] == "palavra":
        continue
    prox = [y["ini"] for y in achados[k + 1:] if y["tipo"] == x["tipo"] and y["slide"] == x["slide"]]
    fim = x["fim"] + (1.5 if x["tipo"] == "slide" else 1.0)
    if prox:
        fim = min(fim, prox[0])
    lim = 40 if x["tipo"] == "slide" else CARD_MAX
    x["fim"] = min(max(fim, x["ini"] + CARD_MIN), x["ini"] + lim)

# ---------------------------------------------------------------- erros / cortes
sel = [c for c in cues_all if c[0] >= j_ini - 20 and c[1] <= j_fim]
PLANO = json.load(open(os.environ["MONTADOR_PLANO"], encoding="utf-8")) if os.environ.get("MONTADOR_PLANO") \
    else DET.detectar([list(c) for c in sel])         # Montador: cortes da Skoopia (ou das regras) já planejados
T0, T1 = PLANO["T0"], PLANO["T1"]
seg = PLANO["trechos"]
aula = os.environ.get("AULA", "1")
ANINHADO = os.environ.get("ANINHADO") == "1"
nome_e = base if base.lower().endswith(".mp4") else base + ".mp4"      # BRUTO 3840x1080 (D/E viram sequências aninhadas)
POS_FALA = 175      # quadro (00;00;05;25) em que a 1ª fala deve começar: fim da vinheta de abertura


def onset_audio(caminho, t0, janela=40.0):
    """Instante (s) em que a fala começa de verdade, medido pelo áudio (o Whisper erra o início por vários segundos)."""
    import subprocess, shutil
    if not (shutil.which("ffmpeg") and os.path.exists(caminho)):
        return None
    a = max(0.0, t0 - 6.0)
    out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(a), "-t", str(janela), "-i", caminho, "-vn", "-ac", "1", "-ar", "16000",
                          "-af", "asetnsamples=n=320:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
                         capture_output=True, text=True).stdout
    v = []
    for m in re.finditer(r"pts_time:([\d.]+)\n.*?RMS_level=(\S+)", out):
        x = m.group(2); v.append((float(m.group(1)), -120.0 if x in ("-inf", "inf") else float(x)))
    if len(v) < 20:
        return None
    vs = sorted(x for _, x in v); piso = vs[len(vs) // 10]; lim = max(piso + 16, -55)
    for i in range(len(v) - 20):
        if all(x > lim for _, x in v[i:i + 20]):      # 400 ms seguidos acima do limiar
            return a + v[i][0]
    return None


_ons = os.environ.get("ONSET")
_ons = float(_ons) if _ons else (onset_audio(os.path.join(pasta_dia, "Footage", nome_e), T0) if ANINHADO else None)
if ANINHADO and _ons is not None:
    T0 = max(0.0, _ons - (POS_FALA - OFFS) / FPS)      # a câmera começa no quadro 148 e a fala cai exatamente no quadro POS_FALA
    seg[:] = [x for x in seg if x[1] > T0 + 0.05] or seg
    seg[0][0] = T0

# ---------------------------------------------------------------- cartoes de texto (PNG)
try:
    import PIL
except ImportError:      # python em modo isolado (-I) nao enxerga o Pillow instalado na pasta do usuario
    import site; site.addsitedir(site.getusersitepackages())
from PIL import Image, ImageDraw, ImageFont
def _acha_fonte(nome):
    for pasta in (os.path.expanduser("~/Library/Fonts/"), "/Library/Fonts/", "/System/Library/Fonts/Supplemental/", "/usr/share/fonts/truetype/google-fonts/"):
        if os.path.exists(pasta + nome):
            return pasta + nome
    sys.exit(f"Fonte {nome} não encontrada (instale a Poppins: Poppins-Light.ttf e Poppins-Bold.ttf em ~/Library/Fonts).")


class _FD:
    pass
os.makedirs(pasta_cart, exist_ok=True)


def desenha(runs, destaque, caminho):
    tam = 92 if destaque else 70
    fl = ImageFont.truetype(_acha_fonte("Poppins-Light.ttf"), tam); fb = ImageFont.truetype(_acha_fonte("Poppins-Bold.ttf"), tam)
    ws = palavras_neg(runs)
    largura = 620; esp = fl.getlength(" ")
    linhas, cur, w_cur = [], [], 0
    for w, b in ws:
        f = fb if b else fl
        wl = f.getlength(w)
        if cur and w_cur + esp + wl > largura:
            linhas.append(cur); cur, w_cur = [], 0
        cur.append((w, b, f, wl)); w_cur += (esp if len(cur) > 1 else 0) + wl
    if cur:
        linhas.append(cur)
    alt_l = int(tam * 1.35); h = alt_l * len(linhas)
    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0)); sombra = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(img), ImageDraw.Draw(sombra)
    y = 470 - h // 2
    for ln in linhas:
        x = 190
        for w, b, f, wl in ln:
            ds.text((x + 3, y + 4), w, font=f, fill=(0, 0, 0, 110)); d.text((x, y), w, font=f, fill=(255, 255, 255, 255)); x += wl + esp
        y += alt_l
    from PIL import ImageFilter
    out = Image.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(5)), img)
    out.save(caminho)


for k, x in enumerate(achados):
    if x["tipo"] in ("cartao", "palavra"):
        x["png"] = os.path.join(pasta_cart, f"{k + 1:02d}_{x['tipo']}.png")
        desenha(x["runs"], x["tipo"] == "palavra", x["png"])
    else:
        x["png"] = os.path.join(pasta_png, f"{os.path.splitext(os.path.basename(pptx))[0]}.{x['slide']:03d}.png")

# ---------------------------------------------------------------- XML
tree = ET.parse(modelo); root = tree.getroot(); seq = root.find("sequence")
vtr = seq.findall("media/video/track"); atr = seq.findall("media/audio/track")
defs = {}
for f in root.iter("file"):
    if len(f) > 0 and f.get("id") and f.get("id") not in defs:
        defs[f.get("id")] = copy.deepcopy(f)
contador = {"n": max(int(c.get("id").split("-")[1]) for c in root.iter("clipitem")), "f": 900}


def novo_id():
    contador["n"] += 1
    return f"clipitem-{contador['n']}"


def txt(c, tag, v):
    c.find(tag).text = str(v)


def pos(c, ini, fim, em, fora):
    txt(c, "start", ini); txt(c, "end", fim); txt(c, "in", em); txt(c, "out", fora)
    txt(c, "pproTicksIn", em * TICKS); txt(c, "pproTicksOut", fora * TICKS)


usados = set()


def arq(clip, definicao=None):
    f = clip.find("file"); i = list(clip).index(f); clip.remove(f)
    fid = definicao.get("id") if definicao is not None else f.get("id")
    if fid in usados:
        novo = ET.Element("file", {"id": fid})
    else:
        novo = copy.deepcopy(definicao if definicao is not None else defs[fid]); usados.add(fid)
    novo.set("id", fid)
    clip.insert(i, novo)


def rotulo(clip, nome):
    ls = clip.find("labels")
    if ls is None:
        ls = ET.SubElement(clip, "labels")
    for x in list(ls):
        ls.remove(x)
    ET.SubElement(ls, "label2").text = nome


def molde(trilha, nome=None, i=0):
    cs = [c for c in trilha.findall("clipitem") if nome is None or c.findtext("name") == nome]
    return copy.deepcopy(cs[i])


m_e = molde(vtr[4]); m_hex = molde(vtr[0]); m_deg = molde(vtr[1]); m_vig = molde(vtr[5]); m_bra = molde(vtr[6])
m_intro = molde(vtr[7], "Final_cima_v4_mov.mov"); m_lower = molde(vtr[7], "Lower Third 2025"); m_cred = molde(vtr[7], "tela_creditos_mov_v1.mov")
m_png = molde(vtr[7], "1-introdução 1.002.png")
m_a1 = molde(atr[0]); m_a2 = molde(atr[1]); m_a3 = molde(atr[2]); m_a4 = molde(atr[3])
id_e, id_raw = m_e.find("file").get("id"), m_a1.find("file").get("id")
cred_dist = int(seq.findtext("duration")) - int(m_cred.findtext("start"))
frames_arq = round(dur_s * 30)
dur_clip = round(frames_arq * 1000 / 1001)
if not ANINHADO:
    nome_e = f"{base}-E.mp4"
for _ef in m_e.iter("effect"):                      # câmera sem ajuste: o cinegrafista decide enquadramento/escala
    if _ef.findtext("effectid") == "basic":
        for _p in _ef.findall("parameter"):
            _id = _p.findtext("parameterid")
            if _id == "scale":
                _p.find("value").text = "100"
            elif _id == "rotation":
                _p.find("value").text = "0"
            elif _id == "center":
                _p.find("value/horiz").text = "0"; _p.find("value/vert").text = "0"
    elif _ef.findtext("effectid") == "crop":
        for _p in _ef.findall("parameter"):
            _p.find("value").text = "0"
d = defs[id_e]; d.find("name").text = nome_e
d.find("pathurl").text = url_local(os.path.join(pasta_dia, "Footage", nome_e)); d.find("duration").text = str(frames_arq)
fid_e = f"file-E{aula}"
if ANINHADO:
    for _w in d.iter("width"):
        _w.text = "3840"
    d.set("id", fid_e); id_e = id_raw = fid_e; defs[fid_e] = d
assert id_raw == id_e, "audio do modelo deve apontar para o mesmo arquivo da camera"

bord = [OFFS + fr(s[0] - T0) for s in seg] + [OFFS + fr(seg[-1][1] - T0)]
FIM = bord[-1]


NESTED = None; _nested_usado = [False]
if ANINHADO:
    _fdxml = ET.tostring(d, encoding="unicode")
    def _mov(h):
        return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>video</mediatype><pproBypass>false</pproBypass>"
                "<parameter authoringApp=\"PremierePro\"><parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax><value>100</value></parameter>"
                "<parameter authoringApp=\"PremierePro\"><parameterid>rotation</parameterid><name>Rotation</name><valuemin>-8640</valuemin><valuemax>8640</valuemax><value>0</value></parameter>"
                "<parameter authoringApp=\"PremierePro\"><parameterid>center</parameterid><name>Center</name><value><horiz>%s</horiz><vert>0</vert></value></parameter>"
                "<parameter authoringApp=\"PremierePro\"><parameterid>centerOffset</parameterid><name>Anchor Point</name><value><horiz>0</horiz><vert>0</vert></value></parameter></effect></filter>" % h)
    _R = "<rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>"
    _N = frames_arq
    def _tm(i, o):
        return f"<start>{i}</start><end>{o}</end><in>{i}</in><out>{o}</out><pproTicksIn>{i*TICKS}</pproTicksIn><pproTicksOut>{o*TICKS}</pproTicksOut>"
    _v, _a1, _a2 = novo_id(), novo_id(), novo_id()
    _lk = (f"<link><linkclipref>{_v}</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>"
           f"<link><linkclipref>{_a1}</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex><clipindex>1</clipindex><groupindex>1</groupindex></link>"
           f"<link><linkclipref>{_a2}</linkclipref><mediatype>audio</mediatype><trackindex>2</trackindex><clipindex>1</clipindex><groupindex>1</groupindex></link>")
    _nm = nome_e[:-4] + "-E"
    _fmt = f"<format><samplecharacteristics>{_R}<width>1920</width><height>1080</height><anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance><colordepth>24</colordepth></samplecharacteristics></format>"
    _xml = (f'<sequence id="sequence-E{aula}"><duration>{_N}</duration>{_R}<name>{_nm}</name><media><video>{_fmt}<track>'
            f'<clipitem id="{_v}"><masterclipid>masterclip-E{aula}</masterclipid><name>{nome_e}</name><enabled>TRUE</enabled><duration>{_N}</duration>{_R}{_tm(0,_N)}<alphatype>none</alphatype><pixelaspectratio>square</pixelaspectratio><anamorphic>FALSE</anamorphic>{_fdxml}{_mov(0.25)}{_lk}</clipitem>'
            f'<enabled>TRUE</enabled><locked>FALSE</locked></track></video><audio><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format><numOutputChannels>2</numOutputChannels>'
            + "".join(f'<track><clipitem id="{ai}" premiereChannelType="mono"><masterclipid>masterclip-E{aula}</masterclipid><name>{nome_e}</name><enabled>TRUE</enabled><duration>{_N}</duration>{_R}{_tm(1,_N)}<file id="{fid_e}"/><sourcetrack><mediatype>audio</mediatype><trackindex>{t}</trackindex></sourcetrack>{_lk}</clipitem><enabled>TRUE</enabled><locked>FALSE</locked></track>' for ai, t in ((_a1, 1), (_a2, 2)))
            + '</audio></media><labels><label2>Iris</label2></labels></sequence>')
    NESTED = ET.fromstring(_xml)


def usa_nested(clip):
    _n = clip.find("name")
    if _n is not None:
        _n.text = nome_e[:-4] + "-E"
    f = clip.find("file"); i = list(clip).index(f); clip.remove(f)
    if not _nested_usado[0]:
        el = copy.deepcopy(NESTED); _nested_usado[0] = True
    else:
        el = ET.Element("sequence", {"id": NESTED.get("id")})
    clip.insert(i, el)


def sq(t):                         # segundos do bruto -> quadro da sequencia
    return OFFS + fr(t - T0)


v5, a1, a2 = [], [], []
for i, s in enumerate(seg):
    ini, fim = bord[i], bord[i + 1]
    em = fr(s[0]); fora = em + (fim - ini)
    vid, id1, id2 = novo_id(), novo_id(), novo_id()
    c = copy.deepcopy(m_e); c.set("id", vid); pos(c, ini, fim, em, fora); txt(c, "duration", dur_clip); (usa_nested(c) if ANINHADO else arq(c, defs[id_e]))
    am, af = max(0, em - 1), max(0, em - 1) + (fim - ini)
    ca1, ca2 = copy.deepcopy(m_a1), copy.deepcopy(m_a2)
    ca1.set("id", id1); ca2.set("id", id2)
    for ca in (ca1, ca2):
        pos(ca, ini, fim, am, af); txt(ca, "duration", dur_clip); (usa_nested(ca) if ANINHADO else arq(ca, defs[id_raw]))
    for x in (c, ca1, ca2):
        for lk in x.findall("link"):
            mt, ti = lk.findtext("mediatype"), lk.findtext("trackindex")
            lk.find("linkclipref").text = vid if mt == "video" else (id1 if ti == "1" else id2)
            lk.find("clipindex").text = str(i + 1)
    v5.append(c); a1.append(ca1); a2.append(ca2)
    if s[2] == "erro":
        for x in (c, ca1, ca2):
            rotulo(x, ROTULO_ERRO)


def longo(m):
    c = copy.deepcopy(m); c.set("id", novo_id())
    em = int(m.findtext("in")); pos(c, OFFS, FIM - 2, em, em + (FIM - 2 - OFFS)); arq(c); return c


v_hex, v_deg, v_vig, v_bra = longo(m_hex), longo(m_deg), longo(m_vig), longo(m_bra)
intro = copy.deepcopy(m_intro); arq(intro)
lower = copy.deepcopy(m_lower); arq(lower)
a3 = copy.deepcopy(m_a3); arq(a3); a4 = copy.deepcopy(m_a4); arq(a4)
cred = copy.deepcopy(m_cred); cred.set("id", novo_id())
cin = int(m_cred.findtext("in")); pos(cred, FIM - cred_dist, FIM - cred_dist + 121, cin, cin + 121); arq(cred)


def png_wh(p):
    import struct
    try:
        d_ = open(p, "rb").read(32); return struct.unpack(">II", d_[16:24])
    except OSError:
        return (int(os.environ.get('PNG_LARG', 1920)), int(os.environ.get('PNG_ALT', 1080)))


PNG_IDS = {}


def clipe_png(x, ini, fim):
    c = copy.deepcopy(m_png); c.set("id", novo_id())
    nome = os.path.basename(x["png"])
    contador["f"] += 1; fid = f"file-{contador['f']}"; PNG_IDS[fid] = ("Slides" if os.path.dirname(x["png"]).rstrip("/") == pasta_png.rstrip("/") else "Cartoes")
    f = copy.deepcopy(defs[m_png.find("file").get("id")]); f.set("id", fid)
    f.find("name").text = nome; f.find("pathurl").text = url_local(x["png"])
    w, h = png_wh(x["png"])
    f.find("media/video/samplecharacteristics/width").text = str(w); f.find("media/video/samplecharacteristics/height").text = str(h)
    txt(c, "name", nome)
    old = c.find("file"); i = list(c).index(old); c.remove(old); c.insert(i, f)
    for p in c.iter("parameter"):
        if p.findtext("parameterid") == "scale":
            p.find("value").text = "100" if w >= 1900 else "200"
    pos(c, ini, fim, 90000, 90000 + (fim - ini))
    rotulo(c, "Mango")
    return c


v9, v10 = [], []
ult9 = -1
for x in achados:
    a, b = x["ini"], x["fim"]
    if b <= T0 or a >= T1:
        continue
    ini, fim = sq(max(a, T0)), min(sq(min(b, T1)), FIM)
    if fim - ini < 20:
        continue
    c = clipe_png(x, ini, fim)
    if x["tipo"] == "palavra":
        v10.append(c)
    elif ini < ult9:
        v10.append(c)            # sobreposicao com o item anterior: sobe para a V10
    else:
        v9.append(c); ult9 = fim


def refaz(tr, clipes):
    for c in tr.findall("clipitem") + tr.findall("transitionitem") + tr.findall("generatoritem"):
        tr.remove(c)
    p = next((i for i, ch in enumerate(list(tr)) if ch.tag in ("enabled", "locked")), len(tr))
    for k, c in enumerate(clipes):
        tr.insert(p + k, c)


refaz(vtr[0], [v_hex]); refaz(vtr[1], [v_deg]); refaz(vtr[2], []); refaz(vtr[3], [])
refaz(vtr[4], v5); refaz(vtr[5], [v_vig]); refaz(vtr[6], [v_bra]); refaz(vtr[7], [intro, lower, cred])
refaz(vtr[8], v9); refaz(vtr[9], v10); refaz(vtr[10], [])
refaz(atr[0], a1); refaz(atr[1], a2); refaz(atr[2], [a3]); refaz(atr[3], [a4])
for t in atr[4:]:
    refaz(t, [])

seq.find("uuid").text = str(uuid.uuid4()); seq.find("duration").text = str(FIM); seq.find("name").text = nome_seq
for m in seq.findall("marker"):
    seq.remove(m)
tc = seq.find("timecode"); ins = list(seq).index(tc) + 1


def marcador(nome, ini, fim, comentario=""):
    m = ET.Element("marker")
    ET.SubElement(m, "comment").text = comentario; ET.SubElement(m, "name").text = nome
    ET.SubElement(m, "in").text = str(ini); ET.SubElement(m, "out").text = str(fim)
    return m


ms = [marcador("Bastidores cortados", OFFS, OFFS + 30, f"Bruto de 0 a {T0:.1f} s ficou fora (conversa/preparo).")]
ms.append(marcador("Lower Third: colocar o nome do professor", 240, 540, "Texto do Lower Third nao e exportado no XML; inserir manualmente."))
for i, s in enumerate(seg):
    if s[2] == "erro":
        ms.append(marcador("ERRO a conferir", bord[i], bord[i + 1], s[3]))
for x in achados:
    if x["tipo"] == "palavra" and T0 <= x["ini"] <= T1:
        ms.append(marcador("Palavra-chave: " + texto(x["runs"]), sq(x["ini"]), sq(x["ini"]) + 30, "Cartao de texto na V10; ajustar posicao/tempo."))
ms.sort(key=lambda m: int(m.findtext("in")))
for k, m in enumerate(ms):
    seq.insert(ins + k, m)

if os.environ.get("BINS") == "1" and ANINHADO:
    main = root.find("sequence")
    def _el(xml):
        return ET.fromstring(xml)
    def _masterclip(mid, nome, dur, fdef_, com_audio):
        v = (f'<track><clipitem id="{mid}-v"><masterclipid>{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><name>{nome}</name><enabled>TRUE</enabled><duration>{dur}</duration><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate><start>-1</start><end>-1</end><in>0</in><out>{dur}</out></clipitem></track>')
        c = _el(f'<clip id="{mid}"><masterclipid>{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><duration>{dur}</duration><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate><in>-1</in><out>-1</out><name>{nome}</name><media><video>{v}</video></media></clip>')
        c.find("media/video/track/clipitem").append(fdef_)
        if com_audio:
            au = ET.SubElement(c.find("media"), "audio")
            for t in (1, 2):
                tr = ET.SubElement(au, "track")
                ci = _el(f'<clipitem id="{mid}-a{t}" premiereChannelType="mono"><masterclipid>{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><name>{nome}</name><enabled>TRUE</enabled><duration>{dur}</duration><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate><start>-1</start><end>-1</end><in>0</in><out>{dur}</out><file id="{fid_e}"/><sourcetrack><mediatype>audio</mediatype><trackindex>{t}</trackindex></sourcetrack></clipitem>')
                tr.append(ci)
        return c
    seq_e = None
    for ci in main.iter("clipitem"):
        sqe = ci.find("sequence")
        if sqe is not None and len(sqe) > 0 and seq_e is None:
            seq_e = sqe
            ref = ET.Element("sequence", {"id": sqe.get("id")})
            ci.insert(list(ci).index(sqe), ref); ci.remove(sqe)
    f_def = None
    for fe in seq_e.iter("file"):
        if len(fe) > 0:
            f_def = copy.deepcopy(fe)
            fe.clear(); fe.set("id", fid_e)
    seq_d = copy.deepcopy(seq_e)
    seq_d.set("id", f"sequence-D{aula}")
    seq_d.find("name").text = nome_e[:-4] + "-D"
    for h in seq_d.iter("horiz"):
        if h.text == "0.25":
            h.text = "-0.25"
    for ci in seq_d.iter("clipitem"):
        ci.set("id", novo_id()); ci.find("masterclipid").text = f"masterclip-D{aula}"
    ids_d = [ci.get("id") for ci in seq_d.iter("clipitem")]
    for k, ci in enumerate(seq_d.iter("clipitem")):
        for lk in ci.findall("link"):
            idx = {"video": 0}.get(lk.findtext("mediatype"), 1 + int(lk.findtext("trackindex")) - 1)
            lk.find("linkclipref").text = ids_d[idx]
    por_bin = {"Slides": [], "Cartoes": []}
    for fe in list(main.iter("file")):
        if fe.get("id") in PNG_IDS and len(fe) > 0:
            definicao = copy.deepcopy(fe)
            por_bin[PNG_IDS[fe.get("id")]].append(_masterclip(f"masterclip-{fe.get('id')}", definicao.findtext("name"), 1080000, definicao, False))
            fe.clear(); fe.set("id", definicao.get("id"))
    pr = ET.Element("project"); ET.SubElement(pr, "name").text = os.path.basename(pasta_dia.rstrip("/"))
    ch = ET.SubElement(pr, "children")
    def _bin(nome):
        b = ET.Element("bin"); ET.SubElement(b, "name").text = nome
        ET.SubElement(b, "children"); return b
    b_foot = _bin("Footage"); b_nest = _bin("nest")
    b_foot.find("children").append(_masterclip(f"masterclip-E{aula}", nome_e, frames_arq, f_def, True))
    b_nest.find("children").append(seq_e); b_nest.find("children").append(seq_d)
    b_foot.find("children").append(b_nest)
    root.remove(main)
    ch.append(b_foot)
    for nome_b in ("Slides", "Cartoes"):
        if por_bin[nome_b]:
            bb = _bin(nome_b)
            for c_ in por_bin[nome_b]:
                bb.find("children").append(c_)
            ch.append(bb)
    ch.append(main)      # a sequência a editar fica solta na raiz do projeto (sem pasta)
    root.append(pr)

ET.indent(root, space="\t")
open(saida, "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n")
print(f"OK {saida}: bruto usado {T0:.1f}-{T1:.1f}s | seq {FIM} quadros = {FIM / FPS:.1f}s | {sum(1 for s in seg if s[2]=='erro')} ERRO | "
      f"cartoes {sum(1 for x in achados if x['tipo']=='cartao')} | palavras {sum(1 for x in achados if x['tipo']=='palavra')} | slides {sum(1 for x in achados if x['tipo']=='slide')}")
for s in seg:
    if s[2] == "erro":
        print(f"  ERRO {s[0]:7.1f}-{s[1]:7.1f} {s[3][:60]}")
for x in achados:
    print(f"  {x['tipo']:7s} s{x['slide']:<2d} {x['ini']:7.1f}-{x['fim']:7.1f} sc={x['score']:.2f} {texto(x['runs'])[:60]}")
