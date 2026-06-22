# Spec 4: Clientes de Consumo (Tempo Real e Sob Demanda)

Este documento especifica a implementação dos dois clientes de consumo exigidos: o Cliente MQTT em Tempo Real (CLI) e a API REST do Backend acoplada ao Painel Administrativo Web.

---

## 1. Cliente MQTT em Tempo Real (CLI)

O cliente de tempo real é um script Python (`cli_mqtt_client.py`) independente que roda no terminal. Ele se conecta a um Broker MQTT (Mosquitto local do Gateway do lab ou ao RabbitMQ central caso o plugin MQTT esteja ativo) para exibir as telemetrias e alertas instantaneamente.

### 1.1 Assinatura de Tópicos
O cliente deve assinar os seguintes tópicos:
* **Status geral do laboratório:** `laboratorio/+/status`
* **Alertas e Anomalias:** `laboratorio/+/alerts`
* **Leituras específicas de CPU (opcional):** `laboratorio/+/dispositivo/+/cpu`

### 1.2 Formato de Saída (CLI)
A saída no terminal deve ser colorida (usando bibliotecas como `colorama` ou códigos ANSI) para destacar alertas:

```text
[12:10:05] [STATUS] LAB1: CPU Média = 45%, RAM Média = 52%, PCs Ativos = 8/10
[12:10:07] [ALERTA] [CRITICAL] LAB1-PC08: CPU em 98% (Superaquecimento do Processador: 87°C)
[12:10:09] [ALERTA] [WARNING] LAB2-AC01: Temperatura ambiente atingiu 31°C (Ar-Condicionado inativo)
[12:10:12] [STATUS] LAB2: CPU Média = 12%, RAM Média = 30%, PCs Ativos = 2/10
```

---

## 2. API REST do Backend (FastAPI)

O backend central expõe rotas HTTP REST para consultas sob demanda efetuadas pelo Painel Administrativo.

### Endpoints Detalhados

#### 1. Estado Atual do Laboratório
* **Rota:** `GET /api/labs/{lab_id}/status`
* **Descrição:** Retorna as médias atuais do laboratório e os estados resumidos dos seus dispositivos.
* **Exemplo de Resposta (JSON):**
  ```json
  {
    "lab_id": "LAB1",
    "timestamp": "2026-06-22T00:20:00Z",
    "cpu_avg": 42.5,
    "ram_avg": 51.0,
    "temp_avg": 46.8,
    "pcs_online": 9,
    "total_energy_kwh": 2.45,
    "alerts_count": 1
  }
  ```

#### 2. Histórico de Telemetria do Laboratório
* **Rota:** `GET /api/labs/{lab_id}/historico`
* **Parâmetros Query:** `intervalo` (padrão `24h`, aceita `1h`, `6h`, `12h`)
* **Descrição:** Retorna série temporal de métricas para gráficos e relatórios.
* **Exemplo de Resposta (JSON):**
  ```json
  [
    {"timestamp": "2026-06-22T00:00:00Z", "cpu_avg": 35.1, "temp_avg": 44.2},
    {"timestamp": "2026-06-22T00:15:00Z", "cpu_avg": 42.5, "temp_avg": 46.8}
  ]
  ```

#### 3. Digital Twin de um Dispositivo
* **Rota:** `GET /api/twins/{device_id}`
* **Descrição:** Retorna o estado completo e histórico de um dispositivo específico.
* **Exemplo de Resposta (JSON):**
  ```json
  {
    "id": "LAB1-PC12",
    "lab_id": "LAB1",
    "tipo": "PC",
    "status": "ATIVO",
    "online": true,
    "last_update": "2026-06-22T00:20:00Z",
    "metrics": {
      "cpu": 78,
      "ram": 64,
      "temperatura": 82,
      "aplicacao": "VS Code",
      "rede_kbps": 128.5
    }
  }
  ```

#### 4. Log de Alertas Ativos
* **Rota:** `GET /api/alerts`
* **Descrição:** Lista as últimas ocorrências de falhas e avisos.

---

## 3. Painel Administrativo Web (Dashboard)

Será desenvolvida uma página web estática e moderna (Single Page Application - SPA) em HTML/CSS/JS, com visual premium e tema escuro.

### 3.1 Design Visual (Aesthetics)
* **Estilo:** *Dark Mode* com *Glassmorphism* (efeito de vidro fosco, sombras suaves e bordas translúcidas).
* **Tipografia:** Fonte *Inter* (Google Fonts).
* **Paleta de Cores:**
    * Fundo: Azul escuro/grafite (`#0F172A`)
    * Cartões: `#1E293B` com transparência
    * Destaques de Status:
      * Verde (`#10B981`): Dispositivo Online / Funcionando perfeitamente.
      * Amarelo/Laranja (`#F59E0B`): Aviso / Ocioso.
      * Vermelho (`#EF4444`): Alerta Crítico / Sobreaquecimento.
      * Cinza (`#64748B`): Offline.

### 3.2 Funcionalidades do Dashboard Web
1. **Grid de Laboratórios:** Três colunas (uma para cada LAB) mostrando a média de CPU, RAM, temperatura da sala e contagem de alertas.
2. **Visualização de Dispositivos (Digital Twins):** Grid visual com 10 computadores por laboratório (representados por pequenos boxes ou ícones que mudam de cor dinamicamente com base no estado e conectividade).
3. **Seção de Alertas em Tempo Real:** Painel dinâmico inferior estilo *ticker* ou feed de logs atualizado via WebSockets (servidor FastAPI websocket na rota `/ws/alerts`) ou por polling curto de HTTP GET a cada 2 segundos.
4. **Controle de Cenários (Bônus):** Botões para ativar diretamente cenários de simulação no backend via chamadas REST (`POST /api/simulation/scenario/{id}`).
