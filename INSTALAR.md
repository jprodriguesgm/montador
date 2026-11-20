# Instalar o Montador

Links diretos (sempre a versão oficial mais nova):
- Mac (Apple Silicon): https://github.com/jprodriguesgm/montador/releases/latest/download/Montador-mac.zip
- Windows 10/11 (64 bits): https://github.com/jprodriguesgm/montador/releases/latest/download/Montador-windows.zip

O LibreOffice (para converter os slides) e as fontes Montserrat, Poppins e Carlito já vão dentro do app.
Não precisa instalar mais nada, nem ter senha de administrador.

## Mac

1. Baixe o `Montador-mac.zip` e abra (o Mac descompacta sozinho).
2. Arraste o `Montador.app` para a pasta Aplicativos (ou para qualquer pasta sua).
3. Só na primeira vez de cada versão (o app não tem assinatura da Apple), abra o Terminal e cole:

       xattr -dr com.apple.quarantine /Applications/Montador.app

   (se pôs o app em outro lugar, troque o caminho — dá para arrastar o app para dentro do Terminal).
4. Dois cliques no Montador: ele abre no navegador. Fechou a aba, ele se fecha sozinho.

## Windows

1. Baixe o `Montador-windows.zip`, clique com o botão direito → **Extrair tudo** (numa pasta sua, ex.: Documentos).
2. Abra a pasta `Montador` e dê dois cliques em `Montador.exe`.
3. Se o Windows avisar "O Windows protegeu o computador": **Mais informações → Executar assim mesmo** (só na primeira vez).

## Primeira vez em cada computador

Em **Configurações** aponte a pasta dos arquivos de projeto (vinheta, créditos, brasão, fundos): o Montador procura
os outros sozinho a partir do primeiro, como o "Link Media" do Premiere.

## Se algo não funcionar

Pelo Terminal (Mac) ou Prompt de Comando (Windows), o diagnóstico confere tudo o que vai dentro do app:

    /Applications/Montador.app/Contents/MacOS/Montador diagnostico
    Montador\montador-terminal.exe diagnostico

O registro do que o app fez fica em `~/Library/Application Support/Montador/montador.log` (Mac)
ou `%APPDATA%\Montador\montador.log` (Windows).
