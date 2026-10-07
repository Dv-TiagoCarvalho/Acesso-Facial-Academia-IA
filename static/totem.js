// Totem da recepção: manda quadros da câmera para o servidor e mostra a resposta.
(() => {
  const INTERVALO_MS = 350;        // tempo entre uma leitura e outra
  const INTERVALO_DESAFIO_MS = 150; // mais rápido enquanto o aluno vira o rosto
  const PAUSA_TENTAR_DE_NOVO_MS = 3500;
  const PAUSA_RESULTADO_MS = 4500; // quanto tempo o resultado fica na tela
  const LARGURA_ENVIO = 640;

  const totem = document.getElementById("totem");
  const video = document.getElementById("camera");
  const titulo = document.getElementById("titulo");
  const apoio = document.getElementById("apoio");
  const relogio = document.getElementById("relogio");
  const quadro = document.createElement("canvas");
  const totemId = Math.random().toString(36).slice(2) + Date.now().toString(36);

  const dataBR = (iso) => iso.split("-").reverse().join("/");

  function mostrar(estado, textoTitulo, textoApoio, html = false) {
    totem.dataset.estado = estado;
    if (titulo.textContent !== textoTitulo) titulo.textContent = textoTitulo;
    if (html) apoio.innerHTML = textoApoio;
    else if (apoio.textContent !== textoApoio) apoio.textContent = textoApoio;
  }

  // Devolve quantos milissegundos esperar até a próxima leitura.
  function interpretar(r) {
    switch (r.estado) {
      case "desafio":
        if (r.passo === "frente") mostrar("desafio", "Olhe para a câmera", "Fique de frente por um instante.");
        else if (r.passo === "segure") mostrar("desafio", "Isso, segure assim", "Só mais um instante.");
        else mostrar("desafio", "Agora vire o rosto", "Devagar, para qualquer um dos lados, e segure um instante.");
        return INTERVALO_DESAFIO_MS;
      case "desafio_falhou":
        mostrar("ajuste", "Vamos de novo",
          "Olhe para a câmera e, quando a tela pedir, vire o rosto devagar para um lado.");
        return PAUSA_TENTAR_DE_NOVO_MS;
      case "liberado": {
        let linha = r.plano_validade ? `Plano válido até ${dataBR(r.plano_validade)}.` : "Entrada liberada.";
        if (r.vence_logo) {
          linha = r.dias === 0 ? "Seu plano vence hoje. Passe na recepção para renovar."
                : r.dias === 1 ? "Seu plano vence amanhã."
                : `Seu plano vence em ${r.dias} dias.`;
        }
        mostrar("liberado", `Bom treino, ${r.nome}`, linha);
        return PAUSA_RESULTADO_MS;
      }
      case "plano_vencido":
        mostrar("plano_vencido", `${r.nome}, seu plano venceu`,
          `Venceu em ${dataBR(r.plano_validade)}. Passe na recepção para renovar.`);
        return PAUSA_RESULTADO_MS;
      case "bloqueado":
        mostrar("bloqueado", `${r.nome}, passe na recepção`,
          "Sua entrada precisa ser liberada por um atendente.");
        return PAUSA_RESULTADO_MS;
      case "desconhecido":
        mostrar("desconhecido", "Não reconheci você",
          "Se já é aluno, peça para a recepção cadastrar seu rosto.");
        return PAUSA_RESULTADO_MS;
      case "analisando":
        mostrar("analisando", "Só um instante", "Continue olhando para a câmera.");
        return INTERVALO_MS;
      case "longe":
        mostrar("ajuste", "Chegue mais perto", "Fique a um braço de distância da tela.");
        return INTERVALO_MS;
      case "escuro":
        mostrar("ajuste", "Está escuro demais", "Vire o rosto para a luz.");
        return INTERVALO_MS;
      case "sem_cadastros":
        mostrar("ajuste", "Nenhum rosto cadastrado",
          'Abra o <a href="/painel">painel da recepção</a> para cadastrar o primeiro aluno.', true);
        return INTERVALO_MS;
      default:
        mostrar("espera", "Olhe para a câmera", "Fique de frente, a um braço de distância da tela.");
        return INTERVALO_MS;
    }
  }

  function capturar() {
    const escala = Math.min(1, LARGURA_ENVIO / video.videoWidth);
    quadro.width = Math.round(video.videoWidth * escala);
    quadro.height = Math.round(video.videoHeight * escala);
    quadro.getContext("2d").drawImage(video, 0, 0, quadro.width, quadro.height);
    return new Promise((ok) => quadro.toBlob(ok, "image/jpeg", 0.85));
  }

  async function ciclo() {
    let espera = INTERVALO_MS;
    try {
      if (video.videoWidth && !document.hidden) {
        const foto = await capturar();
        const resposta = await fetch("/api/reconhecer", {
          method: "POST",
          headers: { "Content-Type": "image/jpeg", "X-Totem": totemId },
          body: foto,
        });
        if (!resposta.ok) throw new Error(resposta.status);
        espera = interpretar(await resposta.json());
      }
    } catch (erro) {
      mostrar("erro", "Sem ligação com o sistema",
        "Confira se o programa da academia continua aberto no computador da recepção.");
      espera = 2000;
    }
    setTimeout(ciclo, espera);
  }

  async function ligarCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      mostrar("erro", "A câmera não abre neste endereço",
        "No tablet, use o endereço que começa com https://, mostrado ao iniciar o programa com --rede.");
      return;
    }
    try {
      video.srcObject = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      await video.play();
      mostrar("espera", "Olhe para a câmera", "Fique de frente, a um braço de distância da tela.");
      ciclo();
    } catch (erro) {
      if (erro.name === "NotAllowedError") {
        mostrar("erro", "Permita o uso da câmera",
          "Clique no cadeado ao lado do endereço, libere a câmera e recarregue a página.");
      } else if (erro.name === "NotFoundError" || erro.name === "OverconstrainedError") {
        mostrar("erro", "Nenhuma câmera encontrada", "Ligue uma webcam e recarregue a página.");
      } else {
        mostrar("erro", "A câmera não abriu",
          "Feche outros programas que estejam usando a câmera e recarregue a página.");
      }
    }
  }

  function atualizarRelogio() {
    relogio.textContent = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  atualizarRelogio();
  setInterval(atualizarRelogio, 10000);

  ligarCamera();
})();
