"""Mapa partindo dos títulos do cartão (dia 2026 11 03: professor que abre com "Neste vídeo você vai entender").

As durações são as reais (afinfo). As falas são montadas aqui, com o mesmo jeito do professor, e com variações
para conferir que o mapa não depende desse hábito: sem a frase de abertura, sem slides, com uma aula que não
foi gravada e com uma aula partida em dois arquivos.
"""
import pytest

from montador import mapa
from montador.srt import Cue

DURACOES = [
    ("07-24-42", 14.868), ("07-25-21", 540.799), ("07-34-22", 548.671), ("07-43-32", 552.959),
    ("07-52-46", 866.004), ("08-07-14", 664.511), ("08-18-23", 596.991), ("08-28-22", 716.969),
    ("08-40-21", 799.167), ("08-53-41", 13.972), ("09-04-03", 830.036), ("09-18-02", 609.471),
    ("09-28-13", 637.097), ("09-38-51", 697.129), ("09-50-30", 824.703), ("10-04-17", 636.927),
    ("10-14-57", 1366.377), ("10-37-44", 3.839), ("10-37-49", 586.836),
]
DESCARTE = {"07-24-42", "08-53-41", "10-37-44"}

# 16 aulas (U3_T1_V1 … U3_T8_V2): assunto de cada uma
TEMAS = [
    ("Fundamentos de redes neurais", "neurônio perceptron camadas pesos ativação"),
    ("Funções de ativação e não linearidade", "sigmoide tangente relu saturação gradiente"),
    ("Retropropagação do erro", "retropropagação derivada cadeia erro atualização"),
    ("Otimizadores e taxa de aprendizado", "otimizador adam momentum taxa convergência"),
    ("Regularização e sobreajuste", "regularização dropout sobreajuste penalidade generalização"),
    ("Redes convolucionais", "convolução filtro kernel pooling imagem"),
    ("Arquiteturas clássicas de visão", "alexnet resnet residual profundidade imagenet"),
    ("Transferência de aprendizado", "transferência pretreinado congelar ajuste domínio"),
    ("Redes recorrentes", "recorrente sequência memória estado temporal"),
    ("LSTM e GRU", "lstm portão esquecimento célula gru"),
    ("Mecanismo de atenção", "atenção consulta chave valor pesos"),
    ("Transformers", "transformer codificador decodificador posicional camada"),
    ("Modelos de linguagem", "linguagem token vocabulário predição texto"),
    ("Avaliação de modelos", "métrica acurácia precisão revocação validação"),
    ("Implantação de modelos", "implantação servidor latência monitoramento produção"),
    ("Ética e vieses em aprendizado profundo", "ética viés justiça transparência responsabilidade"),
]
TITULOS = [t for t, _ in TEMAS]
SLIDES = [f"{t}. {p} {p}" for t, p in TEMAS]


def _c(ini, texto, dur=8.0):
    return Cue(0, ini, ini + dur, texto)


def _aula(tema, palavras, dur, abertura=True, sintese=True, pausa=None):
    pal = palavras.split()
    out = []
    if abertura:
        out.append(_c(2, f"Neste vídeo você vai entender {tema.lower()}."))
    else:
        out.append(_c(2, f"Bom, {pal[0]} é o ponto de partida."))
    t = 30.0
    k = 0
    while t < dur - 60:
        if pausa and pausa[0] <= t < pausa[1]:
            t = pausa[1] + 2
            out.append(_c(t, f"Neste vídeo você vai entender {tema.lower()}.") if abertura
                       else _c(t, f"Bom, {pal[0]} é o ponto de partida."))
            t += 30
            continue
        a, b = pal[k % len(pal)], pal[(k + 2) % len(pal)]
        out.append(_c(t, f"Quando olhamos para {a}, percebemos como {b} aparece no exemplo da empresa."))
        t += 30
        k += 1
    if sintese:
        out.append(_c(dur - 40, f"Em síntese, vimos {tema.lower()}: {pal[0]} e {pal[1]}."))
    return out


def _dia(abertura=True, sintese=True, falta=None):
    videos, falas, aula = [], {}, 0
    for nome, dur in DURACOES:
        n = f"2026-11-03 {nome}"
        videos.append({"nome": n, "duracao": dur})
        if nome == "07-24-42":
            falas[n] = [_c(3, "Testando, som ok?", 3)]
        elif nome == "08-53-41":
            falas[n] = [_c(2, "Vou parar cinco minutinhos.", 3)]
        elif nome == "10-37-44":
            falas[n] = []
        else:
            if falta is not None and aula == falta:
                aula += 1                                   # esta aula não foi gravada
            if aula >= len(TEMAS):
                videos.pop()                                # sobrou arquivo: fica de fora do dia
                continue
            tema, pal = TEMAS[aula]
            pausa = (89, 716) if nome == "10-14-57" else None
            falas[n] = _aula(tema, pal, dur, abertura, sintese, pausa)
            aula += 1
    return videos, falas


def _por_aula(m):
    return {a["n"]: [t["video"][-8:] for t in a["trechos"]] for a in m["aulas"]}


AULAS = [n for n, _ in DURACOES if n not in DESCARTE]


def test_dia_real_cada_video_e_uma_aula_na_ordem_dos_titulos():
    videos, falas = _dia()
    m = mapa.sugerir(videos, falas, TITULOS, SLIDES)
    assert _por_aula(m) == {k: [AULAS[k - 1]] for k in range(1, 17)}
    assert sorted(d["video"][-8:] for d in m["descartados"]) == sorted(DESCARTE)
    assert not any(a.get("nao_reconhecida") for a in m["aulas"])
    # a pausa de 1:29 a 11:56 no 10-14-57 fica marcada para conferir
    a15 = next(a for a in m["aulas"] if a["n"] == 15)
    assert any("pausa longa" in x for x in a15["conferir"])


def test_sem_a_frase_de_abertura_e_sem_slides_a_conta_dos_titulos_ainda_divide():
    videos, falas = _dia(abertura=False, sintese=False)
    m = mapa.sugerir(videos, falas, TITULOS)
    assert _por_aula(m) == {k: [AULAS[k - 1]] for k in range(1, 17)}


def test_aula_que_nao_foi_gravada_fica_nao_reconhecida_sem_empurrar_as_outras():
    videos, falas = _dia(falta=8)                     # "Redes recorrentes" (9ª) não foi gravada
    m = mapa.sugerir(videos, falas, TITULOS, SLIDES)
    faltam = [a["n"] for a in m["aulas"] if a.get("nao_reconhecida")]
    assert faltam == [9]
    pa = _por_aula(m)
    assert pa[8] == [AULAS[7]] and pa[10] == [AULAS[8]] and pa[16] == [AULAS[14]]
    assert any("não reconhecida" in a for a in m["avisos"])


def test_aula_partida_em_dois_arquivos_nao_vira_duas_aulas():
    """O professor parou no meio (bateria) e continuou em outro arquivo, sem cumprimentar: continuação."""
    titulos = TITULOS[:3]
    pal = TEMAS[1][1]
    videos = [{"nome": "A", "duracao": 540}, {"nome": "B1", "duracao": 400}, {"nome": "B2", "duracao": 300},
              {"nome": "C", "duracao": 560}]
    falas = {"A": _aula(*TEMAS[0], 540), "B1": _aula(*TEMAS[1], 400, sintese=False),
             "B2": [_c(5, f"Continuando, a {pal.split()[1]} e a {pal.split()[3]} mudam o resultado.")]
             + [_c(30 + 30 * k, f"Na {pal.split()[k % 5]} vemos a {pal.split()[(k + 1) % 5]} de novo.") for k in range(7)]
             + [_c(260, f"Em síntese, vimos {TEMAS[1][0].lower()}.")],
             "C": _aula(*TEMAS[2], 560)}
    m = mapa.sugerir(videos, falas, titulos, SLIDES[:3])
    assert _por_aula(m) == {1: ["A"], 2: ["B1", "B2"], 3: ["C"]}


def test_dia_com_ola_continua_igual():
    """Professor que cumprimenta: nada de promoção (a conta já fecha)."""
    videos = [{"nome": "A", "duracao": 600}, {"nome": "B", "duracao": 600}]
    meio = [_c(30 + 20 * k, "Seguimos com o exemplo.") for k in range(26)]
    falas = {"A": [_c(0, "Olá, bem-vindos."), *meio, _c(560, "Vejo vocês lá.")],
             "B": [_c(0, "Olá, de novo."), *meio, _c(560, "Vejo vocês lá.")]}
    m = mapa.sugerir(videos, falas, ["Filas", "Robôs"])
    assert _por_aula(m) == {1: ["A"], 2: ["B"]}
    assert not any(a["conferir"] for a in m["aulas"])


def test_slides_ligados_aos_titulos_pelo_nome_e_pelo_texto():
    decks = [(f"U3_T{k // 2 + 1}_V{k % 2 + 1}", SLIDES[k]) for k in range(16)][::-1]
    assert mapa.slides_dos_titulos(decks, TITULOS) == SLIDES
    # menos .pptx que títulos: cada um vai para o título com que se parece
    poucos = [("qualquer nome", SLIDES[5]), ("outro", SLIDES[11])]
    s = mapa.slides_dos_titulos(poucos, TITULOS)
    assert s[5] == SLIDES[5] and s[11] == SLIDES[11] and sum(bool(x) for x in s) == 2


@pytest.mark.parametrize("n", [0, 1])
def test_editor_escolhe_o_trecho_da_aula_nao_reconhecida(n):
    fx = [{"video": "A", "ini": 0, "fim": 100, "tipo": "abre", "aula": 1, "motivo": ""},
          {"video": "B", "ini": 0, "fim": 100, "tipo": "abre", "aula": 3, "motivo": ""}]
    m = mapa.montar(fx, ["Um", "Dois", "Três"])
    assert [a["nome"] for a in m["aulas"]] == ["01 Um", "02 Dois", "03 Três"]
    assert m["aulas"][1]["nao_reconhecida"] and not m["aulas"][1]["trechos"]
    if n:
        fx[1]["aula"] = 2
        m = mapa.montar(fx, ["Um", "Dois", "Três"])
        assert m["aulas"][1]["trechos"] and m["aulas"][2].get("nao_reconhecida")


def test_sem_cartao_so_divide_com_pistas_fortes():
    videos, falas = _dia()
    m = mapa.sugerir(videos, falas, [])                 # abre com "Neste vídeo", síntese no fim, vídeos longos
    assert len([a for a in m["aulas"] if a["trechos"]]) == 16
    videos, falas = _dia(abertura=False, sintese=False)
    m = mapa.sugerir(videos, falas, [])                 # sem pista nenhuma além da duração: não inventa aula
    assert len([a for a in m["aulas"] if a["trechos"]]) == 1
