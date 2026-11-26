"""Servidor local: a janela do Montador abre no navegador e conversa com o motor por aqui.

Só escuta em 127.0.0.1 (nada sai do computador). Rodar: python3 -m montador
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import socket
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, appdata, atualizar, cartao, dia, dialogs, importar, mapa, montagem, skoopia, srt

UI_DIR = Path(__file__).resolve().parent / "ui"
PORTA_PADRAO = 8767


class ApiError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class Estado:
    def __init__(self):
        self.lock = threading.RLock()
        self.ultimo_ping = time.time()
        self.dia: dict | None = None
        self.falas: dict = {}
        self.manuais: dict = {}          # transcrições importadas à mão (vídeo → falas), por pasta do dia
        self.raiz_manuais: str | None = None
        self.tabela: list = []           # onde cada vídeo começa no SRT único (para dividir o que vem do dia inteiro)
        self.marcas: dict = {}           # vídeo → {"arquivo.srt": [cues]} (retorno da Skoopia, já no tempo do vídeo)
        self.skoopia: list = []          # arquivos importados: {nome, tipo, modo, video, motivo, n}
        self.pendentes: dict = {}        # nome → cues (esperando o editor escolher o vídeo)
        self.skoopia_cues: dict = {}     # nome → cues como vieram (para dividir de novo quando a tabela mudar)
        self.escolhidos: dict = {}       # nome → vídeo escolhido pelo editor para um SRT da Skoopia
        self.soltos: dict = {}           # transcrições sem dono que podem ser a master do Premiere: nome → texto
        self.xml_master: dict = {}       # XML da sequência master importado: nome → texto
        self.premiere = False            # o editor marcou "Transcrição feita no Premiere"
        self.material_extra: list = []   # arquivos de inserção escolhidos à mão
        self.material_fora: set = set()  # arquivos tirados da lista (não entram na montagem)
        self.material_dentro: set = set()  # arquivos TP que o editor decidiu usar mesmo assim

    def limpar_dia(self, raiz: str):
        if self.raiz_manuais != raiz:
            self.manuais, self.raiz_manuais, self.tabela = {}, raiz, []
            self.marcas, self.skoopia, self.pendentes, self.material_extra = {}, [], {}, []
            self.material_fora, self.material_dentro = set(), set()
            self.skoopia_cues, self.escolhidos, self.soltos, self.xml_master = {}, {}, {}, {}
            self.premiere = False


ESTADO = Estado()


# ====================================================================== ações

def acao_estado(_q) -> dict:
    cfg = appdata.carregar()
    from . import slides
    return {"versao": __version__, "build": atualizar.__build__, "config": cfg, "assets": appdata.estado_assets(cfg),
            "cores_premiere": appdata.CORES_PREMIERE, "libreoffice": slides.soffice(cfg),
            "keynote": sys.platform == "darwin" and Path("/Applications/Keynote.app").exists()}


def acao_config(corpo) -> dict:
    appdata.salvar(corpo.get("mudancas") or {})
    return acao_estado(None)


def acao_escolher(corpo) -> dict:
    tipo = corpo.get("tipo", "pasta")
    titulo = corpo.get("titulo") or ("Escolha a pasta" if tipo == "pasta" else "Escolha o arquivo")
    inicio = corpo.get("inicio") or appdata.carregar().get("ultima_pasta")
    try:
        if tipo == "pasta":
            p = dialogs.choose_folder(titulo, inicio)
        elif tipo == "arquivos":
            return {"caminhos": dialogs.choose_files(titulo, inicio) or []}
        else:
            p = dialogs.choose_file(titulo, inicio)
    except dialogs.Unsupported:
        return {"sem_janela": True}
    return {"caminho": p}


def acao_raizes(_q) -> dict:
    return {"raizes": dialogs.roots()}


def acao_listar(q) -> dict:
    caminho = (q.get("caminho") or [""])[0]
    try:
        return dialogs.listdir(caminho)
    except FileNotFoundError:
        raise ApiError("Pasta não encontrada.")


def acao_apontar_asset(corpo) -> dict:
    ident, caminho = corpo.get("id"), corpo.get("caminho")
    if not caminho or not Path(caminho).is_file():
        raise ApiError("Arquivo não encontrado.")
    cfg = appdata.carregar()
    assets = dict(cfg["assets"])
    assets[ident] = caminho
    achados = appdata.procurar_assets(caminho)
    novos = 0
    for k, v in achados.items():
        atual = assets.get(k)
        if not atual or not Path(atual).is_file():
            assets[k] = v
            novos += 1
    appdata.salvar({"assets": assets})
    out = acao_estado(None)
    out["achados"] = novos
    return out


def _sem_cues(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_cues"}


def acao_dia(corpo) -> dict:
    caminho = corpo.get("caminho")
    if not caminho:
        raise ApiError("Escolha a pasta do dia.")
    try:
        d = dia.ler(caminho)
    except FileNotFoundError:
        raise ApiError("Pasta não encontrada.")
    cfg = appdata.carregar()
    faltam = [v["nome"] for v in d["videos"] if not v["srt"]]
    if faltam and cfg.get("pasta_transcricoes") and Path(cfg["pasta_transcricoes"]).is_dir():
        achados = importar.procurar_por_nome(cfg["pasta_transcricoes"], faltam)
        for v in d["videos"]:
            if v["nome"] in achados:
                v["srt"] = achados[v["nome"]]
    falas = dia.transcricoes(d)
    tabela = d.get("tabela") or []
    if not tabela and d.get("srt_unico"):
        tabela = [{"video": n, "separador": t, "fala": t + 2.0} for n, t in srt.separadores(srt.ler(d["srt_unico"]))]
    with ESTADO.lock:
        ESTADO.limpar_dia(d["raiz"])
        if tabela:
            ESTADO.tabela = tabela
        falas.update(ESTADO.manuais)
        ESTADO.dia, ESTADO.falas = d, falas
        if d.get("candidato_master"):
            try:
                q = Path(d["candidato_master"])
                ESTADO.soltos.setdefault(q.name, importar._decodifica(q.read_bytes()))
            except OSError:
                pass
    appdata.salvar({"ultima_pasta": d["raiz"]})
    if ESTADO.soltos and (ESTADO.premiere or ESTADO.xml_master):     # a mesma pasta aberta de novo
        _importar([], ESTADO.premiere)
    _religar_skoopia()
    return _resultado(d, ESTADO.falas, (d.get("cartao") or {}).get("titulos") or [])


def _importar(arquivos: list[dict], premiere: bool) -> dict:
    """Classifica as transcrições (com as soltas e o XML já guardados) e atualiza o estado."""
    with ESTADO.lock:
        d = ESTADO.dia
        nomes_novos = {a.get("nome") for a in arquivos}
        for a in arquivos:
            if (a.get("nome") or "").lower().endswith(".xml"):
                ESTADO.xml_master = {a["nome"]: a.get("conteudo") or ""}
        todos = [a for a in arquivos if not (a.get("nome") or "").lower().endswith(".xml")]
        todos += [{"nome": n, "conteudo": t} for n, t in ESTADO.xml_master.items()]
        todos += [{"nome": n, "conteudo": t} for n, t in ESTADO.soltos.items() if n not in nomes_novos]
    nomes = [v["nome"] for v in d["videos"]]
    r = importar.classificar(todos, nomes, d["videos"], premiere=premiere)
    with ESTADO.lock:
        if r["xml"] is None and ESTADO.xml_master and any(n in r["motivos"] for n in ESTADO.xml_master):
            ESTADO.xml_master = {}                        # XML inválido: não fica guardado
        if r["tabela"]:
            ESTADO.tabela = r["tabela"]
        if r["master"]:
            ESTADO.soltos = {}
        else:
            ESTADO.soltos.update(r["soltos"])
        ESTADO.manuais.update(r["por_video"])
        ESTADO.falas.update(r["por_video"])
    return r


def acao_transcricoes(corpo) -> dict:
    """Transcrições importadas à mão: arquivos arrastados/escolhidos (conteúdo) ou uma pasta (caminho).

    Também o XML da sequência master e a caixa "Transcrição feita no Premiere" (premiere: true/false):
    a transcrição sem dono que já veio antes é dividida de novo, sem precisar importar outra vez."""
    with ESTADO.lock:
        d = ESTADO.dia
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    arquivos = corpo.get("arquivos") or []
    if corpo.get("pasta"):
        if not Path(corpo["pasta"]).is_dir():
            raise ApiError("Pasta não encontrada.")
        arquivos = importar.ler_pasta(corpo["pasta"])
    with ESTADO.lock:
        if "premiere" in corpo:
            ESTADO.premiere = bool(corpo["premiere"])
        premiere = ESTADO.premiere
    r = _importar(arquivos, premiere)
    _religar_skoopia()                                    # a tabela pode ter mudado: a Skoopia se divide de novo
    out = _resultado(d, ESTADO.falas, (d.get("cartao") or {}).get("titulos") or [])
    out["importacao"] = {"videos": sorted(r["por_video"]), "unico": r["unico"], "skoopia": r["skoopia"],
                         "ignorados": [n for n in r["ignorados"] if n in {a.get("nome") for a in arquivos}],
                         "master": r.get("master", False), "motivos": r["motivos"], "explicacao": r["explicacao"],
                         "xml": r["xml"]}
    return out


def acao_skoopia(corpo) -> dict:
    """SRTs de cortes e inserções da Skoopia (conteúdo vindo da janela)."""
    with ESTADO.lock:
        d = ESTADO.dia
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    with ESTADO.lock:
        for a in corpo.get("arquivos") or []:
            cues = srt.ler_texto(a.get("conteudo") or "")
            if cues:
                nome = a.get("nome") or "sem nome.srt"
                ESTADO.skoopia_cues[nome] = cues
                ESTADO.escolhidos.pop(nome, None)
        e = corpo.get("escolher")
        if e and e.get("nome") in ESTADO.skoopia_cues and e.get("video"):   # o editor escolheu o vídeo
            ESTADO.escolhidos[e["nome"]] = e["video"]
        if corpo.get("remover"):
            ESTADO.skoopia_cues.pop(corpo["remover"], None)
            ESTADO.escolhidos.pop(corpo["remover"], None)
    _religar_skoopia()
    return _resultado(d, ESTADO.falas, (d.get("cartao") or {}).get("titulos") or [])


def _religar_skoopia():
    """Liga cada SRT da Skoopia ao vídeo (ou divide pelo dia) com o que se sabe agora."""
    with ESTADO.lock:
        d, falas, tabela = ESTADO.dia, ESTADO.falas, ESTADO.tabela
        if d is None:
            return
        ESTADO.marcas, ESTADO.skoopia, ESTADO.pendentes = {}, [], {}
        # cortes primeiro: têm citações e ajudam a achar as posições para as inserções
        lidos = sorted(ESTADO.skoopia_cues.items(), key=lambda x: skoopia.tipo(x[1]) != "cortes")
        tabela_uso = tabela
        for nome, cues in lidos:
            if nome in ESTADO.escolhidos:
                dest = {"modo": "video", "video": ESTADO.escolhidos[nome], "motivo": "escolhido pelo editor"}
            else:
                dest = skoopia.ligar(nome, cues, d["videos"], falas, tabela_uso)
                if dest.get("tabela") and not tabela_uso:
                    tabela_uso = dest["tabela"]       # posições achadas pelas falas: valem para os próximos
            _guardar_skoopia(nome, cues, dest, tabela_uso)


def _guardar_skoopia(nome: str, cues, dest: dict, tabela: list):
    with ESTADO.lock:
        t = skoopia.tipo(cues)
        if dest["modo"] == "pendente":
            ESTADO.pendentes[nome] = cues
        for video, lista in skoopia.distribuir(cues, dest, tabela).items():
            ESTADO.marcas.setdefault(video, {})[nome] = lista
        ESTADO.skoopia.append({"nome": nome, "tipo": t, "n": len(cues), **{k: v for k, v in dest.items() if k != "tabela"}})


# arquivos que começam com "TP" (TP-aula-17.pptx, TP_aula 3.pptx…) são do teleprompter: só para a gravação
_TELEPROMPTER = re.compile(r"^TP(?=[\s_\-.]|\d)", re.I)


def eh_teleprompter(caminho: str) -> bool:
    return bool(_TELEPROMPTER.match(Path(caminho).name))


def acao_material(corpo) -> dict:
    """Material de inserção: adicionar arquivos/pasta, tirar qualquer um da lista ou voltar a usar."""
    with ESTADO.lock:
        d = ESTADO.dia
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    novos = list(corpo.get("adicionar") or [])
    if corpo.get("pasta"):
        p = Path(corpo["pasta"])
        if not p.is_dir():
            raise ApiError("Pasta não encontrada.")
        novos += [str(q) for q in sorted(p.rglob("*")) if q.is_file() and not q.name.startswith(("~$", "."))
                  and q.suffix.lower() in (".pptx", ".docx", ".jpg", ".jpeg", ".png")]
    with ESTADO.lock:
        for n in novos:
            if Path(n).is_file():
                if n not in ESTADO.material_extra:
                    ESTADO.material_extra.append(n)
                ESTADO.material_fora.discard(n)
                if corpo.get("adicionar") and eh_teleprompter(n):   # escolhido um a um: o editor quer usar
                    ESTADO.material_dentro.add(n)
        rm = corpo.get("remover")
        if rm:
            if rm in ESTADO.material_extra:
                ESTADO.material_extra = [x for x in ESTADO.material_extra if x != rm]
            else:
                ESTADO.material_fora.add(rm)
            ESTADO.material_dentro.discard(rm)
        us = corpo.get("usar")
        if us:
            ESTADO.material_fora.discard(us)
            if eh_teleprompter(us):
                ESTADO.material_dentro.add(us)
    return _resultado(d, ESTADO.falas, (d.get("cartao") or {}).get("titulos") or [])


def _material(d: dict) -> dict:
    """Material que entra na montagem + o que ficou de fora (com o motivo)."""
    out = {"pptx": [], "docx": [], "imagens": [], "manuais": list(ESTADO.material_extra), "fora": []}
    todos = list(d["material"]["pptx"]) + list(d["material"]["docx"]) + list(d["material"]["imagens"])
    todos += [p for p in ESTADO.material_extra if p not in todos]
    for p in todos:
        if p in ESTADO.material_fora:
            out["fora"].append({"arquivo": p, "motivo": "tirado"})
            continue
        if eh_teleprompter(p) and p not in ESTADO.material_dentro:
            out["fora"].append({"arquivo": p, "motivo": "teleprompter"})
            continue
        ext = Path(p).suffix.lower()
        out["pptx" if ext == ".pptx" else "docx" if ext == ".docx" else "imagens"].append(p)
    return out


_CACHE_SLIDES: dict = {}


def _texto_pptx(caminho: str) -> str:
    """Texto de todos os slides de um .pptx (guardado enquanto o arquivo não mudar)."""
    from . import slides
    try:
        chave = (caminho, Path(caminho).stat().st_mtime)
    except OSError:
        return ""
    if chave not in _CACHE_SLIDES:
        try:
            _CACHE_SLIDES[chave] = " ".join(t for s in slides.ler(caminho) if not s.get("referencias")
                                            for t in s["textos"])
        except Exception:      # noqa: BLE001 — slide ilegível só deixa de ser pista
            _CACHE_SLIDES[chave] = ""
    return _CACHE_SLIDES[chave]


def _pistas(d: dict, titulos: list[str]) -> tuple[list[str], dict]:
    """Texto dos slides de cada título e inserções da Skoopia de cada vídeo (pistas do mapa)."""
    pptx = _material(d)["pptx"]
    decks = [(Path(p).stem, _texto_pptx(p)) for p in pptx]
    slides_t = mapa.slides_dos_titulos([x for x in decks if x[1]], titulos)
    with ESTADO.lock:
        ins = {v: [c for lista in m.values() for c in lista if skoopia.classe(c) == "insercao"]
               for v, m in ESTADO.marcas.items()}
    return slides_t, {v: cs for v, cs in ins.items() if cs}


def _resultado(d: dict, falas: dict, titulos_brutos: list[str]) -> dict:
    # títulos grudados no cartão: uma 1ª passada sem títulos diz quantas aulas o vídeo mostra; se for mais
    # do que as linhas do cartão, desgruda os títulos até bater. Depois o mapa parte dos títulos.
    linhas = [t.strip() for t in titulos_brutos if t and t.strip()]
    sep = {"titulos": linhas, "separados": 0, "conferir": False, "motivo": ""}
    if linhas:
        previa = mapa.sugerir(d["videos"], falas, [])
        n = len([a for a in previa["aulas"] if a["trechos"]])
        if n > len(linhas):
            sep = cartao.separar_titulos(linhas, n)
    slides_t, ins = _pistas(d, sep["titulos"]) if sep["titulos"] else ([], {})
    m = mapa.sugerir(d["videos"], falas, sep["titulos"], slides_t, ins)
    with ESTADO.lock:
        for a in m["aulas"]:
            a["marcas"] = skoopia.contar(ESTADO.marcas, a["trechos"])
        d = dict(d, transcritos=sorted(k for k, v in falas.items() if v), material=_material(d),
                 skoopia=list(ESTADO.skoopia), tem_tabela=bool(ESTADO.tabela), premiere=ESTADO.premiere,
                 xml_master=next(iter(ESTADO.xml_master), None), soltos=sorted(ESTADO.soltos))
    d["avisos"] = [a for a in d["avisos"] if not a.startswith("Sem transcrição")]
    if set(v["nome"] for v in d["videos"]) <= set(d["transcritos"]):     # a master já foi dividida
        d["avisos"] = [a for a in d["avisos"] if "parece a transcrição da sequência" not in a]
    faltam = [v["nome"] for v in d["videos"] if v["nome"] not in d["transcritos"]]
    if faltam:
        d["avisos"].append("Sem transcrição: " + ", ".join(faltam) + ". Importe os .srt ou rode o transcribe na pasta.")
    return {"dia": d, "titulos": sep, "mapa": m}


def acao_cartao_texto(corpo) -> dict:
    """O editor colou o texto do cartão (ou só a lista de títulos)."""
    texto = corpo.get("texto") or ""
    c = cartao.ler_texto(texto)
    titulos = c.titulos or [l for l in texto.splitlines() if l.strip()]
    with ESTADO.lock:
        d, falas = ESTADO.dia, ESTADO.falas
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    d = dict(d)
    d["cartao"] = {"arquivo": None, **c.resumo(), "titulos": titulos}
    with ESTADO.lock:
        ESTADO.dia = d
    return _resultado(d, falas, titulos)


def acao_mapa(corpo) -> dict:
    fx = corpo.get("faixas") or []
    if corpo.get("dividir"):
        dv = corpo["dividir"]
        fx = mapa.dividir(fx, dv.get("video"), float(dv.get("tempo", 0)))
    m = {"faixas": fx, **mapa.montar(fx, corpo.get("titulos") or [])}
    with ESTADO.lock:
        for a in m["aulas"]:
            a["marcas"] = skoopia.contar(ESTADO.marcas, a["trechos"])
    return m


def acao_montar(corpo) -> dict:
    with ESTADO.lock:
        d, falas, marcas = ESTADO.dia, dict(ESTADO.falas), {k: dict(v) for k, v in ESTADO.marcas.items()}
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    titulos = corpo.get("titulos") or []
    m = mapa.montar(corpo.get("faixas") or [], titulos)
    sem_trecho = [a["nome"] for a in m["aulas"] if not a["trechos"]]
    m["aulas"] = [a for a in m["aulas"] if a["trechos"]]
    if not m["aulas"]:
        raise ApiError("Nenhuma aula no mapa do dia.")
    destino = corpo.get("destino") or str(Path(d["raiz"]) / "Projeto")
    cfg = appdata.carregar()
    if corpo.get("destino"):
        appdata.salvar({"pasta_exportacao": corpo["destino"]})
    if "juntar" in corpo:
        appdata.salvar({"juntar_xml": bool(corpo["juntar"])})
    if "script" in corpo:
        appdata.salvar({"script_com_skoopia": bool(corpo["script"])})
    # o material é lido de novo agora: o editor pode ter posto slides na pasta depois de abrir o dia
    novo, _ = dia.procurar_material(Path(d["raiz"]), d.get("originais") and Path(d["originais"]))
    with ESTADO.lock:
        d = ESTADO.dia = dict(d, material=novo)
    dd = dict(d, material=_material(d))
    try:
        r = montagem.montar(dd, falas, m["aulas"], corpo.get("formato") or "TP", corpo.get("insercao") or "slide",
                               marcas, destino, cfg, cfg.get("marcacoes") or "auto",
                               juntar=bool(corpo["juntar"]) if "juntar" in corpo else bool(cfg.get("juntar_xml", True)),
                               com_script=bool(corpo["script"]) if "script" in corpo else None)
        if sem_trecho:
            r["avisos"].insert(0, "Ficaram sem sequência (aula não reconhecida no mapa): " + ", ".join(sem_trecho))
        return r
    except OSError as e:
        raise ApiError(f"Não consegui gravar em {destino}: {e}")


def acao_thumbs_modelo(_corpo) -> dict:
    from . import thumbs
    try:
        m = thumbs.ler_modelo(appdata.carregar().get("thumb_html"))
    except thumbs.ErroThumb as e:
        raise ApiError(str(e))
    with ESTADO.lock:
        d = ESTADO.dia
    return {**m, "pasta": str(Path(d["raiz"]) / "Saída") if d else ""}


def acao_thumbs_salvar(corpo) -> dict:
    from . import thumbs
    pasta = (corpo.get("pasta") or "").strip()
    if not pasta:
        raise ApiError("Escolha a pasta das thumbs.")
    try:
        return {"arquivos": thumbs.salvar(pasta, corpo.get("itens") or []), "pasta": pasta}
    except OSError as e:
        raise ApiError(f"Não consegui gravar em {pasta}: {e}")


def acao_abrir_pasta(corpo) -> dict:
    import subprocess
    p = corpo.get("caminho")
    if not p or not Path(p).exists():
        raise ApiError("Pasta não encontrada.")
    if sys.platform == "darwin":
        subprocess.Popen(["open", p])
    elif os.name == "nt":
        os.startfile(p)        # noqa: S606 — abre no Explorer
    else:
        subprocess.Popen(["xdg-open", p])
    return {"ok": True}


_ATUALIZACAO: dict = {}           # resposta do GitHub guardada por 1 hora
_SERVIDOR: list = []                # o servidor HTTP aberto (para fechar depois de atualizar)


def acao_atualizacao(corpo) -> dict:
    """Tem versão nova no GitHub? (não trava a janela se estiver sem internet)"""
    testes = bool(appdata.carregar().get("atualizar_testes"))
    agora = time.time()
    if not corpo.get("forcar") and _ATUALIZACAO.get("testes") == testes and agora - _ATUALIZACAO.get("quando", 0) < 3600:
        return _ATUALIZACAO["r"]
    try:
        r = atualizar.verificar(testes)
    except (atualizar.ErroAtualizar, ValueError) as e:
        r = {"tem": False, "erro": str(e)}
    r["atual"] = atualizar.atual()
    _ATUALIZACAO.update(r=r, testes=testes, quando=agora)
    return r


def acao_atualizar(corpo) -> dict:
    """modo "baixar": o .zip vai para Downloads e a pasta abre. modo "instalar": troca o app e reabre."""
    info = acao_atualizacao({})
    if not info.get("tem"):
        raise ApiError(info.get("erro") or "Não há versão nova.")
    try:
        zip_ = atualizar.baixar(info)
    except atualizar.ErroAtualizar as e:
        raise ApiError(f"Não consegui baixar: {e}.")
    if corpo.get("modo") != "instalar":
        try:
            acao_abrir_pasta({"caminho": str(zip_.parent)})
        except ApiError:
            pass
        return {"arquivo": str(zip_)}
    try:
        r = atualizar.instalar(zip_)
    except atualizar.ErroAtualizar as e:
        acao_abrir_pasta({"caminho": str(zip_.parent)})
        raise ApiError(f"Não consegui trocar o app: {e}. O arquivo ficou em {zip_.parent}.")
    except OSError as e:
        acao_abrir_pasta({"caminho": str(zip_.parent)})
        raise ApiError(f"Sem permissão para trocar o app ({e}). O arquivo ficou em {zip_.parent}: "
                       "troque à mão como antes.")
    if _SERVIDOR:                                       # fecha este app: o script troca e abre o novo
        threading.Timer(1.5, _SERVIDOR[0].shutdown).start()
    return {"arquivo": str(zip_), **r}


GET = {"/api/estado": acao_estado, "/api/raizes": acao_raizes, "/api/listar": acao_listar}
POST = {"/api/config": acao_config, "/api/escolher": acao_escolher, "/api/assets/apontar": acao_apontar_asset,
        "/api/dia": acao_dia, "/api/cartao/texto": acao_cartao_texto, "/api/transcricoes": acao_transcricoes,
        "/api/skoopia": acao_skoopia, "/api/material": acao_material, "/api/mapa": acao_mapa,
        "/api/montar": acao_montar, "/api/abrir_pasta": acao_abrir_pasta,
        "/api/thumbs/modelo": acao_thumbs_modelo, "/api/thumbs/salvar": acao_thumbs_salvar,
        "/api/atualizacao": acao_atualizacao, "/api/atualizar": acao_atualizar}


# ====================================================================== HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "Montador"

    def log_message(self, *a):
        pass

    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, p: Path):
        if not p.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        dados = p.read_bytes()
        tipo = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".js":
            tipo = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", tipo + ("; charset=utf-8" if tipo.startswith("text") else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _origem_ok(self) -> bool:
        org = self.headers.get("Origin")
        return not org or org.startswith(("http://127.0.0.1", "http://localhost"))

    def do_GET(self):
        u = urlparse(self.path)
        ESTADO.ultimo_ping = time.time()
        if u.path in ("/", "/index.html"):
            return self._arquivo(UI_DIR / "index.html")
        if u.path.startswith("/ui/"):
            alvo = (UI_DIR / unquote(u.path[4:])).resolve()
            if UI_DIR not in alvo.parents:
                return self.send_error(HTTPStatus.FORBIDDEN)
            return self._arquivo(alvo)
        fn = GET.get(u.path)
        if fn is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        self._rodar(fn, parse_qs(u.query))

    def do_POST(self):
        u = urlparse(self.path)
        ESTADO.ultimo_ping = time.time()
        if not self._origem_ok():
            return self.send_error(HTTPStatus.FORBIDDEN)
        if u.path == "/api/ping":
            return self._json({"ok": True})
        if u.path == "/api/sair":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        fn = POST.get(u.path)
        if fn is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        tam = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(tam).decode("utf-8") or "{}") if tam else {}
        except ValueError:
            return self._json({"erro": "Pedido inválido."}, 400)
        self._rodar(fn, corpo)

    def _rodar(self, fn, arg):
        try:
            self._json(fn(arg))
        except ApiError as e:
            self._json({"erro": str(e)}, e.status)
        except Exception as e:      # noqa: BLE001 — a tela mostra o erro em vez de travar
            traceback.print_exc()
            self._json({"erro": f"Erro inesperado: {e}"}, 500)


def _porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def _versao_aberta(porta: int) -> str | None:
    import json as _json
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(f"http://127.0.0.1:{porta}/api/estado", timeout=3) as r:
            return _json.loads(r.read().decode("utf-8")).get("versao")
    except Exception:          # noqa: BLE001
        return None


def _encerrar(porta: int, espera: float = 10.0) -> bool:
    """Pede para o Montador que está aberto nessa porta se fechar; True se a porta ficou livre."""
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        op.open(urllib.request.Request(f"http://127.0.0.1:{porta}/api/sair", data=b"{}", method="POST",
                                       headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:          # noqa: BLE001
        return False
    fim = time.time() + espera
    while time.time() < fim:
        if _porta_livre(porta):
            return True
        time.sleep(0.3)
    return False


def _precarregar():
    """Carrega já o que os geradores usam: se o app for trocado por uma versão nova com ele aberto,
    o que ainda não estava carregado quebraria ("Error -3 while decompressing data")."""
    import importlib
    for m in ("copy", "difflib", "html", "json", "math", "unicodedata", "urllib.parse", "uuid", "xml.etree.ElementTree",
              "zipfile", "zlib", "runpy", "tempfile", "subprocess", "shutil", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
              "PIL.ImageFilter", "pypdfium2", "montador.montagem", "montador.insercoes", "montador.slides",
              "montador.juntar", "montador.thumbs", "montador.skoopia", "montador.mapa", "montador.premiere",
              "montador.importar", "montador.atualizar", "urllib.request", "ssl", "certifi"):
        try:
            importlib.import_module(m)
        except Exception:      # noqa: BLE001
            pass


def serve(porta: int | None = None, abrir_navegador: bool = True, fechar_sozinho: bool = False):
    porta = porta or PORTA_PADRAO
    url = f"http://127.0.0.1:{porta}/"
    if not _porta_livre(porta):
        aberta = _versao_aberta(porta)
        if aberta == __version__ or aberta is None and not _encerrar(porta):
            if abrir_navegador:                # já está aberto (a mesma versão): só abre a janela
                webbrowser.open(url)
            return
        # outra versão ainda aberta (o app foi atualizado com ele aberto): fecha a antiga e abre esta
        if aberta is not None:
            _encerrar(porta)
        if not _porta_livre(porta):
            if abrir_navegador:
                webbrowser.open(url)
            return
    _precarregar()
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    _SERVIDOR[:] = [srv]
    print(f"Montador {__version__} em {url}")
    if abrir_navegador:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if fechar_sozinho:
        def vigia():
            while True:
                time.sleep(15)
                if time.time() - ESTADO.ultimo_ping > 120:
                    srv.shutdown()
                    return
        threading.Thread(target=vigia, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
