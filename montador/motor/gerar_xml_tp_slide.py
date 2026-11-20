#!/usr/bin/env python3
"""Gera o XML (FCP7/xmeml v4) do formato TP COM SLIDE a partir de um XML modelo + alinhamento do roteiro.

Uso:
  python3 -I gerar_xml_tp_slide.py MODELO.xml ALINHAMENTO.json SRT PASTA_DIA AULA NOME_E.mp4 DURACAO_E_SEG SAIDA.xml PASTA_PNG

  ALINHAMENTO.json = saída de alinhar_tp.py ; SRT = transcrição do bruto ; PASTA_DIA = pasta do dia (para caminhos)
  AULA = POSIÇÃO da aula no dia (1, 2, 3...): a numeração das sequências SEMPRE começa em 01, não importa o número que o professor usou ; NOME_E.mp4 = arquivo E da aula ; DURACAO_E_SEG = duração do E em segundos ;
  PASTA_PNG = nome da pasta de PNG das cartelas dentro de Originais (ex. 2.5-Aula-17-Cartelas)

Regras (v0, de teste):
  - nada é apagado: trechos suspeitos (tentativa repetida, fala fora do roteiro, pausa longa) ficam na timeline
    com rótulo Rose e um marcador ERRO;
  - começo (bastidores) e fim fora do roteiro NÃO entram; um marcador avisa o intervalo do bruto;
  - cada [INSERÇÃO EM TELA: Cxx] vira um PNG na V7 + marcador "slide NN";
  - cortes retos (sem transição), Lower Third apenas sinalizado por marcador.
"""
import copy, json, os, re, sys, unicodedata, uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote

(modelo, aljson, srt, pasta_dia, aula, nome_e, dur_e, saida, pasta_png) = sys.argv[1:10]
aula = int(aula); dur_e = float(dur_e)
PNG_LARG = int(os.environ.get("PNG_LARG", "0")); PNG_ALT = int(os.environ.get("PNG_ALT", "1080"))

FPS = 30000 / 1001
TICKS = 8475667200
OFFS = 148                  # quadro em que a câmera começa (igual ao modelo; intro ocupa 0-181)
GAP_MIN = 2.5               # pausa/ruído acima disso entre falas do roteiro vira ERRO
ROTULO_ERRO = "Rose"
PREFIXO_ASSETS_MODELO = "file://localhost/Volumes/SSD%20Ilha%201/assets/"
PREFIXO_ASSETS_MAC = "file://localhost/Volumes/SSD%20Mac/Drive%20Backup/"


def fr(seg):
    return round(seg * FPS)


def ts(s):
    h, m, r = s.split(":"); sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def le_srt(p):
    cues = []
    for b in re.split(r"\n\s*\n", open(p, encoding="utf-8").read().strip()):
        ln = b.strip().split("\n")
        if len(ln) >= 3 and "-->" in ln[1]:
            a, z = [ts(x.strip()) for x in ln[1].split("-->")]
            cues.append((a, z, " ".join(ln[2:]).strip()))
    return cues


def url_local(caminho):
    p = unicodedata.normalize("NFD", caminho)
    return "file://localhost" + quote(p, safe="/")


# ------------------------------------------------------------------ planejamento
cues = le_srt(srt)
rot = json.load(open(aljson, encoding="utf-8"))["roteiro"]
falas = [r for r in rot if r["tipo"] == "fala"]

prev_ini = -1
for r in falas:                       # escolhe a tentativa válida de cada bloco
    r["esc"] = None
    c = [x for x in r.get("cand", []) if x["ini"] >= prev_ini - 3.0] if r["n"] >= 8 else []   # blocos curtos nao servem de ancora
    if c:
        melhor = max(x["score"] for x in c)
        r["esc"] = [x for x in c if x["score"] >= melhor - 0.05][-1]   # repetição: vale a última
        prev_ini = max(prev_ini, r["esc"]["ini"])
    r["rejeitadas"] = [x for x in r.get("cand", []) if x is not r["esc"] and x["score"] >= 0.7 and r["n"] >= 8]

casados = [r for r in falas if r["esc"]]
if not casados:
    sys.exit("Nenhum bloco do roteiro foi encontrado na transcrição.")
T0 = max(0.0, casados[0]["esc"]["ini"] - 0.3)
_MP = json.load(open(os.environ["MONTADOR_PLANO"], encoding="utf-8")) if os.environ.get("MONTADOR_PLANO") else None
if _MP:                                   # Montador: início, fim e cortes vêm do plano (Skoopia), não do roteiro
    T0 = max(0.0, float(_MP["T0"]))
_JAN = [float(x) for x in os.environ["MONTADOR_JANELA"].split(",")] if os.environ.get("MONTADOR_JANELA") else None
if _JAN:                                  # Montador: a aula é só este trecho do bruto (vídeo com duas aulas, final refeito...)
    T0 = max(T0, _JAN[0])
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
_ons = float(_ons) if _ons else onset_audio(os.path.join(pasta_dia, "Footage", nome_e), T0)
if _ons is not None:
    ONSET_USADO = _ons
    T0 = max(0.0, _ons - (POS_FALA - 148) / FPS)      # a câmera começa no quadro 148 e a fala cai exatamente no quadro POS_FALA
else:
    ONSET_USADO = None
T1 = min(dur_e, casados[-1]["esc"]["fim"] + 0.8)
# fala improvisada depois do último trecho do roteiro (encadeada, sem ruído): mantém na timeline
_z = casados[-1]["esc"]["fim"]
for _a, _b, _t in cues:
    if _a >= _z - 0.5 and _a - _z < 6 and "[" not in _t:
        _z = max(_z, _b)
T1 = min(dur_e, max(T1, _z + 0.8))
if _MP:
    T1 = min(dur_e, float(_MP["T1"]))
if _JAN:
    T1 = min(T1, _JAN[1])

def texto_entre(a, b, lim=140):
    t = " ".join(x[2] for x in cues if x[1] > a and x[0] < b)
    return (t[:lim] + "…") if len(t) > lim else t


FRASES_ERRO = re.compile(r"desculp|vou (cortar|repetir|voltar|come[cç]ar|refazer)|vamos (repetir|voltar|de novo|refazer)|tenho que repetir|repetir de novo|errei|pera[ií] |cortar essa|corta essa|essa parte aqui eu corto|n[aã]o saiu|esqueci a (frase|fala)|\bops\b|\bopa\b", re.I)
RUIDO = re.compile(r"^\s*[\[\(][^\]\)]*[\]\)]\s*$")     # só [Som de ...], [risos]
PAUSA_LONGA = 3.0

erros = []   # (ini, fim, motivo)
# 1) tentativas repetidas (a fala do roteiro aparece de novo mais adiante; vale a última)
for r in falas:
    for x in r["rejeitadas"]:
        if r["esc"] and x["ini"] < r["esc"]["ini"]:
            erros.append((x["ini"], x["fim"], "tentativa repetida (a fala foi regravada depois)"))
# 2) frases de correção e ruídos
for k, (a_, z_, t_) in enumerate(cues):
    if RUIDO.match(t_):
        erros.append((a_, z_, "ruido: " + t_))
    elif FRASES_ERRO.search(t_):
        ini = cues[k - 1][0] if k > 0 else a_      # inclui a frase anterior (provavel erro)
        erros.append((ini, z_, "correcao falada: " + texto_entre(ini, z_)))
# 3) pausas longas sem fala
for k in range(1, len(cues)):
    if cues[k][0] - cues[k - 1][1] >= PAUSA_LONGA:
        erros.append((cues[k - 1][1], cues[k][0], "pausa longa sem fala"))
# recorta ao intervalo usado e junta sobrepostos
erros = sorted((max(a_, T0), min(z_, T1), m) for a_, z_, m in erros if z_ > T0 and a_ < T1)
junta = []
for a_, z_, m in erros:
    if junta and a_ <= junta[-1][1] + 0.3:
        junta[-1][1] = max(junta[-1][1], z_)
        if m not in junta[-1][2]:
            junta[-1][2] += " + " + m
    else:
        junta.append([a_, z_, m])
seg = []
cursor = T0
for a_, z_, m in junta:
    if a_ - cursor > 0.05:
        seg.append([cursor, a_, "ok", ""])
    seg.append([max(a_, cursor), z_, "erro", m])
    cursor = max(cursor, z_)
if T1 - cursor > 0.05:
    seg.append([cursor, T1, "ok", ""])
if _MP:
    seg = []
    cursor = T0
    for a_, z_, t_, m_ in sorted(_MP["trechos"]):
        a_, z_ = max(a_, T0), min(z_, T1)
        if z_ - a_ < 0.05 or z_ <= cursor:
            continue
        if a_ - cursor > 0.05:
            seg.append([cursor, a_, "ok", ""])
        seg.append([max(a_, cursor), z_, t_, m_])
        cursor = z_
    if T1 - cursor > 0.05:
        seg.append([cursor, T1, "ok", ""])

# slides: n-ésima inserção -> n-ésimo PNG
slides = []
n_ins = 0
for i, r in enumerate(rot):
    if r["tipo"] == "INSERÇÃO EM TELA":
        n_ins += 1
        pos = rot.index(r)
        seguintes = []
        for x in rot[pos + 1:]:
            if x["tipo"] != "fala":
                break
            seguintes.append(x)
        com = [x for x in seguintes if x["esc"]]
        if not com:
            continue
        _m = re.match(r"^S(\d+)$", r["cartela"])
        slides.append({"cartela": r["cartela"], "png": (int(_m.group(1)) if (_m and os.environ.get("PNG_POR_SLIDE") == "1") else n_ins), "ini": com[0]["esc"]["ini"], "fim": com[-1]["esc"]["fim"]})

# um slide não pode invadir o seguinte: o fim de cada um é, no máximo, o começo do próximo
# duracao fixa (SLIDE_DUR, em segundos): usada quando nao ha roteiro em .docx e o slide entra pelo texto do pptx
_dur = float(os.environ.get("SLIDE_DUR") or 0)
if _dur > 0:
    for _s in slides:
        _s["fim"] = _s["ini"] + _dur
slides.sort(key=lambda x: x["ini"])
for _k in range(len(slides) - 1):
    if slides[_k]["fim"] > slides[_k + 1]["ini"]:
        slides[_k]["fim"] = max(slides[_k]["ini"] + 2.0, slides[_k + 1]["ini"])

# ------------------------------------------------------------------ montagem do XML
tree = ET.parse(modelo); root = tree.getroot(); seq = root.find("sequence")
vtr = seq.findall("media/video/track"); atr = seq.findall("media/audio/track")

defs = {}
for f in root.iter("file"):
    if len(f) > 0 and f.get("id") and f.get("id") not in defs:
        defs[f.get("id")] = copy.deepcopy(f)

contador = {"n": max(int(c.get("id").split("-")[1]) for c in root.iter("clipitem"))}


def novo_id():
    contador["n"] += 1
    return f"clipitem-{contador['n']}"


def molde(trilha, nome=None, i=0):
    cs = [c for c in trilha.findall("clipitem") if nome is None or c.findtext("name") == nome]
    return copy.deepcopy(cs[i])


def txt(c, tag, v):
    c.find(tag).text = str(v)


def pos(c, ini, fim, em, fora):
    txt(c, "start", ini); txt(c, "end", fim); txt(c, "in", em); txt(c, "out", fora)
    txt(c, "pproTicksIn", em * TICKS); txt(c, "pproTicksOut", fora * TICKS)


def remapa_url(f):
    u = f.find("pathurl")
    if u is not None and u.text.startswith(PREFIXO_ASSETS_MODELO):
        u.text = PREFIXO_ASSETS_MAC + u.text[len(PREFIXO_ASSETS_MODELO):]


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


# moldes
m_hex = molde(vtr[0]); m_deg = molde(vtr[1]); m_e = molde(vtr[2]); m_vig = molde(vtr[3])
m_bra = molde(vtr[4]); m_intro = molde(vtr[5], "Final_cima_v4_mov.mov")
m_slide = molde(vtr[6]); m_cred = molde(vtr[6], "tela_creditos_mov_v1.mov")
m_a1 = molde(atr[0]); m_a2 = molde(atr[1]); m_a3 = molde(atr[2]); m_a4 = molde(atr[3])
for d in defs.values():
    remapa_url(d)
# câmera: escala 100, posição central e sem corte; o cinegrafista ajusta (varia de aula para aula)
for _f in m_e.findall("filter"):
    _ef = _f.find("effect")
    if _ef.findtext("effectid") == "basic":
        for _p in _ef.findall("parameter"):
            _id = _p.findtext("parameterid")
            if _id == "scale":
                _p.find("value").text = "100"
            elif _id == "center":
                _p.find("value/horiz").text = "0"; _p.find("value/vert").text = "0"
    elif _ef.findtext("effectid") == "crop":
        for _p in _ef.findall("parameter"):
            _p.find("value").text = "0"

# arquivo E desta aula
cam_e = os.path.join(pasta_dia, "Footage", nome_e)
fdef = copy.deepcopy(defs[m_e.find("file").get("id")])
fid_e = f"file-E{aula}"
fdef.set("id", fid_e); fdef.find("name").text = nome_e
fdef.find("pathurl").text = url_local(cam_e)
frames_arq = round(dur_e * 30)
fdef.find("duration").text = str(frames_arq)
dur_clip = round(frames_arq * 1000 / 1001)

# --- D/E como sequência aninhada do bruto 3840x1080 (ANINHADO=1): nome_e passa a ser o BRUTO (.mp4) e dur_e a duração do bruto
ANINHADO = os.environ.get("ANINHADO") == "1"
NESTED = None; _nested_usado = [False]
if ANINHADO:
    for w in fdef.iter("width"):
        w.text = "3840"
    _n = lambda: novo_id()
    _fdxml = ET.tostring(fdef, encoding="unicode")
    _tk = str(TICKS)
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
    _v, _a1, _a2 = _n(), _n(), _n()
    _lk = (f"<link><linkclipref>{_v}</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>"
           f"<link><linkclipref>{_a1}</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex><clipindex>1</clipindex><groupindex>1</groupindex></link>"
           f"<link><linkclipref>{_a2}</linkclipref><mediatype>audio</mediatype><trackindex>2</trackindex><clipindex>1</clipindex><groupindex>1</groupindex></link>")
    _nm = nome_e[:-4] + "-E"
    _fmt = f"<format><samplecharacteristics>{_R}<width>1920</width><height>1080</height><anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance><colordepth>24</colordepth></samplecharacteristics></format>"
    _sid = f"sequence-E{aula}"
    _xml = (f'<sequence id="{_sid}"><duration>{_N}</duration>{_R}<name>{_nm}</name><media><video>{_fmt}<track>'
            f'<clipitem id="{_v}"><masterclipid>masterclip-E{aula}</masterclipid><name>{nome_e}</name><enabled>TRUE</enabled><duration>{_N}</duration>{_R}{_tm(0,_N)}<alphatype>none</alphatype><pixelaspectratio>square</pixelaspectratio><anamorphic>FALSE</anamorphic>{_fdxml}{_mov(0.25)}{_lk}</clipitem>'
            f'<enabled>TRUE</enabled><locked>FALSE</locked></track></video><audio><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format><numOutputChannels>2</numOutputChannels>'
            + "".join(f'<track><clipitem id="{ai}" premiereChannelType="mono"><masterclipid>masterclip-E{aula}</masterclipid><name>{nome_e}</name><enabled>TRUE</enabled><duration>{_N}</duration>{_R}{_tm(1,_N)}<file id="{fid_e}"/><sourcetrack><mediatype>audio</mediatype><trackindex>{t}</trackindex></sourcetrack>{_lk}</clipitem><enabled>TRUE</enabled><locked>FALSE</locked></track>' for ai, t in ((_a1, 1), (_a2, 2)))
            + '</audio></media><labels><label2>Iris</label2></labels></sequence>')
    NESTED = ET.fromstring(_xml)


def usa_nested(clip):
    f = clip.find("file"); i = list(clip).index(f); clip.remove(f)
    if not _nested_usado[0]:
        el = copy.deepcopy(NESTED); _nested_usado[0] = True
    else:
        el = ET.Element("sequence", {"id": NESTED.get("id")})
    clip.insert(i, el)


# limites em quadros da sequência
bord = [OFFS + fr(s[0] - T0) for s in seg] + [OFFS + fr(seg[-1][1] - T0)]
FIM = bord[-1]

v1 = []; v3 = []; a1 = []; a2 = []
for i, s in enumerate(seg):
    ini, fim = bord[i], bord[i + 1]
    em = fr(s[0]); fora = em + (fim - ini)
    c = copy.deepcopy(m_e); c.set("id", novo_id()); pos(c, ini, fim, em, fora); txt(c, "duration", dur_clip)
    (usa_nested(c) if ANINHADO else arq(c, fdef)); v3.append(c)
    ca1, ca2 = copy.deepcopy(m_a1), copy.deepcopy(m_a2)
    ca1.set("id", novo_id()); ca2.set("id", novo_id())
    for ca in (ca1, ca2):
        pos(ca, ini, fim, em, fora); txt(ca, "duration", dur_clip); (usa_nested(ca) if ANINHADO else arq(ca, fdef))
    a1.append(ca1); a2.append(ca2)
    if s[2] == "erro":
        for x in (c, ca1, ca2):
            rotulo(x, ROTULO_ERRO)
for i in range(len(seg)):
    ids = [v3[i].get("id"), a1[i].get("id"), a2[i].get("id")]
    for clip, tipo in ((v3[i], "video"), (a1[i], "audio"), (a2[i], "audio")):
        for lk in clip.findall("link"):
            clip.remove(lk)
        pos_link = list(clip).index(clip.find("pproTicksOut")) + 1
        specs = [(ids[0], "video", 3, False), (ids[1], "audio", 1, True), (ids[2], "audio", 2, True)]
        for k, (ref, mt, ti, g) in enumerate(specs):
            lk = ET.Element("link")
            ET.SubElement(lk, "linkclipref").text = ref
            ET.SubElement(lk, "mediatype").text = mt
            ET.SubElement(lk, "trackindex").text = str(ti)
            ET.SubElement(lk, "clipindex").text = str(i + 1)
            if g:
                ET.SubElement(lk, "groupindex").text = "1"
            # o link vai logo antes de <logginginfo>/<sourcetrack> conforme o molde; aqui entra após sourcetrack
            clip.append(lk)
        # reposiciona: sourcetrack primeiro, links depois, depois logginginfo/colorinfo
        for tag in ("logginginfo", "colorinfo"):
            e = clip.find(tag)
            if e is not None:
                clip.remove(e); clip.append(e)
        for tag in ("labels",):
            e = clip.find(tag)
            if e is not None:
                clip.remove(e); clip.append(e)

# fundos, vinheta, brasão (do início da câmera até o fim)
def fundo(m):
    c = copy.deepcopy(m); c.set("id", novo_id())
    em = int(m.findtext("in")); pos(c, OFFS, FIM, em, em + (FIM - OFFS)); arq(c); return c

v_hex, v_deg, v_vig, v_bra = fundo(m_hex), fundo(m_deg), fundo(m_vig), fundo(m_bra)

# intro e créditos
intro = copy.deepcopy(m_intro); arq(intro)   # mantém id: os links com A3/A4 apontam para ele
a3 = copy.deepcopy(m_a3); arq(a3)
a4 = copy.deepcopy(m_a4); arq(a4)
cred = copy.deepcopy(m_cred); cred.set("id", novo_id())
pos(cred, FIM - 16, FIM - 16 + 121, int(m_cred.findtext("in")), int(m_cred.findtext("in")) + 121); arq(cred)

# slides
dia_nome = os.path.basename(pasta_dia.rstrip("/"))
prefixo_png = os.path.join(pasta_dia, "Originais", pasta_png)
v7 = []
molde_f = defs[m_slide.find("file").get("id")]
for sl in slides:
    nome_png = f"{os.path.basename(prefixo_png)}.{sl['png']:03d}.png"
    fd = copy.deepcopy(molde_f); fid = f"file-S{aula}-{sl['png']}"
    fd.set("id", fid); fd.find("name").text = nome_png
    fd.find("pathurl").text = url_local(os.path.join(prefixo_png, nome_png))
    ini = OFFS + fr(max(sl["ini"], T0) - T0); fim = OFFS + fr(min(sl["fim"], T1) - T0)
    if fim - ini < 60:
        fim = ini + 60
    c = copy.deepcopy(m_slide); c.set("id", novo_id()); c.find("name").text = nome_png
    if PNG_LARG:  # PNG em tamanho cheio (ex. 1920x1080): escala 100 em vez de 200
        for tag in ("width", "height"):
            for e in fd.iter(tag):
                e.text = str(PNG_LARG if tag == "width" else PNG_ALT)
        for par in c.iter("parameter"):
            if par.findtext("parameterid") == "scale":
                par.find("value").text = "100"
    pos(c, ini, fim, 90000, 90000 + (fim - ini)); arq(c, fd)
    v7.append(c); sl["q0"], sl["q1"] = ini, fim
v7.append(cred)


def refaz(tr, clipes):
    for c in tr.findall("clipitem") + tr.findall("transitionitem") + tr.findall("generatoritem"):
        tr.remove(c)
    p = next((i for i, ch in enumerate(list(tr)) if ch.tag in ("enabled", "locked")), len(tr))
    for k, c in enumerate(clipes):
        tr.insert(p + k, c)


refaz(vtr[0], [v_hex]); refaz(vtr[1], [v_deg]); refaz(vtr[2], v3); refaz(vtr[3], [v_vig])
refaz(vtr[4], [v_bra]); refaz(vtr[5], [intro]); refaz(vtr[6], v7)
refaz(atr[0], a1); refaz(atr[1], a2); refaz(atr[2], [a3]); refaz(atr[3], [a4])
for t in vtr[7:] + atr[4:]:
    refaz(t, [])

# sequência
seq.find("uuid").text = str(uuid.uuid4()); seq.find("duration").text = str(FIM)
seq.find("name").text = os.environ.get("MONTADOR_NOME_SEQ") or f"{aula:02d}"      # só o número: 01, 02, 03... (ordem do dia). O editor escreve o título à mão, para conferir se a aula é mesmo aquele título
for m in seq.findall("marker"):
    seq.remove(m)
tc = seq.find("timecode"); ins = list(seq).index(tc) + 1


def marcador(nome, ini, fim, comentario="", cor=None):
    m = ET.Element("marker")
    ET.SubElement(m, "comment").text = comentario
    ET.SubElement(m, "name").text = nome
    ET.SubElement(m, "in").text = str(ini); ET.SubElement(m, "out").text = str(fim)
    if cor:
        ET.SubElement(m, "pproColor").text = cor
    return m


ms = [marcador("Bastidores cortados", OFFS, OFFS + 30, f"Bruto de 0 a {T0:.1f} s ficou fora (conversa/preparo). Fim fora do roteiro a partir de {T1:.1f} s.")]
ms.append(marcador("Lower Third: colocar o nome do professor", 240, 540, "Texto do Lower Third nao e exportado no XML; inserir manualmente."))
for i, s in enumerate(seg):
    if s[2] == "erro":
        ms.append(marcador("ERRO a conferir", bord[i], bord[i + 1], s[3]))
for sl in slides:
    ms.append(marcador(f"slide {sl['png']:02d}", sl["q0"], sl["q1"], f"Cartela {sl['cartela']}" + (" | " + os.environ["SLIDE_OBS"] if os.environ.get("SLIDE_OBS") else ""), "4292277273"))
# instrucoes do roteiro (coluna de insercoes de roteiro em duas colunas / palavras em negrito): so marcador, o editor decide
notas_xml = []
for _i, _r in enumerate(rot):
    if _r["tipo"] != "NOTA":
        continue
    _px = next((x for x in rot[_i + 1:] if x["tipo"] == "fala" and x.get("esc")), None)
    if not _px:
        continue
    _t = _px["esc"]["ini"]
    if _r.get("palavra"):               # palavra-chave: procura o instante em que ela e dita dentro daquela fala
        _w = [w for w in re.findall(r"[a-z0-9]+", "".join(c for c in unicodedata.normalize("NFD", _r["palavra"].lower()) if unicodedata.category(c) != "Mn")) if len(w) >= 3]
        for _a, _z, _tx in cues:
            if _px["esc"]["ini"] - 1 <= _a <= _px["esc"]["fim"] + 1 and _w and _w[0] in "".join(c for c in unicodedata.normalize("NFD", _tx.lower()) if unicodedata.category(c) != "Mn"):
                _t = _a; break
    if not (T0 <= _t <= T1):
        continue
    _q = OFFS + fr(_t - T0)
    ms.append(marcador("palavra-chave" if _r.get("palavra") else "INSERIR (roteiro)", _q, _q + 90, _r["texto"][:400]))
    notas_xml.append((_t, _r["texto"]))
for k, m in enumerate(ms):
    seq.insert(ins + k, m)


# ------------------------------------------------------------------ pastas (bins) do projeto: Footage / Footage/nest / Slides / Sequências
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
    # sequência E (aninhada) sai de dentro da trilha e vira só referência
    seq_e = None
    for ci in main.iter("clipitem"):
        sq = ci.find("sequence")
        if sq is not None and len(sq) > 0 and seq_e is None:
            seq_e = sq
            ref = ET.Element("sequence", {"id": sq.get("id")})
            ci.insert(list(ci).index(sq), ref); ci.remove(sq)
    # definição completa do arquivo bruto: sai da sequência E (fica no bin Footage)
    f_def = None
    for fe in seq_e.iter("file"):
        if len(fe) > 0:
            f_def = copy.deepcopy(fe)
            fe.clear(); fe.set("id", fid_e)
    # sequência D (lado direito), irmã da E
    seq_d = copy.deepcopy(seq_e)
    seq_d.set("id", f"sequence-D{aula}")
    seq_d.find("name").text = nome_e[:-4] + "-D"
    for h in seq_d.iter("horiz"):
        if h.text == "0.25":
            h.text = "-0.25"
    for ci in seq_d.iter("clipitem"):
        ci.set("id", novo_id()); ci.find("masterclipid").text = f"masterclip-D{aula}"
    mapa = {}
    for ci in seq_d.iter("clipitem"):
        pass
    # os links do D apontam para os próprios clipitems do D
    ids_d = [ci.get("id") for ci in seq_d.iter("clipitem")]
    for k, ci in enumerate(seq_d.iter("clipitem")):
        for lk in ci.findall("link"):
            idx = {"video": 0}.get(lk.findtext("mediatype"), 1 + int(lk.findtext("trackindex")) - 1)
            lk.find("linkclipref").text = ids_d[idx]
    # PNGs de slide: definição completa vai para o bin Slides, a trilha fica com referência
    clipes_slide = []
    for fe in list(main.iter("file")):
        if (fe.get("id") or "").startswith(f"file-S{aula}-") and len(fe) > 0:
            definicao = copy.deepcopy(fe)
            nome_png = definicao.findtext("name")
            clipes_slide.append(_masterclip(f"masterclip-{fe.get('id')}", nome_png, 1080000, definicao, False))
            fe.clear(); fe.set("id", definicao.get("id"))
    # monta o projeto
    pr = ET.Element("project"); ET.SubElement(pr, "name").text = os.path.basename(pasta_dia.rstrip("/"))
    ch = ET.SubElement(pr, "children")
    def _bin(nome):
        b = ET.SubElement(ch, "bin") if False else ET.Element("bin"); ET.SubElement(b, "name").text = nome
        ET.SubElement(b, "children"); return b
    b_foot = _bin("Footage"); b_nest = _bin("nest"); b_sl = _bin("Slides")
    b_foot.find("children").append(_masterclip(f"masterclip-E{aula}", nome_e, frames_arq, f_def, True))
    b_nest.find("children").append(seq_e); b_nest.find("children").append(seq_d)
    b_foot.find("children").append(b_nest)
    for c_ in clipes_slide:
        b_sl.find("children").append(c_)
    root.remove(main)
    for b in (b_foot, b_sl):
        ch.append(b)
    ch.append(main)      # a sequência a editar fica solta na raiz do projeto (sem pasta)
    root.append(pr)

ET.indent(root, space="\t")
open(saida, "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n")

print(f"OK {saida}: aula {aula} | bruto usado {T0:.1f}-{T1:.1f}s | seq {FIM} quadros = {FIM / FPS:.1f}s")
for i, s in enumerate(seg):
    print(f"  {s[2].upper():4s} seq {bord[i]}-{bord[i+1]}  bruto {s[0]:.1f}-{s[1]:.1f}  {s[3][:90]}")
for sl in slides:
    print(f"  SLIDE {sl['cartela']} png {sl['png']}: bruto {sl['ini']:.1f}-{sl['fim']:.1f}  seq {sl['q0']}-{sl['q1']}")
for _t, _x in notas_xml:
    print(f"  NOTA bruto {_t:.1f}  {_x[:90]}")
