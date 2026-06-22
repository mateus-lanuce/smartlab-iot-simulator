# Módulo 6: Orquestração Docker e Implantação Distribuída

Este documento detalha o setup de contêineres e o procedimento passo a passo para implantar o sistema em duas máquinas físicas na mesma subrede local.

---

## 1. A Rede Virtual no Docker Compose

O arquivo [docker-compose.yml](file:///c:/Users/mateus/Documents/projeto_ph/docker-compose.yml) define uma rede virtual de bridge chamada `iot_network` para conectar todos os contêineres:

* **Desacoplamento:** Serviços internos (como o backend e os gateways de borda) referenciam o RabbitMQ simplesmente pelo nome do seu serviço do Compose (`rabbitmq`) na porta interna `5672`, o que simplifica a orquestração e evita DNS rígido.
* **Isolamento:** Os brokers locais de mosquitto (`mosquitto-lab1` e `mosquitto-lab3`) isolam o tráfego MQTT de seus laboratórios respectivos e expõem portas no host apenas para permitir conexões externas ou ferramentas de depuração (ex: MQTT Explorer).

---

## 2. Configurações por Variáveis de Ambiente (`.env`)

Para evitar chumbamento de configurações no código e no arquivo compose, criamos um arquivo [.env](file:///c:/Users/mateus/Documents/projeto_ph/.env) (espelhado no [.env.example](file:///c:/Users/mateus/Documents/projeto_ph/.env.example)):

* **`BACKEND_PORT`:** Porta exposta pelo dashboard e REST API (padrão: `8000`).
* **`RABBITMQ_USER` / `RABBITMQ_PASS`:** Credenciais padrão do Broker RabbitMQ.
* **`RABBITMQ_AMQP_PORT` / `RABBITMQ_MGMT_PORT`:** Portas expostas para tráfego AMQP (`5672`) e painel administrativo (`15672`).
* **`SIMULATION_INTERVAL`:** O delay de envio das telemetrias dos simuladores (padrão: `5.0` segundos).
* **`AGGREGATION_WINDOW`:** Janela de tempo de agregação nos gateways (padrão: `5.0` segundos).

---

## 3. O Makefile de Facilitação

Para simplificar a operação de todo o ecossistema e evitar a digitação de comandos Docker longos no terminal, disponibilizamos um arquivo [Makefile](file:///c:/Users/mateus/Documents/projeto_ph/Makefile) na raiz. Ele possui os seguintes alvos de execução:

| Comando | Ação Executada |
| :--- | :--- |
| `make up` | Constrói e inicializa todo o ecossistema Docker Compose em background (`-d`). |
| `make down` | Desliga e encerra todos os contêineres criados. |
| `make restart` | Reinicia todos os contêineres. |
| `make logs` | Segue os logs consolidados em tempo real no console. |
| `make cli-lab1` | Instala dependências em um container temporário e roda o Cliente CLI MQTT ouvindo o **LAB1**. |
| `make cli-lab3` | Instala dependências em um container temporário e roda o Cliente CLI MQTT ouvindo o **LAB3**. |
| `make cli-local-lab1` | Executa o Cliente CLI no host conectando na porta `1883` (requer pip local). |
| `make cli-local-lab3` | Executa o Cliente CLI no host conectando na porta `1884` (requer pip local). |
| `make clean` | Desliga o Docker, deleta volumes persistentes e remove bancos SQLite locais. |

---

## 4. Roteiro Passo a Passo de Execução em Duas Máquinas

A apresentação do projeto exige a execução em no mínimo 2 máquinas de rede física para demonstrar a descentralização de sistemas distribuídos:

```text
    MÁQUINA 2 (Cliente / Borda)                  MÁQUINA 1 (Servidora)
┌─────────────────────────────────┐        ┌───────────────────────────────────┐
│ - 3 Simuladores (LAB 1, 2, 3)   │        │ - RabbitMQ Central (AMQP)         │
│ - 3 Gateways de Borda (SQLite)  │───────►│ - Backend Central (FastAPI)       │
│ - Brokers Mosquitto Locais      │  AMQP  │ - Banco SQLite Central            │
└─────────────────────────────────┘        │ - Dashboard Web (SPA)             │
                                           └───────────────────────────────────┘
```

### Passo 1: Preparação da Rede Física
1. Conecte a **Máquina 1** e a **Máquina 2** na mesma rede WiFi ou via switch/cabo de rede local.
2. Identifique o IP de rede local da **Máquina 1** (ex: `192.168.1.100` no Windows via `ipconfig`, ou no Linux via `ip a`).
3. Certifique-se de que a **Máquina 1** possui as portas `8000` (FastAPI) e `5672` (RabbitMQ) desbloqueadas no firewall.

### Passo 2: Execução na Máquina 1 (Servidora)
1. Coloque a pasta do projeto na Máquina 1.
2. No terminal do projeto, inicialize o RabbitMQ e todos os microsserviços do backend central:
   ```bash
   docker compose up -d backend rabbitmq worker-twin worker-alerts service-monitor
   ```
3. O Dashboard já poderá ser acessado localmente pelo navegador da Máquina 1 em `http://localhost:8000`.

### Passo 3: Configuração e Execução na Máquina 2 (Simulação e Borda)
1. Coloque a pasta do projeto na Máquina 2.
2. Abra o arquivo `.env` da Máquina 2 e altere a variável `RABBITMQ_HOST` para o endereço IP da Máquina 1 que você anotou:
   ```env
   RABBITMQ_HOST=192.168.1.100
   ```
3. Suba apenas os simuladores, brokers locais e gateways locais:
   ```bash
   docker compose up -d mosquitto-lab1 mosquitto-lab3 gateway-lab1 gateway-lab2 gateway-lab3 simulator-lab1 simulator-lab2 simulator-lab3
   ```
4. **Verificação:** Os gateways locais da Máquina 2 começarão a empacotar os dados locais e enviá-los de volta através da rede física para o RabbitMQ central na Máquina 1. A interface web na Máquina 1 começará a piscar e atualizar os dados em tempo real automaticamente.
5. Se você desconectar o cabo de rede da Máquina 2, os gateways entrarão no modo buffer SQLite local offline. Ao reconectar, eles descarregarão os dados ordenadamente sem perdas.
