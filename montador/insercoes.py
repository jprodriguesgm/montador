"""Inserções: onde entra cada slide/cartela e como ela vai para a timeline.

Com a Skoopia: cada inserção do SRT dela é casada com um slide do professor
  - pelo código da cartela (C33) quando aparece no texto da inserção;
  - senão, pelo título/texto do slide.
  Inserção sem slide parecido vira só um marcador "CARTELA" com o texto, para o editor criar.
Sem IA: cada slide entra no trecho da fala em que o assunto dele aparece (palavras do slide x palavras ditas),
  como no Fluxo NPD; a posição sai marcada para conferir.

Tempo na tela: o que a nota do slide pedir ("Exibir por 6 a 8 segundos" -> 8 s); se não pedir, o tempo das
Configurações (15 s). Um slide nunca invade o seguinte.
"""
from __future__ import annotations

import copy
import re
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

from . import skoopia
from .srt import Cue

FPS = 30000 / 1001
TICKS = 8475667200
COR_SLIDE = "4292277273"
DURACAO_PADRAO = 15.0
MOTOR = Path(__file__).parent / "motor"

_STOP = set("""para pelo pela pelos pelas com como mais mas que nao uma uns umas dos das nos nas aos este esta esse essa isso
isto aquele aquela ser sao foi era tem ter seu sua seus suas ele ela eles elas voce voces nosso nossa muito muita entre
sobre por sem pra nem the and for meu minha vao vai ver bem tambem quando onde porque qual quais cada todo toda todos
todas ate sob apos entao assim ainda aqui ja so vamos pode podem deve devem temos estamos estao sendo sera forma parte
vez vezes dia hoje aula slide fonte texto imagem elaborado elaborada autor autora""".split())
_CODIGO = re.compile(r"\b(C\d{1,4})\b")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _palavras(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _norm(t)) if len(w) >= 4 and w not in _STOP}


def _titulo(texto: str) -> str:
    for ln in texto.split("\n"):
        ln = re.sub(r"^\s*\[[^\]]+\]\s*", "", ln).strip()
        if ln:
            return ln
    return ""


def todos_os_slides(lista_pptx: list[dict]) -> list[dict]:
    """[{pptx, n, titulo, textos, codigo, segundos, imagem, palavras}] de todos os .pptx, sem as referências."""
    out = []
    for p in lista_pptx:
        for s in p["slides"]:
            if s.get("referencias"):
                continue
            out.append({**s, "pptx": p["pptx"], "imagem": p["imagens"].get(s["n"]),
                        "palavras": _palavras(" ".join(s["textos"]))})
    return out


def slides_de_imagens(imagens: list[str], pptx_usados: list[str]) -> list[dict]:
    """Imagens soltas no material (JPEG/PNG exportados pelo editor) viram "slides" para casar com as inserções.

    O texto de cada imagem vem, nesta ordem:
      1. do .pptx de mesmo nome da pasta (Originais/Aula 3/Aula 3.002.jpg -> slide 2 de Originais/Aula 3.pptx),
         mesmo que o .pptx tenha sido tirado da lista;
      2. do nome do arquivo (código C33 e as palavras do nome).
    """
    from . import slides as slides_mod
    usados = {Path(p).resolve() for p in pptx_usados}
    textos_pptx: dict[Path, dict[int, dict]] = {}
    out = []
    for img in imagens:
        q = Path(img)
        m = re.search(r"(\d+)$", q.stem)
        n = int(m.group(1)) if m else None
        irmao = next((c for c in (q.parent.parent / (q.parent.name + ".pptx"), q.parent / (re.sub(r"[.\s_-]*\d+$", "", q.stem) + ".pptx"))
                      if c.is_file()), None)
        if irmao is not None and irmao.resolve() in usados:
            continue                                   # já entra pelo próprio .pptx
        s = None
        if irmao is not None and n is not None:
            if irmao not in textos_pptx:
                try:
                    textos_pptx[irmao] = {x["n"]: x for x in slides_mod.ler(irmao)}
                except slides_mod.ErroSlides:
                    textos_pptx[irmao] = {}
            s = textos_pptx[irmao].get(n)
        if s is not None:
            if s.get("referencias"):
                continue
            item = {**s}
        else:
            nome = re.sub(r"[_\-.]+", " ", q.stem).strip()
            cod = re.search(r"\b(C\d{1,4})\b", nome, re.I)
            item = {"n": n or 0, "titulo": nome, "textos": [nome], "codigo": cod.group(1).upper() if cod else None,
                    "notas": "", "segundos": None, "referencias": False}
        out.append({**item, "pptx": str(q), "imagem": str(q), "palavras": _palavras(" ".join(item["textos"]))})
    return out


# ------------------------------------------------------------------ casar

def casar_skoopia(cues: list[Cue], slides: list[dict]) -> list[dict]:
    """Inserções da Skoopia (já no tempo do vídeo) -> itens {ini, fim, slide|None, texto, como}."""
    out = []
    for c in sorted(cues, key=lambda x: x.ini):
        if skoopia.classe(c) != "insercao":
            continue
        texto = c.texto.strip()
        alvo, como = None, ""
        cod = _CODIGO.search(texto)
        if cod:
            alvo = next((s for s in slides if s.get("codigo") == cod.group(1).upper()), None)
            como = "Skoopia, pelo código" if alvo else ""
        if alvo is None and slides:
            tit = _norm(_titulo(texto))
            pal = _palavras(texto)
            melhor, nota = None, 0.0
            for s in slides:
                r = SequenceMatcher(None, tit, _norm(s["titulo"])).ratio() if tit and s["titulo"] else 0.0
                j = len(pal & s["palavras"]) / max(1, len(s["palavras"])) if s["palavras"] else 0.0
                n = max(r, 0.6 * r + 0.4 * j)
                if n > nota:
                    melhor, nota = s, n
            if nota >= 0.6:
                alvo, como = melhor, "Skoopia, pelo título"
        out.append({"ini": c.ini, "fim": c.fim, "slide": alvo, "texto": texto, "como": como or "sem slide"})
    return out


def casar_regras(falas: list[Cue], ini: float, fim: float, slides: list[dict], janela: float = 40.0) -> list[dict]:
    """Sem IA: para cada slide, o trecho da fala (dentro da aula) que mais usa as palavras dele."""
    trecho = [c for c in falas if ini <= c.ini <= fim and c.texto.strip()]
    pal_cue = [_palavras(c.texto) for c in trecho]
    out = []
    for s in slides:
        alvo = s["palavras"]
        if len(alvo) < 2:
            continue
        melhor, nota = None, 0.0
        for i, c in enumerate(trecho):
            ditas, j = set(), i
            while j < len(trecho) and trecho[j].ini - c.ini <= janela:
                ditas |= pal_cue[j]
                j += 1
            n = len(alvo & ditas) / len(alvo)
            if n > nota + 1e-9:
                # entra na primeira fala do trecho que usa uma palavra do slide
                k = next((x for x in range(i, j) if pal_cue[x] & alvo), i)
                melhor, nota = trecho[k].ini, n
        if melhor is not None and nota >= 0.4:
            out.append({"ini": melhor, "fim": melhor + (s.get("segundos") or DURACAO_PADRAO), "slide": s,
                        "texto": s["titulo"], "como": f"palavras do slide na fala ({nota:.0%}), conferir", "nota": nota})
    return sorted(out, key=lambda x: x["ini"])


def duracoes(itens: list[dict], t1: float, padrao: float = DURACAO_PADRAO) -> list[dict]:
    """Tempo na tela de cada slide: nota do slide ou o padrão, sem passar do fim do trecho nem invadir o próximo."""
    itens = sorted(itens, key=lambda x: x["ini"])
    for k, it in enumerate(itens):
        s = it.get("slide")
        dur = (s or {}).get("segundos") or padrao
        fim = it["ini"] + dur
        if it.get("fim") and it["fim"] > it["ini"] + 2 and not (s or {}).get("segundos"):
            fim = min(fim, it["fim"])                       # a Skoopia marcou um trecho menor que o padrão
        if k + 1 < len(itens):
            fim = min(fim, max(it["ini"] + 2.0, itens[k + 1]["ini"]))
        it["fim_tela"] = min(fim, t1) if t1 > it["ini"] + 2 else fim
    return itens


# ------------------------------------------------------------------ timeline

def _url(caminho: str) -> str:
    p = str(caminho)
    if p.startswith("\\\\"):                                    # Windows, pasta de rede (\\servidor\\pasta)
        return "file:" + quote(p.replace("\\", "/"), safe="/:")
    if re.match(r"^[A-Za-z]:[\\\\/]", p):                     # Windows (C:\\...)
        return "file://localhost/" + quote(p.replace("\\", "/"), safe="/:")
    return "file://localhost" + quote(unicodedata.normalize("NFD", p), safe="/")


def _molde_slide():
    root = ET.parse(MOTOR / "modelos" / "modelo_tp.xml").getroot()
    v7 = root.find("sequence").findall("media/video/track")[6]
    c = next(x for x in v7.findall("clipitem") if "creditos" not in (x.findtext("name") or ""))
    fid = c.find("file").get("id")
    f = next(x for x in root.iter("file") if x.get("id") == fid and len(x) > 0)
    return copy.deepcopy(c), copy.deepcopy(f)


def _mapa(seq) -> list[tuple[int, int, int, int]]:
    """Trechos da câmera na sequência: (start, end, in, out) em quadros — para levar o tempo do bruto à timeline."""
    for tr in seq.findall("media/video/track"):
        cs = [c for c in tr.findall("clipitem") if c.find("sequence") is not None]
        if cs:
            return sorted((int(c.findtext("start")), int(c.findtext("end")), int(c.findtext("in")), int(c.findtext("out")))
                          for c in cs)
    return []


def _na_timeline(mapa, t: float) -> int | None:
    q = round(t * FPS)
    for st, en, i, o in mapa:
        if i <= q < o:
            return st + (q - i)
    if mapa and q < mapa[0][2]:
        return mapa[0][0]
    if mapa and q >= mapa[-1][3]:
        return mapa[-1][1]
    return None


def _marcador(nome: str, ini: int, fim: int, comentario: str):
    m = ET.Element("marker")
    ET.SubElement(m, "comment").text = comentario
    ET.SubElement(m, "name").text = nome
    ET.SubElement(m, "in").text = str(ini)
    ET.SubElement(m, "out").text = str(fim)
    ET.SubElement(m, "pproColor").text = COR_SLIDE
    return m


def aplicar(arquivo: Path, nome_seq: str, itens: list[dict], formato: str, colocar: bool = True) -> dict:
    """Põe os slides na sequência (TP: faixa V7; TV: uma faixa nova por cima) e um marcador para cada inserção."""
    texto = arquivo.read_text(encoding="utf-8")
    root = ET.fromstring(texto.split("\n", 2)[2] if texto.startswith("<?xml") else texto)
    seq = next((s for s in root.iter("sequence") if s.findtext("name") == nome_seq), None)
    cont = {"n_slides": 0, "n_cartelas": 0}
    if seq is None or not itens:
        return cont
    mapa = _mapa(seq)
    vtr = seq.findall("media/video/track")
    if formato == "TP" and len(vtr) >= 7:
        faixa = vtr[6]
    else:
        faixa = copy.deepcopy(vtr[-1])
        for c in faixa.findall("clipitem") + faixa.findall("transitionitem") + faixa.findall("generatoritem"):
            faixa.remove(c)
        en = faixa.find("enabled")
        if en is not None:
            en.text = "TRUE"
        video = seq.find("media/video")
        video.insert(list(video).index(vtr[-1]) + 1, faixa)
    if formato == "TV":
        return _aplicar_tv(root, arquivo, seq, mapa, faixa, itens)
    molde_c, molde_f = _molde_slide()
    ids = [int(x.get("id").split("-")[-1]) for x in root.iter("clipitem") if re.fullmatch(r"clipitem-\d+", x.get("id") or "")]
    prox = max(ids or [0]) + 1000
    vistos: dict[str, str] = {}
    novos, marcas = [], []
    for k, it in enumerate(itens, 1):
        a = _na_timeline(mapa, it["ini"])
        b = _na_timeline(mapa, it.get("fim_tela") or it["ini"] + DURACAO_PADRAO)
        if a is None:
            continue
        b = max(b or a, a + 60)
        s = it.get("slide")
        img = (s or {}).get("imagem")
        if s and img:
            cod = s.get("codigo") or f"slide {s['n']:02d}"
            marcas.append(_marcador(f"SLIDE {cod}", a, b, f"{s['titulo']} ({Path(s['pptx']).name}, slide {s['n']}) "
                                    f"— posição: {it['como']}. {it['texto'][:300]}"))
            if not colocar:
                continue
            c = copy.deepcopy(molde_c)
            c.set("id", f"clipitem-{prox}")
            prox += 1
            mc = c.find("masterclipid")
            if mc is not None:
                c.remove(mc)
            nome = Path(img).name
            c.find("name").text = nome
            for tag, v in (("start", a), ("end", b), ("in", 90000), ("out", 90000 + (b - a)),
                           ("pproTicksIn", 90000 * TICKS), ("pproTicksOut", (90000 + b - a) * TICKS)):
                c.find(tag).text = str(v)
            for par in c.iter("parameter"):
                if par.findtext("parameterid") == "scale":
                    par.find("value").text = "100"           # JPEG 1920x1080: tamanho cheio
            antigo = c.find("file")
            pos = list(c).index(antigo)
            c.remove(antigo)
            if img in vistos:
                f = ET.Element("file", id=vistos[img])
            else:
                f = copy.deepcopy(molde_f)
                fid = f"file-slide-{len(vistos) + 1}"
                vistos[img] = fid
                f.set("id", fid)
                f.find("name").text = nome
                f.find("pathurl").text = _url(img)
                for e in f.iter("width"):
                    e.text = "1920"
                for e in f.iter("height"):
                    e.text = "1080"
            c.insert(pos, f)
            novos.append(c)
            cont["n_slides"] += 1
        else:
            marcas.append(_marcador("CARTELA", a, b, "Sem slide do professor para esta inserção — criar a cartela. "
                                    + it["texto"][:400]))
            cont["n_cartelas"] += 1
    _gravar(root, arquivo, seq, faixa, novos, marcas)
    return cont


def _gravar(root, arquivo: Path, seq, faixa, novos: list, marcas: list):
    # clipes na ordem do tempo, antes de enabled/locked
    existentes = faixa.findall("clipitem")
    for c in existentes:
        faixa.remove(c)
    todos = sorted(existentes + novos, key=lambda c: int(c.findtext("start")))
    p = next((i for i, ch in enumerate(list(faixa)) if ch.tag in ("enabled", "locked")), len(faixa))
    for i, c in enumerate(todos):
        faixa.insert(p + i, c)
    # marcadores junto dos outros da sequência
    ult = [i for i, ch in enumerate(list(seq)) if ch.tag == "marker"]
    pos = (ult[-1] + 1) if ult else len(seq)
    for i, m in enumerate(marcas):
        seq.insert(pos + i, m)
    arquivo.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n",
                       encoding="utf-8")


def _aplicar_tv(root, arquivo: Path, seq, mapa, faixa, itens: list[dict]) -> dict:
    """TV: no ponto de inserção, a exibição (D) entra em tela cheia numa faixa por cima, ligada."""
    vtr = seq.findall("media/video/track")
    tela = next((tr for tr in vtr if any((c.findtext("name") or "").endswith("-D") and c.find("sequence") is not None
                                         for c in tr.findall("clipitem"))), None)
    cont = {"n_slides": 0, "n_cartelas": 0, "n_tela": 0}
    if tela is None:
        return cont
    clipes_d = sorted(tela.findall("clipitem"), key=lambda c: int(c.findtext("start")))
    ids = [int(x.get("id").split("-")[-1]) for x in root.iter("clipitem") if re.fullmatch(r"clipitem-\d+", x.get("id") or "")]
    prox = max(ids or [0]) + 1000
    novos, marcas, ocupado = [], [], 0
    for it in sorted(itens, key=lambda x: x["ini"]):
        a = _na_timeline(mapa, it["ini"])
        b = _na_timeline(mapa, it.get("fim_tela") or it["ini"] + DURACAO_PADRAO)
        if a is None:
            continue
        b = max(b or a, a + 60)
        s = it.get("slide")
        sobre = f"{s['titulo']} (slide {s.get('codigo') or s['n']})" if s else "sem slide correspondente"
        marcas.append(_marcador("TELA CHEIA", a, b, f"Exibição em tela cheia — {sobre}. {it['texto'][:300]}"))
        for d in clipes_d:
            st, en = int(d.findtext("start")), int(d.findtext("end"))
            x, y = max(a, st, ocupado), min(b, en)     # inserções que se sobrepõem viram uma tela só
            if y - x < 2:
                continue
            c = copy.deepcopy(d)
            c.set("id", f"clipitem-{prox}")
            prox += 1
            for tag in ("labels", "masterclipid"):
                for e in c.findall(tag):
                    c.remove(e)
            for e in c.findall("marker") + c.findall("link"):
                c.remove(e)
            i0 = int(d.findtext("in")) + (x - st)
            for tag, v in (("start", x), ("end", y), ("in", i0), ("out", i0 + (y - x)),
                           ("pproTicksIn", i0 * TICKS), ("pproTicksOut", (i0 + y - x) * TICKS)):
                c.find(tag).text = str(v)
            novos.append(c)
            ocupado = max(ocupado, y)
        cont["n_tela"] += 1
    _gravar(root, arquivo, seq, faixa, novos, marcas)
    return cont
