"""Skoopia + script: o que só as regras sem IA acharam vira "PODE SER UM ERRO", sem duplicar o que a Skoopia marcou."""
from montador import montagem
from montador.srt import Cue


def _cues():
    falas = [(0, 4, "Olá, pessoal, sejam bem-vindos à nossa aula de hoje"),
             (5, 9, "Hoje vamos falar sobre gestão de projetos e planejamento"),
             (10, 14, "O primeiro ponto importante é entender o escopo do projeto"),
             (15, 16, "Ah, errei, vou repetir"),
             (17, 21, "O primeiro ponto importante é entender o escopo do projeto"),
             (22, 26, "Depois disso definimos o cronograma e os recursos necessários"),
             (27, 31, "Por fim, acompanhamos a execução com indicadores claros"),
             (32, 36, "Então é isso, obrigado e até a próxima aula")]
    return [Cue(i + 1, a, b, t) for i, (a, b, t) in enumerate(falas)]


def test_regras_complementam_skoopia_sem_duplicar():
    cues = _cues()
    so_regras = montagem.plano_regras(cues, 0, 40)
    erros = [t for t in so_regras["trechos"] if t[2] == "erro"]
    assert erros, "as regras deveriam achar a tentativa repetida"
    sem = montagem.plano_skoopia(cues, [], 0, 40)
    com = montagem.plano_skoopia(cues, [], 0, 40, com_script=True)
    assert not any("[SCRIPT]" in t[3] for t in sem["trechos"])
    assert any(t[3].startswith("[SCRIPT]") for t in com["trechos"])
    # trechos continuam uma partição da aula
    assert com["trechos"][0][0] == com["T0"] and abs(com["trechos"][-1][1] - com["T1"]) < 1e-6
    for x, y in zip(com["trechos"], com["trechos"][1:]):
        assert abs(x[1] - y[0]) < 1e-6
    # se a Skoopia já marcou o mesmo pedaço, não aparece de novo
    a, b = erros[0][0], erros[0][1]
    marcada = montagem.plano_skoopia(cues, [Cue(1, a, b, "[ERRO] repetiu a frase")], 0, 40, com_script=True)
    assert not any(t[3].startswith("[SCRIPT]") and t[0] < b and t[1] > a for t in marcada["trechos"])
