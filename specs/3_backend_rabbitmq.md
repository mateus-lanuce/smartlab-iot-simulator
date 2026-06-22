# Spec 3: Mensageria e Microsserviços (Backend)

Este documento especifica a configuração do RabbitMQ (camada de mensageria) e a arquitetura do backend, incluindo a modelagem do banco de dados SQLite para os Digital Twins e a lógica de correlação de eventos.

---

## 1. Topologia e Configuração do RabbitMQ

O RabbitMQ atua como o middleware de comunicação assíncrona entre os Gateways de Borda e o Backend Central.

### 1.1 Exchange e Roteamento
* **Nome da Exchange:** `iot_topic_exchange`
* **Tipo da Exchange:** `topic`
* **Persistência:** Durável (`durable=True`).

### 1.2 Filas e Bindings
Serão declaradas 4 filas duráveis para isolar os propósitos de processamento:

| Nome da Fila | Routing Key de Binding | Tipo de Mensagem Recebida |
| :--- | :--- | :--- |
| `alerts_queue` | `*.alert` | Alertas críticos instantâneos (sobreaquecimento, segurança) |
| `energy_queue` | `*.energy` | Dados de consumo elétrico agregados |
| `environment_queue` | `*.environment` | Climatização, temperatura e sensores adicionais |
| `status_queue` | `*.status` | Métricas operacionais consolidadas dos laboratórios |

*O asterisco (`*`) na routing key representa o identificador do laboratório (ex: `LAB1.alert`, `LAB2.status`).*

### 1.3 Garantia de Entrega (Delivery Guarantees)
* **Acks Manuais (`no_ack=False`):** O backend só confirmará a leitura (acknowledge) da mensagem após sua gravação bem-sucedida no SQLite e atualização do Digital Twin correspondente.
* **Mensagens Persistentes:** Publicadas com `delivery_mode=2` para não serem perdidas caso o RabbitMQ reinicie.

---

## 2. Persistência de Dados e Digital Twins (SQLite)

O Backend mantém o estado atualizado de todos os dispositivos (**Digital Twin**) e o histórico de eventos utilizando um banco de dados relacional leve **SQLite** (`database.db`).

### Schema do Banco de Dados

```sql
-- 1. Estado Atual dos Dispositivos (Digital Twins)
CREATE TABLE IF NOT EXISTS digital_twins (
    device_id TEXT PRIMARY KEY,       -- Ex: LAB1-PC05
    lab_id TEXT NOT NULL,             -- Ex: LAB1
    device_type TEXT NOT NULL,        -- PC, AR_CONDICIONADO, PROJETOR
    status TEXT NOT NULL,             -- ATIVO, OCIOSO, EM_PROVA, LIGADO, DESLIGADO, etc.
    online BOOLEAN NOT NULL,          -- TRUE se recebendo dados ativamente, FALSE caso contrário
    last_update DATETIME NOT NULL,    -- Timestamp da última telemetria
    metrics_json TEXT NOT NULL        -- Dados de telemetria em JSON (CPU, RAM, temperatura, consumo)
);

-- 2. Histórico de Eventos e Alertas
CREATE TABLE IF NOT EXISTS events_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT,                   -- Dispositivo de origem (pode ser NULL para eventos do lab)
    lab_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    event_type TEXT NOT NULL,         -- ALERTA, ENERGIA, CONECTIVIDADE, SEGURANCA
    description TEXT NOT NULL,
    severity TEXT NOT NULL            -- INFO, WARNING, CRITICAL
);

-- 3. Métricas Consolidadas e Histórico de Laboratório
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

## 3. Arquitetura de Microsserviços do Backend

O backend é decomposto em **4 microsserviços independentes** operando de forma autônoma e colaborando via mensageria e persistência compartilhada em disco:

### 3.1 API Gateway / Central Web Service (`backend_api.py`)
* **Responsabilidade:** Interface externa REST (HTTP) e em tempo real (WebSockets).
* **Comportamento:**
  * Expõe endpoints públicos `/labs/...`, `/twins/...` e `/alerts`.
  * Mantém conexões WebSocket na rota `/ws`.
  * Assina uma fila temporária exclusiva com routing key `#` para capturar todos os eventos e transmiti-los aos WebSockets em tempo real.
  * Serve os arquivos do Dashboard estático em `/static`.

### 3.2 Twin & Statistics Worker (`worker_twin.py`)
* **Responsabilidade:** Atualização dos Digital Twins e cálculo de estatísticas consolidadas.
* **Comportamento:**
  * Consome as filas `status_queue`, `energy_queue` e `environment_queue`.
  * Grava os dados na tabela `digital_twins` e `lab_statistics`.
  * **Correlação Complexa de Eventos (CEP):**
    1. *Risco de Colapso Térmico:* Se Temp Ambiente > 28°C E CPU média > 75%, publica um alerta `{lab_id}.alert` no RabbitMQ.
    2. *Ineficiência Energética:* Se PCs ativos = 0 E AC/PROJ ligado=True por mais de 10m, publica `{lab_id}.alert` no RabbitMQ.

### 3.3 Alerts & Events Worker (`worker_alerts.py`)
* **Responsabilidade:** Persistência transacional e catalogação de incidentes.
* **Comportamento:**
  * Consome a fila `alerts_queue`.
  * Insere os registros na tabela `events_history` do SQLite central.

### 3.4 Heartbeat & Connectivity Monitor (`service_monitor.py`)
* **Responsabilidade:** Varredura periódica de inatividade e checagem de timeout.
* **Comportamento:**
  * Roda a cada 10s consultando a tabela `digital_twins`.
  * Se `last_update` de um twin online for superior a 20s atrás, marca `online = 0` no banco e publica um alerta crítico `QUEDA_CONEXAO` no RabbitMQ com chave de roteamento `{lab_id}.alert`.

---

## 4. Persistência Compartilhada Concorrente (SQLite WAL)

Os microsserviços acessam simultaneamente o mesmo arquivo SQLite (`database.db`) no volume Docker compartilhado. Para evitar conflitos de bloqueio de escrita (database locks), as conexões seguem as seguintes diretrizes:
1. **Modo WAL (Write-Ahead Logging) Ativado:** Permite múltiplos leitores concorrentes enquanto uma escrita está em andamento.
2. **Timeout Estendido (15s):** As conexões esperam até 15s pela liberação de travas de escrita antes de falhar.
3. **Desacoplamento de Escritas:** Cada tabela possui escritas efetuadas preferencialmente por um único microsserviço dedicadamente.
