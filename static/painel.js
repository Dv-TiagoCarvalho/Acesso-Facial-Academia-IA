// Painel da recepção: alunos, cadastro do rosto, histórico e ajustes.
(() => {
  const $ = (seletor) => document.querySelector(seletor);
  const FOTOS_POR_ALUNO = 5;
  const PASSOS = [
    "Olhe direto para a câmera.",
    "Vire o rosto um pouco para a esquerda.",
    "Vire o rosto um pouco para a direita.",
    "Levante um pouco o queixo.",
    "Olhe para a câmera de novo.",
  ];
  const MOTIVOS = {
    sem_rosto: "Não encontrei um rosto. Fique de frente para a câmera.",
    imagem_invalida: "A imagem da câmera não chegou. Tentando de novo.",
    longe: "Chegue mais perto da câmera.",
    escuro: "Está escuro demais. Vire o rosto para a luz.",
    varios_rostos: "Deixe só o aluno na frente da câmera.",
    rosto_diferente: "Este rosto não parece o das fotos anteriores.",
  };

  // ------------------------------------------------------------------ pedidos ao servidor
  async function api(metodo, url, corpo) {
    const opcoes = { method: metodo, headers: { "X-Painel": "1" } };
    if (corpo instanceof Blob) {
      opcoes.headers["Content-Type"] = corpo.type || "image/jpeg";
      opcoes.body = corpo;
    } else if (corpo !== undefined) {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.body = JSON.stringify(corpo);
    }
    let resposta;
    try {
      resposta = await fetch(url, opcoes);
    } catch (e) {
      throw new Error("Sem ligação com o sistema. Confira se o programa continua aberto.");
    }
    const dados = await resposta.json().catch(() => ({}));
    if (resposta.status === 401 && !url.includes("/entrar") && !url.includes("/trocar-senha")) {
      mostrarEntrada(true);
      throw new Error("Sua sessão terminou. Entre de novo.");
    }
    if (!resposta.ok) throw new Error(dados.erro || "Não deu certo. Tente de novo.");
    return dados;
  }

  const dataBR = (iso) => iso.split("-").reverse().join("/");
  const paraISO = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const hoje = () => paraISO(new Date());
  // "2026-10-07 16:45:31" -> "Hoje, 16:45", "Ontem, 09:10" ou "03/10/2026"
  function quando(momento) {
    if (!momento) return "Nunca";
    const dia = momento.slice(0, 10), hora = momento.slice(11, 16);
    const ontem = new Date(); ontem.setDate(ontem.getDate() - 1);
    if (dia === hoje()) return `Hoje, ${hora}`;
    if (dia === paraISO(ontem)) return `Ontem, ${hora}`;
    return dataBR(dia);
  }
  function avisar(elemento, texto) {
    elemento.textContent = texto || "";
    elemento.hidden = !texto;
  }
  function piscar(elemento) {
    elemento.hidden = false;
    setTimeout(() => { elemento.hidden = true; }, 2500);
  }
  function celula(linha, texto, classe) {
    const td = document.createElement("td");
    if (classe) td.className = classe;
    if (texto !== undefined) td.textContent = texto;
    linha.appendChild(td);
    return td;
  }
  function sinal(td, cor, texto) {
    const span = document.createElement("span");
    span.className = `sinal ${cor}`;
    span.textContent = texto;
    td.appendChild(span);
  }
  function botaoLink(td, texto, acao) {
    const b = document.createElement("button");
    b.className = "link";
    b.textContent = texto;
    b.addEventListener("click", acao);
    td.appendChild(b);
  }

  // ------------------------------------------------------------------ entrada
  let primeiraVez = false;

  function mostrarEntrada(configurado) {
    primeiraVez = !configurado;
    $("#app").hidden = true;
    $("#entrada").hidden = false;
    $("#entrada-titulo").textContent = primeiraVez ? "Crie a senha do painel" : "Painel da recepção";
    $("#entrada-texto").textContent = primeiraVez
      ? "Só quem tiver esta senha poderá cadastrar alunos e ver os acessos. Use pelo menos 8 caracteres."
      : "Digite a senha para cadastrar alunos e ver os acessos.";
    $("#entrada-rotulo").textContent = primeiraVez ? "Nova senha" : "Senha";
    $("#entrada-botao").textContent = primeiraVez ? "Criar senha" : "Entrar";
    $("#entrada-senha").autocomplete = primeiraVez ? "new-password" : "current-password";
    $("#entrada-senha").value = "";
    avisar($("#entrada-erro"), "");
    $("#entrada-senha").focus();
  }

  $("#form-entrada").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    try {
      await api("POST", primeiraVez ? "/api/criar-senha" : "/api/entrar", { senha: $("#entrada-senha").value });
      abrirPainel();
    } catch (erro) {
      avisar($("#entrada-erro"), erro.message);
    }
  });

  $("#sair").addEventListener("click", async () => {
    await api("POST", "/api/sair");
    mostrarEntrada(true);
  });

  function abrirPainel() {
    $("#entrada").hidden = true;
    $("#app").hidden = false;
    trocarAba("alunos");
  }

  // ------------------------------------------------------------------ abas
  let abaAtual = "alunos";
  function trocarAba(nome) {
    abaAtual = nome;
    document.querySelectorAll(".abas button").forEach((b) => b.setAttribute("aria-selected", b.dataset.aba === nome));
    for (const aba of ["alunos", "acessos", "ajustes"]) $(`#aba-${aba}`).hidden = aba !== nome;
    if (nome === "alunos") carregarAlunos();
    if (nome === "acessos") carregarAcessos();
    if (nome === "ajustes") carregarAjustes();
  }
  document.querySelectorAll(".abas button").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));

  // ------------------------------------------------------------------ alunos
  let alunos = [];

  function textoPlano(aluno) {
    const { estado, dias } = aluno.situacao;
    if (estado === "bloqueado") return ["vermelho", "Entrada bloqueada"];
    if (estado === "vencido") return ["vermelho", `Venceu em ${dataBR(aluno.plano_validade)}`];
    if (estado === "vence_logo") {
      return ["amarelo", dias === 0 ? "Vence hoje" : dias === 1 ? "Vence amanhã" : `Vence em ${dias} dias`];
    }
    return ["verde", aluno.plano_validade ? `Até ${dataBR(aluno.plano_validade)}` : "Sem vencimento"];
  }

  async function carregarAlunos() {
    const busca = $("#busca").value.trim();
    let dados;
    try {
      dados = await api("GET", `/api/alunos?busca=${encodeURIComponent(busca)}`);
    } catch (e) { return; }
    alunos = dados.alunos;
    const corpo = $("#tabela-alunos tbody");
    corpo.replaceChildren();
    for (const aluno of alunos) {
      const tr = document.createElement("tr");
      celula(tr, aluno.nome, "nome");
      celula(tr, aluno.matricula, "num");
      sinal(celula(tr), ...textoPlano(aluno));
      const rosto = celula(tr);
      if (aluno.amostras) sinal(rosto, "verde", "Gravado");
      else sinal(rosto, "vazio", "Falta gravar");
      celula(tr, quando(aluno.ultimo_acesso), "num");
      const acoes = celula(tr, undefined, "acoes");
      botaoLink(acoes, "Liberar entrada", (evento) => liberarEntrada(aluno, evento.currentTarget));
      botaoLink(acoes, aluno.amostras ? "Rosto" : "Gravar rosto", () => abrirRosto(aluno));
      botaoLink(acoes, "Editar", () => abrirAluno(aluno));
      corpo.appendChild(tr);
    }
    const nenhum = alunos.length === 0;
    $("#tabela-alunos").hidden = nenhum;
    $("#sem-alunos").hidden = !(nenhum && !busca);
    $("#sem-resultado").hidden = !(nenhum && busca);
  }

  // A recepção libera a passagem sem o rosto. Pede um segundo clique para evitar engano.
  async function liberarEntrada(aluno, botao) {
    if (botao.textContent === "Liberar entrada") {
      botao.textContent = "Confirmar liberação";
      setTimeout(() => { if (botao.isConnected) botao.textContent = "Liberar entrada"; }, 4000);
      return;
    }
    try {
      await api("POST", `/api/alunos/${aluno.id}/liberar`);
      await carregarAlunos();
    } catch (erro) {
      botao.textContent = erro.message;
    }
  }

  let esperaBusca;
  $("#busca").addEventListener("input", () => {
    clearTimeout(esperaBusca);
    esperaBusca = setTimeout(carregarAlunos, 200);
  });

  // --- formulário do aluno
  let alunoEmEdicao = null;
  const dlgAluno = $("#dlg-aluno");

  function abrirAluno(aluno) {
    alunoEmEdicao = aluno;
    $("#al-titulo").textContent = aluno ? "Editar aluno" : "Cadastrar aluno";
    $("#al-nome").value = aluno ? aluno.nome : "";
    $("#al-matricula").value = aluno ? aluno.matricula : "";
    $("#al-validade").value = aluno && aluno.plano_validade ? aluno.plano_validade : "";
    $("#al-bloqueado").checked = aluno ? !aluno.ativo : false;
    $("#al-excluir").hidden = !aluno;
    $("#al-excluir").textContent = "Excluir aluno";
    avisar($("#al-erro"), "");
    dlgAluno.showModal();
  }
  $("#novo-aluno").addEventListener("click", () => abrirAluno(null));
  $("#novo-aluno-2").addEventListener("click", () => abrirAluno(null));

  $("#form-aluno").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const corpo = {
      nome: $("#al-nome").value,
      matricula: $("#al-matricula").value,
      plano_validade: $("#al-validade").value || null,
      ativo: !$("#al-bloqueado").checked,
    };
    try {
      const novo = !alunoEmEdicao;
      const dados = novo
        ? await api("POST", "/api/alunos", corpo)
        : await api("PUT", `/api/alunos/${alunoEmEdicao.id}`, corpo);
      dlgAluno.close();
      await carregarAlunos();
      if (novo) abrirRosto(dados.aluno);  // segue direto para gravar o rosto
    } catch (erro) {
      avisar($("#al-erro"), erro.message);
    }
  });

  // Renovar: soma os meses a partir do vencimento atual (ou de hoje, se já venceu).
  function somarMeses(iso, meses) {
    const [ano, mes, dia] = iso.split("-").map(Number);
    const alvo = new Date(ano, mes - 1 + meses, 1);
    const ultimoDia = new Date(alvo.getFullYear(), alvo.getMonth() + 1, 0).getDate();
    alvo.setDate(Math.min(dia, ultimoDia));
    return paraISO(alvo);
  }
  document.querySelectorAll(".renovar button").forEach((b) => b.addEventListener("click", () => {
    const atual = $("#al-validade").value;
    const base = atual && atual > hoje() ? atual : hoje();
    $("#al-validade").value = somarMeses(base, Number(b.dataset.meses));
  }));

  // Excluir pede um segundo clique em vez de abrir uma janela de confirmação.
  $("#al-excluir").addEventListener("click", async () => {
    const botao = $("#al-excluir");
    if (botao.textContent === "Excluir aluno") {
      botao.textContent = "Clique de novo para excluir";
      return;
    }
    try {
      await api("DELETE", `/api/alunos/${alunoEmEdicao.id}`);
      dlgAluno.close();
      carregarAlunos();
    } catch (erro) {
      avisar($("#al-erro"), erro.message);
    }
  });

  // ------------------------------------------------------------------ importar planilha
  const dlgImportar = $("#dlg-importar");
  $("#importar").addEventListener("click", () => {
    $("#im-arquivo").value = "";
    $("#im-resultado").hidden = true;
    avisar($("#im-erro"), "");
    dlgImportar.showModal();
  });
  $("#im-enviar").addEventListener("click", async () => {
    const arquivo = $("#im-arquivo").files[0];
    avisar($("#im-erro"), "");
    $("#im-resultado").hidden = true;
    if (!arquivo) { avisar($("#im-erro"), "Escolha o arquivo da planilha."); return; }
    try {
      const r = await api("POST", "/api/alunos/importar", new Blob([arquivo], { type: "text/csv" }));
      const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
      $("#im-resumo").textContent =
        `${plural(r.criados, "aluno criado", "alunos criados")}, ${plural(r.atualizados, "atualizado", "atualizados")}` +
        (r.total_problemas ? `, ${plural(r.total_problemas, "linha com problema", "linhas com problema")}:` : ".");
      const lista = $("#im-problemas");
      lista.replaceChildren();
      for (const problema of r.problemas) {
        const li = document.createElement("li");
        li.textContent = `Linha ${problema.linha}: ${problema.motivo}`;
        lista.appendChild(li);
      }
      $("#im-resultado").hidden = false;
      carregarAlunos();
    } catch (erro) {
      avisar($("#im-erro"), erro.message);
    }
  });

  // ------------------------------------------------------------------ rosto
  const dlgRosto = $("#dlg-rosto");
  const videoRosto = $("#ro-video");
  let alunoDoRosto = null;
  let gravando = false;
  let fluxoCamera = null;

  function abrirRosto(aluno) {
    alunoDoRosto = aluno;
    $("#ro-titulo").textContent = `Rosto de ${aluno.nome.split(" ")[0]}`;
    $("#ro-apagar").textContent = "Apagar rosto";
    if (aluno.amostras) {
      $("#ro-existente").hidden = false;
      $("#ro-captura").hidden = true;
      $("#ro-resumo").textContent = aluno.consentimento_em
        ? `Rosto gravado. O aluno autorizou o uso em ${dataBR(aluno.consentimento_em.slice(0, 10))}.`
        : "Rosto gravado.";
    } else {
      prepararCaptura();
    }
    dlgRosto.showModal();
  }

  async function prepararCaptura() {
    $("#ro-existente").hidden = true;
    $("#ro-captura").hidden = false;
    $("#ro-autorizacao").hidden = Boolean(alunoDoRosto.consentimento_em);
    $("#ro-autorizou").checked = false;
    $("#ro-comecar").hidden = false;
    $("#ro-comecar").disabled = false;
    $("#ro-fechar").textContent = "Cancelar";
    $("#ro-passo").textContent = "Peça para o aluno ficar de frente para a câmera.";
    $("#ro-ajuda").textContent = "São 5 fotos rápidas, em posições um pouco diferentes.";
    avisar($("#ro-erro"), "");
    marcar(0);
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      avisar($("#ro-erro"), "A câmera não abre neste endereço. Use http://localhost ou o endereço https://.");
      $("#ro-comecar").disabled = true;
      return;
    }
    try {
      fluxoCamera = await navigator.mediaDevices.getUserMedia({
        audio: false, video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      videoRosto.srcObject = fluxoCamera;
    } catch (erro) {
      avisar($("#ro-erro"), erro.name === "NotAllowedError"
        ? "Permita o uso da câmera no navegador e abra esta janela de novo."
        : "Não consegui abrir a câmera. Confira se ela está ligada e livre.");
      $("#ro-comecar").disabled = true;
    }
  }

  function marcar(feitas) {
    [...$("#ro-marcas").children].forEach((m, i) => m.classList.toggle("ok", i < feitas));
  }

  function fotografar() {
    const tela = document.createElement("canvas");
    const escala = Math.min(1, 640 / videoRosto.videoWidth);
    tela.width = Math.round(videoRosto.videoWidth * escala);
    tela.height = Math.round(videoRosto.videoHeight * escala);
    tela.getContext("2d").drawImage(videoRosto, 0, 0, tela.width, tela.height);
    return new Promise((ok) => tela.toBlob(ok, "image/jpeg", 0.9));
  }
  const pausa = (ms) => new Promise((ok) => setTimeout(ok, ms));

  async function gravarRosto() {
    if (!alunoDoRosto.consentimento_em && !$("#ro-autorizou").checked) {
      avisar($("#ro-erro"), "Marque a autorização do aluno antes de gravar.");
      return;
    }
    avisar($("#ro-erro"), "");
    $("#ro-comecar").hidden = true;
    $("#ro-autorizacao").hidden = true;
    gravando = true;
    let feitas = 0;
    const url = `/api/alunos/${alunoDoRosto.id}/rosto?autorizado=1`;

    while (gravando && feitas < FOTOS_POR_ALUNO) {
      $("#ro-passo").textContent = PASSOS[feitas];
      await pausa(feitas === 0 ? 600 : 1300);
      if (!gravando) break;
      if (!videoRosto.videoWidth) continue;
      let r;
      try {
        r = await api("POST", url, await fotografar());
      } catch (erro) {
        avisar($("#ro-erro"), erro.message);
        break;
      }
      if (r.aceita) {
        feitas += 1;
        marcar(feitas);
        $("#ro-ajuda").textContent = `${feitas} de ${FOTOS_POR_ALUNO} fotos gravadas.`;
      } else if (r.motivo === "duplicado") {
        avisar($("#ro-erro"), `Este rosto já está gravado no cadastro de ${r.outro}. Apague o rosto de lá antes de gravar aqui.`);
        break;
      } else if (r.motivo === "limite") {
        feitas = FOTOS_POR_ALUNO;
      } else {
        $("#ro-ajuda").textContent = MOTIVOS[r.motivo] || "Tentando de novo.";
      }
    }

    const terminou = feitas >= FOTOS_POR_ALUNO;
    gravando = false;
    if (terminou) {
      $("#ro-passo").textContent = "Rosto gravado.";
      $("#ro-ajuda").textContent = "O totem já reconhece este aluno.";
    } else if (dlgRosto.open) {
      $("#ro-passo").textContent = feitas ? "Gravação interrompida." : "Nenhuma foto foi gravada.";
      $("#ro-comecar").hidden = false;
      $("#ro-comecar").textContent = "Tentar de novo";
    }
    $("#ro-fechar").textContent = "Fechar";
    carregarAlunos();
  }
  $("#ro-comecar").addEventListener("click", gravarRosto);

  $("#ro-refazer").addEventListener("click", async () => {
    try {
      await api("DELETE", `/api/alunos/${alunoDoRosto.id}/rosto`);
      alunoDoRosto = { ...alunoDoRosto, amostras: 0, consentimento_em: null };
      carregarAlunos();
      prepararCaptura();
    } catch (erro) {
      $("#ro-resumo").textContent = erro.message;
    }
  });

  $("#ro-apagar").addEventListener("click", async () => {
    const botao = $("#ro-apagar");
    if (botao.textContent === "Apagar rosto") {
      botao.textContent = "Clique de novo para apagar";
      return;
    }
    try {
      await api("DELETE", `/api/alunos/${alunoDoRosto.id}/rosto`);
      dlgRosto.close();
      carregarAlunos();
    } catch (erro) {
      $("#ro-resumo").textContent = erro.message;
    }
  });

  dlgRosto.addEventListener("close", () => {
    gravando = false;
    if (fluxoCamera) fluxoCamera.getTracks().forEach((t) => t.stop());
    fluxoCamera = null;
    videoRosto.srcObject = null;
    $("#ro-comecar").textContent = "Gravar rosto";
  });

  document.querySelectorAll("[data-fechar]").forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close()));

  // ------------------------------------------------------------------ acessos
  const RESULTADOS = {
    liberado: ["verde", "Liberado pelo rosto"],
    liberado_manual: ["verde", "Liberado pela recepção"],
    plano_vencido: ["amarelo", "Barrado: plano vencido"],
    bloqueado: ["vermelho", "Barrado: entrada bloqueada"],
  };

  async function carregarAcessos() {
    const campo = $("#dia");
    if (!campo.value) campo.value = hoje();
    let dados;
    try {
      dados = await api("GET", `/api/acessos?dia=${campo.value}`);
    } catch (e) { return; }
    $("#baixar").href = `/api/acessos.csv?dia=${dados.dia}`;
    const corpo = $("#tabela-acessos tbody");
    corpo.replaceChildren();
    for (const acesso of dados.acessos) {
      const tr = document.createElement("tr");
      celula(tr, acesso.hora, "num");
      celula(tr, acesso.nome, "nome");
      celula(tr, acesso.matricula, "num");
      sinal(celula(tr), ...(RESULTADOS[acesso.resultado] || ["vazio", acesso.resultado]));
      corpo.appendChild(tr);
    }
    const nenhum = dados.acessos.length === 0;
    $("#tabela-acessos").hidden = nenhum;
    $("#sem-acessos").hidden = !nenhum;
    const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
    $("#resumo-acessos").textContent = nenhum ? "" :
      `${plural(dados.liberados, "entrada liberada", "entradas liberadas")}, ${plural(dados.barrados, "barrada", "barradas")}`;
  }
  $("#dia").addEventListener("change", carregarAcessos);
  // Mantém a lista de hoje atualizada enquanto a aba estiver aberta.
  setInterval(() => {
    if (!$("#app").hidden && abaAtual === "acessos" && $("#dia").value === hoje() && !document.hidden) carregarAcessos();
  }, 10000);

  // ------------------------------------------------------------------ ajustes
  const numeroBR = (n) => Number(n).toFixed(2).replace(".", ",");

  function mostrarCatraca(ultimo) {
    $("#aj-catraca-ultimo").textContent = ultimo
      ? `Último acionamento em ${ultimo.quando}: ${ultimo.ok ? "deu certo" : "falhou"}. ${ultimo.detalhe}`
      : "";
  }
  function mostrarAjustes(dados) {
    $("#aj-nome").value = dados.nome_academia;
    $("#aj-limiar").value = dados.limiar;
    $("#aj-valor").textContent = numeroBR(dados.limiar);
    $("#aj-vida").checked = dados.prova_de_vida;
    $("#aj-catraca").value = dados.catraca_url;
    mostrarCatraca(dados.catraca_ultimo);
  }

  async function carregarAjustes() {
    try {
      mostrarAjustes(await api("GET", "/api/ajustes"));
    } catch (e) { /* a tela de entrada já foi mostrada */ }
  }
  $("#aj-limiar").addEventListener("input", () => { $("#aj-valor").textContent = numeroBR($("#aj-limiar").value); });

  $("#form-ajustes").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    avisar($("#aj-erro"), "");
    try {
      const dados = await api("PUT", "/api/ajustes", {
        nome_academia: $("#aj-nome").value, limiar: Number($("#aj-limiar").value),
        prova_de_vida: $("#aj-vida").checked, catraca_url: $("#aj-catraca").value.trim(),
      });
      mostrarAjustes(dados);
      $("#nome-academia").textContent = dados.nome_academia;
      piscar($("#aj-feito"));
    } catch (erro) {
      avisar($("#aj-erro"), erro.message);
    }
  });

  $("#aj-testar").addEventListener("click", async () => {
    avisar($("#aj-erro"), "");
    try {
      mostrarCatraca(await api("POST", "/api/catraca/testar", { catraca_url: $("#aj-catraca").value.trim() }));
    } catch (erro) {
      avisar($("#aj-erro"), erro.message);
    }
  });

  $("#form-senha").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    avisar($("#se-erro"), "");
    try {
      await api("POST", "/api/trocar-senha", { atual: $("#se-atual").value, nova: $("#se-nova").value });
      evento.target.reset();
      piscar($("#se-feito"));
    } catch (erro) {
      avisar($("#se-erro"), erro.message);
    }
  });

  // ------------------------------------------------------------------ início
  (async () => {
    try {
      const estado = await fetch("/api/sessao").then((r) => r.json());
      if (estado.dentro) abrirPainel();
      else mostrarEntrada(estado.configurado);
    } catch (e) {
      mostrarEntrada(true);
      avisar($("#entrada-erro"), "Sem ligação com o sistema. Confira se o programa continua aberto.");
    }
  })();
})();
