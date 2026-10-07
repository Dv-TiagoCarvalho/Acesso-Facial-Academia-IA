"""Baixa os dois modelos de reconhecimento facial na primeira execução.

São arquivos públicos do projeto OpenCV Zoo (licenças MIT e Apache 2.0).
O download é conferido por soma SHA-256 antes de ser usado.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"

MODELOS = {
    "detector": {
        "arquivo": "face_detection_yunet_2023mar.onnx",
        "url": f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "tamanho": "0,2 MB",
    },
    "reconhecedor": {
        "arquivo": "face_recognition_sface_2021dec.onnx",
        "url": f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "tamanho": "37 MB",
    },
}


def _sha256(caminho: Path) -> str:
    soma = hashlib.sha256()
    with open(caminho, "rb") as arq:
        for bloco in iter(lambda: arq.read(1 << 20), b""):
            soma.update(bloco)
    return soma.hexdigest()


def garantir_modelos(pasta: Path) -> dict[str, str]:
    """Confere se os modelos existem e estão íntegros; baixa o que faltar."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = {}
    for nome, info in MODELOS.items():
        destino = pasta / info["arquivo"]
        if not destino.exists() or _sha256(destino) != info["sha256"]:
            print(f"Baixando modelo ({info['tamanho']}): {info['arquivo']} ...", flush=True)
            temporario = destino.with_suffix(".baixando")
            try:
                urllib.request.urlretrieve(info["url"], temporario)
            except Exception as erro:  # sem internet, proxy, etc.
                temporario.unlink(missing_ok=True)
                sys.exit(
                    f"\nNão consegui baixar {info['arquivo']} ({erro}).\n"
                    f"Baixe manualmente em:\n  {info['url']}\n"
                    f"e salve na pasta:\n  {pasta}\n"
                )
            if _sha256(temporario) != info["sha256"]:
                temporario.unlink(missing_ok=True)
                sys.exit(f"\nO arquivo {info['arquivo']} chegou corrompido. Rode de novo para tentar outra vez.\n")
            temporario.replace(destino)
        caminhos[nome] = str(destino)
    return caminhos


if __name__ == "__main__":
    garantir_modelos(Path(__file__).parent / "models")
    print("Modelos prontos.")
