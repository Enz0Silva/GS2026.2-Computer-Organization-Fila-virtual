"""Mede desempenho e memória do protótipo (evidência da análise de arquitetura).

O que é medido, no computador onde o script roda:
- tempo de processamento de cada pedido HTTP (chegada, conclusão, estado);
- memória usada pela fila por pessoa e pelos modelos (tracemalloc);
- bytes gravados no armazenamento por evento (eventos.csv);
- tempo para re-treinar os modelos com todo o histórico.

Usa o cliente de teste do Flask (sem rede), então mede só CPU e memória do
servidor; a latência da rede Wi-Fi vem por cima disso.

Uso: python medir_desempenho.py
"""
import platform
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

import previsao
from config import ARQ_HISTORICO_SIMULADO
from fila import FilaVirtual
from servidor import Previsor, criar_app


def cronometrar(funcao, repeticoes):
    tempos = []
    for _ in range(repeticoes):
        t0 = time.perf_counter()
        funcao()
        tempos.append((time.perf_counter() - t0) * 1000)
    return statistics.median(tempos), max(tempos)


def main():
    pasta = Path(tempfile.mkdtemp())
    tracemalloc.start()
    antes = tracemalloc.take_snapshot()
    historico = previsao.ler_historico(ARQ_HISTORICO_SIMULADO)
    previsor = Previsor(historico)
    depois = tracemalloc.take_snapshot()
    mem_modelos = sum(s.size_diff for s in depois.compare_to(antes, "filename"))

    fila = FilaVirtual(limite_senhas=10_000, arq_eventos=pasta / "eventos.csv",
                       arq_atendimentos=pasta / "atendimentos.csv")
    app = criar_app(fila, previsor).test_client()

    antes = tracemalloc.take_snapshot()
    chegada_med, chegada_max = cronometrar(lambda: app.post("/api/chegada"), 1000)
    depois = tracemalloc.take_snapshot()
    mem_1000 = sum(s.size_diff for s in depois.compare_to(antes, "filename"))
    estado_med, estado_max = cronometrar(lambda: app.get("/api/estado"), 300)
    concluir_med, concluir_max = cronometrar(lambda: app.post("/api/concluir"), 300)
    tracemalloc.stop()

    t0 = time.perf_counter()
    previsao.EstimadorRegressaoMultipla().treinar(historico)
    treino_ms = (time.perf_counter() - t0) * 1000

    eventos = (pasta / "eventos.csv").read_bytes()
    linhas = eventos.count(b"\n") - 1

    print(f"Máquina: {platform.machine()} · {platform.processor() or platform.system()} · Python {platform.python_version()}")
    print(f"POST /api/chegada   mediana {chegada_med:.2f} ms · pior {chegada_max:.2f} ms (1000 pedidos)")
    print(f"POST /api/concluir  mediana {concluir_med:.2f} ms · pior {concluir_max:.2f} ms (300 pedidos)")
    print(f"GET  /api/estado    mediana {estado_med:.2f} ms · pior {estado_max:.2f} ms (300 pedidos)")
    print(f"Treinar a regressão múltipla com {len(historico)} registros: {treino_ms:.1f} ms")
    print(f"Memória: histórico de {len(historico)} registros + modelos {mem_modelos / 1024:.0f} KiB · "
          f"1000 pessoas na fila + log em memória {mem_1000 / 1024:.0f} KiB "
          f"(~{mem_1000 / 1000:.0f} bytes por chegada)")
    print(f"Armazenamento: {len(eventos) / max(1, linhas):.0f} bytes por evento no CSV; "
          f"um dia de mutirão (40 senhas, ~120 eventos) ≈ {120 * len(eventos) / max(1, linhas) / 1024:.1f} KiB")


if __name__ == "__main__":
    main()
