"""Motor de montagem: os geradores de XML do Fluxo NPD (regras de montagem já aprovadas) e os modelos.

Os scripts vieram do repositório video_editor_assist (Fluxo NPD) quase sem mudança. Diferenças:
  - gerar_xml_tp_slide.py e gerar_xml_pk.py aceitam MONTADOR_PLANO (início, fim e cortes vindos do Montador:
    Skoopia ou regras) e o primeiro aceita MONTADOR_NOME_SEQ;
  - os modelos tiveram os nomes de pasta dos professores trocados por "26_000 Professor Exemplo".
O Montador roda cada script dentro do próprio processo (runpy), com os argumentos de sempre.
"""
