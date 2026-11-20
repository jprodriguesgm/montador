#!/usr/bin/env python3
"""Gera o XML (Final Cut Pro 7 / xmeml v4) do formato SCREENCAST (inclui mesa digitalizadora) a partir de um XML modelo exportado do Premiere.

Uso:
  python3 -I gerar_xml_screencast.py MODELO.xml PLANO.json PASTA_DIA SAIDA.xml

  PLANO.json = {"raw": "AAAA-MM-DD HH-MM-SS.mp4", "dur": segundos_do_bruto, "nome": "01", "T0": s, "T1": s,
                "trechos": [[ini, fim, "ok"|"erro", "motivo"], ...]}      (saída de detectar_erros.py + dados do bruto)
  PASTA_DIA  = pasta do dia (o bruto 3840x1080 está em Footage/)

Padrão NPD (igual ao TP com slide e à TV):
  - D e E são SEQUÊNCIAS ANINHADAS do bruto 3840x1080 (nomes "<bruto>-E" e "<bruto>-D", rótulo Iris); nada é dividido em arquivos;
  - a 1ª fala cai no quadro 175 (00;00;05;25); a câmera/tela começam no quadro 148 (a agulha de vinheta);
  - pastas do projeto: Footage (bruto) > nest (E, D e a sequência da câmera com fundo); a sequência a editar fica solta;
  - câmera dentro do fundo: escala 100, posição central, sem rotação nem corte (o cinegrafista ajusta); só o círculo (posição/tamanho) vem do modelo.
Trilhas geradas: V1 tela (D), V2 moldura, V3 câmera (fundo + névoa + E), V4 bolinha, V6 brasão, V7 vinheta de abertura + Lower Third + créditos, A1/A2 áudio de E, A3/A4 áudio da vinheta.
Nada é apagado: trechos suspeitos ficam com rótulo Rose e marcador "ERRO a conferir"."""
import copy, json, os, re, sys, unicodedata, uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote

modelo, plano_json, pasta_dia, saida = sys.argv[1:5]
PLANO = json.load(open(plano_json, encoding="utf-8"))
RAW = PLANO["raw"]; BASE = RAW[:-4]; DUR = float(PLANO["dur"]); NOME_SEQ = PLANO.get("nome", "01")
T0 = float(PLANO["T0"]); T1 = float(PLANO.get("T1", DUR))
TRECHOS = [list(t) for t in PLANO["trechos"]]
aula = os.environ.get("AULA", "1")
FPS = 30000 / 1001
TICKS = 8475667200
OFFS = 148            # quadro em que a câmera/tela começam (fim da vinheta de abertura)
POS_FALA = 175        # quadro (00;00;05;25) em que a 1ª fala deve começar
ROTULO_ERRO = "Rose"
CAM_X, CAM_Y = 1723.2, 907.5      # centro do círculo da câmera (px, sequência 1920x1080), conferido no Premiere
LARG, ALT = 1920, 1080


def fr(s):
    return round(s * FPS)


def url_local(caminho):
    p = unicodedata.normalize("NFD", caminho)
    return "file://localhost" + quote(p, safe="/")


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

# ------------------------------------------------------------------ modelo
root = ET.parse(modelo).getroot(); seq = root.find("sequence")
vt = seq.findall("media/video/track"); at = seq.findall("media/audio/track")
arquivos = {}
for f in root.iter("file"):
    if len(f) > 0 and f.get("id") and f.get("id") not in arquivos:
        arquivos[f.get("id")] = copy.deepcopy(f)
# o Premiere exporta a moldura (V2) apontando para o arquivo da bolinha: corrige nome/caminho da definição
for c in vt[1].findall("clipitem"):
    f = c.find("file")
    if f is not None and f.get("id") in arquivos:
        d = arquivos[f.get("id")]; nome = c.findtext("name")
        if d.findtext("name") != nome and nome.lower().endswith(".png"):
            antigo = d.findtext("name"); d.find("name").text = nome
            u = d.find("pathurl"); u.text = u.text.replace(antigo.replace(" ", "%20"), nome.replace(" ", "%20"))
        break
contador = {"n": max(int(c.get("id").split("-")[1]) for c in root.iter("clipitem") if c.get("id", "").count("-"))}


def novo_id():
    contador["n"] += 1
    return f"clipitem-{contador['n']}"


def molde(trilha, i=0):
    return copy.deepcopy(trilha.findall("clipitem")[i])


m_d, m_mold, m_cam, m_bol, m_bra = molde(vt[0]), molde(vt[1]), molde(vt[2]), molde(vt[3]), molde(vt[5])
m_a1, m_a2 = molde(at[0]), molde(at[1])


def molde_nome(trilha, nome):
    return copy.deepcopy(next(c for c in trilha.findall("clipitem") if c.findtext("name") == nome))


m_intro = molde_nome(vt[6], "Final_cima_v4_mov.mov"); m_lower = molde_nome(vt[6], "Lower Third 2025"); m_cred = molde_nome(vt[6], "tela_creditos_mov_v1.mov")
m_a3, m_a4 = molde(at[2]), molde(at[3])
cred_dist = int(seq.findtext("duration")) - int(m_cred.findtext("start"))     # quadros do começo dos créditos até o fim
cred_dur = int(m_cred.findtext("end")) - int(m_cred.findtext("start"))
id_raw_modelo = m_a1.find("file").get("id")
usados = set()


def arq(clip):
    """1ª vez = <file> completo; depois só referência (PNGs de moldura, bolinha, brasão)."""
    f = clip.find("file")
    if f is None:
        return
    fid = f.get("id"); i = list(clip).index(f); clip.remove(f)
    if fid in usados or fid not in arquivos:
        novo = ET.Element("file", {"id": fid})
    else:
        novo = copy.deepcopy(arquivos[fid]); usados.add(fid)
    clip.insert(i, novo)


def pos(c, ini, fim, em, fora):
    for tag, v in (("start", ini), ("end", fim), ("in", em), ("out", fora)):
        c.find(tag).text = str(v)
    c.find("pproTicksIn").text = str(em * TICKS); c.find("pproTicksOut").text = str(fora * TICKS)


def rotulo(clip, nome):
    ls = clip.find("labels")
    if ls is None:
        ls = ET.SubElement(clip, "labels")
    for x in list(ls):
        ls.remove(x)
    ET.SubElement(ls, "label2").text = nome


def troca_por_seq(clip, seqid, nome, masterclip=None):
    for tag in ("file", "sequence"):
        e = clip.find(tag)
        if e is not None:
            i = list(clip).index(e); clip.remove(e); break
    clip.insert(i, ET.Element("sequence", {"id": seqid}))
    clip.find("name").text = nome
    if masterclip:
        clip.find("masterclipid").text = masterclip


# ------------------------------------------------------------------ bruto (3840x1080) e nests
frames_arq = round(DUR * 30)
dur_clip = round(frames_arq * 1000 / 1001)
FID = f"file-E{aula}"
fdef = copy.deepcopy(arquivos[id_raw_modelo]); fdef.set("id", FID)
fdef.find("name").text = RAW
fdef.find("pathurl").text = url_local(os.path.join(pasta_dia, "Footage", RAW))
fdef.find("duration").text = str(frames_arq)
for w in fdef.iter("width"):
    w.text = "3840"
for h in fdef.iter("height"):
    h.text = "1080"
R = "<rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>"


def mov(h):
    return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>video</mediatype><pproBypass>false</pproBypass>"
            "<parameter authoringApp=\"PremierePro\"><parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax><value>100</value></parameter>"
            "<parameter authoringApp=\"PremierePro\"><parameterid>rotation</parameterid><name>Rotation</name><valuemin>-8640</valuemin><valuemax>8640</valuemax><value>0</value></parameter>"
            "<parameter authoringApp=\"PremierePro\"><parameterid>center</parameterid><name>Center</name><value><horiz>%s</horiz><vert>0</vert></value></parameter>"
            "<parameter authoringApp=\"PremierePro\"><parameterid>centerOffset</parameterid><name>Anchor Point</name><value><horiz>0</horiz><vert>0</vert></value></parameter></effect></filter>" % h)


def tm(i, o):
    return f"<start>{i}</start><end>{o}</end><in>{i}</in><out>{o}</out><pproTicksIn>{i * TICKS}</pproTicksIn><pproTicksOut>{o * TICKS}</pproTicksOut>"


FMT = (f"<format><samplecharacteristics>{R}<width>1920</width><height>1080</height><anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio>"
       "<fielddominance>none</fielddominance><colordepth>24</colordepth></samplecharacteristics></format>")


def nest(lado):
    """Sequência 1920x1080 com o lado esquerdo (E, horiz +0,25) ou direito (D, -0,25) do bruto 3840x1080."""
    h = "0.25" if lado == "E" else "-0.25"; N = frames_arq
    v, a1, a2 = novo_id(), novo_id(), novo_id()
    mid = f"masterclip-{lado}{aula}"
    if lado == "E":
        lk = (f"<link><linkclipref>{v}</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>"
              f"<link><linkclipref>{a1}</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex><clipindex>1</clipindex><groupindex>1</groupindex></link>"
              f"<link><linkclipref>{a2}</linkclipref><mediatype>audio</mediatype><trackindex>2</trackindex><clipindex>1</clipindex><groupindex>1</groupindex></link>")
    else:
        lk = ""
    xml = (f'<sequence id="sequence-{lado}{aula}"><duration>{N}</duration>{R}<name>{BASE}-{lado}</name><media><video>{FMT}<track>'
           f'<clipitem id="{v}"><masterclipid>{mid}</masterclipid><name>{RAW}</name><enabled>TRUE</enabled><duration>{N}</duration>{R}{tm(0, N)}'
           f'<alphatype>none</alphatype><pixelaspectratio>square</pixelaspectratio><anamorphic>FALSE</anamorphic><file id="{FID}"/>{mov(h)}{lk}</clipitem>'
           '<enabled>TRUE</enabled><locked>FALSE</locked></track></video>')
    if lado == "E":
        xml += ('<audio><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format><numOutputChannels>2</numOutputChannels>'
                + "".join(f'<track><clipitem id="{ai}" premiereChannelType="mono"><masterclipid>{mid}</masterclipid><name>{RAW}</name><enabled>TRUE</enabled><duration>{N}</duration>{R}{tm(1, N)}'
                          f'<file id="{FID}"/><sourcetrack><mediatype>audio</mediatype><trackindex>{t}</trackindex></sourcetrack>{lk}</clipitem><enabled>TRUE</enabled><locked>FALSE</locked></track>'
                          for ai, t in ((a1, 1), (a2, 2))) + '</audio>')
    xml += '</media><labels><label2>Iris</label2></labels></sequence>'
    return ET.fromstring(xml)


seq_e, seq_d = nest("E"), nest("D")

# sequência da câmera (fundo + névoa + E): vem do modelo; a câmera E vira o nest E, em escala 100 e centralizada
cam_nest = copy.deepcopy(m_cam.find("sequence"))
cam_nest.set("id", f"sequence-C{aula}"); cam_nest.find("name").text = BASE + "-CAM"
cam_nest.find("duration").text = str(frames_arq)
for e in cam_nest.findall("media/audio/track"):
    for c in e.findall("clipitem"):
        e.remove(c)
for t in cam_nest.findall("media/video/track"):
    for c in t.findall("clipitem"):
        c.find("start").text = "0"; c.find("end").text = str(frames_arq); c.find("in").text = "0"; c.find("out").text = str(frames_arq)
        c.find("duration").text = str(frames_arq)
        c.find("pproTicksIn").text = "0"; c.find("pproTicksOut").text = str(frames_arq * TICKS)
        arq_el = c.find("file")
        if arq_el is not None and arq_el.findtext("name") and arq_el.findtext("name").endswith("-E.mp4"):
            for lk in c.findall("link"):
                c.remove(lk)
            troca_por_seq(c, f"sequence-E{aula}", BASE + "-E", f"masterclip-E{aula}")
            for ef in c.findall("filter/effect"):
                if ef.findtext("effectid") == "basic":
                    for p in ef.findall("parameter"):
                        pid = p.findtext("parameterid")
                        if pid == "scale":
                            p.find("value").text = "100"
                        elif pid == "rotation":
                            p.find("value").text = "0"
                        elif pid == "center":
                            p.find("value/horiz").text = "0"; p.find("value/vert").text = "0"
                elif ef.findtext("effectid") == "crop":
                    for p in ef.findall("parameter"):
                        if p.find("value") is not None:
                            p.find("value").text = "0"
            c.find("name").text = BASE + "-E"

# ------------------------------------------------------------------ agulha: 1ª fala no quadro 175
_ons = os.environ.get("ONSET")
_ons = float(_ons) if _ons else onset_audio(os.path.join(pasta_dia, "Footage", RAW), T0)
if _ons is not None:
    T0 = max(0.0, _ons - (POS_FALA - OFFS) / FPS)
    TRECHOS[:] = [s for s in TRECHOS if s[1] > T0 + 0.05] or TRECHOS
    TRECHOS[0][0] = T0
bord = [OFFS + fr(s[0] - T0) for s in TRECHOS] + [OFFS + fr(TRECHOS[-1][1] - T0)]
FIM = bord[-1]

# ------------------------------------------------------------------ trilhas
v1, v2, v3, v4, a1, a2 = [], [], [], [], [], []
for i, s in enumerate(TRECHOS):
    ini, fim = bord[i], bord[i + 1]; em = fr(s[0]); fora = em + (fim - ini); erro = s[2] == "erro"
    c = copy.deepcopy(m_d); c.set("id", novo_id()); pos(c, ini, fim, em, fora); c.find("duration").text = str(dur_clip)
    troca_por_seq(c, f"sequence-D{aula}", BASE + "-D", f"masterclip-D{aula}")
    if erro: rotulo(c, ROTULO_ERRO)
    v1.append(c)
    c = copy.deepcopy(m_mold); c.set("id", novo_id()); mi = int(m_mold.findtext("in")); pos(c, ini, fim, mi, mi + (fim - ini)); arq(c); v2.append(c)
    c = copy.deepcopy(m_cam); c.set("id", novo_id()); pos(c, ini, fim, em, fora); c.find("duration").text = str(dur_clip)
    for par in c.iter("parameter"):
        if par.findtext("name") == "Center":
            par.find("value/horiz").text = f"{(CAM_X - LARG / 2) / LARG:.6f}"; par.find("value/vert").text = f"{(CAM_Y - ALT / 2) / ALT:.6f}"
    troca_por_seq(c, f"sequence-C{aula}", BASE + "-CAM", f"masterclip-C{aula}")
    if erro: rotulo(c, ROTULO_ERRO)
    v3.append(c)
    c = copy.deepcopy(m_bol); c.set("id", novo_id()); bi = int(m_bol.findtext("in")); pos(c, ini, fim, bi, bi + (fim - ini)); arq(c); v4.append(c)
    ca1, ca2 = copy.deepcopy(m_a1), copy.deepcopy(m_a2); id1, id2 = novo_id(), novo_id(); ca1.set("id", id1); ca2.set("id", id2)
    for ca in (ca1, ca2):
        pos(ca, ini, fim, em, fora); ca.find("duration").text = str(dur_clip)
        troca_por_seq(ca, f"sequence-E{aula}", BASE + "-E", f"masterclip-E{aula}")
        if erro: rotulo(ca, ROTULO_ERRO)
        for lk in ca.findall("link"):
            lk.find("linkclipref").text = id1 if lk.findtext("trackindex") == "1" else id2
            lk.find("clipindex").text = str(i + 1)
    a1.append(ca1); a2.append(ca2)
bra = copy.deepcopy(m_bra); bra.set("id", novo_id()); bi = int(m_bra.findtext("in")); pos(bra, OFFS, FIM, bi, bi + (FIM - OFFS)); arq(bra)
# vinheta de abertura (V7 + áudio A3/A4), Lower Third e créditos de encerramento: iguais ao modelo
intro = copy.deepcopy(m_intro); arq(intro)           # mantém o id (links com A3/A4)
lower = copy.deepcopy(m_lower); arq(lower)
a3 = copy.deepcopy(m_a3); arq(a3); a4 = copy.deepcopy(m_a4); arq(a4)
cred = copy.deepcopy(m_cred); cred.set("id", novo_id()); ci = int(m_cred.findtext("in"))
pos(cred, FIM - cred_dist, FIM - cred_dist + cred_dur, ci, ci + cred_dur); arq(cred)


def refaz(tr, clipes):
    for c in tr.findall("clipitem") + tr.findall("generatoritem") + tr.findall("transitionitem"):
        tr.remove(c)
    p = next((i for i, ch in enumerate(list(tr)) if ch.tag in ("enabled", "locked")), len(tr))
    for k, c in enumerate(clipes):
        tr.insert(p + k, c)


refaz(vt[0], v1); refaz(vt[1], v2); refaz(vt[2], v3); refaz(vt[3], v4); refaz(vt[4], []); refaz(vt[5], [bra]); refaz(vt[6], [intro, lower, cred])
refaz(at[0], a1); refaz(at[1], a2); refaz(at[2], [a3]); refaz(at[3], [a4])
for t in at[4:]:
    refaz(t, [])
seq.find("uuid").text = str(uuid.uuid4()); seq.find("duration").text = str(FIM); seq.find("name").text = NOME_SEQ
for m in seq.findall("marker"):
    seq.remove(m)
ins = list(seq).index(seq.find("timecode")) + 1
m = ET.Element("marker")
ET.SubElement(m, "comment").text = "O texto do Lower Third não é exportado no XML; inserir manualmente."
ET.SubElement(m, "name").text = "Lower Third: colocar o nome do professor"; ET.SubElement(m, "in").text = "240"; ET.SubElement(m, "out").text = "540"
seq.insert(ins, m); ins += 1
mk = 0
for i, s in enumerate(TRECHOS):
    if s[2] != "erro":
        continue
    m = ET.Element("marker")
    ET.SubElement(m, "comment").text = f"Possível erro (nada foi apagado): {s[3]} | bruto {s[0]:.1f}-{s[1]:.1f}s"
    ET.SubElement(m, "name").text = "ERRO a conferir"; ET.SubElement(m, "in").text = str(bord[i]); ET.SubElement(m, "out").text = str(bord[i + 1])
    seq.insert(ins + mk, m); mk += 1

# ------------------------------------------------------------------ pastas do projeto: Footage > nest ; sequência solta
def masterclip(mid, nome, dur, definicao):
    v = (f'<track><clipitem id="{mid}-v"><masterclipid>{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><name>{nome}</name><enabled>TRUE</enabled><duration>{dur}</duration>{R}'
         f'<start>-1</start><end>-1</end><in>0</in><out>{dur}</out></clipitem></track>')
    c = ET.fromstring(f'<clip id="{mid}"><masterclipid>{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><duration>{dur}</duration>{R}<in>-1</in><out>-1</out><name>{nome}</name><media><video>{v}</video></media></clip>')
    c.find("media/video/track/clipitem").append(definicao)
    au = ET.SubElement(c.find("media"), "audio")
    for t in (1, 2):
        tr = ET.SubElement(au, "track")
        tr.append(ET.fromstring(f'<clipitem id="{mid}-a{t}" premiereChannelType="mono"><masterclipid>{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><name>{nome}</name><enabled>TRUE</enabled><duration>{dur}</duration>{R}'
                                f'<start>-1</start><end>-1</end><in>0</in><out>{dur}</out><file id="{FID}"/><sourcetrack><mediatype>audio</mediatype><trackindex>{t}</trackindex></sourcetrack></clipitem>'))
    return c


def pasta(nome):
    b = ET.Element("bin"); ET.SubElement(b, "name").text = nome; ET.SubElement(b, "children"); return b


pr = ET.Element("project"); ET.SubElement(pr, "name").text = os.path.basename(pasta_dia.rstrip("/"))
ch = ET.SubElement(pr, "children")
b_foot, b_nest = pasta("Footage"), pasta("nest")
b_foot.find("children").append(masterclip(f"masterclip-E{aula}", RAW, frames_arq, fdef))
for sq in (seq_e, seq_d, cam_nest):
    b_nest.find("children").append(sq)
b_foot.find("children").append(b_nest)
root.remove(seq)
ch.append(b_foot)
ch.append(seq)      # a sequência a editar fica solta na raiz do projeto (sem pasta)
root.append(pr)

ET.indent(root, space="\t")
open(saida, "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n")
print(f"OK {saida}: bruto usado {T0:.1f}-{T1:.1f}s | seq {FIM} quadros = {FIM / FPS:.1f}s | {sum(1 for s in TRECHOS if s[2] == 'erro')} ERRO")
for i, s in enumerate(TRECHOS):
    print(f"  {s[2].upper():4s} seq {bord[i]}-{bord[i + 1]}  bruto {s[0]:.1f}-{s[1]:.1f}  {s[3][:90]}")
