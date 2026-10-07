# Acesso facial para academia

O aluno olha para a câmera na entrada, vira o rosto para confirmar que é uma pessoa
e a tela mostra se a entrada está liberada. Roda em Python no computador da academia,
usa a webcam e é operado pelo navegador.

## Como iniciar

Você precisa do Python 3.10 ou mais novo (python.org/downloads), do Git e de uma webcam.

```
git clone https://github.com/Dv-TiagoCarvalho/Acesso-Facial-Academia-IA.git
cd Acesso-Facial-Academia-IA
sh iniciar.sh
```

No Windows, em vez de `sh iniciar.sh`, dê dois cliques em `iniciar.bat` (na instalação
do Python, marque "Add Python to PATH"). No macOS também dá para dar dois cliques em
`Iniciar.command`; se o sistema bloquear, clique com o botão direito e escolha "Abrir".

Na primeira vez o programa instala as dependências e baixa os dois modelos de
reconhecimento (37 MB), então precisa de internet. Depois disso funciona sem internet.

Quando aparecer "Acesso facial da academia no ar", o navegador abre sozinho em
`http://localhost:5050`. Deixe a janela do programa aberta enquanto usa.
Para encerrar, aperte Ctrl + C nela.

## Primeiro uso

1. Abra `http://localhost:5050/painel` e crie a senha do painel.
2. Clique em **Cadastrar aluno** e preencha nome, matrícula e validade do plano.
   Para muitos alunos de uma vez, use **Importar planilha**.
3. Na janela seguinte, marque a autorização do aluno e clique em **Gravar rosto**.
   São 5 fotos rápidas, seguindo as instruções na tela.
4. Abra o totem (`http://localhost:5050`) em tela cheia.

## O que acontece na entrada

1. O aluno olha para a câmera e é reconhecido.
2. A tela pede: "Agora vire o rosto". Ele vira devagar para qualquer lado e segura
   um instante. É isso que barra quem mostra uma foto ou a tela de um celular.
3. A tela responde:

| Situação | Tela |
|---|---|
| Plano em dia | Verde: "Bom treino, Nome" |
| Plano vence em até 5 dias | Verde, com aviso do vencimento |
| Plano vencido | Amarela: pede para passar na recepção |
| Entrada bloqueada no cadastro | Vermelha: pede para passar na recepção |
| Rosto não cadastrado | "Não reconheci você" |
| Não virou o rosto a tempo | "Vamos de novo" |

Cada passagem fica no histórico (aba **Acessos**), que pode ser baixado como planilha.

## O que o painel faz

- **Alunos:** cadastrar, editar, bloquear, excluir, buscar e ver a última entrada.
- **Renovar plano:** em "Editar", os botões "1 mês", "3 meses" e "1 ano" somam ao
  vencimento atual (ou a hoje, se já venceu).
- **Liberar entrada:** a recepção libera a passagem sem o rosto, por exemplo para
  quem não quis cadastrar a biometria. Fica registrado como "Liberado pela recepção".
- **Importar planilha:** arquivo CSV com as colunas `nome`, `matricula` e `validade`.
  Matrículas que já existem são atualizadas, sem apagar o rosto gravado.
- **Ajustes:** nome da academia, rigor do reconhecimento, ligar ou desligar o pedido
  de virar o rosto, endereço da catraca e senha do painel.

## Catraca ou trava de porta

Sem equipamento, a liberação é simulada: aparece na tela e no histórico.

Para acionar um equipamento de verdade, preencha em **Ajustes** o endereço que o
sistema deve chamar a cada entrada liberada. Serve para relés de rede e controladoras
que aceitam um comando por HTTP (o endereço exato vem no manual do equipamento).
O botão **Testar catraca** faz uma chamada na hora e mostra se o equipamento respondeu.
Para equipamentos com outro protocolo, o ponto de troca é a função `_acionar` em
`catraca.py`.

## Usar em um tablet

Inicie com `sh iniciar.sh --rede` (ou `iniciar.bat --rede`). O programa mostra um
endereço `https://...` para abrir no tablet, que precisa estar no mesmo Wi-Fi.
O navegador vai avisar que o certificado não é reconhecido: escolha "Avançado" e
"Continuar". O HTTPS é obrigatório porque os navegadores só liberam a câmera em
endereços seguros. Nesse modo, qualquer aparelho da rede alcança o sistema: use só
em uma rede separada da rede dos clientes.

## Limites que você precisa conhecer

- **A checagem contra foto tem alcance limitado.** Nos testes, nenhuma foto parada
  ou inclinada na frente da câmera foi aceita. Um vídeo da pessoa virando o rosto,
  tocado em um celular, pode enganar o sistema: só equipamentos com câmera
  infravermelha ou 3D barram isso. Para uma entrada sem ninguém por perto, use um
  terminal facial dedicado.
- **A checagem foi testada com vídeos públicos, não com os seus alunos.** Se muita
  gente precisar repetir o movimento, veja os valores no topo de `app.py`
  (`GIRO_MINIMO` é o principal) ou desligue o pedido em **Ajustes**.
- **Gêmeos e pessoas muito parecidas** podem ser confundidos. O ajuste de rigor reduz
  esse risco.
- **Uma senha só para o painel.** Não há usuários separados para dono e recepcionista.
- **Não cobra nem controla pagamento.** A validade do plano é informada por quem
  opera o painel ou pela planilha.

## Dados e privacidade

- Tudo fica na pasta `dados/` deste computador. Nada é enviado para a internet.
- Nenhuma foto é guardada: de cada rosto ficam só 128 números, que não permitem
  reconstruir a imagem.
- A data em que o aluno autorizou o uso do rosto fica registrada. "Apagar rosto"
  remove os dados do rosto e a autorização; "Excluir aluno" remove o cadastro
  (o nome continua nas linhas antigas do histórico).
- **Cópia de segurança:** uma por dia, automática, em `dados/copias/`, guardando as
  14 mais recentes. Elas ficam no mesmo computador: copie essa pasta para outro lugar
  de vez em quando. Para restaurar, feche o programa e substitua `dados/academia.db`
  pela cópia desejada.
- O banco não é criptografado. Quem copiar a pasta `dados` leva os cadastros, então
  proteja o computador com senha.
- Pela LGPD, dado biométrico é dado pessoal sensível. Antes de usar com alunos de
  verdade, confirme com um advogado o termo de consentimento e mantenha a liberação
  pela recepção como alternativa para quem não quiser usar o rosto.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | Servidor: páginas, regras de acesso, prova de vida e painel |
| `motor_facial.py` | Encontra o rosto, mede a pose e compara com os cadastrados |
| `catraca.py` | Aciona a catraca (simulada ou por rede) |
| `banco.py` | Banco de dados (SQLite) e cópia de segurança |
| `modelos.py` | Baixa e confere os modelos na primeira execução |
| `templates/`, `static/` | Telas do totem e do painel |

Modelos: YuNet (licença MIT) e SFace (Apache 2.0), do projeto OpenCV Zoo.
Fonte: Archivo (SIL Open Font License).
