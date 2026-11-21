"""Montagem das sequências: um XML por aula, para o Premiere 25.

Usa os geradores do Fluxo NPD (pasta motor/) com as regras de montagem de sempre e acrescenta o que é do
Montador:
  - cortes da Skoopia (ou das regras sem IA) já planejados para o trecho de cada aula;
  - aula em mais de um vídeo: uma sequência por trecho ("03 Título" e "03 Título (parte 2)");
  - pós-processo: nome "01 Título", tipo de cada marcação (ERRO, BASTIDORES, A CONFERIR, SILÊNCIO) com a cor
    das Configurações, nenhum efeito (Lumetri, Desfoque gaussiano) e os arquivos de vinheta/brasão/fundos desta máquina.
Nada é apagado: tudo entra cortado nos limites, com cor e marcador.
"""
from __future__ import annotations

import io
import json
import os
import re
import runpy
import sys
import tempfile
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.parse import quote

from . import insercoes, slides as slides_mod, __version__, appdata, skoopia, srt
from .srt import Cue

MOTOR = Path(__file__).resolve().parent / "motor"
MODELOS = {"TP": "modelo_tp.xml", "PALAVRA": "modelo_pk.xml", "TV": "modelo_tv.xml", "SCREENCAST": "modelo_screencast.xml"}
SILENCIO_MIN = 8.0          # segundos sem fala dentro da aula que viram marcação "SILÊNCIO"
_lock = threading.Lock()


class ErroMontagem(Exception):
    pass


# ------------------------------------------------------------------ planos de corte

def _detectar_regras(cues: list[Cue]) -> dict:
    mod = runpy.run_path(str(MOTOR / "detectar_erros.py"), run_name="detectar_erros")
    return mod["detectar"]([[c.ini, c.fim, c.texto] for c in cues])


def plano_regras(cues: list[Cue], ini: float, fim: float) -> dict:
    """Modo sem IA: as regras do Fluxo NPD (frases de interrupção, tentativas repetidas, pausas, bastidores)."""
    sel = [c for c in cues if c.ini >= ini - 0.5 and c.fim <= fim + 0.5 and c.texto.strip()]
    if not sel:
        raise ErroMontagem("trecho sem fala na transcrição")
    p = _detectar_regras(sel)
    t0, t1 = max(ini, p["T0"]), min(fim, p["T1"])
    trechos = [[max(a, t0), min(b, t1), t, (f"[ERRO] {m}" if t == "erro" else m)]
               for a, b, t, m in p["trechos"] if b > t0 and a < t1]
    return {"T0": t0, "T1": t1, "trechos": trechos, "fonte": "regras"}


def plano_skoopia(cues: list[Cue], marcas: list[Cue], ini: float, fim: float) -> dict:
    """Modo Skoopia: início e fim pela fala (regras), cortes pelas marcações dela, silêncios longos pelo app."""
    base = plano_regras(cues, ini, fim)
    t0, t1 = base["T0"], base["T1"]
    trechos = []
    for c in sorted(marcas, key=lambda x: x.ini):
        if skoopia.classe(c) == "insercao":
            continue
        a, b = max(c.ini, t0), min(c.fim, t1)
        if b - a < 0.2:
            continue
        texto = c.texto.strip()
        trechos.append([a, b, "erro", texto])
    # silêncios longos (a Skoopia só lê texto)
    fala = [c for c in cues if t0 <= c.ini <= t1 and c.texto.strip()]
    for x, y in zip(fala, fala[1:]):
        if y.ini - x.fim >= SILENCIO_MIN:
            trechos.append([x.fim, y.ini, "erro", f"[SILÊNCIO] {y.ini - x.fim:.0f} s sem fala"])
    # junta sobrepostos (a Skoopia às vezes marca o mesmo trecho como ERRO e BASTIDORES)
    trechos.sort()
    junto: list[list] = []
    for a, b, t, m in trechos:
        if junto and a < junto[-1][1] - 0.05:          # só sobreposição de verdade (vizinhos ficam separados)
            junto[-1][1] = max(junto[-1][1], b)
            if m not in junto[-1][3]:
                junto[-1][3] += " + " + m
        else:
            junto.append([a, b, t, m])
    # TV e screencast esperam a aula inteira dividida em trechos: o que não é marcação vira trecho "ok"
    cheio, cursor = [], t0
    for a, b, t, m in junto:
        a, b = max(a, t0), min(b, t1)
        if b - a < 0.05 or b <= cursor:
            continue
        if a - cursor > 0.05:
            cheio.append([cursor, a, "ok", ""])
        cheio.append([max(a, cursor), b, t, m])
        cursor = b
    if t1 - cursor > 0.05 or not cheio:
        cheio.append([cursor, t1, "ok", ""])
    return {"T0": t0, "T1": t1, "trechos": cheio, "fonte": "skoopia"}


# ------------------------------------------------------------------ geradores

def fontes() -> str | None:
    """Pasta com as fontes que vão no app (Poppins, Montserrat, Carlito)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "fontes"
    return str(p) if p.is_dir() else None


def _rodar(script: str, argv: list[str], env: dict) -> str:
    """Roda um gerador do Fluxo NPD dentro do processo (funciona também no app empacotado)."""
    saida = io.StringIO()
    with _lock:
        velho_argv, velho_env = sys.argv, dict(os.environ)
        sys.argv = [str(MOTOR / script)] + [str(a) for a in argv]
        os.environ.update({k: str(v) for k, v in env.items()})
        try:
            with redirect_stdout(saida), redirect_stderr(saida):
                runpy.run_path(str(MOTOR / script), run_name="__main__")
        except SystemExit as e:
            if e.code not in (None, 0):
                raise ErroMontagem(f"{script}: {e.code if isinstance(e.code, str) else saida.getvalue()[-300:]}")
        except Exception as e:        # noqa: BLE001
            raise ErroMontagem(f"{script}: {e}") from e
        finally:
            sys.argv = velho_argv
            os.environ.clear()
            os.environ.update(velho_env)
    return saida.getvalue()


def _gerar(formato: str, insercao: str, video: dict, cues: list[Cue], plano: dict, pasta_dia: str, n: int,
           nome_seq: str, saida: Path, tmp: Path, pptx: str | None, janela: tuple[float, float]) -> str:
    srt_p = tmp / f"{n:02d}.srt"
    srt.escrever(srt_p, cues)
    plano_p = tmp / f"{n:02d}_plano.json"
    nome_mp4 = Path(video["arquivo"]).name
    dur = video.get("duracao") or (cues[-1].fim + 1 if cues else 0)
    env = {"ANINHADO": "1", "BINS": "1", "AULA": str(n)}
    if fontes():
        env["MONTADOR_FONTES"] = fontes()
    modelo = MOTOR / "modelos" / MODELOS["PALAVRA" if formato == "TP" and insercao == "palavra" and pptx else formato]
    if formato == "SCREENCAST":
        json.dump({**plano, "raw": nome_mp4, "dur": dur, "nome": nome_seq}, open(plano_p, "w", encoding="utf-8"), ensure_ascii=False)
        return _rodar("gerar_xml_screencast.py", [modelo, plano_p, pasta_dia, saida], env)
    json.dump(plano, open(plano_p, "w", encoding="utf-8"), ensure_ascii=False)
    if formato == "TV":
        return _rodar("gerar_xml_tv.py", [modelo, plano_p, srt_p, pasta_dia, Path(nome_mp4).stem, f"{dur:.6f}", saida, nome_seq], env)
    if plano.get("fonte") == "skoopia":
        env["MONTADOR_PLANO"] = str(plano_p)      # sem IA, o TP e a palavra-chave usam as regras próprias do Fluxo NPD
    else:
        env["MONTADOR_JANELA"] = f"{janela[0]:.3f},{janela[1]:.3f}"
    if insercao == "palavra" and pptx:
        cart = tmp / f"cartoes_{n:02d}"
        cart.mkdir(exist_ok=True)
        return _rodar("gerar_xml_pk.py", [modelo, srt_p, pptx, pasta_dia, Path(nome_mp4).stem, f"{dur:.6f}",
                                          f"{janela[0]:.3f}", f"{janela[1]:.3f}", "sem-slides", cart, saida, nome_seq], env)
    # TP (slides entram na etapa 3: por enquanto a sequência sai montada, sem inserções)
    alinh = tmp / f"{n:02d}_alinh.json"
    _rodar("alinhar_pptx.py", ["-", srt_p, alinh], {})
    env["MONTADOR_NOME_SEQ"] = nome_seq
    return _rodar("gerar_xml_tp_slide.py", [modelo, alinh, srt_p, pasta_dia, n, nome_mp4, f"{dur:.6f}", saida, "sem-slides"], env)


# ------------------------------------------------------------------ pós-processo

_CLASSES = {"ERRO": ("erro", "ERRO"), "BASTIDORES": ("bastidores", "BASTIDORES"),
            "SILÊNCIO": ("conferir", "SILÊNCIO"), "CONFERIR": ("conferir", "A CONFERIR")}


def _url(caminho: str) -> str:
    p = str(caminho)
    if p.startswith("\\\\"):                                    # Windows, pasta de rede (\\servidor\\pasta)
        return "file:" + quote(p.replace("\\", "/"), safe="/:")
    if re.match(r"^[A-Za-z]:[\\\\/]", p):                     # Windows (C:\\...)
        return "file://localhost/" + quote(p.replace("\\", "/"), safe="/:")
    return "file://localhost" + quote(unicodedata.normalize("NFD", p), safe="/")


EFEITOS_FORA = {"lumetri", "gaussian blur"}


def pos_processar(arquivo: Path, nome_seq: str, cfg: dict) -> dict:
    texto = arquivo.read_text(encoding="utf-8")
    root = ET.fromstring(texto.split("\n", 2)[2] if texto.startswith("<?xml") else texto)
    cores = cfg.get("cores") or {}
    cont = {"n_erro": 0, "n_bastidores": 0, "n_silencio": 0, "n_conferir": 0, "efeitos_removidos": 0}

    # sem efeitos: cor (Lumetri) e desfoque gaussiano saem; ficam só movimento, corte, opacidade e áudio
    for pai in root.iter():
        for f in list(pai.findall("filter")):
            e = f.find("effect")
            if e is not None and (e.findtext("effectid") or "").lower() in EFEITOS_FORA:
                pai.remove(f)
                cont["efeitos_removidos"] += 1

    # arquivos de vinheta, brasão e fundos desta máquina
    por_nome = {}
    for a in appdata.ASSETS:
        p = (cfg.get("assets") or {}).get(a["id"])
        if p and Path(p).is_file():
            por_nome[unicodedata.normalize("NFC", a["nome"]).lower()] = p
    for f in root.iter("file"):
        nome = f.findtext("name")
        u = f.find("pathurl")
        if nome and u is not None:
            p = por_nome.get(unicodedata.normalize("NFC", nome).lower())
            if p:
                u.text = _url(p)

    # clipes da câmera (aninhados) com o nome da própria sequência aninhada (o modelo trazia o nome de outra gravação)
    nomes_seq = {x.get("id"): x.findtext("name") for x in root.iter("sequence") if x.get("id") and x.findtext("name")}
    for c in root.iter("clipitem"):
        sq = c.find("sequence")
        if sq is not None and c.find("name") is not None:
            nm = sq.findtext("name") or nomes_seq.get(sq.get("id"))
            if nm:
                c.find("name").text = nm

    # tipo de cada marcação e cor dos trechos
    for seq in root.iter("sequence"):
        if seq.findtext("name") != nome_seq:
            continue
        faixas = {}
        for m in seq.findall("marker"):
            if m.findtext("name") != "ERRO a conferir":
                continue
            com = m.find("comment")
            txt = (com.text or "") if com is not None else ""
            k = re.search(r"\[(ERRO|BASTIDORES|SILÊNCIO|CONFERIR)\]\s*", txt, re.I)
            classe = k.group(1).upper() if k else "ERRO"
            cor_chave, rotulo = _CLASSES.get(classe, ("erro", "ERRO"))
            m.find("name").text = rotulo
            if com is not None and k:
                com.text = re.sub(r"^Possível erro \(nada foi apagado\):\s*", "", txt[:k.start()] + txt[k.end():]).strip()
            faixas[(m.findtext("in"), m.findtext("out"))] = cores.get(cor_chave)
            cont["n_" + {"ERRO": "erro", "BASTIDORES": "bastidores", "SILÊNCIO": "silencio"}.get(classe, "conferir")] += 1
        for c in seq.iter("clipitem"):
            cor = faixas.get((c.findtext("start"), c.findtext("end")))
            if cor:
                for l2 in c.iter("label2"):
                    if l2.text == "Rose":            # só o que o gerador marcou como suspeito (as outras trilhas mantêm o rótulo)
                        l2.text = cor
    arquivo.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n",
                       encoding="utf-8")
    return cont


# ------------------------------------------------------------------ o dia inteiro

def _nome_arquivo(nome: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", nome).strip(" .") or "sequencia"


def montar(dia: dict, falas: dict, aulas: list[dict], formato: str, insercao: str, marcas: dict,
           destino: str | Path, cfg: dict | None = None, modo: str = "auto", juntar: bool = False) -> dict:
    """Gera um XML por aula (por trecho, quando a aula está em mais de um vídeo) — ou um XML só com todas."""
    cfg = cfg or appdata.carregar()
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    videos = {v["nome"]: v for v in dia["videos"]}
    pptx = (dia.get("material") or {}).get("pptx") or []
    usar_skoopia = modo == "skoopia" or (modo == "auto" and any(marcas.values()))
    resultados, avisos = [], []
    padrao = float(cfg.get("duracao_slide") or insercoes.DURACAO_PADRAO)

    # slides do professor (TP e TV): texto de cada slide e imagens JPEG
    com_slides = formato in ("TP", "TV") and insercao not in ("nenhuma", "palavra")
    lista_pptx = []
    if com_slides:
        for p in pptx:
            try:
                conv = slides_mod.converter(p, cfg)
                lista_pptx.append({"pptx": p, "slides": slides_mod.ler(p), "imagens": conv["imagens"]})
                avisos.append(f"Slides de {Path(p).name}: {len(conv['imagens'])} imagem(ns) ({conv['metodo']})")
            except slides_mod.ErroSlides as e:
                avisos.append(f"{Path(p).name}: {e}")
    todos_slides = insercoes.todos_os_slides(lista_pptx)
    imagens = (dia.get("material") or {}).get("imagens") or []
    if com_slides and imagens:
        soltas = insercoes.slides_de_imagens(imagens, pptx)
        if soltas:
            todos_slides += soltas
            avisos.append(f"Imagens prontas usadas como slides: {len(soltas)}")
    if com_slides and not pptx and not imagens:
        avisos.append("Nenhum .pptx no material do dia: as inserções viraram marcadores CARTELA. "
                      "Adicione os slides na caixa Material e monte de novo.")

    # onde entra cada inserção, aula por aula (sem IA: cada slide fica só na aula em que mais combina)
    planos, itens_por = {}, {}
    for a in aulas:
        for k, tr in enumerate(a["trechos"], 1):
            cues = falas.get(tr["video"]) or []
            if not cues:
                continue
            mk = [c for lista in (marcas.get(tr["video"]) or {}).values() if skoopia.tipo(lista) != "aulas" for c in lista]
            plano = plano_skoopia(cues, mk, tr["ini"], tr["fim"]) if usar_skoopia else plano_regras(cues, tr["ini"], tr["fim"])
            planos[(a["n"], k)] = plano
            if not com_slides:
                continue
            if usar_skoopia:
                its = insercoes.casar_skoopia([c for c in mk if plano["T0"] - 1 <= c.ini <= plano["T1"]], todos_slides)
            else:
                its = insercoes.casar_regras(cues, plano["T0"], plano["T1"], todos_slides)
            itens_por[(a["n"], k)] = its
    if com_slides and not usar_skoopia:
        melhor = {}
        for chave, its in itens_por.items():
            for it in its:
                sid = (it["slide"]["pptx"], it["slide"]["n"])
                if sid not in melhor or it["nota"] > melhor[sid][1]["nota"]:
                    melhor[sid] = (chave, it)
        for chave in itens_por:
            itens_por[chave] = [it for it in itens_por[chave]
                                if melhor[(it["slide"]["pptx"], it["slide"]["n"])][1] is it]
    with tempfile.TemporaryDirectory(prefix="montador_") as t:
        tmp = Path(t)
        for a in aulas:
            partes = a["trechos"]
            for k, tr in enumerate(partes, 1):
                nome = a["nome"] if len(partes) == 1 else (a["nome"] + (f" (parte {k})" if k > 1 else ""))
                v = videos.get(tr["video"])
                cues = falas.get(tr["video"]) or []
                item = {"aula": a["n"], "nome": nome, "video": tr["video"], "arquivo": None, "erro": None}
                try:
                    if not v:
                        raise ErroMontagem("vídeo não encontrado")
                    if not cues:
                        raise ErroMontagem("sem transcrição")
                    plano = planos[(a["n"], k)]
                    saida = (tmp / "aulas" if juntar else destino) / f"{_nome_arquivo(nome)}.xml"
                    saida.parent.mkdir(exist_ok=True)
                    log = _gerar(formato, insercao, v, cues, plano, dia["raiz"], a["n"], nome, saida, tmp,
                                 pptx[0] if pptx else None, (tr["ini"], tr["fim"]))
                    cont = pos_processar(saida, nome, cfg)
                    its = itens_por.get((a["n"], k)) or []
                    if formato == "TV" and usar_skoopia:     # TV: a tela fica cheia o trecho todo que a Skoopia marcou
                        for it in its:
                            it["fim_tela"] = min(max(it["fim"], it["ini"] + 2.0), plano["T1"])
                    else:
                        its = insercoes.duracoes(its, plano["T1"], padrao)
                    cont.update(insercoes.aplicar(saida, nome, its, formato))
                    item.update(arquivo=str(saida), fonte=plano["fonte"], T0=plano["T0"], T1=plano["T1"], **cont,
                                log=log.strip().splitlines()[-1:] if log.strip() else [])
                except ErroMontagem as e:
                    item["erro"] = str(e)
                    avisos.append(f"{nome}: {e}")
                resultados.append(item)
                if len(partes) > 1 and k == 1:
                    avisos.append(f"{a['nome']}: a aula está em {len(partes)} vídeos e saiu em {len(partes)} sequências "
                                  "— junte as partes na timeline")
        unico = None
        prontos = [Path(r["arquivo"]) for r in resultados if r["arquivo"]]
        if juntar and prontos:
            from .juntar import juntar as _juntar
            unico = destino / f"{_nome_arquivo(dia['nome'])} - aulas.xml"
            _juntar(prontos, unico, dia["nome"])
            for r in resultados:
                if r["arquivo"]:
                    r["arquivo"] = str(unico)
    rel = _relatorio(dia, formato, insercao, usar_skoopia, resultados, avisos, destino)
    return {"resultados": resultados, "avisos": avisos, "relatorio": str(rel), "destino": str(destino),
            "modo": "skoopia" if usar_skoopia else "regras", "unico": str(unico) if unico else None}


def _relatorio(dia, formato, insercao, usar_skoopia, resultados, avisos, destino: Path) -> Path:
    """Relatório de uso, ao lado dos XMLs (para mandar junto quando algo der errado)."""
    agora = time.strftime("%Y-%m-%d %H%M")
    p = destino / f"Montador - relatório {agora}.txt"
    linhas = [f"Montador {__version__} · {agora}", f"Dia: {dia['curso']} / {dia['nome']}",
              f"Formato: {formato}" + (f" · inserção: {insercao}" if formato in ("TP", "TV") else ""),
              f"Marcações: {'Skoopia' if usar_skoopia else 'regras do Fluxo NPD (sem IA)'}", ""]
    for r in resultados:
        if r["erro"]:
            linhas.append(f"{r['nome']}: NÃO GERADO ({r['erro']})")
            continue
        linhas.append(f"{r['nome']} · {r['video']} de {r['T0']:.1f} a {r['T1']:.1f} s · {r['n_erro']} erro(s), "
                      f"{r['n_bastidores']} bastidores, {r['n_silencio']} silêncio(s), {r['n_conferir']} a conferir"
                      + (f" · {r.get('n_slides', 0)} slide(s)" if r.get("n_slides") else "")
                      + (f" · {r['n_cartelas']} cartela(s) a criar" if r.get("n_cartelas") else "")
                      + (f" · {r['n_palavras']} palavra(s)-chave/tarja(s) marcada(s)" if r.get("n_palavras") else "")
                      + (f" · {r['n_tela']} tela(s) cheia(s)" if r.get("n_tela") else "")
                      + (f" · {r['efeitos_removidos']} efeito(s) removido(s)" if r["efeitos_removidos"] else ""))
    linhas += [""] + [f"Aviso: {a}" for a in avisos]
    p.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return p
