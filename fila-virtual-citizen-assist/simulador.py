"""Gera o histórico SIMULADO de dias de mutirão usado para treinar a previsão.

ATENÇÃO: estes dados são SIMULADOS (o briefing permite, desde que identificados).
Toda linha do CSV tem origem = SIMULADO e o arquivo se chama historico_simulado.csv.

Como a simulação funciona (simulação de eventos discretos, minuto a minuto):
- 16 dias de mutirão (8 semanas, terça e quinta), das 9h às 15h;
- até 40 senhas por dia; a chegada é mais forte na abertura (fila na porta);
- 2 atendentes; das 12h às 13h um deles sai para o almoço;
- tempo de atendimento sorteado de uma distribuição lognormal com média de
  cerca de 11 minutos (há atendimentos rápidos e alguns bem longos);
- 8% das senhas chamadas não aparecem (a pessoa desistiu): o atendente chama,
  espera 1 minuto e conclui. Premissa declarada, comum em filas com senha.

Para cada pessoa gravamos o que o sistema saberia NA HORA DA CHEGADA
(pessoas à frente, atendentes ativos) e o que aconteceu depois (espera real).
É com isso que comparamos a média histórica e a regressão linear.

Uso: python simulador.py
"""
import csv
import math
import random
from datetime import date, datetime, timedelta

from config import ARQ_HISTORICO_SIMULADO, ATENDENTES, LIMITE_SENHAS_DIA

SEMENTE = 2026          # mesma semente = mesmos dados (reprodutível)
DIAS = 16
ABERTURA, FECHAMENTO = 9 * 60, 15 * 60          # minutos do dia
ALMOCO_INICIO, ALMOCO_FIM = 12 * 60, 13 * 60
MEDIA_ATENDIMENTO_MIN = 11.0
DESVIO_LOG = 0.45
PROB_AUSENTE = 0.08


def dias_de_mutirao(inicio=date(2026, 9, 1), quantidade=DIAS):
    """Terças (1) e quintas (3) a partir de uma data."""
    dias, d = [], inicio
    while len(dias) < quantidade:
        if d.weekday() in (1, 3):
            dias.append(d)
        d += timedelta(days=1)
    return dias


def atendentes_no_minuto(minuto):
    return ATENDENTES - 1 if ALMOCO_INICIO <= minuto < ALMOCO_FIM else ATENDENTES


def sortear_chegadas(rng):
    """Minutos de chegada das pessoas do dia (no máximo 40 senhas)."""
    chegadas = []
    # 10 a 16 pessoas já esperando na abertura, chegando entre 8h40 e 9h
    for _ in range(rng.randint(10, 16)):
        chegadas.append(ABERTURA)
    minuto = ABERTURA
    while minuto < FECHAMENTO - 30 and len(chegadas) < LIMITE_SENHAS_DIA:
        taxa = 1 / 7 if minuto < 11 * 60 else 1 / 12       # pessoas por minuto
        minuto += rng.expovariate(taxa)
        if minuto < FECHAMENTO - 30:
            chegadas.append(int(minuto))
    return sorted(chegadas[:LIMITE_SENHAS_DIA])


def sortear_duracao(rng):
    if rng.random() < PROB_AUSENTE:
        return 1                     # senha chamada e ausente
    mu = math.log(MEDIA_ATENDIMENTO_MIN) - DESVIO_LOG ** 2 / 2
    return max(2, round(rng.lognormvariate(mu, DESVIO_LOG)))


def simular_dia(dia, rng):
    chegadas = sortear_chegadas(rng)
    duracoes = [sortear_duracao(rng) for _ in chegadas]
    guiches_livres_em = [ABERTURA] * ATENDENTES     # minuto em que cada guichê fica livre
    inicio, fim = [None] * len(chegadas), [None] * len(chegadas)
    registros = []

    for i, chegada in enumerate(chegadas):
        # quantas pessoas estão no sistema (esperando ou sendo atendidas) quando i chega
        na_frente = sum(1 for j in range(i) if fim[j] is None or fim[j] > chegada)
        # escolhe o guichê que fica livre primeiro; o guichê 2 fecha no almoço
        while True:
            g = min(range(ATENDENTES), key=lambda k: guiches_livres_em[k])
            t = max(chegada, guiches_livres_em[g])
            if g == ATENDENTES - 1 and ALMOCO_INICIO <= t < ALMOCO_FIM:
                guiches_livres_em[g] = ALMOCO_FIM
                continue
            break
        inicio[i] = t
        fim[i] = t + duracoes[i]
        guiches_livres_em[g] = fim[i]
        registros.append({
            "origem": "SIMULADO",
            "data": dia.isoformat(),
            "senha": i + 1,
            "hora_chegada": f"{chegada // 60:02d}:{chegada % 60:02d}",
            "pessoas_na_frente": na_frente,
            "atendentes_ativos": atendentes_no_minuto(chegada),
            "espera_min": t - chegada,
            "duracao_atendimento_min": duracoes[i],
        })
    return registros


def gerar(caminho=ARQ_HISTORICO_SIMULADO, semente=SEMENTE):
    rng = random.Random(semente)
    linhas = []
    for dia in dias_de_mutirao():
        linhas.extend(simular_dia(dia, rng))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)
    return linhas


if __name__ == "__main__":
    linhas = gerar()
    print(f"{len(linhas)} atendimentos SIMULADOS em {DIAS} dias gravados em "
          f"{ARQ_HISTORICO_SIMULADO.name} ({datetime.now():%d/%m/%Y %H:%M}).")
