"""Acionamento da catraca (ou da trava da porta).

Sem endereço configurado, a liberação é só simulada: aparece na tela do totem e
no histórico. Com um endereço em Ajustes, o sistema chama esse endereço pela rede
a cada entrada liberada. É assim que se acionam relés de rede e placas
controladoras que aceitam um comando por HTTP, por exemplo:

    http://192.168.0.50/relay/0?turn=on&timer=3

Para um equipamento que usa outro protocolo (porta serial, SDK do fabricante),
troque o conteúdo de `_acionar`.
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from datetime import datetime

TEMPO_LIMITE_S = 3


def endereco_valido(url: str) -> bool:
    return len(url) <= 300 and url.startswith(("http://", "https://")) and " " not in url


class Catraca:
    def __init__(self, obter_endereco):
        self._obter_endereco = obter_endereco
        self.ultimo: dict | None = None   # resultado do último acionamento

    def liberar(self) -> None:
        """Libera a passagem sem fazer o totem esperar pela resposta do equipamento."""
        url = self._obter_endereco()
        if not url:
            self.ultimo = {"quando": _agora(), "ok": True, "detalhe": "Simulada (nenhum equipamento configurado)."}
            return
        threading.Thread(target=self.acionar, args=(url,), daemon=True).start()

    def acionar(self, url: str) -> dict:
        ok, detalhe = self._acionar(url)
        self.ultimo = {"quando": _agora(), "ok": ok, "detalhe": detalhe}
        return self.ultimo

    @staticmethod
    def _acionar(url: str) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(url, timeout=TEMPO_LIMITE_S) as resposta:
                return True, f"O equipamento respondeu (código {resposta.status})."
        except urllib.error.HTTPError as erro:
            return False, f"O equipamento recusou o comando (código {erro.code})."
        except Exception:  # sem rede, endereço errado, tempo esgotado
            return False, "Sem resposta do equipamento. Confira o endereço e se ele está ligado na mesma rede."


def _agora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
