"""Configuração da fila virtual do mutirão (um lugar só para as decisões).

Cenário: mutirão de orientação sobre apostas e dívidas no Posto Cidadão Centro
de Vila Aurora (município fictício do projeto Citizen Assist AI), terças e
quintas, das 9h às 15h, com até 40 senhas por dia (Comunicado nº 18/2026, DOC02
da base documental de Prompt and AI).
"""
from pathlib import Path

POSTO = "Posto Cidadão Centro — mutirão de orientação sobre apostas e dívidas"
HORARIO = "terças e quintas, das 9h às 15h"
LIMITE_SENHAS_DIA = 40          # o comunicado distribui até 40 senhas por dia
ATENDENTES = 2                  # guichês atendendo ao mesmo tempo

PASTA_DADOS = Path(__file__).resolve().parent / "dados"
ARQ_EVENTOS = PASTA_DADOS / "eventos.csv"                    # log de todos os eventos
ARQ_ATENDIMENTOS = PASTA_DADOS / "atendimentos_reais.csv"    # esperas medidas no protótipo
ARQ_HISTORICO_SIMULADO = PASTA_DADOS / "historico_simulado.csv"  # dados SIMULADOS, identificados

INTERVALO_ATUALIZACAO_MS = 2000  # o painel consulta o servidor a cada 2 s
PORTA = 5000
