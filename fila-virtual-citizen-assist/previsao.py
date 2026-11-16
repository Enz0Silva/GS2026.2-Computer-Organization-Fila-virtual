"""Previsão do tempo de espera: média histórica x regressão linear.

Os dois métodos recebem a mesma informação, disponível no momento em que a
pessoa pega a senha: quantas pessoas já estão no sistema (esperando ou sendo
atendidas) e quantos atendentes estão trabalhando.

1. Estimativa convencional (média histórica do tempo de atendimento):
       espera = max(0, pessoas_na_frente - atendentes + 1) x TMA / atendentes
   TMA = tempo médio de atendimento do histórico. É a conta "de cabeça" de
   quem trabalha no posto: cada guichê resolve uma pessoa a cada TMA minutos.

2. Regressão linear simples (modelo de IA treinado com o histórico):
       espera = a + b x pessoas_na_frente
   a e b saem do método dos mínimos quadrados, calculados aqui sem biblioteca:
       b = cov(x, y) / var(x)      a = média(y) - b x média(x)
   O modelo aprende com o que aconteceu de verdade, inclusive o que a conta
   convencional ignora (o almoço de um atendente, o atendimento que já estava
   em andamento, as senhas chamadas que não aparecem).

3. Regressão linear múltipla (o modelo usado no painel):
       espera = b0 + b1 x pessoas_na_frente + b2 x (pessoas_na_frente / atendentes)
   Os coeficientes saem das equações normais (X^T X) b = X^T y, resolvidas por
   eliminação de Gauss. A segunda variável deixa o modelo perceber que, com um
   atendente só (almoço), cada pessoa à frente pesa mais.

Os métodos são avaliados com o erro absoluto médio (MAE) em dias que o modelo
não viu no treino. Quanto menor o MAE, melhor.
"""
import csv
import math


def ler_historico(caminho):
    """Lê um CSV com pessoas_na_frente, atendentes_ativos, espera_min e duracao_atendimento_min."""
    try:
        with open(caminho, newline="", encoding="utf-8") as arquivo:
            linhas = list(csv.DictReader(arquivo))
    except FileNotFoundError:
        return []
    registros = []
    for linha in linhas:
        try:
            registros.append({
                "origem": linha.get("origem", ""),
                "data": linha.get("data", ""),
                "pessoas_na_frente": int(linha["pessoas_na_frente"]),
                "atendentes_ativos": int(linha["atendentes_ativos"]),
                "espera_min": float(linha["espera_min"]),
                "duracao_atendimento_min": float(linha["duracao_atendimento_min"]),
            })
        except (KeyError, ValueError):
            continue          # linha incompleta não derruba o treino
    return registros


class EstimadorMedia:
    """Estimativa convencional: fila / atendentes x tempo médio de atendimento."""
    nome = "média histórica"

    def __init__(self):
        self.tma = None

    def treinar(self, registros):
        duracoes = [r["duracao_atendimento_min"] for r in registros]
        self.tma = sum(duracoes) / len(duracoes) if duracoes else 10.0
        return self

    def prever(self, pessoas_na_frente, atendentes):
        atendentes = max(1, atendentes)
        a_esperar = max(0, pessoas_na_frente - atendentes + 1)
        return a_esperar * self.tma / atendentes


class EstimadorRegressao:
    """Regressão linear simples: espera = a + b x pessoas_na_frente."""
    nome = "regressão linear"

    def __init__(self):
        self.a = self.b = None
        self.r2 = None

    def treinar(self, registros):
        x = [r["pessoas_na_frente"] for r in registros]
        y = [r["espera_min"] for r in registros]
        n = len(x)
        if n < 2:
            self.a, self.b = 0.0, 5.0          # sem histórico: chute declarado
            return self
        mx, my = sum(x) / n, sum(y) / n
        sxx = sum((xi - mx) ** 2 for xi in x)
        sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        self.b = sxy / sxx if sxx else 0.0
        self.a = my - self.b * mx
        sst = sum((yi - my) ** 2 for yi in y)
        sse = sum((yi - self.a - self.b * xi) ** 2 for xi, yi in zip(x, y))
        self.r2 = 1 - sse / sst if sst else None
        return self

    def prever(self, pessoas_na_frente, atendentes=None):
        return max(0.0, self.a + self.b * pessoas_na_frente)


def resolver_sistema(A, b):
    """Eliminação de Gauss com pivoteamento parcial (A é uma lista de listas)."""
    n = len(A)
    M = [linha[:] + [b[i]] for i, linha in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda i: abs(M[i][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("sistema sem solução única")
        M[col], M[piv] = M[piv], M[col]
        for i in range(col + 1, n):
            fator = M[i][col] / M[col][col]
            for j in range(col, n + 1):
                M[i][j] -= fator * M[col][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


class EstimadorRegressaoMultipla:
    """espera = b0 + b1 x pessoas_na_frente + b2 x pessoas_na_frente / atendentes."""
    nome = "regressão linear múltipla"

    def __init__(self):
        self.coef = None

    @staticmethod
    def _variaveis(pessoas_na_frente, atendentes):
        return [1.0, float(pessoas_na_frente), pessoas_na_frente / max(1, atendentes)]

    def treinar(self, registros):
        X = [self._variaveis(r["pessoas_na_frente"], r["atendentes_ativos"]) for r in registros]
        y = [r["espera_min"] for r in registros]
        try:
            XtX = [[sum(l[i] * l[j] for l in X) for j in range(3)] for i in range(3)]
            Xty = [sum(l[i] * yi for l, yi in zip(X, y)) for i in range(3)]
            self.coef = resolver_sistema(XtX, Xty)
        except (ValueError, ZeroDivisionError):
            # pouco histórico ou sem variação: cai para a regressão simples
            simples = EstimadorRegressao().treinar(registros)
            self.coef = [simples.a, simples.b, 0.0]
        return self

    def prever(self, pessoas_na_frente, atendentes):
        v = self._variaveis(pessoas_na_frente, atendentes)
        return max(0.0, sum(c * xi for c, xi in zip(self.coef, v)))


def mae(estimador, registros):
    erros = [abs(estimador.prever(r["pessoas_na_frente"], r["atendentes_ativos"]) - r["espera_min"])
             for r in registros]
    return sum(erros) / len(erros) if erros else None


def rmse(estimador, registros):
    erros = [(estimador.prever(r["pessoas_na_frente"], r["atendentes_ativos"]) - r["espera_min"]) ** 2
             for r in registros]
    return math.sqrt(sum(erros) / len(erros)) if erros else None


def separar_por_dia(registros, dias_teste=4):
    """Treino com os primeiros dias, teste com os últimos (o modelo não vê o futuro)."""
    dias = sorted({r["data"] for r in registros})
    teste_dias = set(dias[-dias_teste:])
    treino = [r for r in registros if r["data"] not in teste_dias]
    teste = [r for r in registros if r["data"] in teste_dias]
    return treino, teste


def comparar(registros, dias_teste=4):
    """Treina os dois métodos e mede o erro nos dias de teste."""
    treino, teste = separar_por_dia(registros, dias_teste)
    modelos = {
        "media": EstimadorMedia().treinar(treino),
        "regressao_simples": EstimadorRegressao().treinar(treino),
        "regressao_multipla": EstimadorRegressaoMultipla().treinar(treino),
    }
    almoco = [r for r in teste if r["atendentes_ativos"] < max(r2["atendentes_ativos"] for r2 in teste)]
    simples = modelos["regressao_simples"]
    return {
        "registros_treino": len(treino),
        "registros_teste": len(teste),
        "tma_min": round(modelos["media"].tma, 2),
        "regressao_simples": {"a": round(simples.a, 3), "b": round(simples.b, 3),
                              "r2_treino": round(simples.r2, 3) if simples.r2 is not None else None},
        "regressao_multipla": {"coeficientes": [round(c, 3) for c in modelos["regressao_multipla"].coef]},
        "mae_min": {k: round(mae(m, teste), 2) for k, m in modelos.items()},
        "rmse_min": {k: round(rmse(m, teste), 2) for k, m in modelos.items()},
        "mae_no_almoco_min": ({k: round(mae(m, almoco), 2) for k, m in modelos.items()}
                              if almoco else None),
        "registros_almoco": len(almoco),
    }


if __name__ == "__main__":
    from config import ARQ_HISTORICO_SIMULADO
    resultado = comparar(ler_historico(ARQ_HISTORICO_SIMULADO))
    print("Comparação nos dias de teste (dados SIMULADOS):")
    for chave, valor in resultado.items():
        print(f"  {chave}: {valor}")
