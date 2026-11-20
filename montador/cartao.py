"""Leitura do cartão da gravação (TXT gerado do Planner/Trello, ou o texto do próprio cartão).

O que o Montador tira do cartão:
  - formato (TP, TV, Screencast) e tipo de inserção (slide, palavra-chave, a critério do editor);
  - títulos das aulas do dia, na ordem (são sempre as aulas gravadas naquele dia);
  - campos soltos (curso, disciplina, professor...), só para mostrar.

Os títulos às vezes chegam grudados na mesma linha (o professor colou a lista e as quebras
de linha se perderam). `separar_titulos` desgruda até a conta bater com o número de aulas.
A leitura fica isolada aqui para trocar a fonte (Planner) sem mexer no resto do app.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _chave(s: str) -> str:
    return re.sub(r"\s+", " ", _sem_acento(s).lower()).strip(" :")


@dataclass
class Cartao:
    campos: dict = field(default_factory=dict)       # chave normalizada → valor
    titulos: list = field(default_factory=list)       # linhas de título como vieram (sem "Unidade N")
    unidade: str = ""
    formato: str = ""                                 # TP | TV | SCREENCAST | ""
    insercao: str = ""                                # slide | palavra | ambas | editor | nenhuma | ""
    texto: str = ""

    def resumo(self) -> dict:
        def campo(*nomes):
            for n in nomes:
                for k, v in self.campos.items():
                    if k.startswith(n) and v:
                        return v
            return ""
        return {
            "professor": campo("professor", "nome do professor", "docente"),
            "curso": campo("curso"),
            "disciplina": campo("disciplina"),
            "unidade": self.unidade,
            "formato": self.formato,
            "insercao": self.insercao,
            "titulos": list(self.titulos),
        }


_INICIO_TITULOS = re.compile(r"^\s*t[ií]tulos?(\s+das\s+aulas)?\s*:?\s*(.*)$", re.I)
_UNIDADE = re.compile(r"^\s*unidade\s+([0-9ivx]+)\b\s*:?\s*(.*)$", re.I)
_CAMPO = re.compile(r"^\s*([^:?]{2,60}?)\s*[:?]\s*(.*)$")


def _parece_campo(linha: str) -> bool:
    """Linha de outro campo do formulário (fim da lista de títulos)."""
    s = linha.strip()
    if not s:
        return False
    if s.endswith("?") or re.search(r"\?\s+\S", s):
        return True
    m = _CAMPO.match(s)
    if not m:
        return False
    chave = _chave(m.group(1))
    conhecidos = ("esta ciente", "deseja", "finalizou", "gravou", "inicio", "microfundamento", "tipo do curso",
                  "curso", "disciplina", "professor", "cinegrafista", "pasta", "insercoes", "aspectos",
                  "sobre as aulas", "para registro", "observa", "formato", "data")
    return any(chave.startswith(k) for k in conhecidos) or bool(re.match(r"^\d+\s*-", chave))


def ler_texto(texto: str) -> Cartao:
    texto = texto.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    c = Cartao(texto=texto)
    linhas = texto.split("\n")
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        m = _INICIO_TITULOS.match(linha)
        if m and not c.titulos:
            resto = m.group(2).strip()
            bloco = [resto] if resto else []
            i += 1
            while i < len(linhas):
                l = linhas[i]
                if _parece_campo(l):
                    break
                if l.strip() in ("\\---", "---", "\\-\\-\\-"):
                    break
                bloco.append(l)
                i += 1
            for l in bloco:
                s = l.strip()
                if not s:
                    continue
                u = _UNIDADE.match(s)
                if u:
                    c.unidade = f"Unidade {u.group(1).upper()}"
                    if u.group(2).strip():
                        c.titulos.append(u.group(2).strip())
                    continue
                c.titulos.append(s)
            continue
        cm = _CAMPO.match(linha)
        if cm:
            c.campos[_chave(cm.group(1))] = cm.group(2).strip()
        i += 1
    c.formato = detectar_formato(texto)
    c.insercao = detectar_insercao(texto, c.campos)
    return c


def detectar_formato(texto: str) -> str:
    t = _sem_acento(texto).lower()
    if "tv interativa" in t or re.search(r"\btv\b", t):
        return "TV"
    if "screencast" in t or "mesa digitalizadora" in t:
        return "SCREENCAST"
    if re.search(r"\btp\b", t) or "teleprompter" in t:
        return "TP"
    return ""


def detectar_insercao(texto: str, campos: dict) -> str:
    valor = ""
    for k, v in campos.items():
        if "insercao" in k or "insercoes" in k:
            valor = v
            break
    t = _sem_acento((valor or texto)).lower()
    if "criterio" in t:
        return "editor"
    tem_slide = "slide" in t
    tem_palavra = "palavra" in t
    if tem_slide and tem_palavra:
        return "ambas"
    if tem_palavra:
        return "palavra"
    if tem_slide:
        return "slide"
    if valor and re.search(r"\b(nao|nenhuma|sem)\b", t):
        return "nenhuma"
    return ""


# ------------------------------------------------------------------ títulos grudados

_PREPOSICOES = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
                "com", "para", "por", "um", "uma", "ao", "aos", "à", "às", "que", "se", "pelo", "pela"}


def _candidatos(linha: str) -> list[tuple[int, float]]:
    """Pontos onde a linha provavelmente junta dois títulos: (posição do caractere, pontuação)."""
    tokens = [(m.start(), m.group()) for m in re.finditer(r"\S+", linha)]
    out = []
    for k in range(1, len(tokens)):
        pos, w = tokens[k]
        prev = tokens[k - 1][1]
        letras = re.sub(r"[^\wÀ-ÿ]", "", w)
        if not letras or not letras[0].isupper():
            continue
        sigla = letras.isupper() and len(letras) > 1      # PDD, LGPD, IA
        if not sigla and any(ch.isupper() for ch in letras[1:]):   # OpenTelemetry, DataDog
            continue
        if re.search(r"[.:;!?,(\-–—]$", prev):            # depois de pontuação não é título grudado
            continue
        if not re.search(r"[a-zà-ÿ0-9)]$", prev):
            continue
        nota = 1.0
        if sigla:                                         # sigla pode abrir título ("IA embarcada"), com cautela
            nota -= 0.2
        elif prev[:1].isupper():                          # "New Relic": continuação de nome próprio
            nota -= 0.4
        if prev.lower() in _PREPOSICOES:                  # título não termina em "de", "o", "com"...
            nota -= 0.8
        if k + 1 < len(tokens):
            prox = re.sub(r"[^\wÀ-ÿ]", "", tokens[k + 1][1])
            if prox and prox[0].isupper():                # "New Relic": nome próprio composto
                nota -= 0.6
        if k < 2 or len(tokens) - k < 2:                  # pedaço de uma palavra só: improvável
            nota -= 0.5
        out.append((pos, nota))
    return out


def separar_titulos(linhas: list[str], alvo: int | None = None) -> dict:
    """Desgruda títulos até chegar a `alvo` (quando informado).

    Devolve {"titulos": [...], "separados": n, "conferir": bool, "motivo": str}.
    Sem alvo, não separa nada (só informa quantos pontos suspeitos existem).
    """
    linhas = [l.strip() for l in linhas if l and l.strip()]
    cand = []
    for i, l in enumerate(linhas):
        for pos, nota in _candidatos(l):
            cand.append((nota, i, pos))
    if not alvo or len(linhas) >= alvo:
        motivo = ""
        if alvo and len(linhas) > alvo:
            motivo = f"o cartão tem {len(linhas)} títulos para {alvo} aulas"
        elif not alvo and cand:
            motivo = f"{len(cand)} possíveis títulos grudados"
        return {"titulos": linhas, "separados": 0, "conferir": bool(motivo), "motivo": motivo}
    faltam = alvo - len(linhas)
    escolhidos = sorted(cand, key=lambda c: -c[0])[:faltam]
    cortes: dict[int, list[int]] = {}
    for _, i, pos in escolhidos:
        cortes.setdefault(i, []).append(pos)
    out = []
    for i, l in enumerate(linhas):
        ps = sorted(cortes.get(i, []))
        ini = 0
        for p in ps:
            out.append(l[ini:p].strip())
            ini = p
        out.append(l[ini:].strip())
    out = [t for t in out if t]
    conferir = len(out) != alvo or any(n < 0.9 for n, _, _ in escolhidos) or len(cand) > faltam
    motivo = ""
    if len(out) != alvo:
        motivo = f"{len(out)} títulos para {alvo} aulas"
    elif escolhidos:
        motivo = f"{len(escolhidos)} título(s) estavam grudados e foram separados — confira"
    return {"titulos": out, "separados": len(escolhidos), "conferir": conferir or bool(escolhidos), "motivo": motivo}


def numerar(titulos: list[str]) -> list[str]:
    """Nome das sequências: "01 Título", "02 Título"... (ordem no dia)."""
    return [f"{k:02d} {t}".strip() for k, t in enumerate(titulos, 1)]
