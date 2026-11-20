"""Leitura da pasta do dia de gravação.

Estrutura (padrão do Drive "Gravações IEC"):
  <curso>/<AAAA MM DD>/Footage     vídeos do OBS (+ .srt de cada um, SRT único e tabela do `transcribe`)
  <curso>/<AAAA MM DD>/Originais   material do professor (.pptx, .docx, imagens) e o .txt do cartão
  <curso>/<AAAA MM DD>/Projeto     onde os XMLs costumam ser salvos
O editor pode apontar a pasta do dia ou a própria Footage.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import cartao, mp4info, srt

VIDEOS = (".mp4", ".mov", ".m4v", ".mkv")
IMAGENS = (".jpg", ".jpeg", ".png")
_PARTE = re.compile(r"-(D|E)$", re.I)        # metades antigas (dividido pelo HandBrake): não são o bruto


def _filhos(p: Path, nome: str) -> Path | None:
    alvo = nome.lower()
    try:
        for q in p.iterdir():
            if q.is_dir() and q.name.lower() == alvo:
                return q
    except OSError:
        pass
    return None


def raiz_do_dia(caminho: str | Path) -> Path:
    p = Path(caminho).expanduser()
    if p.is_file():
        p = p.parent
    if p.name.lower() in ("footage", "originais", "projeto", "saida", "saída"):
        return p.parent
    return p


def _tabela(caminho: Path) -> list[dict]:
    """"SRT unico - tabela.txt": vídeo, separador, início da fala."""
    out = []
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        partes = linha.split("\t")
        if len(partes) >= 3 and "-->" not in linha:
            try:
                out.append({"video": partes[0].strip(), "separador": srt.tempo(partes[1]),
                            "fala": srt.tempo(partes[2])})
            except ValueError:
                continue
    return out


def ler(caminho: str | Path) -> dict:
    raiz = raiz_do_dia(caminho)
    if not raiz.is_dir():
        raise FileNotFoundError(str(raiz))
    footage = _filhos(raiz, "footage") or raiz
    originais = _filhos(raiz, "originais")
    projeto = _filhos(raiz, "projeto")
    saida = _filhos(raiz, "saida") or _filhos(raiz, "saída")
    avisos = []

    videos = []
    for q in sorted(footage.iterdir(), key=lambda x: x.name.lower()):
        if q.is_file() and q.suffix.lower() in VIDEOS and not q.name.startswith("."):
            if _PARTE.search(q.stem):
                continue
            inf = mp4info.info(q) or {}
            srt_p = q.with_suffix(".srt")
            videos.append({
                "nome": q.stem, "arquivo": str(q),
                "duracao": inf.get("duracao") or mp4info.ffprobe(q), "largura": inf.get("largura"), "altura": inf.get("altura"),
                "srt": str(srt_p) if srt_p.is_file() else None,
            })
    if not videos:
        avisos.append("Nenhum vídeo na pasta Footage.")

    unico, tabela = None, []
    for base in {footage, raiz}:
        for q in base.glob("SRT unico*.srt"):
            unico = str(q)
        t = base / "SRT unico - tabela.txt"
        if t.is_file():
            tabela = _tabela(t)

    sem_transcricao = [v["nome"] for v in videos if not v["srt"]]
    if sem_transcricao and not unico:
        avisos.append("Sem transcrição: " + ", ".join(sem_transcricao) + ". Rode o transcribe na pasta.")

    # material do professor e cartão
    material = {"pptx": [], "docx": [], "imagens": []}
    cartoes = []
    # procura na pasta do dia inteira (Originais, Material, solto na raiz...), menos onde ficam vídeos e saídas
    fora = {"footage", "projeto", "saida", "saída", "editado", "nest"}
    candidatos = []
    for q in sorted(raiz.rglob("*"), key=lambda x: str(x).lower()):
        rel = q.relative_to(raiz).parts
        if any(x.lower() in fora or x.startswith(".") for x in rel[:-1]):
            continue
        if q.is_file() and not q.name.startswith(("~$", ".")):
            candidatos.append(q)
    stems_pptx = {q.stem for q in candidatos if q.suffix.lower() == ".pptx"}
    if candidatos:
        for q in candidatos:
            ext = q.suffix.lower()
            if ext in IMAGENS and q.parent.name in stems_pptx:
                continue                              # slides já convertidos pelo Montador
            if ext in (".mp4", ".mov", ".srt", ".xml", ".prproj"):
                continue
            if ext == ".pptx":
                material["pptx"].append(str(q))
            elif ext == ".docx":
                material["docx"].append(str(q))
            elif ext in IMAGENS:
                material["imagens"].append(str(q))
            elif ext == ".txt" and originais and q.parent == originais:
                cartoes.append(q)
    for q in raiz.glob("*.txt"):
        cartoes.append(q)

    cart = None
    for q in cartoes:
        try:
            c = cartao.ler_texto(q.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if c.titulos or c.formato or c.campos:
            cart = {"arquivo": str(q), **c.resumo()}
            if c.titulos:
                break

    return {
        "raiz": str(raiz), "nome": raiz.name, "curso": raiz.parent.name,
        "footage": str(footage), "originais": str(originais) if originais else None,
        "projeto": str(projeto) if projeto else None, "editado": bool(projeto or saida),
        "videos": videos, "srt_unico": unico, "tabela": tabela,
        "material": material, "cartao": cart, "avisos": avisos,
    }


def transcricoes(dia: dict) -> dict[str, list[srt.Cue]]:
    """Falas de cada vídeo (tempo do próprio vídeo). Usa o .srt de cada um; se faltar, recorta do SRT único."""
    out: dict[str, list[srt.Cue]] = {}
    for v in dia["videos"]:
        if v["srt"]:
            out[v["nome"]] = [c for c in srt.ler(v["srt"]) if not srt.SEPARADOR.match(c.texto.strip())]
    faltam = [v["nome"] for v in dia["videos"] if v["nome"] not in out]
    if faltam and dia.get("srt_unico"):
        out.update({k: v for k, v in dividir_unico(srt.ler(dia["srt_unico"]), dia.get("tabela") or []).items()
                    if k in faltam})
    return out


def dividir_unico(cues: list[srt.Cue], tabela: list[dict]) -> dict[str, list[srt.Cue]]:
    """Separa um SRT do dia inteiro (o SRT único ou o retorno da Skoopia) por vídeo, cada um começando em 0.

    Usa a tabela; sem ela, usa os separadores [ARQUIVO: ...] do próprio arquivo (fala = separador + 2 s).
    Uma marcação que atravessa dois vídeos é dividida entre eles.
    """
    if not tabela:
        tabela = [{"video": nome, "separador": t, "fala": t + 2.0} for nome, t in srt.separadores(cues)]
    tabela = sorted(tabela, key=lambda r: r["separador"])
    out: dict[str, list[srt.Cue]] = {r["video"]: [] for r in tabela}
    for k, r in enumerate(tabela):
        fim_janela = tabela[k + 1]["separador"] if k + 1 < len(tabela) else float("inf")
        for c in cues:
            if srt.SEPARADOR.match(c.texto.strip()):
                continue
            a, b = max(c.ini, r["separador"]), min(c.fim, fim_janela)
            la, lb = max(0.0, a - r["fala"]), max(0.0, b - r["fala"])
            if lb - la < 0.2:                       # só o separador (antes da fala do vídeo): não conta
                continue
            out[r["video"]].append(srt.Cue(c.n, la, lb, c.texto))
    return out
