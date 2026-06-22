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

## 3. Microsserviços e Processamento de Eventos

O Backend rodará workers em threads ou processos assíncronos que consomem as filas do RabbitMQ e aplicam a inteligência de negócios.

### 3.1 Gerenciamento do Ciclo de Vida dos Digital Twins
* Ao receber qualquer mensagem de status/telemetria, o worker atualiza a tabela `digital_twins`.
* **Heartbeat / Checagem Online:** Uma thread periódica (a cada 30 segundos) varre os Digital Twins e marca como `online = False` qualquer dispositivo cuja coluna `last_update` seja superior a 20 segundos atrás, gerando um evento na tabela `events_history` com tipo `CONECTIVIDADE` e severidade `WARNING`.

### 3.2 Lógica de Correlação e Geração de Alertas Inteligentes
Além das anomalias simples detectadas na borda, o backend executa correlações de eventos complexas:

1. **Risco de Colapso Térmico (Fila `environment` + `status`):**
   * *Correlação:* Se a temperatura do laboratório estiver subindo progressivamente (> 28°C) E a média de CPU do laboratório estiver alta (> 75%), gera um alerta inteligente crítico: `"Risco iminente de colapso de hardware devido à falha de resfriamento em alta carga"`.
2. **Ineficiência Energética (Fila `energy` + `status`):**
   * *Correlação:* Se o Ar-Condicionado ou o Projetor estiverem ativos, mas a ocupação do laboratório for zero (PCs ativos = 0 por mais de 10 minutos), gera um alerta de eficiência: `"Dispositivo de alto consumo ativo em laboratório ocioso"`.
3. **Pico Coletivo de Carga:**
   * *Correlação:* Se > 80% das máquinas do laboratório mudarem o estado para `"EM_PROVA"` ao mesmo tempo, ajusta automaticamente as médias móveis de carga e notifica o painel.
