-- Exporta um .pptx como imagens (um arquivo por slide) pelo Keynote, sem janelas de aviso.
-- Uso: osascript keynote_exportar.applescript "/caminho/arquivo.pptx" "/pasta/de/saida"
on run argv
	set caminhoArquivo to item 1 of argv
	set pastaSaida to item 2 of argv
	if pastaSaida does not end with "/" then set pastaSaida to pastaSaida & "/"
	do shell script "mkdir -p " & quoted form of pastaSaida
	set doc to missing value
	tell application "Keynote" to set qtdAntes to count of documents
	do shell script "open -g -a Keynote " & quoted form of caminhoArquivo
	set tentativas to 0
	repeat while doc is missing value and tentativas < 240
		delay 0.5
		tell application "Keynote"
			if (count of documents) > qtdAntes then set doc to document 1
		end tell
		set tentativas to tentativas + 1
	end repeat
	if doc is missing value then error "Keynote não abriu o arquivo a tempo"
	my dispensarDialogos()
	with timeout of 600 seconds
		tell application "Keynote" to export doc to (POSIX file pastaSaida as alias) as slide images with properties {image format:PNG}
	end timeout
	tell application "Keynote" to close doc saving no
	return "ok"
end run

on dispensarDialogos()
	try
		tell application "System Events"
			tell process "Keynote"
				set t to 0
				repeat while t < 6
					if (count of windows) > 0 then
						try
							keystroke return
						end try
					end if
					delay 0.5
					set t to t + 1
				end repeat
			end tell
		end tell
	end try
end dispensarDialogos
