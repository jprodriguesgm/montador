"""Servidor local: a janela do Montador abre no navegador e conversa com o motor por aqui.

Só escuta em 127.0.0.1 (nada sai do computador). Rodar: python3 -m montador
"""
from __future__ import annotations

import json
import mimetypes
import os
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

from . import __version__, appdata, cartao, dia, dialogs, importar, mapa, montagem, skoopia, srt

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
        self.material_extra: list = []   # arquivos de inserção escolhidos à mão

    def limpar_dia(self, raiz: str):
        if self.raiz_manuais != raiz:
            self.manuais, self.raiz_manuais, self.tabela = {}, raiz, []
            self.marcas, self.skoopia, self.pendentes, self.material_extra = {}, [], {}, []


ESTADO = Estado()


# ====================================================================== ações

def acao_estado(_q) -> dict:
    cfg = appdata.carregar()
    return {"versao": __version__, "config": cfg, "assets": appdata.estado_assets(cfg),
            "cores_premiere": appdata.CORES_PREMIERE}


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
    appdata.salvar({"ultima_pasta": d["raiz"]})
    return _resultado(d, falas, (d.get("cartao") or {}).get("titulos") or [])


def acao_transcricoes(corpo) -> dict:
    """Transcrições importadas à mão: arquivos arrastados/escolhidos (conteúdo) ou uma pasta (caminho)."""
    with ESTADO.lock:
        d = ESTADO.dia
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    arquivos = corpo.get("arquivos") or []
    if corpo.get("pasta"):
        if not Path(corpo["pasta"]).is_dir():
            raise ApiError("Pasta não encontrada.")
        arquivos = importar.ler_pasta(corpo["pasta"])
    nomes = [v["nome"] for v in d["videos"]]
    r = importar.classificar(arquivos, nomes)
    with ESTADO.lock:
        if r["tabela"]:
            ESTADO.tabela = r["tabela"]
        ESTADO.manuais.update(r["por_video"])
        ESTADO.falas.update(r["por_video"])
        falas = ESTADO.falas
    out = _resultado(d, falas, (d.get("cartao") or {}).get("titulos") or [])
    out["importacao"] = {"videos": sorted(r["por_video"]), "unico": r["unico"], "skoopia": r["skoopia"],
                         "ignorados": r["ignorados"]}
    return out


def acao_skoopia(corpo) -> dict:
    """SRTs de cortes e inserções da Skoopia (conteúdo vindo da janela)."""
    with ESTADO.lock:
        d, falas, tabela = ESTADO.dia, ESTADO.falas, ESTADO.tabela
    if d is None:
        raise ApiError("Escolha a pasta do dia primeiro.")
    for a in corpo.get("arquivos") or []:
        cues = srt.ler_texto(a.get("conteudo") or "")
        if not cues:
            continue
        nome = a.get("nome") or "sem nome.srt"
        dest = skoopia.ligar(nome, cues, d["videos"], falas, tabela)
        _guardar_skoopia(nome, cues, dest, tabela)
    if corpo.get("escolher"):                 # o editor escolheu o vídeo de um pendente
        e = corpo["escolher"]
        cues = ESTADO.pendentes.get(e.get("nome"))
        if cues is not None and e.get("video"):
            _guardar_skoopia(e["nome"], cues, {"modo": "video", "video": e["video"], "motivo": "escolhido pelo editor"}, tabela)
    if corpo.get("remover"):
        _remover_skoopia(corpo["remover"])
    return _resultado(d, ESTADO.falas, (d.get("cartao") or {}).get("titulos") or [])


def _remover_skoopia(nome: str):
    with ESTADO.lock:
        ESTADO.skoopia = [x for x in ESTADO.skoopia if x["nome"] != nome]
        ESTADO.pendentes.pop(nome, None)
        for m in ESTADO.marcas.values():
            m.pop(nome, None)


def _guardar_skoopia(nome: str, cues, dest: dict, tabela: list):
    _remover_skoopia(nome)
    with ESTADO.lock:
        t = skoopia.tipo(cues)
        if dest["modo"] == "pendente":
            ESTADO.pendentes[nome] = cues
        for video, lista in skoopia.distribuir(cues, dest, tabela).items():
            ESTADO.marcas.setdefault(video, {})[nome] = lista
        ESTADO.skoopia.append({"nome": nome, "tipo": t, "n": len(cues), **dest})


def acao_material(corpo) -> dict:
    """Material de inserção escolhido à mão (arquivos ou uma pasta)."""
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
            if Path(n).is_file() and n not in ESTADO.material_extra:
                ESTADO.material_extra.append(n)
        if corpo.get("remover"):
            ESTADO.material_extra = [x for x in ESTADO.material_extra if x != corpo["remover"]]
    return _resultado(d, ESTADO.falas, (d.get("cartao") or {}).get("titulos") or [])


def _material(d: dict) -> dict:
    out = {"pptx": list(d["material"]["pptx"]), "docx": list(d["material"]["docx"]),
           "imagens": list(d["material"]["imagens"]), "manuais": list(ESTADO.material_extra)}
    for p in ESTADO.material_extra:
        ext = Path(p).suffix.lower()
        chave = "pptx" if ext == ".pptx" else "docx" if ext == ".docx" else "imagens"
        if p not in out[chave]:
            out[chave].append(p)
    return out


def _resultado(d: dict, falas: dict, titulos_brutos: list[str]) -> dict:
    # 1ª passada sem títulos para saber quantas aulas o vídeo mostra; depois desgruda os títulos para
    # bater com essa conta e refaz o mapa com eles
    previa = mapa.sugerir(d["videos"], falas, [])
    sep = cartao.separar_titulos(titulos_brutos, len(previa["aulas"]) or None) if titulos_brutos else \
        {"titulos": [], "separados": 0, "conferir": False, "motivo": ""}
    m = mapa.sugerir(d["videos"], falas, sep["titulos"])
    with ESTADO.lock:
        for a in m["aulas"]:
            a["marcas"] = skoopia.contar(ESTADO.marcas, a["trechos"])
        d = dict(d, transcritos=sorted(k for k, v in falas.items() if v), material=_material(d),
                 skoopia=list(ESTADO.skoopia), tem_tabela=bool(ESTADO.tabela))
    d["avisos"] = [a for a in d["avisos"] if not a.startswith("Sem transcrição")]
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
    if not m["aulas"]:
        raise ApiError("Nenhuma aula no mapa do dia.")
    destino = corpo.get("destino") or str(Path(d["raiz"]) / "Projeto")
    cfg = appdata.carregar()
    if corpo.get("destino"):
        appdata.salvar({"pasta_exportacao": corpo["destino"]})
    dd = dict(d, material=_material(d))
    try:
        return montagem.montar(dd, falas, m["aulas"], corpo.get("formato") or "TP", corpo.get("insercao") or "slide",
                               marcas, destino, cfg, cfg.get("marcacoes") or "auto")
    except OSError as e:
        raise ApiError(f"Não consegui gravar em {destino}: {e}")


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


GET = {"/api/estado": acao_estado, "/api/raizes": acao_raizes, "/api/listar": acao_listar}
POST = {"/api/config": acao_config, "/api/escolher": acao_escolher, "/api/assets/apontar": acao_apontar_asset,
        "/api/dia": acao_dia, "/api/cartao/texto": acao_cartao_texto, "/api/transcricoes": acao_transcricoes,
        "/api/skoopia": acao_skoopia, "/api/material": acao_material, "/api/mapa": acao_mapa,
        "/api/montar": acao_montar, "/api/abrir_pasta": acao_abrir_pasta}


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


def serve(porta: int | None = None, abrir_navegador: bool = True, fechar_sozinho: bool = False):
    porta = porta or PORTA_PADRAO
    url = f"http://127.0.0.1:{porta}/"
    if not _porta_livre(porta):            # já está aberto: só abre a janela
        if abrir_navegador:
            webbrowser.open(url)
        return
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
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
