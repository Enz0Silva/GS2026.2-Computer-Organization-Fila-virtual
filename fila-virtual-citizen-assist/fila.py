"""Núcleo da fila virtual: estado, regras e registro dos eventos.

Dois botões mudam o estado:
- CHEGADA: a pessoa pega uma senha e entra no fim da fila;
- CONCLUSÃO: um atendente termina um atendimento.

Com ATENDENTES guichês, as primeiras pessoas da fila estão sendo atendidas e
as demais aguardam. Quando um atendimento termina, a próxima senha é chamada
automaticamente. Assim, só com os dois botões, o sistema mede:
- a espera real de cada pessoa (chamada - chegada);
- a duração de cada atendimento (conclusão - chamada).

Regras que impedem estados inválidos:
- concluir com a fila vazia é recusado (a contagem nunca fica negativa);
- depois de LIMITE_SENHAS_DIA senhas, novas chegadas são recusadas;
- todas as operações passam por um Lock, porque o servidor atende vários
  pedidos ao mesmo tempo (dois cliques simultâneos não corrompem a contagem).
"""
import csv
import threading
from collections import deque
from datetime import datetime

from config import ARQ_ATENDIMENTOS, ARQ_EVENTOS, ATENDENTES, LIMITE_SENHAS_DIA

CAMPOS_EVENTOS = ["data_hora", "evento", "senha", "aguardando", "em_atendimento",
                  "atendidos", "detalhe"]
CAMPOS_ATENDIMENTOS = ["origem", "data", "senha", "hora_chegada", "pessoas_na_frente",
                       "atendentes_ativos", "espera_min", "duracao_atendimento_min"]


class OperacaoInvalida(Exception):
    """Pedido recusado por uma regra da fila (fila vazia, limite de senhas)."""


class FilaVirtual:
    def __init__(self, atendentes=ATENDENTES, limite_senhas=LIMITE_SENHAS_DIA,
                 arq_eventos=ARQ_EVENTOS, arq_atendimentos=ARQ_ATENDIMENTOS,
                 relogio=datetime.now):
        self.atendentes = atendentes
        self.limite_senhas = limite_senhas
        self.arq_eventos = arq_eventos
        self.arq_atendimentos = arq_atendimentos
        self.relogio = relogio              # trocável nos testes
        self._trava = threading.Lock()
        self.fila = deque()                 # cada item: dict da pessoa
        self.proxima_senha = 1
        self.atendidos = 0
        self.ultimos_eventos = deque(maxlen=20)
        self.ao_concluir = []               # funções chamadas com cada atendimento medido

    # ---------- consultas ----------
    def em_atendimento(self):
        return min(len(self.fila), self.atendentes)

    def aguardando(self):
        return max(0, len(self.fila) - self.atendentes)

    def senhas_restantes(self):
        return max(0, self.limite_senhas - (self.proxima_senha - 1))

    def estado(self):
        with self._trava:
            return {
                "na_fila": self.aguardando(),
                "em_atendimento": self.em_atendimento(),
                "total_no_posto": len(self.fila),
                "atendidos": self.atendidos,
                "senhas_emitidas": self.proxima_senha - 1,
                "senhas_restantes": self.senhas_restantes(),
                "atendentes": self.atendentes,
                "senhas_aguardando": [p["senha"] for p in list(self.fila)[self.atendentes:]],
                "senhas_em_atendimento": [p["senha"] for p in list(self.fila)[:self.atendentes]],
                "ultimos_eventos": list(self.ultimos_eventos),
            }

    # ---------- botões ----------
    def chegada(self):
        with self._trava:
            agora = self.relogio()
            if self.proxima_senha > self.limite_senhas:
                self._registrar(agora, "RECUSADO", "", "limite de senhas do dia atingido")
                raise OperacaoInvalida(
                    f"As {self.limite_senhas} senhas de hoje já foram distribuídas.")
            pessoa = {"senha": self.proxima_senha, "chegada": agora,
                      "pessoas_na_frente": len(self.fila), "chamada": None}
            self.proxima_senha += 1
            self.fila.append(pessoa)
            self._registrar(agora, "CHEGADA", pessoa["senha"],
                            f"{pessoa['pessoas_na_frente']} pessoa(s) à frente")
            if len(self.fila) <= self.atendentes:      # guichê livre: chamada imediata
                self._chamar(pessoa, agora)
            return dict(pessoa)

    def concluir(self):
        with self._trava:
            agora = self.relogio()
            if not self.fila:
                self._registrar(agora, "RECUSADO", "", "conclusão com a fila vazia")
                raise OperacaoInvalida("Não há ninguém sendo atendido: a fila está vazia.")
            pessoa = self.fila.popleft()              # quem foi chamado primeiro termina primeiro
            self.atendidos += 1
            duracao = (agora - pessoa["chamada"]).total_seconds() / 60
            espera = (pessoa["chamada"] - pessoa["chegada"]).total_seconds() / 60
            self._registrar(agora, "CONCLUSAO", pessoa["senha"],
                            f"esperou {espera:.1f} min; atendimento de {duracao:.1f} min")
            if len(self.fila) >= self.atendentes:     # o guichê liberado chama a próxima
                self._chamar(self.fila[self.atendentes - 1], agora)
            medido = {
                "origem": "PROTOTIPO",
                "data": pessoa["chegada"].date().isoformat(),
                "senha": pessoa["senha"],
                "hora_chegada": pessoa["chegada"].strftime("%H:%M:%S"),
                "pessoas_na_frente": pessoa["pessoas_na_frente"],
                "atendentes_ativos": self.atendentes,
                "espera_min": round(espera, 2),
                "duracao_atendimento_min": round(duracao, 2),
            }
            self._gravar_csv(self.arq_atendimentos, CAMPOS_ATENDIMENTOS, medido)
        for funcao in self.ao_concluir:               # fora da trava: re-treino do modelo
            funcao(medido)
        return medido

    # ---------- internos ----------
    def _chamar(self, pessoa, agora):
        pessoa["chamada"] = agora
        self._registrar(agora, "CHAMADA", pessoa["senha"], "senha chamada ao guichê")

    def _registrar(self, agora, evento, senha, detalhe):
        linha = {"data_hora": agora.strftime("%Y-%m-%d %H:%M:%S"), "evento": evento,
                 "senha": senha, "aguardando": self.aguardando(),
                 "em_atendimento": self.em_atendimento(), "atendidos": self.atendidos,
                 "detalhe": detalhe}
        self.ultimos_eventos.appendleft(linha)
        self._gravar_csv(self.arq_eventos, CAMPOS_EVENTOS, linha)

    @staticmethod
    def _gravar_csv(caminho, campos, linha):
        if caminho is None:
            return
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            novo = not caminho.exists() or caminho.stat().st_size == 0
            with open(caminho, "a", newline="", encoding="utf-8") as arquivo:
                escritor = csv.DictWriter(arquivo, fieldnames=campos)
                if novo:
                    escritor.writeheader()
                escritor.writerow(linha)
        except OSError:
            pass        # sem disco, a fila continua funcionando em memória
