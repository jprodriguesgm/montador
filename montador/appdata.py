"""Configurações do Montador em cada máquina (o que fica salvo entre um uso e outro).

Tudo numa pasta do usuário (não precisa de administrador):
  Mac:      ~/Library/Application Support/Montador
  Windows:  %APPDATA%\\Montador
  Linux:    ~/.local/share/montador
A variável MONTADOR_HOME troca essa pasta (testes).
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "Montador"

# Arquivos que entram nos projetos (nomes como estão nos modelos do Fluxo NPD).
# O "Link Media": a pessoa aponta um, o app procura os outros pelo nome perto dele.
ASSETS = [
    {"id": "vinheta", "nome": "Final_cima_v4_mov.mov", "descricao": "Vinheta de abertura", "formatos": "todos"},
    {"id": "creditos", "nome": "tela_creditos_mov_v1.mov", "descricao": "Tela de créditos (final)", "formatos": "todos"},
    {"id": "brasao", "nome": "Brasão 2025.png", "descricao": "Brasão da PUC", "formatos": "todos"},
    {"id": "vignette", "nome": "vignette_00000_00000.png", "descricao": "Vignette", "formatos": "TP e TV"},
    {"id": "hex", "nome": "HEX.png", "descricao": "Fundo HEX", "formatos": "TP"},
    {"id": "degrade", "nome": "DEGRADE AZUL VREMEIO.jpg", "descricao": "Fundo degradê", "formatos": "TP"},
    {"id": "marinho", "nome": "Marinho.jpg", "descricao": "Fundo marinho", "formatos": "Screencast"},
    {"id": "nevoa", "nome": "NEVOA3.png", "descricao": "Névoa", "formatos": "Screencast"},
    {"id": "moldura", "nome": "01-v3.png", "descricao": "Moldura da tela", "formatos": "Screencast"},
    {"id": "moldura_bolinha", "nome": "01-v3-bolinha.png", "descricao": "Moldura com bolinha", "formatos": "Screencast"},
]

CORES_PREMIERE = ["Violet", "Iris", "Caribbean", "Lavender", "Cerulean", "Forest", "Rose", "Mango",
                  "Purple", "Blue", "Teal", "Magenta", "Tan", "Green", "Brown", "Yellow"]

DEFAULTS = {
    "pasta_gravacoes": None,        # onde ficam as pastas de curso/dia (ponto de partida para escolher)
    "pasta_transcricoes": None,     # opcional: pasta onde ficam os .srt, quando não estão na Footage
    "assets": {},                   # id → caminho do arquivo
    "pasta_exportacao": None,       # última pasta onde os XMLs foram salvos (None = pasta Projeto do dia)
    "trello_chave": "",
    "trello_token": "",
    "cores": {"erro": "Rose", "bastidores": "Mango", "conferir": "Violet"},
    "marcacoes": "auto",            # auto | skoopia | regras
    "duracao_slide": 15,            # segundos de cada slide na tela quando a nota do slide não diz
    "libreoffice": None,            # caminho do soffice, se não estiver no lugar de sempre
    "ultima_pasta": None,
}

_lock = threading.Lock()


def home() -> Path:
    env = os.environ.get("MONTADOR_HOME")
    if env:
        p = Path(env)
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / APP_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "montador"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _arquivo() -> Path:
    return home() / "configuracoes.json"


def carregar() -> dict:
    with _lock:
        dados = {}
        try:
            dados = json.loads(_arquivo().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        out = json.loads(json.dumps(DEFAULTS))
        for k, v in dados.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k].update(v)
            elif k in out:
                out[k] = v
        return out


def salvar(mudancas: dict) -> dict:
    atual = carregar()
    for k, v in mudancas.items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], dict) and isinstance(v, dict):
            atual[k].update(v)
        else:
            atual[k] = v
    with _lock:
        tmp = _arquivo().with_suffix(".tmp")
        tmp.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_arquivo())
    return atual


def estado_assets(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or carregar()
    out = []
    for a in ASSETS:
        p = cfg["assets"].get(a["id"])
        out.append({**a, "caminho": p, "ok": bool(p and Path(p).is_file())})
    return out


def _norm(nome: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", nome).lower()


def procurar_assets(ponto: str | Path, niveis_acima: int = 4, limite: int = 60000) -> dict:
    """Como o Link Media: a partir do arquivo apontado, procura os outros assets pelo nome.

    Sobe até `niveis_acima` pastas e varre tudo abaixo dela (para no limite de arquivos, para não
    travar num disco inteiro). Devolve {id: caminho} do que achou.
    """
    p = Path(ponto)
    base = p.parent if p.is_file() else p
    for _ in range(niveis_acima):
        if base.parent == base:
            break
        base = base.parent
    procurados = {_norm(a["nome"]): a["id"] for a in ASSETS}
    achados: dict[str, str] = {}
    vistos = 0
    for raiz, pastas, arquivos in os.walk(base):
        pastas[:] = [d for d in pastas if not d.startswith(".")]
        for nome in arquivos:
            vistos += 1
            i = procurados.get(_norm(nome))
            if i and i not in achados:
                achados[i] = str(Path(raiz) / nome)
        if len(achados) == len(procurados) or vistos > limite:
            break
    return achados
