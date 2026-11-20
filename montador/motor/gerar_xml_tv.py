#!/usr/bin/env python3
"""Gera o XML (Final Cut Pro 7 / xmeml v4) do formato TV a partir de um XML modelo exportado do Premiere.

Uso:
  python3 -I gerar_xml_tv.py MODELO.xml PLANO.json SRT PASTA_DIA BASE_BRUTO DURACAO_BRUTO_SEG SAIDA.xml [NOME_SEQUENCIA]

  PLANO.json   = saída de detectar_erros.py (T0, T1 e trechos ok/erro em segundos do bruto)
  SRT          = transcrição do bruto (para os marcadores de sugestão de tela)
  PASTA_DIA    = pasta do dia (onde estão Footage/<BASE>-E.mp4 e -D.mp4)
  BASE_BRUTO   = nome do bruto sem extensão (ex. "2026-10-29 11-14-11-001")
  DURACAO_BRUTO_SEG = duração do bruto em segundos

O que faz (nada é apagado):
  V1  LIVRE (espaço para o editor colocar o fundo do chroma)
  V2  câmera E em tela cheia, cortada nos trechos; trechos suspeitos ficam com rótulo Rose e marcador
  V3  tela (D) nos mesmos cortes, com a FAIXA desligada (olho apagado): o editor liga a faixa onde a tela deve aparecer
  V4  vinheta, V5 brasão, V6 intro + Lower Third (marcador para o nome) + créditos
  A1/A2 áudio do bruto, A3/A4 áudio da intro
  Marcadores: bastidores cortados, Lower Third, ERRO a conferir, Sugestão: tela (quando o professor aponta para a tela)
"""
import copy, json, os, re, sys, unicodedata, uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote

modelo, plano_json, srt, pasta_dia, base, dur_s, saida = sys.argv[1:8]
nome_seq = sys.argv[8] if len(sys.argv) > 8 else "TV - TESTE montagem"
dur_s = float(dur_s)
PLANO = json.load(open(plano_json, encoding="utf-8"))
T0, T1 = PLANO["T0"], PLANO["T1"]
seg = PLANO["trechos"]

FPS = 30000 / 1001
aula = os.environ.get("AULA", "1")
ANINHADO = os.environ.get("ANINHADO") == "1"
TICKS = 8475667200
OFFS = 148
ROTULO_ERRO = "Rose"
DEIXIS = re.compile(r"\bveja\b|\bolha\b|\bolhem\b|\bessa tela\b|\bnessa tela\b|\besse slide\b|\bneste slide\b|\bno slide\b|"
                    r"\bisso a[qc]u[ií]\b|\bprint\b|\bessa imagem\b|\bnessa imagem\b|\best[aá] vendo\b|\bobserv", re.I)


def fr(s):
    return round(s * FPS)


def ts(s):
    h, m, r = s.split(":"); sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def le_srt(p):
    cues = []
    for b in re.split(r"\n\s*\n", open(p, encoding="utf-8").read().strip()):
        ln = b.strip().split("\n")
        if len(ln) >= 3 and "-->" in ln[1]:
            a, z = [ts(x.strip()) for x in ln[1].split("-->")]
            cues.append([a, z, " ".join(ln[2:]).strip()])
    return cues


def junta(cues, folga=0.8):
    out = []
    for a, b, t in cues:
        if out and a - out[-1][1] < folga:
            out[-1][1] = b; out[-1][2] = (out[-1][2] + " " + t).strip()
        else:
            out.append([a, b, t])
    return out


def url_local(caminho):
    p = str(caminho)
    if p.startswith("\\\\"):                                    # Windows, pasta de rede (\\servidor\\pasta)
        return "file:" + quote(p.replace("\\", "/"), safe="/:")
    if re.match(r"^[A-Za-z]:[\\\\/]", p):                     # Windows (C:\\...)
        return "file://localhost/" + quote(p.replace("\\", "/"), safe="/:")
    return "file://localhost" + quote(unicodedata.normalize("NFD", p), safe="/")


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


m_e = molde(vtr[0]); m_d = molde(vtr[1]); m_vig = molde(vtr[2]); m_bra = molde(vtr[3])
m_intro = molde(vtr[4], "Final_cima_v4_mov.mov"); m_lower = molde(vtr[4], "Lower Third 2025")
m_cred = molde(vtr[4], "tela_creditos_mov_v1.mov")
m_a1 = molde(atr[0]); m_a2 = molde(atr[1]); m_a3 = molde(atr[2]); m_a4 = molde(atr[3])
id_e, id_d, id_raw = m_e.find("file").get("id"), m_d.find("file").get("id"), m_a1.find("file").get("id")
cred_dist = int(seq.findtext("duration")) - int(m_cred.findtext("start"))   # quadros do começo dos créditos até o fim

# câmera: escala 100, posição central, sem rotação nem corte; o cinegrafista ajusta (varia de aula para aula). Cor e demais efeitos do modelo ficam.
for _f in m_e.findall("filter"):
    _ef = _f.find("effect")
    if _ef.findtext("effectid") == "basic":
        for _p in _ef.findall("parameter"):
            _id = _p.findtext("parameterid")
            if _id == "scale":
                _p.find("value").text = "100"
            elif _id == "rotation":
                _p.find("value").text = "0"
            elif _id == "center" and _p.find("value/horiz") is not None:
                _p.find("value/horiz").text = "0"; _p.find("value/vert").text = "0"
    elif _ef.findtext("effectid") == "crop":
        for _p in _ef.findall("parameter"):
            if _p.find("value") is not None and _p.find("value").text is not None:
                _p.find("value").text = "0"

frames_arq = round(dur_s * 30)
dur_clip = round(frames_arq * 1000 / 1001)
for fid, nome in ((id_e, f"{base}-E.mp4"), (id_d, f"{base}-D.mp4"), (id_raw, f"{base}.mp4")):
    d = defs[fid]
    d.find("name").text = nome
    d.find("pathurl").text = url_local(os.path.join(pasta_dia, "Footage", nome))
    d.find("duration").text = str(frames_arq)


# bruto único 3840x1080 (D/E são sequências aninhadas dele)
nome_e = f"{base}.mp4"; fid_e = id_raw; fdef = defs[id_raw]
# --- D/E como sequência aninhada do bruto 3840x1080 (ANINHADO=1): nome_e passa a ser o BRUTO (.mp4) e dur_e a duração do bruto
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
    clip.find("name").text = base + "-E"


def usa_nested_d(clip):
    f = clip.find("file"); i = list(clip).index(f); clip.remove(f)
    clip.insert(i, ET.Element("sequence", {"id": f"sequence-D{aula}"}))
    clip.find("name").text = base + "-D"


# agulha: a 1ª fala cai exatamente no quadro 175 (00;00;05;25); a câmera começa no quadro 148
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
POS_FALA = 175
if ANINHADO and _ons is not None:
    T0 = max(0.0, _ons - (POS_FALA - OFFS) / FPS)
    seg[:] = [s for s in seg if s[1] > T0 + 0.05] or seg
    seg[0][0] = T0
# limites em quadros da sequência
bord = [OFFS + fr(s[0] - T0) for s in seg] + [OFFS + fr(seg[-1][1] - T0)]
FIM = bord[-1]

v1, v2, a1, a2 = [], [], [], []
for i, s in enumerate(seg):
    ini, fim = bord[i], bord[i + 1]
    em = fr(s[0]); fora = em + (fim - ini)
    c = copy.deepcopy(m_e); c.set("id", novo_id()); pos(c, ini, fim, em, fora); txt(c, "duration", dur_clip); (usa_nested(c) if ANINHADO else arq(c, defs[id_e]))
    v1.append(c)
    d = copy.deepcopy(m_d); d.set("id", novo_id()); pos(d, ini, fim, em, fora); txt(d, "duration", dur_clip); (usa_nested_d(d) if ANINHADO else arq(d, defs[id_d]))
    v2.append(d)
    am, af = max(0, em - 1), max(0, em - 1) + (fim - ini)     # no modelo o áudio fica 1 quadro antes do vídeo
    ca1, ca2 = copy.deepcopy(m_a1), copy.deepcopy(m_a2)
    id1, id2 = novo_id(), novo_id()
    ca1.set("id", id1); ca2.set("id", id2)
    for ca in (ca1, ca2):
        pos(ca, ini, fim, em if ANINHADO else am, (em + (fim - ini)) if ANINHADO else af); txt(ca, "duration", dur_clip); (usa_nested(ca) if ANINHADO else arq(ca, defs[id_raw]))
        for lk in ca.findall("link"):
            ti = lk.findtext("trackindex")
            lk.find("linkclipref").text = id1 if ti == "1" else id2
            lk.find("clipindex").text = str(i + 1)
    a1.append(ca1); a2.append(ca2)
    if s[2] == "erro":
        for x in (c, d, ca1, ca2):
            rotulo(x, ROTULO_ERRO)


def longo(m):
    c = copy.deepcopy(m); c.set("id", novo_id())
    em = int(m.findtext("in")); pos(c, OFFS, FIM - 2, em, em + (FIM - 2 - OFFS)); arq(c); return c


v_vig, v_bra = longo(m_vig), longo(m_bra)
intro = copy.deepcopy(m_intro); arq(intro)       # mantém id (links com A3/A4)
lower = copy.deepcopy(m_lower); arq(lower)
a3 = copy.deepcopy(m_a3); arq(a3); a4 = copy.deepcopy(m_a4); arq(a4)
cred = copy.deepcopy(m_cred); cred.set("id", novo_id())
cin = int(m_cred.findtext("in"))
pos(cred, FIM - cred_dist, FIM - cred_dist + 121, cin, cin + 121); arq(cred)


def refaz(tr, clipes):
    for c in tr.findall("clipitem") + tr.findall("transitionitem") + tr.findall("generatoritem"):
        tr.remove(c)
    p = next((i for i, ch in enumerate(list(tr)) if ch.tag in ("enabled", "locked")), len(tr))
    for k, c in enumerate(clipes):
        tr.insert(p + k, c)


refaz(vtr[0], v1); refaz(vtr[1], v2); refaz(vtr[2], [v_vig]); refaz(vtr[3], [v_bra]); refaz(vtr[4], [intro, lower, cred])
refaz(atr[0], a1); refaz(atr[1], a2); refaz(atr[2], [a3]); refaz(atr[3], [a4])
vtr[1].find("enabled").text = "FALSE"      # faixa da tela (D) com o olho desligado: o editor liga a faixa onde a tela deve aparecer
# TV com chroma: a V1 fica LIVRE para o editor colocar o fundo; a câmera (E) vai para a V2 e a tela (D, olho desligado) para a V3
_vid = seq.find("media/video")
_livre = copy.deepcopy(vtr[2]); refaz(_livre, [])
_vid.insert(list(_vid).index(vtr[0]), _livre)
for t in atr[4:]:
    refaz(t, [])

seq.find("uuid").text = str(uuid.uuid4()); seq.find("duration").text = str(FIM)
seq.find("name").text = nome_seq
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


ms = [marcador("Bastidores cortados", OFFS, OFFS + 30, f"Bruto de 0 a {T0:.1f} s ficou fora (conversa/preparo). Fim fora da fala a partir de {T1:.1f} s.")]
ms.append(marcador("Lower Third: colocar o nome do professor", 240, 540, "Texto do Lower Third nao e exportado no XML; inserir manualmente."))
for i, s in enumerate(seg):
    if s[2] == "erro":
        ms.append(marcador("ERRO a conferir", bord[i], bord[i + 1], s[3]))

# sugestões de tela: frases em que o professor aponta para a tela, dentro dos trechos "ok"
def seq_pos(t):
    for i, s in enumerate(seg):
        if s[0] <= t <= s[1]:
            return i, bord[i] + fr(t - s[0])
    return None, None


ult = -999.0
n_sug = 0
for a, b, t in junta(le_srt(srt)):
    if DEIXIS.search(t) and a - ult > 8:
        i, q = seq_pos(a)
        if i is not None and seg[i][2] == "ok":
            fim = min(q + fr(max(b - a, 3.0)), bord[i + 1])
            ms.append(marcador("Sugestão: tela", q, fim, t[:140]))
            ult = a; n_sug += 1
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
    # monta o projeto
    pr = ET.Element("project"); ET.SubElement(pr, "name").text = os.path.basename(pasta_dia.rstrip("/"))
    ch = ET.SubElement(pr, "children")
    def _bin(nome):
        b = ET.SubElement(ch, "bin") if False else ET.Element("bin"); ET.SubElement(b, "name").text = nome
        ET.SubElement(b, "children"); return b
    b_foot = _bin("Footage"); b_nest = _bin("nest")
    b_foot.find("children").append(_masterclip(f"masterclip-E{aula}", nome_e, frames_arq, f_def, True))
    b_nest.find("children").append(seq_e); b_nest.find("children").append(seq_d)
    b_foot.find("children").append(b_nest)
    root.remove(main)
    ch.append(b_foot)
    ch.append(main)      # a sequência a editar fica solta na raiz do projeto (sem pasta)
    root.append(pr)


ET.indent(root, space="\t")
open(saida, "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n")
print(f"OK {saida}: bruto usado {T0:.1f}-{T1:.1f}s | seq {FIM} quadros = {FIM / FPS:.1f}s | {sum(1 for s in seg if s[2]=='erro')} ERRO | {n_sug} sugestões de tela")
