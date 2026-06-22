# Módulo 1: Arquitetura do Sistema e Fluxo de Dados

Este documento descreve detalhadamente a arquitetura do **SmartLab IoT**, explicando a escolha dos protocolos e como os dados fluem pelas camadas do sistema.

---

## 1. As 4 Camadas da Arquitetura

O sistema foi modelado seguindo as melhores práticas de sistemas distribuídos e IoT, dividindo-se em 4 camadas físicas e lógicas:

```text
┌────────────────────────────────────────────────────────┐
│ 1. CAMADA DE DISPOSITIVOS (Simulador IoT)              │
│    - 30 Computadores, 3 Ar-Condicionados, 3 Projetores │
│    - Emite telemetria periódica via MQTT/CoAP          │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Rede Local)
┌────────────────────────────────────────────────────────┐
│ 2. COMPUTAÇÃO DE BORDA (Edge Gateways)                 │
│    - Um Gateway por laboratório                        │
│    - Brokers Mosquitto locais (MQTT) / Servidor CoAP   │
│    - Agregação por janela e Buffer Offline SQLite      │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Protocolo AMQP)
┌────────────────────────────────────────────────────────┐
│ 3. MENSAGERIA CENTRAL E BACKEND (Nuvem / Servidor)     │
│    - Broker RabbitMQ com 4 filas persistentes          │
│    - Backend FastAPI + Consumidor RabbitMQ             │
│    - Digital Twins em SQLite e Monitor de Heartbeat    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (WebSockets / HTTP REST)
┌────────────────────────────────────────────────────────┐
│ 4. APRESENTAÇÃO (Clientes / Interface)                 │
│    - Dashboard Web SPA (HTML5, CSS, JS)                │
│    - Cliente de Tempo Real de Terminal (CLI Python)     │
└────────────────────────────────────────────────────────┘
```

---

## 2. A Escolha dos Protocolos de Comunicação IoT

Para demonstrar a versatilidade de integração com diferentes tipos de hardware, os laboratórios foram divididos em protocolos distintos:

### MQTT (Message Queuing Telemetry Transport) - Utilizado nos LAB1 e LAB3
* **Características:** Protocolo baseado em Publish/Subscribe sobre TCP. Leve, confiável e ideal para redes instáveis.
* **QoS = 1 (Quality of Service):** Garante que a mensagem seja entregue ao menos uma vez ao broker local (Mosquitto), enviando uma confirmação (`PUBACK`) de volta ao cliente.
* **Justificativa:** É o padrão de fato da indústria IoT para comunicação bidirecional contínua de telemetria de sensores.

### CoAP (Constrained Application Protocol) - Utilizado no LAB2
* **Características:** Protocolo baseado em Request/Response (RESTful) sobre UDP. É projetado especificamente para dispositivos extremamente limitados que não suportam o overhead do TCP.
* **Mensagens CON (Confirmable):** Embora rode sobre UDP (que não é confiável por padrão), o CoAP adiciona confiabilidade na camada de aplicação retransmitindo a mensagem caso o servidor não responda com um `ACK` em tempo hábil.
* **Justificativa:** Demonstra como o sistema pode coletar dados de sensores de baixo custo que usam microcontroladores simples sem pilha TCP complexa.

---

## 3. Topologia de Rede e Portas do Sistema

Para permitir que todo o sistema rode concorrentemente na mesma máquina (ou em máquinas distribuídas) usando Docker, a seguinte atribuição de portas foi realizada:

| Serviço | Contêiner Docker | Porta Interna | Porta Exposta no Host | Protocolo | Papel |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RabbitMQ** | `rabbitmq_central` | `5672`<br>`15672` | `5672`<br>`15672` | AMQP<br>HTTP | Broker de mensageria central.<br>Painel Web de Gerenciamento do RabbitMQ. |
| **Mosquitto LAB1** | `mosquitto_lab1` | `1883`<br>`9001` | `1883`<br>`9001` | MQTT<br>WebSockets | Broker MQTT local do Laboratório 1. |
| **Gateway LAB2** | `gateway_lab2` | `5683` | `5683` | CoAP (UDP) | Coletor CoAP local rodando servidor Python. |
| **Mosquitto LAB3** | `mosquitto_lab3` | `1883`<br>`9001` | `1884`<br>`9002` | MQTT<br>WebSockets | Broker MQTT local alternativo do Laboratório 3. |
| **Backend Central** | `backend_central` | `8000` | `8000` | HTTP / WS | Servidor FastAPI, REST API e WebSockets do Dashboard. |

---

## 4. Fluxo de Dados Ponta a Ponta

1. **Geração:** O [simulator.py](file:///c:/Users/mateus/Documents/projeto_ph/simulator/simulator.py) gera as métricas dos sensores (CPU, RAM, temperatura, consumo) de forma concorrente a cada 5s.
2. **Coleta Local:** 
   * No LAB1/LAB3, o simulador publica no broker Mosquitto local. O coletor [edge_gateway.py](file:///c:/Users/mateus/Documents/projeto_ph/edge_gateway/edge_gateway.py) assina e puxa essas mensagens.
   * No LAB2, o simulador faz um `POST` direto via CoAP no servidor que roda dentro do coletor.
3. **Agregação e Bypass na Borda:** O gateway acumula os dados locais em janelas de 5s, calcula as médias operacionais e publica os pacotes agregados via rede local/externa (AMQP) para o RabbitMQ central. Se houver alertas críticos (anomalias), o gateway faz um **bypass** e publica o alerta imediatamente sem esperar a janela de tempo.
4. **Consumo no Backend:** O backend consome as mensagens do RabbitMQ, atualiza os Digital Twins no banco SQLite (`database.db`) e propaga o status imediatamente para o Dashboard Web ativo via WebSocket.
