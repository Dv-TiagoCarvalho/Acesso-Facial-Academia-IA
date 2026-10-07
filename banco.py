"""Banco de dados (SQLite) do sistema de acesso da academia.

Guarda alunos, as "impressões" numéricas do rosto (nunca a foto) e o
histórico de acessos. O arquivo fica em dados/academia.db.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS alunos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT NOT NULL,
    matricula        TEXT NOT NULL UNIQUE,
    plano_validade   TEXT,                 -- AAAA-MM-DD; vazio = sem vencimento
    ativo            INTEGER NOT NULL DEFAULT 1,
    consentimento_em TEXT,                 -- quando o aluno autorizou a biometria
    criado_em        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS amostras (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id  INTEGER NOT NULL REFERENCES alunos(id) ON DELETE CASCADE,
    vetor     BLOB NOT NULL,               -- 128 números (float32) que descrevem o rosto
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amostras_aluno ON amostras(aluno_id);

CREATE TABLE IF NOT EXISTS acessos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id  INTEGER REFERENCES alunos(id) ON DELETE SET NULL,
    nome      TEXT NOT NULL,
    matricula TEXT NOT NULL,
    resultado TEXT NOT NULL,               -- liberado | liberado_manual | plano_vencido | bloqueado
    semelhanca REAL,
    momento   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acessos_momento ON acessos(momento);

CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

PADROES = {
    "limiar": "0.42",
    "nome_academia": "Minha Academia",
    "prova_de_vida": "1",   # 1 = pede para o aluno virar o rosto antes de liberar
    "catraca_url": "",      # endereço chamado a cada entrada liberada (vazio = só na tela)
}


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Banco:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.conectar() as con:
            con.executescript(ESQUEMA)

    def conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.caminho, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        return con

    # ---------- configurações ----------
    def config(self, chave: str) -> str | None:
        with self.conectar() as con:
            linha = con.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
        return linha["valor"] if linha else PADROES.get(chave)

    def definir_config(self, chave: str, valor: str) -> None:
        with self.conectar() as con:
            con.execute(
                "INSERT INTO config (chave, valor) VALUES (?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                (chave, valor),
            )

    # ---------- alunos ----------
    _SELECAO_ALUNO = """
        SELECT a.*,
               (SELECT COUNT(*) FROM amostras m WHERE m.aluno_id = a.id) AS amostras,
               (SELECT MAX(x.momento) FROM acessos x
                 WHERE x.aluno_id = a.id AND x.resultado LIKE 'liberado%') AS ultimo_acesso
        FROM alunos a
    """

    def listar_alunos(self, busca: str = "") -> list[sqlite3.Row]:
        termo = f"%{busca.strip()}%"
        with self.conectar() as con:
            return con.execute(
                self._SELECAO_ALUNO + " WHERE a.nome LIKE ? OR a.matricula LIKE ? ORDER BY a.nome COLLATE NOCASE",
                (termo, termo),
            ).fetchall()

    def aluno(self, aluno_id: int) -> sqlite3.Row | None:
        with self.conectar() as con:
            return con.execute(self._SELECAO_ALUNO + " WHERE a.id = ?", (aluno_id,)).fetchone()

    def aluno_por_matricula(self, matricula: str) -> sqlite3.Row | None:
        with self.conectar() as con:
            return con.execute(self._SELECAO_ALUNO + " WHERE a.matricula = ?", (matricula,)).fetchone()

    def criar_aluno(self, nome: str, matricula: str, validade: str | None, ativo: bool) -> int:
        with self.conectar() as con:
            cur = con.execute(
                "INSERT INTO alunos (nome, matricula, plano_validade, ativo, criado_em) VALUES (?, ?, ?, ?, ?)",
                (nome, matricula, validade, int(ativo), agora()),
            )
            return cur.lastrowid

    def atualizar_aluno(self, aluno_id: int, nome: str, matricula: str, validade: str | None, ativo: bool) -> None:
        with self.conectar() as con:
            con.execute(
                "UPDATE alunos SET nome = ?, matricula = ?, plano_validade = ?, ativo = ? WHERE id = ?",
                (nome, matricula, validade, int(ativo), aluno_id),
            )

    def excluir_aluno(self, aluno_id: int) -> None:
        with self.conectar() as con:
            con.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))

    def registrar_consentimento(self, aluno_id: int) -> None:
        with self.conectar() as con:
            con.execute("UPDATE alunos SET consentimento_em = ? WHERE id = ?", (agora(), aluno_id))

    # ---------- amostras do rosto ----------
    def adicionar_amostra(self, aluno_id: int, vetor: bytes) -> int:
        with self.conectar() as con:
            con.execute(
                "INSERT INTO amostras (aluno_id, vetor, criado_em) VALUES (?, ?, ?)",
                (aluno_id, vetor, agora()),
            )
            return con.execute(
                "SELECT COUNT(*) AS n FROM amostras WHERE aluno_id = ?", (aluno_id,)
            ).fetchone()["n"]

    def excluir_amostras(self, aluno_id: int) -> None:
        """Apaga a biometria do aluno e o registro da autorização."""
        with self.conectar() as con:
            con.execute("DELETE FROM amostras WHERE aluno_id = ?", (aluno_id,))
            con.execute("UPDATE alunos SET consentimento_em = NULL WHERE id = ?", (aluno_id,))

    def todas_amostras(self) -> list[sqlite3.Row]:
        with self.conectar() as con:
            return con.execute("SELECT aluno_id, vetor FROM amostras ORDER BY id").fetchall()

    # ---------- acessos ----------
    def registrar_acesso(self, aluno: sqlite3.Row, resultado: str, semelhanca: float, intervalo_s: int = 60) -> bool:
        """Grava a passagem. Ignora repetições do mesmo aluno dentro do intervalo."""
        with self.conectar() as con:
            ultimo = con.execute(
                "SELECT momento FROM acessos WHERE aluno_id = ? AND resultado = ? ORDER BY id DESC LIMIT 1",
                (aluno["id"], resultado),
            ).fetchone()
            if ultimo:
                passou = datetime.now() - datetime.strptime(ultimo["momento"], "%Y-%m-%d %H:%M:%S")
                if 0 <= passou.total_seconds() < intervalo_s:
                    return False
            con.execute(
                "INSERT INTO acessos (aluno_id, nome, matricula, resultado, semelhanca, momento) VALUES (?, ?, ?, ?, ?, ?)",
                (aluno["id"], aluno["nome"], aluno["matricula"], resultado, round(semelhanca, 3), agora()),
            )
            return True

    def listar_acessos(self, dia: str) -> list[sqlite3.Row]:
        with self.conectar() as con:
            return con.execute(
                "SELECT * FROM acessos WHERE momento >= ? AND momento < ? ORDER BY momento DESC, id DESC",
                (f"{dia} 00:00:00", f"{dia} 99"),
            ).fetchall()

    # ---------- cópia de segurança ----------
    def copia_de_seguranca(self, pasta: Path, manter: int = 14) -> Path | None:
        """Faz uma cópia do banco por dia e apaga as mais antigas que `manter` dias."""
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"academia-{datetime.now():%Y-%m-%d}.db"
        if destino.exists():
            return None
        temporario = destino.with_suffix(".copiando")
        origem = self.conectar()
        copia = sqlite3.connect(temporario)
        try:
            origem.backup(copia)
        finally:
            copia.close()
            origem.close()
        temporario.replace(destino)
        for antiga in sorted(pasta.glob("academia-*.db"))[:-manter]:
            antiga.unlink(missing_ok=True)
        return destino
