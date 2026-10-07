"""Motor de reconhecimento facial.

Usa dois modelos abertos do OpenCV:
  - YuNet: encontra o rosto na imagem;
  - SFace: transforma o rosto em 128 números (o "vetor").

Dois vetores da mesma pessoa ficam parecidos; a semelhança vai de -1 a 1.
Nenhuma foto é guardada: só os vetores.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np

cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)

LADO_MAXIMO = 640          # a imagem é reduzida até este tamanho antes de analisar
CONFIANCA_DETECCAO = 0.85  # certeza mínima de que aquilo é um rosto
LARGURA_MIN_TOTEM = 70     # rosto menor que isso (em pixels) = pessoa longe demais
LARGURA_MIN_CADASTRO = 110 # no cadastro exigimos o rosto maior, para mais qualidade
BRILHO_MINIMO = 45         # média de 0 (preto) a 255 (branco)


@dataclass
class Analise:
    status: str                      # ok | imagem_invalida | sem_rosto | longe | escuro | varios_rostos
    vetor: np.ndarray | None = None  # 128 números, já normalizados
    rostos: int = 0
    # Medidas usadas na prova de vida (ver pose_do_rosto):
    giro: float = 0.0        # 0 = de frente; cresce quando a pessoa vira o rosto para um lado
    proporcao: float = 1.0   # distância entre os olhos dividida pela altura olhos-boca
    altura: float = 0.0      # altura olhos-boca, em pixels


def pose_do_rosto(rosto) -> tuple[float, float, float]:
    """Mede a pose a partir dos 5 pontos que o detector devolve (olhos, nariz, cantos da boca).

    Num rosto de verdade o nariz fica à frente dos olhos, então ao virar a cabeça
    ele se desloca para um lado. Numa foto, que é plana, isso não acontece: inclinar
    a foto só "achata" o rosto. É essa diferença que a prova de vida explora.
    """
    olho_d, olho_e, nariz, boca_d, boca_e = (
        np.array(rosto[4 + 2 * i: 6 + 2 * i], np.float32) for i in range(5)
    )
    eixo = olho_e - olho_d
    entre_olhos = float(np.linalg.norm(eixo)) or 1.0
    centro = (olho_d + olho_e + boca_d + boca_e) / 4
    altura = float(np.linalg.norm((olho_d + olho_e) / 2 - (boca_d + boca_e) / 2)) or 1.0
    giro = float(np.dot(nariz - centro, eixo / entre_olhos) / entre_olhos)
    return giro, entre_olhos / altura, altura


class MotorFacial:
    def __init__(self, caminho_detector: str, caminho_reconhecedor: str):
        self._detector = cv2.FaceDetectorYN.create(
            caminho_detector, "", (320, 320), CONFIANCA_DETECCAO, 0.3, 5000
        )
        self._reconhecedor = cv2.FaceRecognizerSF.create(caminho_reconhecedor, "")
        self._trava = threading.Lock()  # os modelos não aceitam chamadas simultâneas

    def analisar(self, jpeg: bytes, cadastro: bool = False) -> Analise:
        """Recebe uma foto (JPEG ou PNG) e devolve o vetor do rosto principal."""
        if not jpeg:
            return Analise("imagem_invalida")
        imagem = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if imagem is None or imagem.ndim != 3:
            return Analise("imagem_invalida")

        altura, largura = imagem.shape[:2]
        escala = LADO_MAXIMO / max(altura, largura)
        if escala < 1:
            imagem = cv2.resize(imagem, (round(largura * escala), round(altura * escala)))
            altura, largura = imagem.shape[:2]

        with self._trava:
            self._detector.setInputSize((largura, altura))
            _, rostos = self._detector.detect(imagem)
            if rostos is None or len(rostos) == 0:
                return Analise("sem_rosto")

            # Fica com o maior rosto: é quem está mais perto da câmera.
            rostos = sorted(rostos, key=lambda r: r[2] * r[3], reverse=True)
            principal = rostos[0]
            largura_rosto = float(principal[2])

            if cadastro and len(rostos) > 1 and rostos[1][2] > 0.5 * largura_rosto:
                return Analise("varios_rostos", rostos=len(rostos))
            if largura_rosto < (LARGURA_MIN_CADASTRO if cadastro else LARGURA_MIN_TOTEM):
                return Analise("longe", rostos=len(rostos))

            recorte = self._reconhecedor.alignCrop(imagem, principal)
            if float(cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY).mean()) < BRILHO_MINIMO:
                return Analise("escuro", rostos=len(rostos))
            vetor = self._reconhecedor.feature(recorte).flatten().astype(np.float32)

        norma = float(np.linalg.norm(vetor))
        if norma == 0:
            return Analise("sem_rosto")
        giro, proporcao, altura = pose_do_rosto(principal)
        return Analise("ok", vetor=vetor / norma, rostos=len(rostos),
                       giro=giro, proporcao=proporcao, altura=altura)


class Galeria:
    """Todos os vetores cadastrados, mantidos na memória para comparar rápido."""

    def __init__(self):
        self._trava = threading.Lock()
        self._vetores = np.zeros((0, 128), np.float32)
        self._ids = np.zeros((0,), np.int64)

    def carregar(self, linhas) -> None:
        vetores = [np.frombuffer(l["vetor"], np.float32) for l in linhas]
        ids = [l["aluno_id"] for l in linhas]
        with self._trava:
            self._vetores = np.vstack(vetores) if vetores else np.zeros((0, 128), np.float32)
            self._ids = np.array(ids, np.int64)

    @property
    def vazia(self) -> bool:
        return len(self._ids) == 0

    def semelhancas(self, vetor: np.ndarray) -> dict[int, float]:
        """Melhor semelhança do vetor com cada aluno cadastrado."""
        with self._trava:
            if len(self._ids) == 0:
                return {}
            notas = self._vetores @ vetor
            melhores: dict[int, float] = {}
            for aluno_id, nota in zip(self._ids.tolist(), notas.tolist()):
                if nota > melhores.get(aluno_id, -2.0):
                    melhores[aluno_id] = nota
            return melhores

    def identificar(self, vetor: np.ndarray) -> tuple[int | None, float, float]:
        """Devolve (aluno mais parecido, semelhança dele, semelhança do segundo colocado)."""
        ordem = sorted(self.semelhancas(vetor).items(), key=lambda par: par[1], reverse=True)
        if not ordem:
            return None, -1.0, -1.0
        segundo = ordem[1][1] if len(ordem) > 1 else -1.0
        return ordem[0][0], ordem[0][1], segundo
