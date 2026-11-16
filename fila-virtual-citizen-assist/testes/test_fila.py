"""Testes da fila virtual: os 4 testes mínimos do briefing e casos extras.

Uso (na pasta do projeto):  python -m unittest discover -s testes -v
Os testes usam um relógio falso, para medir esperas sem esperar de verdade,
e arquivos temporários, para não sujar o log real.
"""
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import previsao  # noqa: E402
from config import ARQ_HISTORICO_SIMULADO  # noqa: E402
from fila import FilaVirtual, OperacaoInvalida  # noqa: E402
from servidor import Previsor, criar_app  # noqa: E402


class RelogioFalso:
    def __init__(self):
        self.agora = datetime(2026, 11, 17, 9, 0, 0)

    def __call__(self):
        return self.agora

    def avancar(self, minutos):
        self.agora += timedelta(minutes=minutos)


def nova_fila(pasta, **extra):
    relogio = RelogioFalso()
    fila = FilaVirtual(atendentes=2, limite_senhas=extra.get("limite", 40),
                       arq_eventos=Path(pasta) / "eventos.csv",
                       arq_atendimentos=Path(pasta) / "atendimentos.csv", relogio=relogio)
    return fila, relogio


class TestesMinimos(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp()
        self.fila, self.relogio = nova_fila(self.pasta)
        historico = previsao.ler_historico(ARQ_HISTORICO_SIMULADO)
        self.app = criar_app(self.fila, Previsor(historico)).test_client()

    def test_1_chegada_de_novos_cidadaos(self):
        for esperado in range(1, 5):
            r = self.app.post("/api/chegada")
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r.get_json()["senha"], esperado)
        e = self.app.get("/api/estado").get_json()
        self.assertEqual(e["total_no_posto"], 4)
        self.assertEqual(e["em_atendimento"], 2)
        self.assertEqual(e["na_fila"], 2)
        self.assertEqual(e["senhas_aguardando"], [3, 4])

    def test_2_conclusao_de_atendimentos(self):
        for _ in range(3):
            self.app.post("/api/chegada")
        self.relogio.avancar(12)
        r = self.app.post("/api/concluir")
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertEqual(dados["senha"], 1)
        self.assertEqual(dados["atendimento"]["duracao_atendimento_min"], 12.0)
        e = dados["estado"]
        self.assertEqual((e["atendidos"], e["em_atendimento"], e["na_fila"]), (1, 2, 0))
        self.assertEqual(e["senhas_em_atendimento"], [2, 3])   # a senha 3 foi chamada

    def test_3_saida_com_fila_vazia_e_recusada(self):
        r = self.app.post("/api/concluir")
        self.assertEqual(r.status_code, 409)
        self.assertIn("vazia", r.get_json()["erro"])
        e = self.app.get("/api/estado").get_json()
        self.assertEqual((e["na_fila"], e["em_atendimento"], e["atendidos"]), (0, 0, 0))
        self.assertEqual(e["ultimos_eventos"][0]["evento"], "RECUSADO")

    def test_4_estimativa_de_espera_se_atualiza(self):
        espera_vazia = self.app.get("/api/estado").get_json()["espera_nova_senha_min"]
        for _ in range(8):
            self.app.post("/api/chegada")
        espera_cheia = self.app.get("/api/estado").get_json()["espera_nova_senha_min"]
        self.assertGreater(espera_cheia, espera_vazia)
        self.relogio.avancar(10)
        self.app.post("/api/concluir")
        espera_depois = self.app.get("/api/estado").get_json()["espera_nova_senha_min"]
        self.assertLess(espera_depois, espera_cheia)


class TestesExtras(unittest.TestCase):
    def test_limite_de_senhas_do_dia(self):
        fila, _ = nova_fila(tempfile.mkdtemp(), limite=3)
        for _ in range(3):
            fila.chegada()
        with self.assertRaises(OperacaoInvalida):
            fila.chegada()
        self.assertEqual(fila.senhas_restantes(), 0)
        self.assertEqual(len(fila.fila), 3)

    def test_espera_medida_pelos_dois_botoes(self):
        fila, relogio = nova_fila(tempfile.mkdtemp())
        for _ in range(3):
            fila.chegada()                 # senhas 1 e 2 chamadas na hora, 3 espera
        relogio.avancar(15)
        fila.concluir()                    # libera guichê: senha 3 é chamada aos 15 min
        relogio.avancar(5)
        fila.concluir()                    # senha 2 conclui
        relogio.avancar(7)
        medido = fila.concluir()           # senha 3 conclui
        self.assertEqual(medido["senha"], 3)
        self.assertEqual(medido["espera_min"], 15.0)
        self.assertEqual(medido["duracao_atendimento_min"], 12.0)
        self.assertEqual(medido["pessoas_na_frente"], 2)

    def test_eventos_gravados_com_horario(self):
        pasta = tempfile.mkdtemp()
        fila, _ = nova_fila(pasta)
        fila.chegada()
        fila.concluir()
        try:
            fila.concluir()
        except OperacaoInvalida:
            pass
        linhas = (Path(pasta) / "eventos.csv").read_text(encoding="utf-8").splitlines()
        self.assertTrue(linhas[0].startswith("data_hora,evento"))
        eventos = [linha.split(",")[1] for linha in linhas[1:]]
        self.assertEqual(eventos, ["CHEGADA", "CHAMADA", "CONCLUSAO", "RECUSADO"])

    def test_cliques_simultaneos_nao_corrompem_a_contagem(self):
        fila, _ = nova_fila(tempfile.mkdtemp(), limite=1000)
        fila.arq_eventos = fila.arq_atendimentos = None
        threads = [threading.Thread(target=fila.chegada) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(fila.fila), 200)
        self.assertEqual(sorted(p["senha"] for p in fila.fila), list(range(1, 201)))

    def test_regressao_aprende_a_reta_exata(self):
        registros = [{"pessoas_na_frente": x, "atendentes_ativos": 2,
                      "espera_min": 3 + 5 * x, "duracao_atendimento_min": 10} for x in range(10)]
        modelo = previsao.EstimadorRegressao().treinar(registros)
        self.assertAlmostEqual(modelo.a, 3)
        self.assertAlmostEqual(modelo.b, 5)
        self.assertAlmostEqual(modelo.r2, 1)

    def test_gauss_resolve_sistema(self):
        x = previsao.resolver_sistema([[2, 1, -1], [-3, -1, 2], [-2, 1, 2]], [8, -11, -3])
        for obtido, esperado in zip(x, [2, 3, -1]):
            self.assertAlmostEqual(obtido, esperado)

    def test_media_sem_fila_estima_zero(self):
        modelo = previsao.EstimadorMedia().treinar([{"duracao_atendimento_min": 10}])
        self.assertEqual(modelo.prever(0, 2), 0)
        self.assertEqual(modelo.prever(1, 2), 0)     # ainda há guichê livre
        self.assertEqual(modelo.prever(2, 2), 5)     # 1 pessoa a esperar / 2 guichês x 10 min

    def test_paginas_abrem(self):
        fila, _ = nova_fila(tempfile.mkdtemp())
        app = criar_app(fila).test_client()
        self.assertEqual(app.get("/").status_code, 200)
        self.assertEqual(app.get("/operador").status_code, 200)
        self.assertIn("mae_min", app.get("/api/avaliacao").get_json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
