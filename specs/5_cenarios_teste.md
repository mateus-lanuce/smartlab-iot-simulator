# Spec 5: Orquestração de Cenários e Apresentação

Este documento detalha a implementação dos cenários de teste exigidos pelo projeto, a configuração do Docker Compose multi-serviços e os passos para a execução em ambiente real (multi-máquinas).

---

## 1. Definição dos 5 Cenários de Simulação

O simulador de dispositivos (`simulator.py`) aceitará um parâmetro dinâmico de cenário (que pode ser alterado via variável de ambiente no startup ou dinamicamente via requisição HTTP/REST que o backend propaga para os simuladores).

### Cenário 1: Uso Normal
* **Comportamento:** Carga distribuída de forma equilibrada.
* **Métricas Esperadas:**
  * CPU dos PCs: Flutuando entre 5% e 40%.
  * RAM dos PCs: Flutuando entre 20% e 50%.
  * Temperatura do PC: Estável entre 40°C e 55°C.
  * Ar-Condicionado: Ligado, mantendo a sala em ~22°C.
  * Projetor: Ligado/desligado aleatoriamente, consumo estável.

### Cenário 2: Pico de Uso (Provas ou Aulas Práticas)
* **Comportamento:** Simula o laboratório cheio com todos os alunos programando ou rodando testes pesados.
* **Métricas Esperadas:**
  * Status dos PCs: Alterado para `"EM_PROVA"`.
  * CPU dos PCs: Constante entre 70% e 90%.
  * RAM dos PCs: Elevada entre 60% e 85%.
  * Temperatura do PC: Sobe para 65°C a 75°C.
  * Consumo de Rede: Alto fluxo (ex: download de pacotes).
  * Ar-Condicionado: Forçado em modo resfriamento máximo (`RESFRIAR`).

### Cenário 3: Falha de Infraestrutura
* **Comportamento:** O ar-condicionado do laboratório é desligado remotamente ou falha de resfriamento é simulada.
* **Métricas Esperadas:**
  * Ar-Condicionado: `ligado = False`.
  * Temperatura Ambiente: Sobe progressivamente a cada leitura (+1°C a cada 5s) até estabilizar em 35°C.
  * Temperatura do PC: A temperatura do processador de cada PC sobe proporcionalmente à temperatura ambiente (ex: Temperatura_PC = Temperatura_Ambiente + CPU * 0.5).
  * Alertas Gerados: Alerta de `"Superaquecimento do Ambiente"` no Gateway e posterior `"Superaquecimento de Hardware"` nos PCs.

### Cenário 4: Sobrecarga e Estresse
* **Comportamento:** Processamento pesado induzido em múltiplas máquinas simultaneamente, levando o sistema ao limite de rede e processamento.
* **Métricas Esperadas:**
  * CPU dos PCs: Acima de 95% em mais de 80% das máquinas.
  * Temperatura do PC: Ultrapassa 85°C.
  * Alertas Gerados: Gateway dispara alerta de `"Sobrecarga do Laboratório"` (médias agregadas ultrapassam os limites) e alertas individuais de CPU Crítica.

### Cenário 5: Comportamento Anômalo
* **Comportamento:** Simulação de incidentes de segurança cibernética ou uso não autorizado.
* **Métricas Esperadas:**
  * PC-03 e PC-07 mudam `evento_seguranca` para `"SOFTWARE_NAO_AUTORIZADO"` (simulando mineração de criptomoedas ou torrent executando em background).
  * PC-10 muda `evento_seguranca` para `"USO_FORA_DO_HORARIO"` (máquina ligada e ativa durante a madrugada).
  * Alertas Gerados: Alertas imediatos de segurança de nível `CRITICAL` enviados à fila de alertas.

---

## 2. Controle de Cenários em Tempo Real

Para facilitar a apresentação, o Backend fornecerá um endpoint de controle:
* `POST /api/simulation/scenario`
* **Payload:** `{"scenario": "CENARIO_3", "lab_id": "LAB1"}`
* **Ação:** O backend recebe a requisição do Dashboard Web e envia uma mensagem de comando pelo RabbitMQ (exchange de comandos/configuração) ou via requisição direta. Os simuladores inscritos nesse laboratório recebem o comando e alteram seu comportamento de geração de ruído imediatamente.

---

## 3. Orquestração Multi-Serviços com Docker Compose

O arquivo `docker-compose.yml` será estruturado da seguinte forma:

```yaml
version: '3.8'

networks:
  iot_network:
    driver: bridge

services:
  # Broker de Mensageria Central
  rabbitmq:
    image: rabbitmq:3-management-alpine
    container_name: rabbitmq_central
    ports:
      - "5672:5672"
      - "15672:15672"
    networks:
      - iot_network

  # Gateways de Borda (Exemplo LAB1 com MQTT Mosquitto local + Agente Coletor)
  mosquitto-lab1:
    image: eclipse-mosquitto:latest
    container_name: mosquitto_lab1
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf
    networks:
      - iot_network

  gateway-lab1:
    build: ./edge_gateway
    container_name: gateway_lab1
    environment:
      - LAB_ID=LAB1
      - PROTOCOL=MQTT
      - MQTT_HOST=mosquitto-lab1
      - RABBITMQ_HOST=rabbitmq
    depends_on:
      - rabbitmq
      - mosquitto-lab1
    networks:
      - iot_network

  # Gateway de Borda LAB2 (CoAP Server integrado)
  gateway-lab2:
    build: ./edge_gateway
    container_name: gateway_lab2
    environment:
      - LAB_ID=LAB2
      - PROTOCOL=CoAP
      - COAP_PORT=5683
      - RABBITMQ_HOST=rabbitmq
    ports:
      - "5683:5683/udp"
    depends_on:
      - rabbitmq
    networks:
      - iot_network

  # Simuladores (Um contêiner para cada Lab executando múltiplos dispositivos)
  simulator-lab1:
    build: ./simulator
    container_name: simulator_lab1
    environment:
      - LAB_ID=LAB1
      - PROTOCOL=MQTT
      - GATEWAY_HOST=mosquitto-lab1
      - INTERVAL=5
    depends_on:
      - gateway-lab1
    networks:
      - iot_network

  simulator-lab2:
    build: ./simulator
    container_name: simulator_lab2
    environment:
      - LAB_ID=LAB2
      - PROTOCOL=CoAP
      - GATEWAY_HOST=gateway-lab2
      - INTERVAL=5
    depends_on:
      - gateway-lab2
    networks:
      - iot_network

  # Backend Central & API REST
  backend:
    build: ./backend
    container_name: backend_central
    ports:
      - "8000:8000"
    environment:
      - RABBITMQ_HOST=rabbitmq
    depends_on:
      - rabbitmq
    networks:
      - iot_network
```

---

## 4. Guia de Apresentação e Execução (Duas Máquinas)

Conforme as observações do PDF, a apresentação exige execução em no mínimo duas máquinas físicas:

### Configuração de Rede:
1. As duas máquinas devem estar na mesma subrede local (Wi-Fi do laboratório ou cabo de rede).
2. **Máquina 1 (Servidora):** Executa o RabbitMQ central, o Backend central e o Dashboard Web.
3. **Máquina 2 (Cliente/Borda):** Executa os Simuladores e os Gateways de Borda.

### Procedimento:
* Na Máquina 2, os Gateways de Borda e Simuladores devem ser configurados para apontar o `RABBITMQ_HOST` para o endereço IP local da Máquina 1 (ex: `192.168.1.50`), garantindo que as mensagens de telemetria agregadas atravessem a rede física e cheguem ao backend.
* O Docker Compose da Máquina 2 será iniciado omitindo os serviços `rabbitmq` e `backend`, conectando-se remotamente ao host da Máquina 1.
