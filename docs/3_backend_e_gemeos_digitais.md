# Módulo 3: Backend Central e Gêmeos Digitais (Digital Twins)

Este documento descreve as engrenagens internas do servidor central e da **arquitetura de microsserviços orientada a eventos** do **SmartLab IoT**, detalhando os serviços decompostos, a persistência concorrente em banco compartilhado com SQLite WAL e a lógica de inteligência de negócios.

---

## 1. Arquitetura Decomposta em Microsserviços

O backend central foi dividido em **4 serviços independentes e autônomos**, cada um executando em seu próprio contêiner isolado e desempenhando um papel específico:

```text
                             ┌───────────────────────┐
                             │    Gateways de Borda  │
                             └───────────┬───────────┘
                                         │ (MQTT / CoAP)
                                         ▼
                             ┌───────────────────────┐
                             │    RabbitMQ Broker    │
                             └─────┬───┬───┬───┬─────┘
                                   │   │   │   │
        ┌──────────────────────────┘   │   │   └──────────────────────────┐
        │ (*.status / *.energy)        │   │ (*.alert)                    │ (Todos os eventos)
        ▼                              │   ▼                              ▼
┌──────────────┐                       │ ┌──────────────┐          ┌──────────────┐
│ Twin Worker  │                       │ │Alerts Worker │          │ API Gateway  │
│              │                       │ │              │          │              │
│ - Atualiza   │                       │ │ - Persiste   │          │ - HTTP REST  │
│   Twins      │                       │ │   Alertas    │          │ - WebSockets │
│ - CEP rules  │                       │ └──────┬───────┘          └──────┬───────┘
└──────┬───────┘                       │        │                         │
       │                               │        │                         │
       │      ┌────────────────────────┘        │                         │
       ▼      ▼ (Gera novo *.alert)             ▼                         │
   ┌─────────────┐                       ┌─────────────┐                  │
   │  Shared DB  │◄──────────────────────┤   Monitor   │                  │
   │  (SQLite)   │                       │ (Heartbeat) │                  │
   └─────────────┘                       └─────────────┘                  │
          ▲                                                               │
          └───────────────────── (Leituras REST) ─────────────────────────┘
```

### 1. API Gateway ([backend_api.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/backend_api.py))
* **Papel:** Ponto central de interação externa com a Camada de Apresentação.
* **Funcionalidades:**
  * Serve os arquivos estáticos da SPA do Dashboard Web.
  * Expõe endpoints REST (`/api/labs/...`, `/api/twins/...`, `/api/alerts`) consultando o banco SQLite comum.
  * Gerencia conexões **WebSockets** ativas (`/ws`).
  * Assina uma fila exclusiva no RabbitMQ ouvindo todos os tópicos (`#`) para receber e repassar instantaneamente quaisquer atualizações e alertas aos WebSockets ativos.

### 2. Twin & Statistics Worker ([worker_twin.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/worker_twin.py))
* **Papel:** Processamento e consolidação de telemetrias e dados operacionais/energéticos.
* **Funcionalidades:**
  * Consome as filas `status_queue`, `energy_queue` e `environment_queue`.
  * Grava os estados instantâneos dos computadores, projetores e ar-condicionados em `digital_twins`.
  * Consolida estatísticas agregadas periódicas em `lab_statistics`.
  * Executa a correlação de eventos CEP (Risco de Colapso Térmico e Desperdício Energético).

### 3. Alerts & Events Worker ([worker_alerts.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/worker_alerts.py))
* **Papel:** Persistência exclusiva de incidentes do sistema.
* **Funcionalidades:**
  * Consome a fila `alerts_queue`.
  * Grava alertas (gerados na borda ou pelos outros microsserviços) na tabela `events_history` do SQLite compartilhado.

### 4. Heartbeat & Connectivity Monitor ([service_monitor.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/service_monitor.py))
* **Papel:** Verificação ativa da conectividade física dos dispositivos.
* **Funcionalidades:**
  * Roda um loop contínuo (a cada 10 segundos).
  * Varre a tabela `digital_twins` e, caso detecte inatividade maior que 20 segundos para algum dispositivo online, altera localmente seu estado e emite um alerta `QUEDA_CONEXAO` no RabbitMQ (`{lab_id}.alert`).

---

## 2. Topologia de Filas no RabbitMQ Central

O backend comunica-se de forma assíncrona por meio do RabbitMQ central. Ele declara a exchange `iot_topic_exchange` (tipo `topic`) e vincula as seguintes filas:

| Fila | Binding Routing Key | Propósito e Payload |
| :--- | :--- | :--- |
| **`alerts_queue`** | `*.alert` | Alarmes de CPU crítica, temperatura da sala e segurança. |
| **`status_queue`** | `*.status` | Telemetrias e status consolidados dos laboratórios. |
| **`energy_queue`** | `*.energy` | Dados de consumo de energia acumulados por laboratório. |
| **`environment_queue`** | `*.environment` | Status e sensores ambientais do ar-condicionado (CO2, ocupação, lux). |

### Garantias de Entrega (`basic_ack`)
Todos os workers operam com **confirmações manuais (Acknowledge)**. O worker recebe a mensagem, realiza as operações necessárias de processamento e persistência no banco SQLite central, e apenas ao final dispara `ch.basic_ack(delivery_tag=method.delivery_tag)`. Se um contêiner for desligado repentinamente durante o processamento, a mensagem retorna à fila do RabbitMQ e é reprocessada por outro worker disponível assim que ele reestabelecer.

---

## 3. Concorrência de Banco de Dados com SQLite WAL

Como 4 contêineres gravam e leem simultaneamente no mesmo arquivo de banco de dados (`data/database.db`), implementamos uma estratégia centralizada em [shared_db.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/shared_db.py) para evitar travamentos de concorrência (`database is locked`):

1. **Write-Ahead Logging (WAL):** Ativado através da pragma `PRAGMA journal_mode=WAL;`. No modo WAL, o SQLite permite múltiplos leitores simultâneos com um escritor concorrente ativo, reduzindo drasticamente os bloqueios.
2. **Busy Timeout de 15 Segundos:** A conexão é inicializada com `PRAGMA busy_timeout = 15000;`. Caso ocorra contenção temporária de escrita, a thread do SQLite aguardará de forma transparente até 15 segundos antes de gerar uma exceção, eliminando falhas de concorrência entre os microsserviços.
3. **Mecanismo de Conexão Contextual:** Utilização de um gerenciador de contexto `contextmanager` do Python para garantir abertura atômica, execução transacional segura (auto-commit/rollback) e fechamento limpo das conexões de banco de dados.

---

## 4. Modelagem Física do Banco de Dados

O arquivo central `database.db` possui 3 tabelas fundamentais:

### 1. `digital_twins`
Mantém o estado instantâneo (Gêmeo Digital) de todos os dispositivos do sistema, incluindo os sensores ambientais opcionais integrados (CO2, luminosidade, ocupação):
```sql
CREATE TABLE IF NOT EXISTS digital_twins (
    device_id TEXT PRIMARY KEY,
    lab_id TEXT NOT NULL,
    device_type TEXT NOT NULL,
    status TEXT NOT NULL,
    online BOOLEAN NOT NULL,
    last_update DATETIME NOT NULL,
    metrics_json TEXT NOT NULL
);
```

### 2. `events_history`
Registra incidentes operacionais detectados na borda ou inferidos no backend central:
```sql
CREATE TABLE IF NOT EXISTS events_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT,
    lab_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL
);
```

### 3. `lab_statistics`
Série temporal de dados consolidados das salas para geração de médias históricas:
```sql
CREATE TABLE IF NOT EXISTS lab_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    cpu_avg REAL,
    ram_avg REAL,
    temp_avg REAL,
    active_pcs INTEGER,
    total_energy REAL
);
```

---

## 5. Lógica de Correlação de Eventos Complexos (CEP)

Implementada no [worker_twin.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/worker_twin.py), a inteligência correlaciona dados recebidos de canais e dispositivos diferentes na mesma sala:

### A. Risco de Colapso Térmico
* **Cruzamento:** Temperatura da sala (ar-condicionado) e média de CPU dos computadores.
* **Critério:** Média de CPU > 75% **E** Temperatura Ambiente > 28°C.
* **Resultado:** Publica alerta `{lab_id}.alert` indicando risco de colapso devido à alta carga sob resfriamento ineficiente.

### B. Ineficiência Energética (Desperdício)
* **Cruzamento:** Ocupação do ambiente (sensor do ar-condicionado) e computadores ativos na sala.
* **Critério:** Ar-Condicionado ou Projetor ligado = True **E** Contagem de PCs ativos = 0 (ou seja, sala vazia).
* **Resultado:** Publica alerta `{lab_id}.alert` indicando desperdício energético após 10 minutos de inatividade detectada.
