"""Acesso por reconhecimento facial para academia — servidor.

Como usar:
    python app.py            -> abre em http://localhost:5050 (só neste computador)
    python app.py --rede     -> libera para tablets na mesma rede Wi-Fi (HTTPS)

Telas:
    /         totem da entrada (câmera + resultado)
    /painel   cadastro de alunos, rostos, histórico de acessos e ajustes
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import secrets
import socket
import sqlite3
import statistics
import threading
import time
import unicodedata
import webbrowser
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from banco import Banco
from catraca import Catraca, endereco_valido
from modelos import garantir_modelos
from motor_facial import Galeria, MotorFacial

RAIZ = Path(__file__).parent
PASTA_DADOS = RAIZ / "dados"

# ---- reconhecimento
MARGEM = 0.05             # distância mínima entre o 1º e o 2º aluno mais parecidos
QUADROS_CONFIRMAR = 2     # leituras seguidas do mesmo aluno antes de decidir
QUADROS_DESCONHECIDO = 5  # leituras seguidas sem achar ninguém antes de avisar
MAX_AMOSTRAS = 8          # fotos de rosto por aluno

# ---- prova de vida (o aluno vira o rosto; uma foto não consegue imitar isso)
# Os valores vêm de medições com vídeos de pessoas reais e com fotos planas
# inclinadas em várias posições: com eles nenhuma foto plana foi aprovada.
TEMPO_DESAFIO_S = 8       # tempo para o aluno virar o rosto
GIRO_FRENTE = 0.12        # até aqui o rosto conta como "de frente"
GIRO_MINIMO = 0.30        # quanto o nariz precisa se deslocar ao virar
PROPORCAO = (0.62, 0.97)  # um rosto real estreita um pouco ao virar; a foto inclinada estreita demais ou nada
ALTURA = (0.85, 1.18)     # e o rosto não muda de tamanho de repente
APROVACOES = 2            # leituras aprovadas em sequência antes de liberar
FOLGA_SEMELHANCA = 0.12   # de lado o rosto fica um pouco menos parecido com o cadastro
FALHAS_TOLERADAS = 2      # leituras ruins seguidas aceitas durante o desafio

# ---- plano e painel
AVISO_VENCIMENTO = 5      # dias antes do vencimento em que o totem avisa o aluno
MAX_TENTATIVAS_SENHA = 5
BLOQUEIO_SENHA_S = 60
HORAS_DE_SESSAO = 12
MAX_LINHAS_IMPORTACAO = 5000


def criar_app(pasta_dados: Path = PASTA_DADOS, pasta_modelos: Path = RAIZ / "models") -> Flask:
    app = Flask(__name__)
    pasta_dados.mkdir(parents=True, exist_ok=True)

    arquivo_chave = pasta_dados / "chave_secreta"
    if not arquivo_chave.exists():
        arquivo_chave.write_text(secrets.token_hex(32))
    app.secret_key = arquivo_chave.read_text().strip()
    app.config.update(
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=HORAS_DE_SESSAO),
        JSON_AS_ASCII=False,
    )

    banco = Banco(pasta_dados / "academia.db")
    caminhos = garantir_modelos(pasta_modelos)
    motor = MotorFacial(caminhos["detector"], caminhos["reconhecedor"])
    galeria = Galeria()
    galeria.carregar(banco.todas_amostras())
    catraca = Catraca(lambda: banco.config("catraca_url"))

    totens: dict[str, dict] = {}      # em que passo cada totem está
    trava_totens = threading.Lock()
    falhas_senha = {"n": 0, "ate": 0.0}

    # Cópia de segurança diária, enquanto o programa estiver aberto.
    def copiar_periodicamente():
        while True:
            try:
                banco.copia_de_seguranca(pasta_dados / "copias")
            except Exception as problema:
                logging.getLogger(__name__).warning("Cópia de segurança falhou: %s", problema)
            time.sleep(3600)
    threading.Thread(target=copiar_periodicamente, daemon=True).start()

    # ------------------------------------------------------------------ utilidades
    def limiar() -> float:
        return float(banco.config("limiar"))

    def prova_de_vida_ligada() -> bool:
        return banco.config("prova_de_vida") == "1"

    def erro(mensagem: str, codigo: int = 400):
        return jsonify(erro=mensagem), codigo

    def abrir_sessao():
        session.clear()
        session.permanent = True
        session["admin"] = True

    def exige_admin(funcao):
        @wraps(funcao)
        def protegida(*args, **kwargs):
            if not session.get("admin"):
                return erro("Entre no painel para continuar.", 401)
            # Pedidos que alteram dados precisam vir da própria página do painel.
            if request.method != "GET" and request.headers.get("X-Painel") != "1":
                return erro("Pedido recusado.", 403)
            return funcao(*args, **kwargs)
        return protegida

    def situacao(aluno) -> dict:
        """Situação do plano: em_dia | vence_logo | vencido | bloqueado."""
        dias = None
        if aluno["plano_validade"]:
            dias = (date.fromisoformat(aluno["plano_validade"]) - date.today()).days
        if not aluno["ativo"]:
            estado = "bloqueado"
        elif dias is not None and dias < 0:
            estado = "vencido"
        elif dias is not None and dias <= AVISO_VENCIMENTO:
            estado = "vence_logo"
        else:
            estado = "em_dia"
        return {"estado": estado, "dias": dias}

    def aluno_json(aluno) -> dict:
        return {
            "id": aluno["id"],
            "nome": aluno["nome"],
            "matricula": aluno["matricula"],
            "plano_validade": aluno["plano_validade"],
            "ativo": bool(aluno["ativo"]),
            "amostras": aluno["amostras"],
            "consentimento_em": aluno["consentimento_em"],
            "ultimo_acesso": aluno["ultimo_acesso"],
            "situacao": situacao(aluno),
        }

    def validar_aluno(nome, matricula, validade):
        """Devolve (nome, matrícula, validade) limpos ou levanta ValueError com o motivo."""
        nome = " ".join(str(nome or "").split())
        matricula = str(matricula or "").strip()
        validade = str(validade or "").strip() or None
        if len(nome) < 2:
            raise ValueError("Informe o nome do aluno.")
        if not matricula:
            raise ValueError("Informe a matrícula.")
        if len(nome) > 120 or len(matricula) > 40:
            raise ValueError("Nome ou matrícula longos demais.")
        if validade:
            try:
                date.fromisoformat(validade)
            except ValueError:
                raise ValueError("A data de validade do plano não é válida.") from None
        return nome, matricula, validade

    def ler_aluno_do_pedido():
        dados = request.get_json(silent=True) or {}
        try:
            campos = validar_aluno(dados.get("nome"), dados.get("matricula"), dados.get("plano_validade"))
        except ValueError as problema:
            return None, str(problema)
        return (*campos, bool(dados.get("ativo", True))), None

    # ------------------------------------------------------------------ páginas
    @app.get("/")
    def totem():
        return render_template("totem.html", academia=banco.config("nome_academia"))

    @app.get("/painel")
    def painel():
        return render_template("painel.html", academia=banco.config("nome_academia"))

    @app.after_request
    def cabecalhos(resposta):
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    @app.errorhandler(413)
    def grande_demais(_):
        return erro("Arquivo grande demais.", 413)

    # ------------------------------------------------------------------ totem
    def concluir(aluno, resultado: str, nota: float, sit: dict) -> dict:
        """Grava a passagem, aciona a catraca se for o caso e monta a resposta final."""
        banco.registrar_acesso(aluno, resultado, nota)
        if resultado == "liberado":
            catraca.liberar()
        return {
            "final": True,
            "estado": resultado,
            "nome": aluno["nome"].split()[0],
            "plano_validade": aluno["plano_validade"],
            "dias": sit["dias"],
            "vence_logo": sit["estado"] == "vence_logo",
        }

    def desafiar(passo: dict, analise, notas: dict, agora: float) -> dict:
        """Prova de vida: espera o aluno, já reconhecido, virar o rosto para um lado."""
        if agora - passo["inicio"] > TEMPO_DESAFIO_S:
            return {"final": True, "estado": "desafio_falhou"}

        aluno_id = passo["aluno_id"]
        nota = notas.get(aluno_id, -1.0)
        mesmo_aluno = (
            analise.status == "ok"
            and bool(notas)
            and max(notas, key=notas.get) == aluno_id
            and nota >= max(0.30, limiar() - FOLGA_SEMELHANCA)
        )
        if not mesmo_aluno:
            # Rosto sumiu ou trocou: tolera um instante, depois recomeça do zero.
            passo["aprovacoes"] = 0
            passo["falhas"] += 1
            if passo["falhas"] > FALHAS_TOLERADAS:
                return {"final": True, "estado": "analisando"}
            return {"estado": "desafio", "passo": "lado" if passo["frente"] else "frente"}
        passo["falhas"] = 0

        if abs(analise.giro) <= GIRO_FRENTE:
            # Referência "de frente": o giro típico das leituras frontais e as medidas da mais recente.
            passo["giros_frente"].append(analise.giro)
            passo["frente"] = (statistics.median(passo["giros_frente"]), analise.proporcao, analise.altura)
            passo["aprovacoes"] = 0
        elif passo["frente"]:
            giro0, proporcao0, altura0 = passo["frente"]
            virou = abs(analise.giro - giro0) >= GIRO_MINIMO
            sem_achatar = PROPORCAO[0] <= analise.proporcao / proporcao0 <= PROPORCAO[1]
            mesmo_tamanho = ALTURA[0] <= analise.altura / altura0 <= ALTURA[1]
            if not (virou and sem_achatar and mesmo_tamanho):
                passo["aprovacoes"] = 0
            else:
                passo["aprovacoes"] += 1
                if passo["aprovacoes"] >= APROVACOES:
                    aluno = banco.aluno(aluno_id)
                    if aluno is None:
                        return {"final": True, "estado": "analisando"}
                    sit = situacao(aluno)
                    if sit["estado"] in ("bloqueado", "vencido"):  # mudou durante o desafio
                        return {"final": True, "estado": "analisando"}
                    return concluir(aluno, "liberado", passo["nota"], sit)
                return {"estado": "desafio", "passo": "segure"}
        return {"estado": "desafio", "passo": "lado" if passo["frente"] else "frente"}

    def avancar(passo: dict, analise, agora: float) -> dict:
        """Um passo do totem: recebe a leitura atual e devolve o que mostrar."""
        notas = galeria.semelhancas(analise.vetor) if analise.status == "ok" else {}

        if passo["fase"] == "desafio":
            return desafiar(passo, analise, notas, agora)

        if analise.status != "ok" or not notas:
            passo.update(chave=None, n=0)
            return {"estado": analise.status if analise.status != "ok" else "sem_cadastros"}

        ordem = sorted(notas.items(), key=lambda par: par[1], reverse=True)
        aluno_id, nota = ordem[0]
        segunda = ordem[1][1] if len(ordem) > 1 else -1.0
        reconhecido = nota >= limiar() and nota - segunda >= MARGEM

        chave = aluno_id if reconhecido else 0
        if passo["chave"] != chave:
            passo.update(chave=chave, n=0)
        passo["n"] += 1

        if not reconhecido:
            if passo["n"] >= QUADROS_DESCONHECIDO:
                return {"final": True, "estado": "desconhecido"}
            return {"estado": "analisando"}
        if passo["n"] < QUADROS_CONFIRMAR:
            return {"estado": "analisando"}

        aluno = banco.aluno(aluno_id)
        if aluno is None:  # apagado agora há pouco
            galeria.carregar(banco.todas_amostras())
            return {"final": True, "estado": "analisando"}

        sit = situacao(aluno)
        if sit["estado"] == "bloqueado":
            return concluir(aluno, "bloqueado", nota, sit)
        if sit["estado"] == "vencido":
            return concluir(aluno, "plano_vencido", nota, sit)
        if not prova_de_vida_ligada():
            return concluir(aluno, "liberado", nota, sit)

        passo.update(fase="desafio", aluno_id=aluno_id, nota=nota, inicio=agora,
                     frente=None, giros_frente=[], aprovacoes=0, falhas=0)
        return desafiar(passo, analise, notas, agora)

    @app.post("/api/reconhecer")
    def reconhecer():
        if galeria.vazia:
            return jsonify(estado="sem_cadastros")
        totem_id = (request.headers.get("X-Totem") or request.remote_addr or "?")[:40]
        analise = motor.analisar(request.get_data(cache=False))
        agora = time.monotonic()

        with trava_totens:
            if len(totens) > 200:
                totens.clear()
            passo = totens.get(totem_id)
            if passo is None or agora - passo["visto"] > 3:  # totem novo ou parado há um tempo
                passo = {"fase": "identificando", "chave": None, "n": 0}
            passo["visto"] = agora
            resposta = avancar(passo, analise, agora)
            if resposta.pop("final", False):
                totens.pop(totem_id, None)
            else:
                totens[totem_id] = passo
        return jsonify(resposta)

    # ------------------------------------------------------------------ entrada no painel
    @app.get("/api/sessao")
    def sessao():
        return jsonify(
            configurado=banco.config("senha_hash") is not None,
            dentro=bool(session.get("admin")),
        )

    @app.post("/api/criar-senha")
    def criar_senha():
        if banco.config("senha_hash") is not None:
            return erro("A senha do painel já foi criada.", 409)
        senha = str((request.get_json(silent=True) or {}).get("senha", ""))
        if len(senha) < 8:
            return erro("Use uma senha com pelo menos 8 caracteres.")
        banco.definir_config("senha_hash", generate_password_hash(senha))
        abrir_sessao()
        return jsonify(ok=True)

    @app.post("/api/entrar")
    def entrar():
        espera = falhas_senha["ate"] - time.time()
        if espera > 0:
            return erro(f"Muitas tentativas. Aguarde {int(espera) + 1} segundos.", 429)
        senha = str((request.get_json(silent=True) or {}).get("senha", ""))
        guardada = banco.config("senha_hash")
        if not guardada or not check_password_hash(guardada, senha):
            falhas_senha["n"] += 1
            if falhas_senha["n"] >= MAX_TENTATIVAS_SENHA:
                falhas_senha.update(n=0, ate=time.time() + BLOQUEIO_SENHA_S)
            return erro("Senha incorreta.", 401)
        falhas_senha.update(n=0, ate=0.0)
        abrir_sessao()
        return jsonify(ok=True)

    @app.post("/api/sair")
    def sair():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/trocar-senha")
    @exige_admin
    def trocar_senha():
        dados = request.get_json(silent=True) or {}
        if not check_password_hash(banco.config("senha_hash"), str(dados.get("atual", ""))):
            return erro("A senha atual não confere.", 401)
        nova = str(dados.get("nova", ""))
        if len(nova) < 8:
            return erro("Use uma senha com pelo menos 8 caracteres.")
        banco.definir_config("senha_hash", generate_password_hash(nova))
        return jsonify(ok=True)

    # ------------------------------------------------------------------ alunos
    @app.get("/api/alunos")
    @exige_admin
    def listar_alunos():
        return jsonify(alunos=[aluno_json(a) for a in banco.listar_alunos(request.args.get("busca", ""))])

    @app.post("/api/alunos")
    @exige_admin
    def criar_aluno():
        campos, problema = ler_aluno_do_pedido()
        if problema:
            return erro(problema)
        try:
            novo_id = banco.criar_aluno(*campos)
        except sqlite3.IntegrityError:
            return erro("Já existe um aluno com essa matrícula.", 409)
        return jsonify(aluno=aluno_json(banco.aluno(novo_id))), 201

    @app.put("/api/alunos/<int:aluno_id>")
    @exige_admin
    def atualizar_aluno(aluno_id: int):
        if banco.aluno(aluno_id) is None:
            return erro("Aluno não encontrado.", 404)
        campos, problema = ler_aluno_do_pedido()
        if problema:
            return erro(problema)
        try:
            banco.atualizar_aluno(aluno_id, *campos)
        except sqlite3.IntegrityError:
            return erro("Já existe um aluno com essa matrícula.", 409)
        return jsonify(aluno=aluno_json(banco.aluno(aluno_id)))

    @app.delete("/api/alunos/<int:aluno_id>")
    @exige_admin
    def excluir_aluno(aluno_id: int):
        banco.excluir_aluno(aluno_id)
        galeria.carregar(banco.todas_amostras())
        return jsonify(ok=True)

    @app.post("/api/alunos/<int:aluno_id>/liberar")
    @exige_admin
    def liberar_manual(aluno_id: int):
        """A recepção libera a entrada sem o rosto (aluno sem cadastro facial, câmera com problema etc.)."""
        aluno = banco.aluno(aluno_id)
        if aluno is None:
            return erro("Aluno não encontrado.", 404)
        banco.registrar_acesso(aluno, "liberado_manual", 0.0, intervalo_s=5)
        catraca.liberar()
        return jsonify(aluno=aluno_json(banco.aluno(aluno_id)))

    # --- importação por planilha (CSV)
    def sem_acento(texto: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", texto.lower().strip()) if not unicodedata.combining(c))

    COLUNAS = {
        "nome": "nome", "aluno": "nome", "nome completo": "nome",
        "matricula": "matricula", "codigo": "matricula",
        "validade": "validade", "plano_validade": "validade", "vencimento": "validade",
        "plano valido ate": "validade", "valido ate": "validade",
    }

    def ler_data(texto: str) -> str | None:
        texto = texto.strip()
        if not texto:
            return None
        for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(texto, formato).date().isoformat()
            except ValueError:
                pass
        raise ValueError(f'Não entendi a data "{texto}". Use dia/mês/ano, como 31/12/2026.')

    @app.post("/api/alunos/importar")
    @exige_admin
    def importar_alunos():
        bruto = request.get_data(cache=False)
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("cp1252", errors="replace")  # planilha salva pelo Excel antigo
        linhas = texto.splitlines()
        if not linhas:
            return erro("O arquivo está vazio.")
        separador = max(";,\t", key=linhas[0].count)
        leitor = csv.reader(linhas, delimiter=separador)
        cabecalho = [COLUNAS.get(sem_acento(c)) for c in next(leitor)]
        if "nome" not in cabecalho or "matricula" not in cabecalho:
            return erro('A primeira linha precisa ter as colunas "nome" e "matricula" (e, se quiser, "validade").')

        criados = atualizados = 0
        problemas = []
        for numero, celulas in enumerate(leitor, start=2):
            if numero > MAX_LINHAS_IMPORTACAO + 1:
                problemas.append({"linha": numero, "motivo": f"O limite é de {MAX_LINHAS_IMPORTACAO} linhas por arquivo."})
                break
            if not any(c.strip() for c in celulas):
                continue
            linha = {coluna: valor for coluna, valor in zip(cabecalho, celulas) if coluna}
            try:
                nome, matricula, validade = validar_aluno(
                    linha.get("nome"), linha.get("matricula"), ler_data(linha.get("validade", "")))
            except ValueError as problema:
                problemas.append({"linha": numero, "motivo": str(problema)})
                continue
            existente = banco.aluno_por_matricula(matricula)
            if existente:
                if "validade" not in cabecalho:
                    validade = existente["plano_validade"]
                banco.atualizar_aluno(existente["id"], nome, matricula, validade, bool(existente["ativo"]))
                atualizados += 1
            else:
                banco.criar_aluno(nome, matricula, validade, True)
                criados += 1
        return jsonify(criados=criados, atualizados=atualizados, problemas=problemas[:50],
                       total_problemas=len(problemas))

    @app.get("/api/alunos/modelo.csv")
    @exige_admin
    def modelo_importacao():
        exemplo = "nome;matricula;validade\r\nMaria Exemplo da Silva;1001;31/12/2026\r\nJoão Exemplo Souza;1002;\r\n"
        return Response("﻿" + exemplo, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="modelo-alunos.csv"'})

    # ------------------------------------------------------------------ rosto do aluno
    @app.post("/api/alunos/<int:aluno_id>/rosto")
    @exige_admin
    def adicionar_rosto(aluno_id: int):
        aluno = banco.aluno(aluno_id)
        if aluno is None:
            return erro("Aluno não encontrado.", 404)
        if not aluno["consentimento_em"] and request.args.get("autorizado") != "1":
            return erro("Confirme que o aluno autorizou o uso do rosto.")
        if aluno["amostras"] >= MAX_AMOSTRAS:
            return jsonify(aceita=False, motivo="limite", total=aluno["amostras"])

        analise = motor.analisar(request.get_data(cache=False), cadastro=True)
        if analise.status != "ok":
            return jsonify(aceita=False, motivo=analise.status, total=aluno["amostras"])

        notas = galeria.semelhancas(analise.vetor)
        propria = notas.pop(aluno_id, None)
        if notas:
            outro_id, outra_nota = max(notas.items(), key=lambda par: par[1])
            if outra_nota >= limiar():
                outro = banco.aluno(outro_id)
                return jsonify(aceita=False, motivo="duplicado", total=aluno["amostras"],
                               outro=outro["nome"] if outro else "outro aluno")
        if propria is not None and propria < limiar():
            return jsonify(aceita=False, motivo="rosto_diferente", total=aluno["amostras"])

        if not aluno["consentimento_em"]:
            banco.registrar_consentimento(aluno_id)
        total = banco.adicionar_amostra(aluno_id, analise.vetor.astype("float32").tobytes())
        galeria.carregar(banco.todas_amostras())
        return jsonify(aceita=True, total=total)

    @app.delete("/api/alunos/<int:aluno_id>/rosto")
    @exige_admin
    def excluir_rosto(aluno_id: int):
        banco.excluir_amostras(aluno_id)
        galeria.carregar(banco.todas_amostras())
        return jsonify(ok=True)

    # ------------------------------------------------------------------ histórico
    NOMES_RESULTADO = {
        "liberado": "Liberado pelo rosto",
        "liberado_manual": "Liberado pela recepção",
        "plano_vencido": "Barrado: plano vencido",
        "bloqueado": "Barrado: entrada bloqueada",
    }

    def dia_pedido() -> str:
        dia = request.args.get("dia") or date.today().isoformat()
        try:
            return date.fromisoformat(dia).isoformat()
        except ValueError:
            return date.today().isoformat()

    @app.get("/api/acessos")
    @exige_admin
    def listar_acessos():
        dia = dia_pedido()
        linhas = banco.listar_acessos(dia)
        return jsonify(
            dia=dia,
            acessos=[{"hora": l["momento"][11:16], "nome": l["nome"], "matricula": l["matricula"],
                      "resultado": l["resultado"]} for l in linhas],
            liberados=sum(1 for l in linhas if l["resultado"].startswith("liberado")),
            barrados=sum(1 for l in linhas if not l["resultado"].startswith("liberado")),
        )

    @app.get("/api/acessos.csv")
    @exige_admin
    def exportar_acessos():
        dia = dia_pedido()
        saida = io.StringIO()
        planilha = csv.writer(saida, delimiter=";")
        planilha.writerow(["Data", "Hora", "Nome", "Matrícula", "Resultado"])
        for l in reversed(banco.listar_acessos(dia)):
            momento = datetime.strptime(l["momento"], "%Y-%m-%d %H:%M:%S")
            # O apóstrofo impede que o Excel trate o texto como fórmula.
            seguro = [("'" + v) if v[:1] in "=+-@" else v for v in (l["nome"], l["matricula"])]
            planilha.writerow([momento.strftime("%d/%m/%Y"), momento.strftime("%H:%M:%S"), *seguro,
                               NOMES_RESULTADO.get(l["resultado"], l["resultado"])])
        return Response(
            "﻿" + saida.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="acessos-{dia}.csv"'},
        )

    # ------------------------------------------------------------------ ajustes
    def ajustes_json() -> dict:
        return {
            "limiar": limiar(),
            "nome_academia": banco.config("nome_academia"),
            "prova_de_vida": prova_de_vida_ligada(),
            "catraca_url": banco.config("catraca_url"),
            "catraca_ultimo": catraca.ultimo,
        }

    @app.get("/api/ajustes")
    @exige_admin
    def ver_ajustes():
        return jsonify(ajustes_json())

    @app.put("/api/ajustes")
    @exige_admin
    def salvar_ajustes():
        dados = request.get_json(silent=True) or {}
        try:
            novo_limiar = float(dados.get("limiar", limiar()))
        except (TypeError, ValueError):
            return erro("Valor de rigor inválido.")
        if not 0.30 <= novo_limiar <= 0.70:
            return erro("O rigor precisa ficar entre 0,30 e 0,70.")
        nome = " ".join(str(dados.get("nome_academia", "")).split())[:60]
        if not nome:
            return erro("Informe o nome da academia.")
        url = str(dados.get("catraca_url", banco.config("catraca_url")) or "").strip()
        if url and not endereco_valido(url):
            return erro("O endereço da catraca precisa começar com http:// ou https://.")
        banco.definir_config("limiar", f"{novo_limiar:.2f}")
        banco.definir_config("nome_academia", nome)
        banco.definir_config("catraca_url", url)
        if "prova_de_vida" in dados:
            banco.definir_config("prova_de_vida", "1" if dados["prova_de_vida"] else "0")
        return jsonify(ajustes_json())

    @app.post("/api/catraca/testar")
    @exige_admin
    def testar_catraca():
        url = str((request.get_json(silent=True) or {}).get("catraca_url", "")).strip()
        if not url:
            return erro("Informe o endereço do equipamento para testar.")
        if not endereco_valido(url):
            return erro("O endereço da catraca precisa começar com http:// ou https://.")
        return jsonify(catraca.acionar(url))

    return app


def porta_livre(endereco: str, porta: int) -> bool:
    familia = socket.AF_INET6 if ":" in endereco else socket.AF_INET
    try:
        with socket.socket(familia, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((endereco, porta))
        return True
    except OSError:
        return False


def enderecos_na_rede() -> list[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return [s.getsockname()[0]]
    except OSError:
        return []


if __name__ == "__main__":
    opcoes = argparse.ArgumentParser(description="Acesso por reconhecimento facial para academia")
    opcoes.add_argument("--rede", action="store_true",
                        help="aceita tablets e outros aparelhos da mesma rede (liga HTTPS)")
    opcoes.add_argument("--porta", type=int, default=5050)
    opcoes.add_argument("--sem-navegador", action="store_true",
                        help="não abre o navegador sozinho ao iniciar")
    args = opcoes.parse_args()

    if not porta_livre("0.0.0.0" if args.rede else "127.0.0.1", args.porta):
        raise SystemExit(
            f"\n  A porta {args.porta} já está em uso. Se o programa já está aberto em outra janela,\n"
            f"  use aquela ou feche-a. Para usar outra porta, acrescente --porta {args.porta + 1} ao comando.\n"
        )

    app = criar_app()
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # não enche a tela com cada leitura
    print("\n  Acesso facial da academia no ar. Para encerrar, aperte Ctrl + C.\n")
    if args.rede:
        app.config["SESSION_COOKIE_SECURE"] = True
        for ip in enderecos_na_rede():
            print(f"  No tablet, abra:   https://{ip}:{args.porta}")
        print(f"  Neste computador:  https://localhost:{args.porta}")
        print("  O navegador vai avisar sobre o certificado: escolha Avançado > Continuar.\n")
        app.run(host="0.0.0.0", port=args.porta, ssl_context="adhoc", threaded=True)
    else:
        print(f"  Totem da entrada:  http://localhost:{args.porta}")
        print(f"  Painel:            http://localhost:{args.porta}/painel\n")
        if not args.sem_navegador:
            threading.Timer(1.5, webbrowser.open, [f"http://localhost:{args.porta}"]).start()
        try:
            from waitress import serve  # servidor próprio para uso contínuo
        except ImportError:
            app.run(host="127.0.0.1", port=args.porta, threaded=True)
        else:
            # Atende em IPv4 e, se der, em IPv6, para "localhost" funcionar em qualquer navegador.
            enderecos = f"127.0.0.1:{args.porta}"
            if porta_livre("::1", args.porta):
                enderecos += f" [::1]:{args.porta}"
            serve(app, listen=enderecos, threads=8, ident=None)
