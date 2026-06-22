# Módulo 3: Backend Central e Gêmeos Digitais (Digital Twins)

Este documento descreve as engrenagens internas do servidor central e microsserviço Python, detalhando a mensageria central, a persistência do estado e a inteligência de negócios.

---

## 1. Topologia de Filas no RabbitMQ Central

O backend do **SmartLab IoT** comunica-se com os coletores periféricos por meio de mensageria assíncrona. Ele declara uma exchange do tipo `topic` chamada `iot_topic_exchange` e divide as mensagens em 4 filas duráveis para garantir isolamento e escalabilidade no processamento:

| Fila | Binding Routing Key | Propósito e Payload |
| :--- | :--- | :--- |
| **`alerts_queue`** | `*.alert` | Consome alertas instantâneos de CPU crítica, segurança e sobreaquecimento. |
| **`status_queue`** | `*.status` | Consome as telemetrias e status consolidados dos computadores e labs. |
| **`energy_queue`** | `*.energy` | Consome dados de consumo de energia consolidados (kW) de cada sala. |
| **`environment_queue`** | `*.environment` | Consome telemetrias térmicas dos ar-condicionados (climatização). |

### Garantias de Entrega (`basic_ack`)
O backend utiliza a política de **confirmações manuais (Acknowledge)**. O consumidor do RabbitMQ em [backend.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/backend.py#L200-L411) processa a mensagem, abre uma transação no banco SQLite, persiste os dados do twin/alerta, dispara o broadcast WebSocket e, apenas ao final de tudo, executa `ch.basic_ack(delivery_tag=method.delivery_tag)`. 

Isso garante que, se o contêiner do backend falhar ou reiniciar durante o processamento de uma mensagem, o RabbitMQ não a removerá e a entregará novamente assim que o backend reestabelecer.

---

## 2. Modelagem Física do Banco de Dados (SQLite)

O banco central `database.db` armazena dados operacionais consolidados e históricos divididos em 3 tabelas principais:

### 1. `digital_twins`
Mantém o estado instantâneo (Gêmeo Digital) de todos os dispositivos.
```sql
CREATE TABLE IF NOT EXISTS digital_twins (
    device_id TEXT PRIMARY KEY,       -- Ex: LAB1-PC05, LAB1-AC01
    lab_id TEXT NOT NULL,             -- Ex: LAB1
    device_type TEXT NOT NULL,        -- PC, AR_CONDICIONADO, PROJETOR, ENERGY_SENSOR
    status TEXT NOT NULL,             -- ATIVO, OCIOSO, EM_PROVA, LIGADO, DESLIGADO
    online BOOLEAN NOT NULL,          -- 1 se enviando dados ativamente, 0 caso contrário
    last_update DATETIME NOT NULL,    -- Timestamp ISO8601 da última telemetria
    metrics_json TEXT NOT NULL        -- JSON serializado contendo telemetrias voláteis (CPU, RAM, etc.)
);
```

### 2. `events_history`
Registra todo o histórico de alertas e eventos gerados no sistema.
```sql
CREATE TABLE IF NOT EXISTS events_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT,                   -- Dispositivo de origem (pode ser NULL para eventos da sala)
    lab_id TEXT NOT NULL,             -- Laboratório
    timestamp DATETIME NOT NULL,      -- Horário da ocorrência
    event_type TEXT NOT NULL,         -- ALERTA, ENERGIA, CONECTIVIDADE, SEGURANCA, etc.
    description TEXT NOT NULL,        -- Descrição detalhada do incidente
    severity TEXT NOT NULL            -- INFO, WARNING, CRITICAL
);
```

### 3. `lab_statistics`
Armazena a série temporal das médias do laboratório para relatórios históricos.
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

## 3. Gerenciamento do Ciclo de Vida (Heartbeat Monitor)

Como os dispositivos IoT podem perder energia ou sinal de rede sem enviar um aviso prévio ("Graceful Shutdown"), o backend implementa um **Monitor de Inatividade**.

* **Funcionamento:** Uma thread em segundo plano ([backend.py:L418-L462](file:///c:/Users/mateus/Documents/projeto_ph/backend/backend.py#L418-L462)) varre a tabela `digital_twins` a cada 10 segundos, buscando registros marcados como `online = 1`.
* **Detecção:** O monitor calcula a diferença de tempo entre o horário atual e a coluna `last_update`. Se essa diferença for superior a **20 segundos**, o status é atualizado para `online = 0`.
* **Geração de Evento:** O monitor insere um alerta de queda de conectividade na tabela `events_history`: `"Dispositivo LABX-PCYY perdeu conexao (timeout de 20s)"` com severidade `WARNING` e notifica os clientes.

---

## 4. Correlação de Eventos Complexos (CEP)

Além de receber alertas simples da borda, o backend central correlaciona métricas que trafegam em filas distintas para tomar decisões inteligentes de infraestrutura:

### A. Risco de Colapso Térmico
* **Dados Cruzados:** Temperatura ambiente (fila `environment`) e uso de CPU médio dos computadores (fila `status`).
* **Lógica:** Se a média de CPU dos computadores for superior a **75%** e a temperatura da sala for superior a **28°C**, o backend conclui que as máquinas estão trabalhando em carga máxima sob refrigeração ineficiente.
* **Resultado:** Dispara um alerta crítico: `"Risco iminente de colapso de hardware devido à falha de resfriamento em alta carga"`.

### B. Ineficiência Energética (Desperdício)
* **Dados Cruzados:** Ocupação do laboratório (fila `status`) e estado de ar-condicionado/projetor (tabela `digital_twins`).
* **Lógica:** Se o Ar-Condicionado ou o Projetor estiverem ativos (`LIGADO`), mas a contagem de PCs ativos na sala for exatamente **0** por mais de 10 minutos.
* **Resultado:** Dispara um alerta de desperdício energético: `"Desperdicio de Energia: Equipamento ligado em sala sem uso"`.
