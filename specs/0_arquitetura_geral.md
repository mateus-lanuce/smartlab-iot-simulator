# Spec 0: Arquitetura Geral do Sistema

Este documento descreve a arquitetura macro, a topologia de rede, as escolhas tecnológicas e o mapeamento de portas para o **Sistema Distribuído de Monitoramento Inteligente de Laboratórios de Informática**.

---

## 1. Visão Geral da Arquitetura

O sistema é composto por 4 camadas tecnológicas estruturadas de forma a garantir escalabilidade, resiliência e processamento em tempo real:

1. **Camada de Dispositivos (Simulação IoT):** Simulação de hardware concorrente (threads) gerando dados realistas de 30 Computadores, 3 Ar-Condicionados e 3 Projetores Multimídia divididos em 3 Laboratórios (LAB1, LAB2 e LAB3).
2. **Camada de Computação de Borda (Edge Gateway):** Três Gateways de Borda (um para cada laboratório) que atuam como coletores locais, executam processamento de stream preliminar (agregação, filtragem, detecção local de anomalias) e garantem resiliência offline (buffering local).
3. **Camada de Mensageria e Nuvem/Backend:** Broker central RabbitMQ que distribui as mensagens para microsserviços Python encarregados de manter os **Digital Twins** atualizados e persistir dados no banco **SQLite**.
4. **Camada de Apresentação (Clientes):** Painel Web administrativo em tempo real e clientes de terminal (MQTT/REST) para visualização e consulta sob demanda.

---

## 2. Diagrama de Topologia de Rede e Comunicação

```mermaid
graph TD
    subgraph LAB1_Borda ["Laboratório 1 (Borda)"]
        PC1_1[PC 1..10] -- MQTT:1883 --> GW1[Gateway LAB1]
        AC1[Ar-Condicionado] -- MQTT:1883 --> GW1
        PROJ1[Projetor] -- MQTT:1883 --> GW1
    end

    subgraph LAB2_Borda ["Laboratório 2 (Borda)"]
        PC2_1[PC 1..10] -- CoAP:5683 --> GW2[Gateway LAB2]
        AC2[Ar-Condicionado] -- CoAP:5683 --> GW2
        PROJ2[Projetor] -- CoAP:5683 --> GW2
    end

    subgraph LAB3_Borda ["Laboratório 3 (Borda)"]
        PC3_1[PC 1..10] -- MQTT:1884 --> GW3[Gateway LAB3]
        AC3[Ar-Condicionado] -- MQTT:1884 --> GW3
        PROJ3[Projetor] -- MQTT:1884 --> GW3
    end

    subgraph Cloud_Backend ["Nuvem / Backend Central"]
        GW1 -- AMQP:5672 --> RMQ[RabbitMQ Broker]
        GW2 -- AMQP:5672 --> RMQ
        GW3 -- AMQP:5672 --> RMQ

        RMQ -- alerts_queue --> W_ALERTS[Worker Alertas]
        RMQ -- status/energy/env --> W_TWIN[Worker Twins]
        RMQ -- `#` (todos os eventos) --> API_GW[API Gateway / WS]
        
        W_ALERTS & W_TWIN & MON[Heartbeat Monitor] -- Shared Volume --> DB[(SQLite DB WAL)]
        API_GW -- Reads --> DB
        
        MON -- Publishes Alerts --> RMQ
        W_TWIN -- Publishes CEP Alerts --> RMQ
    end

    subgraph Presentation_Layer ["Camada de Apresentação"]
        CLI_MQTT[Cliente Real-Time MQTT] <-- Assina tópicos:1883 -- GW1 & GW3
        WEB_DASH[Painel Administrativo Web] <-- HTTP GET:8000 --> API_GW
        WEB_DASH <-- WebSockets:8000 --> API_GW
    end
```

---

## 3. Divisão de Protocolos e Portas de Rede

Para garantir o teste simultâneo no mesmo host ou em hosts distribuídos através do Docker Compose, a seguinte distribuição de protocolos, serviços e portas é estabelecida:

| Componente | Protocolo de Entrada | Porta Interna | Porta Exposta no Host | Papel |
| :--- | :--- | :--- | :--- | :--- |
| **Gateway LAB1** | MQTT | `1883` | `1883` | Broker Mosquitto local + Agente Coletor Python |
| **Gateway LAB2** | CoAP | `5683` (UDP) | `5683` (UDP) | Servidor CoAP local Python |
| **Gateway LAB3** | MQTT | `1883` | `1884` | Broker Mosquitto local alternativo + Agente Coletor |
| **RabbitMQ** | AMQP / HTTP | `5672`, `15672` | `5672`, `15672` | Fila de mensageria central + Painel Web de gerenciamento |
| **Backend API** | HTTP REST | `8000` | `8000` | FastAPI Server exposing Twins and historical data |
| **Banco SQLite** | Local File | N/A | N/A | Arquivo local `database.db` no container Backend |

---

## 4. Stack Tecnológico Detalhado

* **Linguagem Principal:** Python 3.11.
* **Bibliotecas IoT:**
  * `paho-mqtt` para clientes e assinaturas MQTT.
  * `aiocoap` (assíncrono) para implementação do cliente e servidor CoAP.
* **Mensageria Central:**
  * `RabbitMQ` rodando na imagem Docker oficial.
  * `pika` (Python) para conexão, declaração de exchanges/filas e publicação/consumo de mensagens AMQP.
* **Framework Backend / REST:**
  * `FastAPI` para endpoints HTTP rápidos, com documentação automática Swagger UI `/docs`.
  * `Uvicorn` como servidor ASGI para executar a API REST.
* **Persistência de Dados:**
  * `sqlite3` nativo do Python para persistência de métricas agregadas e histórico de eventos.
* **Orquestração e Execução:**
  * Contêineres `Docker` isolados para os simuladores, gateways, backend e broker.
  * `Docker Compose` configurado com múltiplos perfis de cenários.
