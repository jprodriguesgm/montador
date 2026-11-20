"use strict";
// Montador — janela (etapa 1: configurações, pasta do dia, cartão, mapa do dia)

const $ = (id) => document.getElementById(id);
const CORES_AULA = ["#7fb2ff", "#7fd19b", "#f0c674", "#d9a3ff", "#ff9f80", "#6fd6d6", "#f7a8c8", "#b8d97a",
                    "#a8b8ff", "#ffd27f", "#9fe0b8", "#e6a0e0", "#8fd0ff", "#ffb38a", "#c8c87a", "#a0c4e0"];
const S = { estado: null, dia: null, titulos: [], faixas: [], aulas: [], trechoAtual: null };

async function api(caminho, corpo) {
  const opt = corpo === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) };
  const r = await fetch(caminho, opt);
  const j = await r.json().catch(() => ({ erro: "Resposta inválida do app." }));
  if (!r.ok || j.erro) throw new Error(j.erro || `Erro ${r.status}`);
  return j;
}

function toast(msg, ms = 4500) {
  const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function mmss(s) { s = Math.max(0, Math.round(s || 0)); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; }
function lerMmss(t) {
  const p = String(t).trim().split(":").map(Number);
  if (p.some(isNaN)) return null;
  return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p.length === 2 ? p[0] * 60 + p[1] : p[0];
}
function pilula(texto, tipo = "ok") { return `<span class="pilula ${tipo}">${esc(texto)}</span>`; }

// ------------------------------------------------------------------ escolher pasta/arquivo

async function escolher(tipo, titulo, inicio) {
  const r = await api("/api/escolher", { tipo, titulo, inicio });
  if (!r.sem_janela) return r.caminho || null;
  return navegar(tipo, titulo, inicio);           // Windows: navegador de pastas do app
}

function navegar(tipo, titulo, inicio) {
  return new Promise(async (resolve) => {
    $("navTitulo").textContent = titulo;
    $("navEscolher").classList.toggle("hidden", tipo !== "pasta");
    const { raizes } = await api("/api/raizes");
    $("navRaizes").innerHTML = raizes.map((r) => `<option value="${esc(r.path)}">${esc(r.name)}</option>`).join("");
    let atual = inicio || raizes[0].path;
    const fim = (v) => { $("modalNav").classList.add("hidden"); resolve(v); };
    async function abrir(p) {
      try {
        const l = await api("/api/listar?caminho=" + encodeURIComponent(p));
        atual = l.path; $("navCaminho").textContent = l.path;
        $("navAcima").onclick = () => l.parent && abrir(l.parent);
        const itens = l.dirs.map((d) => `<div class="pasta" data-p="${esc(d.path)}">${esc(d.name)}</div>`);
        if (tipo !== "pasta") itens.push(...[...l.videos, ...l.files].map((f) => `<div class="arq" data-f="${esc(f.path)}">${esc(f.name)}</div>`));
        $("navLista").innerHTML = itens.join("") || `<div class="arq">(vazia)</div>`;
        $("navLista").querySelectorAll("[data-p]").forEach((el) => (el.onclick = () => abrir(el.dataset.p)));
        $("navLista").querySelectorAll("[data-f]").forEach((el) => (el.onclick = () => fim(el.dataset.f)));
      } catch (e) { toast(e.message); }
    }
    $("navRaizes").onchange = () => abrir($("navRaizes").value);
    $("navCancelar").onclick = () => fim(null);
    $("navEscolher").onclick = () => fim(atual);
    $("modalNav").classList.remove("hidden");
    abrir(atual);
  });
}

// ------------------------------------------------------------------ configurações

function renderConfig() {
  const { config, assets, cores_premiere } = S.estado;
  $("listaAssets").innerHTML = assets.map((a) => `
    <div class="asset">
      <div><b>${esc(a.descricao)}</b> <span class="dica">${esc(a.nome)} · ${esc(a.formatos)}</span></div>
      <button class="btn pequeno" data-asset="${a.id}">${a.ok ? "Trocar" : "Procurar"}</button>
      <div class="cam">${a.ok ? esc(a.caminho) : ""}</div>
      <div class="st ${a.ok ? "ok" : "falta"}">${a.ok ? "ok" : "não encontrado"}</div>
    </div>`).join("");
  $("listaAssets").querySelectorAll("[data-asset]").forEach((b) => (b.onclick = () => apontarAsset(b.dataset.asset)));
  $("cfgGravacoes").value = config.pasta_gravacoes || "";
  for (const [id, chave] of [["corErro", "erro"], ["corBastidores", "bastidores"], ["corConferir", "conferir"]]) {
    $(id).innerHTML = cores_premiere.map((c) => `<option ${c === config.cores[chave] ? "selected" : ""}>${c}</option>`).join("");
    $(id).onchange = () => salvarConfig({ cores: { [chave]: $(id).value } });
  }
  $("cfgMarcacoes").value = config.marcacoes;
  $("cfgTrans").value = config.pasta_transcricoes || "";
  const faltam = assets.filter((a) => !a.ok).length;
  $("avisoConfig").classList.toggle("hidden", faltam === 0);
}

async function salvarConfig(mudancas) {
  try { S.estado = await api("/api/config", { mudancas }); renderConfig(); } catch (e) { toast(e.message); }
}

async function apontarAsset(id) {
  const a = S.estado.assets.find((x) => x.id === id);
  const p = await escolher("arquivo", `Onde está "${a.nome}"?`, S.estado.config.pasta_gravacoes);
  if (!p) return;
  try {
    S.estado = await api("/api/assets/apontar", { id, caminho: p });
    renderConfig();
    toast(S.estado.achados ? `Achei mais ${S.estado.achados} arquivo(s) na mesma estrutura.` : "Arquivo salvo.");
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ pasta do dia

async function abrirDia(caminho) {
  if (!caminho) return;
  $("caminhoDia").value = caminho;
  toast("Lendo a pasta do dia…", 2500);
  try { mostrarDia(await api("/api/dia", { caminho })); } catch (e) { toast(e.message); }
}

function mostrarDia(r) {
  S.dia = r.dia; S.titulos = r.titulos.titulos || []; S.faixas = r.mapa.faixas;
  const d = r.dia, c = d.cartao;
  $("caminhoDia").value = d.raiz;
  const nTrans = (d.transcritos || []).length;
  $("pilulasDia").innerHTML = [
    pilula(`${d.videos.length} vídeo(s)`, d.videos.length ? "ok" : "alerta"),
    nTrans >= d.videos.length ? pilula(`${nTrans} transcrição(ões)`) : pilula(`faltam ${d.videos.length - nTrans} transcrição(ões)`, "alerta"),
    d.srt_unico ? pilula("SRT único") : "",
    c ? pilula("cartão") : pilula("sem cartão", "alerta"),
    d.editado ? pilula("já tem Projeto/Saída", "alerta") : "",
  ].join(" ");
  $("avisosDia").innerHTML = d.avisos.map((a) => `<div class="aviso">${esc(a)}</div>`).join("");
  $("importarTrans").classList.remove("hidden");

  ["caixaCartao", "caixaFormato", "caixaSkoopia", "caixaMaterial", "caixaMapa", "rodape"].forEach((id) => $(id).classList.remove("hidden"));
  $("resumoCartao").innerHTML = c ? `
    <div><span>Curso</span> ${esc(c.curso || d.curso)}</div><div><span>Disciplina</span> ${esc(c.disciplina || "—")}</div>
    <div><span>Formato</span> ${esc(c.formato || "não informado")}</div><div><span>Inserção</span> ${esc(c.insercao || "não informada")}</div>
    <div><span>Títulos</span> ${S.titulos.length}</div><div><span>Arquivo</span> ${esc(c.arquivo ? c.arquivo.split(/[\\/]/).pop() : "texto colado")}</div>`
    : `<div class="dica">Nenhum .txt de cartão na pasta Originais. Cole o texto do cartão abaixo para preencher os títulos.</div>`;
  $("colarCartao").open = !c;
  if (r.titulos.motivo) $("resumoCartao").insertAdjacentHTML("beforeend", `<div class="aviso" style="grid-column:1/-1">${esc(r.titulos.motivo)}</div>`);

  if (c && c.formato) $("formato").value = c.formato;
  if (c && c.insercao) $("insercao").value = c.insercao;
  atualizarFormato();

  const m = d.material;
  $("pilulasMaterial").innerHTML = [
    m.pptx.length ? pilula(`${m.pptx.length} .pptx`) : "", m.docx.length ? pilula(`${m.docx.length} roteiro(s) .docx`) : "",
    m.imagens.length ? pilula(`${m.imagens.length} imagem(ns)`) : "",
  ].join(" ") || `<span class="dica">Nenhum material na pasta Originais.</span>`;
  const manuais = new Set(m.manuais || []);
  const todos = [...m.pptx, ...m.docx, ...m.imagens];
  $("listaMaterial").innerHTML = todos.length > 12 ? "" : todos.map((p) => `
    <div class="arq-linha"><span class="n" title="${esc(p)}">${esc(p.split(/[\\/]/).pop())}</span>
      <span class="info">${manuais.has(p) ? "escolhido à mão" : "Originais"}</span>
      ${manuais.has(p) ? `<button class="x" data-rm="${esc(p)}" title="Tirar">✕</button>` : "<span></span>"}</div>`).join("");
  $("listaMaterial").querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => material({ remover: b.dataset.rm })));

  const sk = d.skoopia || [];
  const opVideos = d.videos.map((v) => `<option value="${esc(v.nome)}">${esc(v.nome)}</option>`).join("");
  $("listaSkoopia").innerHTML = sk.map((a) => {
    const destino = a.modo === "dia" ? "dia inteiro, dividido por vídeo" : a.modo === "video" ? a.video : "";
    const info = a.modo === "pendente"
      ? `<span class="info pend">${esc(a.motivo)} <select data-pend="${esc(a.nome)}"><option value="">escolher vídeo…</option>${opVideos}</select></span>`
      : `<span class="info">${a.tipo === "cortes" ? "Cortes" : "Inserções"} · ${a.n} marcação(ões) · ${esc(destino)}</span>`;
    return `<div class="arq-linha"><span class="n">${esc(a.nome)}</span>${info}<button class="x" data-rmsk="${esc(a.nome)}" title="Tirar">✕</button></div>`;
  }).join("");
  $("listaSkoopia").querySelectorAll("[data-pend]").forEach((sel) => (sel.onchange = () => sel.value && enviarSkoopia({ escolher: { nome: sel.dataset.pend, video: sel.value } })));
  $("listaSkoopia").querySelectorAll("[data-rmsk]").forEach((b) => (b.onclick = () => enviarSkoopia({ remover: b.dataset.rmsk })));
  $("dicaSkoopia").textContent = sk.length ? "As marcações entram na timeline ao montar. Contagem por aula no mapa do dia."
    : "Sem SRTs da Skoopia, o app usa as regras do Fluxo NPD (sem IA).";

  mostrarMapa(r.mapa);
}

function atualizarFormato() {
  const f = $("formato").value;
  $("insercao").classList.toggle("hidden", f === "SCREENCAST");
  $("dicaFormato").textContent = f === "SCREENCAST" ? "Screencast: só cortes, sem inserções."
    : f === "TV" ? "TV: nos pontos de inserção, a exibição entra em tela cheia." : "";
}

// ------------------------------------------------------------------ mapa do dia

function corAula(n) { return n ? CORES_AULA[(n - 1) % CORES_AULA.length] : null; }

function mostrarMapa(m) {
  S.faixas = m.faixas; S.aulas = m.aulas;
  const porVideo = {};
  m.faixas.forEach((f, i) => (porVideo[f.video] ||= []).push({ ...f, i }));
  const nomes = S.dia.videos.length ? S.dia.videos.map((v) => v.nome) : Object.keys(porVideo);
  const durs = Object.fromEntries(nomes.map((n) => [n, (porVideo[n] || []).reduce((s, f) => s + Math.max(1, f.fim - f.ini), 0) || 1]));
  const maior = Math.max(...Object.values(durs), 1);
  const html = nomes.map((nome) => {
    const fs = porVideo[nome] || [];
    const total = durs[nome];
    const larguraBarra = Math.max(8, (100 * total) / maior);
    const partes = fs.map((f) => {
      const larg = Math.max(4, (100 * Math.max(1, f.fim - f.ini)) / total);
      const desc = f.aula === 0;
      const curto = (larguraBarra * larg) / 100 < 12;
      const rot = desc ? (curto ? "✕" : "descartado") : (curto ? `${f.aula}` : `aula ${f.aula}`);
      return `<div class="trecho ${desc ? "descartado" : ""} ${f.motivo ? "conferir" : ""}" data-i="${f.i}"
        style="width:${larg}%;${desc ? "" : `background:${corAula(f.aula)}`}" title="${esc(`${desc ? "descartado" : "aula " + f.aula} · ${mmss(f.ini)}–${mmss(f.fim)}${f.motivo ? " · " + f.motivo : ""}`)}">${esc(rot)}</div>`;
    }).join("");
    return `<div class="video"><div class="nome" title="${esc(nome)}">${esc(nome)}</div>
      <div class="trilho"><div class="barra" style="width:${larguraBarra}%">${partes}</div><span class="dur">${mmss(total)}</span></div></div>`;
  }).join("");
  $("mapa").innerHTML = html;
  $("mapa").querySelectorAll(".trecho").forEach((el) => (el.onclick = () => abrirTrecho(+el.dataset.i)));
  $("avisosMapa").innerHTML = m.avisos.map((a) => `<div class="aviso">${esc(a)}</div>`).join("");
  $("aulas").innerHTML = `<div class="aulas-lista">${m.aulas.map((a) => `
    <div class="aula"><span class="cor" style="background:${corAula(a.n)}"></span><span class="num">${String(a.n).padStart(2, "0")}</span>
      <input class="campo" data-t="${a.n - 1}" value="${esc(a.titulo)}" placeholder="Título da aula ${a.n}">
      ${a.marcas && (a.marcas.erro + a.marcas.bastidores + a.marcas.insercao) ? `<span class="marcas">Skoopia: ${a.marcas.erro} erro(s) · ${a.marcas.bastidores} bastidores · ${a.marcas.insercao} inserção(ões)</span>` : ""}
      ${a.conferir.map((x) => `<span class="motivo">${esc(x)}</span>`).join("")}</div>`).join("")}</div>`;
  $("aulas").querySelectorAll("[data-t]").forEach((el) => (el.onchange = () => { S.titulos[+el.dataset.t] = el.value.trim(); }));
}

function abrirTrecho(i) {
  const f = S.faixas[i]; S.trechoAtual = i;
  $("trechoTitulo").textContent = f.video;
  $("trechoInfo").textContent = `${mmss(f.ini)} a ${mmss(f.fim)}${f.motivo ? " · " + f.motivo : ""}`;
  const n = Math.max(S.aulas.length, S.titulos.length) + 1;
  const ops = [`<option value="0">Descartar</option>`];
  for (let k = 1; k <= n; k++) ops.push(`<option value="${k}" ${k === f.aula ? "selected" : ""}>Aula ${k}${S.titulos[k - 1] ? " · " + esc(S.titulos[k - 1]).slice(0, 50) : k === n ? " (nova)" : ""}</option>`);
  $("trechoAula").innerHTML = ops.join("");
  if (f.aula === 0) $("trechoAula").value = "0";
  $("trechoDividir").value = "";
  $("modalTrecho").classList.remove("hidden");
}

async function refazerMapa(extra = {}) {
  try { mostrarMapa(await api("/api/mapa", { faixas: S.faixas, titulos: S.titulos, ...extra })); } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ importar à mão

function lerArquivos(lista) {
  return Promise.all([...lista].map((f) => f.text().then((conteudo) => ({ nome: f.name, conteudo }))));
}

async function importarTranscricoes(corpo) {
  try {
    const r = await api("/api/transcricoes", corpo);
    mostrarDia(r);
    const i = r.importacao, partes = [];
    if (i.videos.length) partes.push(`${i.videos.length} transcrição(ões) ligadas aos vídeos${i.unico ? " (pelo SRT único)" : ""}`);
    if (i.skoopia.length) partes.push(`${i.skoopia.length} SRT(s) da Skoopia: entram na etapa 2`);
    if (i.ignorados.length) partes.push(`não reconheci: ${i.ignorados.slice(0, 4).join(", ")}${i.ignorados.length > 4 ? "…" : ""}`);
    toast(partes.join(" · ") || "Nenhuma transcrição reconhecida.", 7000);
  } catch (e) { toast(e.message); }
}

async function enviarSkoopia(corpo) {
  try { mostrarDia(await api("/api/skoopia", corpo)); } catch (e) { toast(e.message); }
}

async function material(corpo) {
  try { mostrarDia(await api("/api/material", corpo)); } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ montar

function abrirMontar() {
  if (!S.dia) { toast("Escolha a pasta do dia primeiro."); return; }
  const proj = S.dia.projeto || (S.dia.raiz.replace(/[\\/]+$/, "") + (S.dia.raiz.includes("\\") ? "\\" : "/") + "Projeto");
  $("montarDestino").value = proj;
  const nSk = (S.dia.skoopia || []).length, modo = S.estado.config.marcacoes;
  const fonte = modo === "regras" || (modo === "auto" && !nSk) ? "regras do Fluxo NPD (sem IA)" : "Skoopia";
  const fmt = $("formato").value === "SCREENCAST" ? "Screencast" : $("formato").value;
  $("montarResumo").textContent = `${S.aulas.length} aula(s) · formato ${fmt} · marcações: ${fonte}. Um XML por aula.`
    + ($("formato").value === "TP" ? " Os slides entram na próxima versão (etapa 3)." : "");
  $("montarAntes").classList.remove("hidden"); $("montarDepois").classList.add("hidden");
  $("montarIr").classList.remove("hidden"); $("montarAbrir").classList.add("hidden");
  $("modalMontar").classList.remove("hidden");
}

async function montarAgora() {
  $("montarIr").textContent = "Montando…";
  try {
    const r = await api("/api/montar", { faixas: S.faixas, titulos: S.titulos, formato: $("formato").value,
      insercao: $("insercao").value, destino: $("montarDestino").value.trim() });
    $("montarLista").innerHTML = r.resultados.map((x) => `
      <div class="arq-linha"><span class="n">${esc(x.nome)}.xml</span>
        <span class="info ${x.erro ? "pend" : ""}">${x.erro ? "não gerado: " + esc(x.erro)
          : `${x.n_erro} erro(s) · ${x.n_bastidores} bastidores · ${x.n_silencio} silêncio(s)`}</span><span></span></div>`).join("");
    $("montarAvisos").innerHTML = r.avisos.map((a) => `<div class="aviso">${esc(a)}</div>`).join("")
      + `<div class="dica">Relatório salvo junto: ${esc(r.relatorio.split(/[\\/]/).pop())}</div>`;
    $("montarAntes").classList.add("hidden"); $("montarDepois").classList.remove("hidden");
    $("montarIr").classList.add("hidden"); $("montarAbrir").classList.remove("hidden");
    $("montarAbrir").onclick = () => api("/api/abrir_pasta", { caminho: r.destino }).catch((e) => toast(e.message));
  } catch (e) { toast(e.message); }
  $("montarIr").textContent = "Montar";
}

// ------------------------------------------------------------------ início

async function iniciar() {
  S.estado = await api("/api/estado");
  $("versao").textContent = S.estado.versao;
  renderConfig();
  if (S.estado.config.ultima_pasta) $("caminhoDia").placeholder = S.estado.config.ultima_pasta;

  $("abrirConfig").onclick = $("avisoConfigBtn").onclick = () => $("modalConfig").classList.remove("hidden");
  $("fecharConfig").onclick = () => $("modalConfig").classList.add("hidden");
  $("cfgGravacoesBtn").onclick = async () => { const p = await escolher("pasta", "Pasta das gravações"); if (p) salvarConfig({ pasta_gravacoes: p }); };
  $("cfgGravacoes").onchange = () => salvarConfig({ pasta_gravacoes: $("cfgGravacoes").value.trim() || null });
  $("cfgMarcacoes").onchange = () => salvarConfig({ marcacoes: $("cfgMarcacoes").value });

  $("escolherDia").onclick = async () => abrirDia(await escolher("pasta", "Escolha a pasta do dia", S.estado.config.ultima_pasta || S.estado.config.pasta_gravacoes));
  $("caminhoDia").onkeydown = (e) => { if (e.key === "Enter") abrirDia($("caminhoDia").value.trim()); };
  $("usarCartao").onclick = async () => {
    try { mostrarDia(await api("/api/cartao/texto", { texto: $("textoCartao").value })); toast("Cartão lido."); } catch (e) { toast(e.message); }
  };
  $("formato").onchange = atualizarFormato;
  $("arqTrans").onchange = async (e) => { if (e.target.files.length) importarTranscricoes({ arquivos: await lerArquivos(e.target.files) }); e.target.value = ""; };
  $("pastaTrans").onclick = async () => {
    const p = await escolher("pasta", "Pasta com as transcrições (.srt)", S.estado.config.pasta_transcricoes || S.dia?.raiz);
    if (p) importarTranscricoes({ pasta: p });
  };
  const caixa = $("caixaDia");
  caixa.ondragover = (e) => { e.preventDefault(); caixa.classList.add("soltando"); };
  caixa.ondragleave = () => caixa.classList.remove("soltando");
  caixa.ondrop = async (e) => {
    e.preventDefault(); caixa.classList.remove("soltando");
    if (!S.dia) { toast("Escolha a pasta do dia primeiro."); return; }
    const fs = [...e.dataTransfer.files].filter((f) => /\.(srt|txt)$/i.test(f.name));
    if (fs.length) importarTranscricoes({ arquivos: await lerArquivos(fs) });
  };
  $("arqSkoopia").onchange = async (e) => { if (e.target.files.length) enviarSkoopia({ arquivos: await lerArquivos(e.target.files) }); e.target.value = ""; };
  const zona = $("soltarSkoopia");
  zona.ondragover = (e) => { e.preventDefault(); e.stopPropagation(); zona.classList.add("soltando"); };
  zona.ondragleave = () => zona.classList.remove("soltando");
  zona.ondrop = async (e) => {
    e.preventDefault(); e.stopPropagation(); zona.classList.remove("soltando");
    const fs = [...e.dataTransfer.files].filter((f) => /\.srt$/i.test(f.name));
    if (fs.length) enviarSkoopia({ arquivos: await lerArquivos(fs) });
  };
  $("addMaterial").onclick = async () => {
    const p = await escolher("arquivo", "Arquivo de inserção (.pptx, .docx ou imagem)", S.dia?.originais || S.dia?.raiz);
    if (p) material({ adicionar: [p] });
  };
  $("pastaMaterial").onclick = async () => {
    const p = await escolher("pasta", "Pasta com o material de inserção", S.dia?.originais || S.dia?.raiz);
    if (p) material({ pasta: p });
  };
  $("arqCartao").onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    $("textoCartao").value = await f.text();
    try { mostrarDia(await api("/api/cartao/texto", { texto: $("textoCartao").value })); toast("Cartão lido."); } catch (err) { toast(err.message); }
  };
  $("cfgTransBtn").onclick = async () => { const p = await escolher("pasta", "Pasta das transcrições"); if (p) salvarConfig({ pasta_transcricoes: p }); };
  $("cfgTrans").onchange = () => salvarConfig({ pasta_transcricoes: $("cfgTrans").value.trim() || null });

  $("trechoFechar").onclick = () => $("modalTrecho").classList.add("hidden");
  $("trechoOk").onclick = () => {
    S.faixas[S.trechoAtual].aula = +$("trechoAula").value;
    S.faixas[S.trechoAtual].motivo = "";
    $("modalTrecho").classList.add("hidden"); refazerMapa();
  };
  $("trechoDividirBtn").onclick = () => {
    const f = S.faixas[S.trechoAtual], t = lerMmss($("trechoDividir").value);
    if (t === null || t <= f.ini + 1 || t >= f.fim - 1) { toast(`Use um tempo entre ${mmss(f.ini)} e ${mmss(f.fim)}.`); return; }
    $("modalTrecho").classList.add("hidden");
    refazerMapa({ dividir: { video: f.video, tempo: t } });
  };
  $("montar").onclick = abrirMontar;
  $("montarFechar").onclick = () => $("modalMontar").classList.add("hidden");
  $("montarTrocar").onclick = async () => { const p = await escolher("pasta", "Onde salvar os XMLs", $("montarDestino").value); if (p) $("montarDestino").value = p; };
  $("montarIr").onclick = montarAgora;

  setInterval(() => fetch("/api/ping", { method: "POST" }).catch(() => {}), 20000);
}

iniciar().catch((e) => toast(e.message));
