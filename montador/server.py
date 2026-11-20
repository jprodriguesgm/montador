"""Servidor local: a janela do Montador abre no navegador e conversa com o motor por aqui.

Só escuta em 127.0.0.1 (nada sai do computador). Rodar: python3 -m montador
"""
from __future__ import annotations

import json
import mimetypes
import socket
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, appdata, cartao, dia, dialogs, mapa

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
    falas = dia.transcricoes(d)
    titulos_brutos = (d.get("cartao") or {}).get("titulos") or []
    with ESTADO.lock:
        ESTADO.dia, ESTADO.falas = d, falas
    appdata.salvar({"ultima_pasta": d["raiz"]})
    return _resultado(d, falas, titulos_brutos)


def _resultado(d: dict, falas: dict, titulos_brutos: list[str]) -> dict:
    # 1ª passada sem títulos para saber quantas aulas o vídeo mostra; depois desgruda os títulos para
    # bater com essa conta e refaz o mapa com eles
    previa = mapa.sugerir(d["videos"], falas, [])
    sep = cartao.separar_titulos(titulos_brutos, len(previa["aulas"]) or None) if titulos_brutos else \
        {"titulos": [], "separados": 0, "conferir": False, "motivo": ""}
    m = mapa.sugerir(d["videos"], falas, sep["titulos"])
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
    return {"faixas": fx, **mapa.montar(fx, corpo.get("titulos") or [])}


def acao_montar(_corpo) -> dict:
    raise ApiError("A montagem das sequências chega na etapa 2. Por enquanto, confira o mapa do dia.", 501)


GET = {"/api/estado": acao_estado, "/api/raizes": acao_raizes, "/api/listar": acao_listar}
POST = {"/api/config": acao_config, "/api/escolher": acao_escolher, "/api/assets/apontar": acao_apontar_asset,
        "/api/dia": acao_dia, "/api/cartao/texto": acao_cartao_texto, "/api/mapa": acao_mapa,
        "/api/montar": acao_montar}


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
