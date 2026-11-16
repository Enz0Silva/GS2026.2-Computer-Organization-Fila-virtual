"""Servidor da fila virtual (Flask): processamento, previsão e comunicação.

Rotas
  GET  /                 painel público (pessoas na fila, espera estimada, atendidos)
  GET  /operador         botões de chegada e de conclusão + registro de eventos
  GET  /api/estado       estado atual em JSON (o painel consulta a cada 2 s)
  POST /api/chegada      botão 1: registra a chegada e devolve a senha
  POST /api/concluir     botão 2: registra a conclusão de um atendimento
  GET  /api/avaliacao    comparação dos métodos de previsão (erro em dias de teste)
  GET  /api/eventos.csv  baixa o log de eventos com horário

Uso: python servidor.py   (abre em http://127.0.0.1:5000)
"""
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template, send_file

import previsao
import simulador
from config import (ARQ_ATENDIMENTOS, ARQ_EVENTOS, ARQ_HISTORICO_SIMULADO, ATENDENTES,
                    HORARIO, INTERVALO_ATUALIZACAO_MS, LIMITE_SENHAS_DIA, PORTA, POSTO)
from fila import FilaVirtual, OperacaoInvalida


class Previsor:
    """Guarda os três métodos treinados e re-treina quando chega dado novo."""

    def __init__(self, registros):
        self._trava = threading.Lock()
        self.registros = list(registros)
        self._treinar()

    def _treinar(self):
        self.media = previsao.EstimadorMedia().treinar(self.registros)
        self.simples = previsao.EstimadorRegressao().treinar(self.registros)
        self.multipla = previsao.EstimadorRegressaoMultipla().treinar(self.registros)

    def adicionar(self, registro):
        with self._trava:
            self.registros.append({k: registro[k] for k in (
                "origem", "data", "pessoas_na_frente", "atendentes_ativos")} | {
                "espera_min": float(registro["espera_min"]),
                "duracao_atendimento_min": float(registro["duracao_atendimento_min"])})
            self._treinar()

    def estimar(self, pessoas_na_frente, atendentes):
        with self._trava:
            return {
                "media": round(self.media.prever(pessoas_na_frente, atendentes), 1),
                "regressao_simples": round(self.simples.prever(pessoas_na_frente, atendentes), 1),
                "regressao_multipla": round(self.multipla.prever(pessoas_na_frente, atendentes), 1),
            }

    def resumo(self):
        with self._trava:
            simulados = sum(1 for r in self.registros if r["origem"] == "SIMULADO")
            return {"registros": len(self.registros), "simulados": simulados,
                    "do_prototipo": len(self.registros) - simulados,
                    "tma_min": round(self.media.tma, 2),
                    "regressao_simples": {"a": round(self.simples.a, 3), "b": round(self.simples.b, 3)},
                    "regressao_multipla": [round(c, 3) for c in self.multipla.coef]}


def carregar_historico():
    if not ARQ_HISTORICO_SIMULADO.exists():
        simulador.gerar()
    return previsao.ler_historico(ARQ_HISTORICO_SIMULADO) + previsao.ler_historico(ARQ_ATENDIMENTOS)


def criar_app(fila=None, previsor=None):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    fila = fila or FilaVirtual()
    previsor = previsor or Previsor(carregar_historico())
    fila.ao_concluir.append(previsor.adicionar)
    app.config["FILA"], app.config["PREVISOR"] = fila, previsor

    def estado_completo():
        estado = fila.estado()
        estimativas = previsor.estimar(estado["total_no_posto"], fila.atendentes)
        estado.update({
            "posto": POSTO, "horario": HORARIO,
            "espera_nova_senha_min": estimativas["regressao_multipla"],
            "metodo_principal": "regressão linear múltipla",
            "estimativas_min": estimativas,
            "modelo": previsor.resumo(),
            "atualizado_em": datetime.now().strftime("%H:%M:%S"),
            "aviso": "Estimativa, não garantia. Este painel não é um canal oficial.",
        })
        return estado

    @app.get("/")
    def painel():
        return render_template("painel.html", intervalo=INTERVALO_ATUALIZACAO_MS,
                               posto=POSTO, horario=HORARIO)

    @app.get("/operador")
    def operador():
        return render_template("operador.html", intervalo=INTERVALO_ATUALIZACAO_MS,
                               posto=POSTO, limite=LIMITE_SENHAS_DIA, atendentes=ATENDENTES)

    @app.get("/api/estado")
    def api_estado():
        return jsonify(estado_completo())

    @app.post("/api/chegada")
    def api_chegada():
        try:
            pessoa = fila.chegada()
        except OperacaoInvalida as erro:
            return jsonify({"ok": False, "erro": str(erro), "estado": estado_completo()}), 409
        espera = previsor.estimar(pessoa["pessoas_na_frente"], fila.atendentes)
        return jsonify({"ok": True, "senha": pessoa["senha"],
                        "espera_estimada_min": espera["regressao_multipla"],
                        "estado": estado_completo()}), 201

    @app.post("/api/concluir")
    def api_concluir():
        try:
            medido = fila.concluir()
        except OperacaoInvalida as erro:
            return jsonify({"ok": False, "erro": str(erro), "estado": estado_completo()}), 409
        return jsonify({"ok": True, "senha": medido["senha"], "atendimento": medido,
                        "estado": estado_completo()})

    @app.get("/api/avaliacao")
    def api_avaliacao():
        resultado = previsao.comparar(previsao.ler_historico(ARQ_HISTORICO_SIMULADO))
        resultado["observacao"] = "Erro medido em 4 dias SIMULADOS que os modelos não viram no treino."
        return jsonify(resultado)

    @app.get("/api/eventos.csv")
    def api_eventos():
        if not ARQ_EVENTOS.exists():
            return jsonify({"erro": "ainda não há eventos registrados"}), 404
        return send_file(ARQ_EVENTOS, mimetype="text/csv", as_attachment=True,
                         download_name="eventos.csv")

    return app


if __name__ == "__main__":
    print(f"Fila virtual — {POSTO}")
    print(f"Painel:   http://127.0.0.1:{PORTA}/")
    print(f"Operador: http://127.0.0.1:{PORTA}/operador")
    # host 0.0.0.0 deixa celulares da mesma rede Wi-Fi abrirem o painel pelo IP do computador
    criar_app().run(host="0.0.0.0", port=PORTA, threaded=True, debug=False)
