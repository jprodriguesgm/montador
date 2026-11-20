// Thumbs das aulas no padrão do "Gerador de Thumbnail" da equipe.
// A fonte e as artes vêm do index.html do gerador (Configurações → Thumbs); a conta do tamanho da letra,
// as regras de barra (\\ e //) e o [[ ]] são as mesmas dele. Exporta PNG 1920x1080.

const TH = { modelo: null, opcao: null, previa: 720 };     // a prévia tem 720 px de largura, como no gerador
const TH_SAIDA = { largura: 1920, altura: 1080 };

function thExtrair(texto) {
  // igual ao gerador: "\\" corta à esquerda, "//" corta à direita, [[ ... ]] junta linhas numa thumb só
  if (!texto) return [];
  const linhas = texto.split("\n").map((el) => el.split("\\\\").pop().split("//")[0].trim());
  const out = []; let junta = []; let juntando = false;
  for (const el of linhas) {
    if (el.includes("[[")) { junta.push(el.split("[[").pop().trim()); juntando = true; continue; }
    if (el.includes("]]")) { junta.push(el.split("]]")[0].trim()); juntando = false; out.push(junta.join("\n")); junta = []; continue; }
    if (juntando) { junta.push(el); continue; }
    out.push(el);
  }
  return out.filter((t) => t.trim() !== "");
}

function thPx(v, base) {
  v = String(v || "").trim();
  if (v === "none" || v === "") return Infinity;
  if (v.endsWith("rem")) return parseFloat(v) * 16;
  if (v.endsWith("%")) return (parseFloat(v) / 100) * base;
  return parseFloat(v);
}

// mesma conta do gerador: estima as linhas com letra de 16 px, chuta o tamanho e diminui até caber
function thTamanho(caixa, txt, area) {
  const { width: maxW, height: maxH } = caixa.getBoundingClientRect();
  const base = 16, minS = thPx(area.font_min, base), maxS = thPx(area.font_max, base);
  const quebras = txt.innerText.split("\n").map((l) => Math.ceil((l.length * base) / maxW));
  const linhas = Math.max(1, Math.ceil(quebras.reduce((a, n) => a + n, 0)));
  const mult = Math.ceil(maxH / (linhas * base + linhas));
  let tam = Math.max(minS, Math.min(base * mult, maxS));
  txt.style.fontSize = `${tam}px`;
  while (tam > minS && (txt.scrollHeight > txt.clientHeight || txt.scrollWidth > txt.clientWidth)) {
    tam = Math.max(minS, tam - 1);
    txt.style.fontSize = `${tam}px`;
  }
}

function thNomes(titulos) {
  // mesmo nome das sequências ("01 Título"); se o número da linha bater com uma aula, usa o título dela
  return titulos.map((t, i) => {
    const a = S.aulas[i];
    return { numero: i + 1, nome: a && titulos.length === S.aulas.length ? a.nome : null, texto: t };
  });
}

function thNomeArquivo(item, numero) {
  const n = String(numero).padStart(2, "0");
  if (item.nome) return item.nome.replace(/^\d+/, n);
  return `${n} ${item.texto.replace(/\s*\n\s*/g, " ")}`;
}

async function thDesenhar() {
  const lista = $("thumbsLista");
  const op = TH.opcao, a = op.area;
  const titulos = thExtrair($("thumbsTitulos").value);
  const itens = thNomes(titulos);
  lista.innerHTML = itens.map((it, i) => `
    <div class="th-item" data-i="${i}">
      <div class="th-lado">
        <input type="checkbox" class="th-usar" checked title="Gerar esta thumb">
        <input type="number" class="campo th-num" min="1" value="${it.numero}" title="Número da thumb">
      </div>
      <div>
        <div class="th-main" style="width:${TH.previa}px;height:${TH.previa * 9 / 16}px">
          <img src="${op.img}" draggable="false" alt="">
          <div class="th-area" style="width:${a.w};height:${a.h};transform:translate(calc(-50% + ${a.tw}), calc(-50% + ${a.th}))">
            <div class="th-txt" contenteditable="true" spellcheck="false"></div>
          </div>
        </div>
        <div class="dica th-arq"></div>
      </div>
    </div>`).join("");
  const familia = `'${TH.modelo.familia}', Arial, sans-serif`;
  lista.querySelectorAll(".th-item").forEach((el, i) => {
    const txt = el.querySelector(".th-txt");
    txt.innerText = itens[i].texto;
    txt.style.fontFamily = familia;
    el._item = itens[i];
    const atualizar = () => {
      thTamanho(el.querySelector(".th-area"), txt, a);
      el.querySelector(".th-arq").textContent = thNomeArquivo(el._item, el.querySelector(".th-num").value || i + 1) + ".png";
    };
    txt.addEventListener("input", atualizar);
    el.querySelector(".th-num").addEventListener("change", () => { atualizar(); thRepetidos(); });
    el._atualizar = atualizar;
  });
  await document.fonts.load(`bold 40px '${TH.modelo.familia}'`).catch(() => {});
  await document.fonts.ready;
  await Promise.all([...lista.querySelectorAll("img")].map((im) => im.decode().catch(() => {})));
  lista.querySelectorAll(".th-item").forEach((el) => el._atualizar());
}

function thRepetidos() {
  const nums = [...document.querySelectorAll(".th-item")].filter((el) => el.querySelector(".th-usar").checked)
    .map((el) => Number(el.querySelector(".th-num").value));
  const rep = [...new Set(nums.filter((n, i) => nums.indexOf(n) !== i))];
  $("thumbsFeito").textContent = rep.length ? `Números repetidos: ${rep.join(", ")}` : "";
  return rep.length === 0;
}

function thOpcoes() {
  $("thumbsOpcoes").innerHTML = TH.modelo.opcoes.map((o) =>
    `<label class="pilula-op"><input type="radio" name="thOp" value="${esc(o.id)}" ${o.id === TH.opcao.id ? "checked" : ""}> ${esc(o.label)}</label>`).join("");
  $("thumbsOpcoes").querySelectorAll("input").forEach((r) => (r.onchange = () => {
    // guarda o que foi editado nas thumbs (como o gerador faz ao trocar de modelo)
    const textos = [...document.querySelectorAll(".th-txt")].map((t) => (t.innerText.includes("\n") ? `[[ ${t.innerText} ]]` : t.innerText));
    if (textos.length) $("thumbsTitulos").value = textos.join("\n");
    TH.opcao = TH.modelo.opcoes.find((o) => o.id === r.value);
    thDesenhar();
  }));
}

async function abrirThumbs() {
  $("modalThumbs").classList.remove("hidden");
  $("thumbsFeito").textContent = ""; $("thumbsAbrir").classList.add("hidden");
  try {
    TH.modelo = await api("/api/thumbs/modelo", {});
  } catch (e) {
    $("thumbsErro").textContent = e.message;
    $("thumbsSemModelo").classList.remove("hidden"); $("thumbsCorpo").classList.add("hidden");
    $("thumbsSalvar").classList.add("hidden");
    return;
  }
  $("thumbsSemModelo").classList.add("hidden"); $("thumbsCorpo").classList.remove("hidden");
  $("thumbsSalvar").classList.remove("hidden");
  let st = document.getElementById("thumbFonte");
  if (!st) { st = document.createElement("style"); st.id = "thumbFonte"; document.head.appendChild(st); }
  st.textContent = TH.modelo.fonte_css;
  TH.opcao = TH.opcao && TH.modelo.opcoes.find((o) => o.id === TH.opcao.id) || TH.modelo.opcoes.find((o) => o.padrao);
  if (!$("thumbsPasta").value) $("thumbsPasta").value = TH.modelo.pasta;
  $("thumbsTitulos").value = (S.aulas || []).map((a) => a.titulo).join("\n");
  thOpcoes();
  await thDesenhar();
}

async function thExportar(el) {
  const area = el.querySelector(".th-main");
  const txt = el.querySelector(".th-txt");
  txt.blur();
  const tela = await html2canvas(area, { scale: TH_SAIDA.largura / area.getBoundingClientRect().width, backgroundColor: null, logging: false });
  const c = document.createElement("canvas");
  c.width = TH_SAIDA.largura; c.height = TH_SAIDA.altura;
  c.getContext("2d").drawImage(tela, 0, 0, TH_SAIDA.largura, TH_SAIDA.altura);
  return c.toDataURL("image/png");
}

async function salvarThumbs() {
  if (!thRepetidos()) return toast("Há números de thumb repetidos.");
  const itens = [...document.querySelectorAll(".th-item")].filter((el) => el.querySelector(".th-usar").checked);
  if (!itens.length) return toast("Nenhuma thumb marcada.");
  $("thumbsSalvar").textContent = "Gerando…"; $("thumbsSalvar").disabled = true;
  try {
    const saida = [];
    for (const el of itens) {
      saida.push({ nome: thNomeArquivo(el._item, el.querySelector(".th-num").value || el._item.numero), png: await thExportar(el) });
    }
    const r = await api("/api/thumbs/salvar", { pasta: $("thumbsPasta").value.trim(), itens: saida });
    $("thumbsFeito").textContent = `${r.arquivos.length} thumb(s) salvas em ${r.pasta}`;
    $("thumbsAbrir").classList.remove("hidden");
    $("thumbsAbrir").onclick = () => api("/api/abrir_pasta", { caminho: r.pasta }).catch((e) => toast(e.message));
  } catch (e) { toast(e.message); }
  $("thumbsSalvar").textContent = "Confirmar e salvar"; $("thumbsSalvar").disabled = false;
}

$("thumbsFechar").onclick = () => $("modalThumbs").classList.add("hidden");
$("thumbsSalvar").onclick = salvarThumbs;
$("thumbsTitulos").addEventListener("change", thDesenhar);
$("thumbsTrocar").onclick = async () => { const p = await escolher("pasta", "Pasta das thumbs", $("thumbsPasta").value); if (p) $("thumbsPasta").value = p; };
$("thumbsApontar").onclick = async () => {
  const p = await escolher("arquivo", "Escolha o index.html do gerador de thumbnail");
  if (p) { await salvarConfig({ thumb_html: p }); abrirThumbs(); }
};
$("montarThumbs").onclick = () => { $("modalMontar").classList.add("hidden"); abrirThumbs(); };
$("cfgThumbBtn").onclick = async () => {
  const p = await escolher("arquivo", "Escolha o index.html do gerador de thumbnail");
  if (p) salvarConfig({ thumb_html: p });
};
