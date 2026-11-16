"""Botões "físicos" emulados no terminal.

Representa o dispositivo de entrada da arquitetura (no hardware real seria um
ESP32 com dois botões no balcão). Ele não acessa a fila diretamente: manda um
pedido HTTP POST pela rede, igual ao que o microcontrolador faria.

Uso (com o servidor ligado):  python botoes_teclado.py [endereço]
  c + Enter -> chegada      a + Enter -> atendimento concluído      s -> sair
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDERECO = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"


def apertar(rota):
    pedido = Request(ENDERECO + rota, method="POST")
    try:
        with urlopen(pedido, timeout=3) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except HTTPError as erro:              # 409 = operação recusada pela regra da fila
        return json.loads(erro.read().decode("utf-8"))
    except URLError:
        return {"ok": False, "erro": "servidor fora do ar"}


def main():
    print(f"Botões ligados a {ENDERECO}.  c = chegada · a = concluído · s = sair")
    while True:
        tecla = input("> ").strip().lower()
        if tecla == "s":
            break
        if tecla not in ("c", "a"):
            print("Tecla inválida. Use c, a ou s.")
            continue
        r = apertar("/api/chegada" if tecla == "c" else "/api/concluir")
        if r.get("ok"):
            e = r["estado"]
            feito = (f"senha {r['senha']} emitida" if tecla == "c"
                     else f"senha {r['senha']} concluída")
            print(f"OK: {feito} | aguardando {e['na_fila']} | em atendimento "
                  f"{e['em_atendimento']} | espera nova senha {e['espera_nova_senha_min']:.0f} min")
        else:
            print("RECUSADO:", r.get("erro"))


if __name__ == "__main__":
    main()
