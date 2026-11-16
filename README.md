# Fila virtual do mutirão — Citizen Assist AI

**Global Solution 2026.2 · FIAP · Ciência da Computação · Arquitetura e Organização de Computadores (Computer Organization and Architecture)**

Protótipo de um **Sistema Inteligente de Gerenciamento de Filas Virtuais** para o mutirão de orientação sobre apostas e dívidas do Posto Cidadão Centro de Vila Aurora (município fictício do projeto Citizen Assist AI): terças e quintas, das 9h às 15h, até 40 senhas por dia. Dois botões registram a chegada de uma pessoa e a conclusão de um atendimento; o servidor mantém a fila, grava cada evento com horário, estima a espera com inteligência artificial (regressão linear) e publica tudo numa página que se atualiza sozinha.

| Integrante | RM |
|---|---|
| Enzo Ricardo Silva | 571333 |
| Eric Hernandes Penhalbel | 570237 |
| Matheus Borges Soares | 574085 |

**Vídeo de demonstração (até 5 min, YouTube não listado):** _(colar o link)_
**Relatório técnico:** [`docs/RELATORIO_TECNICO.pdf`](docs/RELATORIO_TECNICO.pdf) · **Diagrama de arquitetura:** [`docs/arquitetura.png`](docs/arquitetura.png)

![Arquitetura](docs/arquitetura.png)

## Como executar

Requisito: Python 3.10 ou mais recente.

```bash
pip install -r requirements.txt     # só o Flask
python servidor.py                  # liga o servidor na porta 5000
```

- Painel público: http://127.0.0.1:5000/
- Botões do operador: http://127.0.0.1:5000/operador (clique ou use as teclas **C** e **A**)
- Botões "físicos" emulados num segundo terminal: `python botoes_teclado.py`
- Celular na mesma rede Wi-Fi: http://IP-DO-COMPUTADOR:5000/

Outros comandos:

| Comando | O que faz |
|---|---|
| `python -m unittest discover -s testes -v` | Roda os 12 testes (os 4 mínimos do briefing e 8 extras) |
| `python previsao.py` | Compara média histórica × regressão linear em dias de teste |
| `python simulador.py` | Gera de novo o histórico SIMULADO (mesma semente, mesmos dados) |
| `python medir_desempenho.py` | Mede tempo por pedido, memória e bytes por evento nesta máquina |

## Estrutura

```
fila-virtual-citizen-assist/
├── README.md
├── requirements.txt
├── config.py              cenário do mutirão: 2 atendentes, 40 senhas, caminhos dos arquivos
├── fila.py                FilaVirtual: botões, regras (sem contagem negativa, limite), log de eventos
├── previsao.py            média histórica, regressão linear simples e múltipla (sem bibliotecas)
├── simulador.py           gera dados/historico_simulado.csv (dados SIMULADOS, identificados)
├── servidor.py            Flask: rotas HTTP, painel e API JSON
├── botoes_teclado.py      dispositivo de entrada emulado (manda HTTP POST como um ESP32 faria)
├── medir_desempenho.py    evidência da análise de CPU, memória e armazenamento
├── templates/             painel.html (público) e operador.html (botões)
├── static/estilo.css
├── dados/
│   ├── historico_simulado.csv    637 atendimentos SIMULADOS em 16 dias (treino da IA)
│   ├── eventos.csv               criado ao usar: CHEGADA, CHAMADA, CONCLUSAO, RECUSADO, com horário
│   └── atendimentos_reais.csv    criado ao usar: espera e duração medidas pelo protótipo
├── testes/test_fila.py
└── docs/                  diagrama (.dot, .svg, .png), prints e relatório técnico
```

## Como a fila funciona

- **Botão 1, chegada:** emite a próxima senha e coloca a pessoa no fim da fila.
- **Botão 2, atendimento concluído:** tira da fila quem foi chamado primeiro e chama a próxima senha para o guichê livre.
- Com 2 atendentes, as 2 primeiras pessoas estão em atendimento e as outras aguardam. Só com os dois botões o sistema mede a **espera real** (chamada − chegada) e a **duração do atendimento** (conclusão − chamada).
- **Operações inválidas são recusadas** com HTTP 409 e ficam no log: concluir com a fila vazia (a contagem nunca fica negativa) e pedir senha depois da 40ª do dia.
- Todas as operações passam por um `threading.Lock`: dois cliques ao mesmo tempo não corrompem a contagem (há teste com 200 chegadas simultâneas).

## Previsão de espera

Os métodos recebem a mesma informação, conhecida na hora em que a pessoa pega a senha: quantas pessoas já estão no posto e quantos atendentes trabalham.

| Método | Fórmula | Erro médio (MAE) | No almoço (1 atendente) |
|---|---|---|---|
| Média histórica (convencional) | `max(0, n − k + 1) × TMA / k`, com TMA = 10,44 min | 4,53 min | 5,68 min |
| Regressão linear simples (IA) | `−0,90 + 4,81 × n` | 4,52 min | 2,27 min |
| **Regressão linear múltipla (IA, usada no painel)** | `−1,90 + 1,92 × n + 5,94 × n/k` | **4,41 min** | **1,67 min** |

Erros medidos em 4 dias **simulados** que os modelos não viram no treino (159 atendimentos). No dia a dia as três ficam próximas, porque a fila é por ordem de chegada e a conta convencional já é quase exata. A diferença aparece quando o cenário foge da conta: no almoço, com um atendente só, a média histórica superestima a espera de quem chega perto das 13h, e a regressão, que aprendeu com o que aconteceu, erra menos. Cada atendimento concluído no protótipo entra no histórico e os modelos são re-treinados na hora.

**Dados simulados:** o histórico de treino foi gerado por `simulador.py` (semente fixa 2026) e toda linha tem `origem = SIMULADO`. As premissas (fila na abertura, chegadas mais fortes até 11h, atendimento médio de cerca de 11 min, 8% de senhas chamadas que não aparecem, almoço de um atendente das 12h às 13h) estão no próprio arquivo. Não são dados de um posto real.

## Testes mínimos do briefing

| # | Situação | Teste | Resultado |
|---|---|---|---|
| 1 | Chegada de novos cidadãos | `test_1_chegada_de_novos_cidadaos` | 4 senhas emitidas, 2 em atendimento e 2 aguardando |
| 2 | Conclusão de atendimentos | `test_2_conclusao_de_atendimentos` | senha 1 concluída com duração medida de 12 min; senha 3 chamada |
| 3 | Saída com fila vazia | `test_3_saida_com_fila_vazia_e_recusada` | HTTP 409, contagem continua em 0, evento RECUSADO gravado |
| 4 | Atualização da estimativa | `test_4_estimativa_de_espera_se_atualiza` | a espera sobe com 8 chegadas e cai depois de uma conclusão |

Os 12 testes passam (`python -m unittest discover -s testes -v`).

## Integração com o Citizen Assist AI

O assistente de terminal da disciplina de Python (repositório `citizen-assist-ai`) tem a opção **"Ver a fila do mutirão"**, que lê `GET /api/estado` pela rede e mostra ao cidadão as pessoas na fila, a espera estimada e as senhas restantes. Se o servidor estiver desligado, o assistente avisa e continua funcionando. O cenário do mutirão (dias, horário e 40 senhas) é o mesmo do comunicado DOC02 da base documental de Prompt and AI.

## Limitações

- Botão único de conclusão: o sistema supõe que quem foi chamado primeiro termina primeiro. Com um botão por guichê, a duração de cada atendimento seria medida sem essa suposição.
- O protótipo não sabe quando um atendente sai para o almoço; o número de atendentes é fixo em `config.py`.
- A fila fica na memória: se o servidor reiniciar, a fila do dia recomeça (o log em CSV continua).
- O painel consulta o servidor a cada 2 s (polling). Para centenas de telas, WebSocket ou Server-Sent Events gastariam menos rede.
- O servidor de desenvolvimento do Flask serve para o protótipo; em produção seria um servidor WSGI (gunicorn, waitress) e HTTPS.
- A previsão foi treinada com dados simulados. Em uso real, os dados do posto substituiriam a simulação.

## Aviso

Protótipo acadêmico. Não é canal oficial, não coleta dados pessoais (a senha é só um número) e a espera exibida é estimativa, não garantia.
