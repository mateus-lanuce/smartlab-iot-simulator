# Spec 1: Camada de Dispositivos e Simulação IoT

Este documento detalha a simulação de hardware concorrente dos dispositivos físicos dos laboratórios (Computadores, Ar-condicionado e Projetores) e o envio dos dados via protocolos MQTT e CoAP utilizando Docker.

---

## 1. Escopo da Simulação

O ecossistema a ser simulado compreende os seguintes dispositivos distribuídos uniformemente em **3 laboratórios**:

| Tipo de Dispositivo | Quantidade por Lab | Total Geral | Variáveis Principais |
| :--- | :--- | :--- | :--- |
| **Computador (PC)** | 10 | 30 | CPU, RAM, Temperatura do Processador, Estado de Uso, Aplicação, Rede, Alertas |
| **Ar-Condicionado (AC)** | 1 | 3 | Temperatura do Lab, Estado (On/Off), Consumo, Modo de Operação |
| **Projetor Multimídia** | 1 | 3 | Estado (On/Off), Tempo de Uso, Temperatura Interna, Entrada Ativa, Consumo |

### Frequência de Envio (Mapeamento de Telemetria)
* Os dispositivos devem gerar e enviar telemetrias periodicamente a cada **5 segundos** (ajustável por variável de ambiente).
* Variações realistas de comportamento devem ser implementadas usando ruído estatístico (ex: caminhada aleatória com `random.gauss` ou `random.uniform`).

---

## 2. Contratos de Dados (Formatos JSON)

### 2.1 Computador (PC)
```json
{
  "id": "LAB1-PC05",
  "timestamp": "2026-06-22T00:10:00Z",
  "cpu": 24.5,
  "ram": 55.2,
  "temperatura": 48.3,
  "status": "ATIVO",
  "aplicacao": "VS Code",
  "rede_kbps": 256.4,
  "evento_seguranca": null
}
```
* **Estados de Uso (`status`):** `ATIVO`, `OCIOSO`, `EM_PROVA`, `MANUTENCAO`.
* **Eventos de Segurança (`evento_seguranca`):** `null`, `"SOFTWARE_NAO_AUTORIZADO"`, `"TENTATIVA_INVASÃO"`, `"USO_FORA_DO_HORARIO"`.

### 2.2 Ar-Condicionado (AC)
```json
{
  "id": "LAB1-AC01",
  "timestamp": "2026-06-22T00:10:00Z",
  "ligado": true,
  "temperatura_ambiente": 21.8,
  "consumo_kwh": 1.45,
  "modo": "RESFRIAR",
  "co2_ppm": 450.0,
  "luminosidade_lux": 500.0,
  "ocupacao_pessoas": 6
}
```
* **Modos de Operação (`modo`):** `RESFRIAR`, `VENTILAR`, `DESUMIDIFICAR`, `AQUECER`.
* **Métricas Opcionais integradas:** `co2_ppm` (nível de CO2), `luminosidade_lux` (lux do ambiente), `ocupacao_pessoas` (pessoas estimadas).

### 2.3 Projetor Multimídia
```json
{
  "id": "LAB1-PROJ01",
  "timestamp": "2026-06-22T00:10:00Z",
  "ligado": true,
  "tempo_uso_minutos": 90,
  "temperatura_interna": 62.4,
  "entrada_video": "HDMI1",
  "consumo_kwh": 0.28
}
```
* **Entradas de Vídeo (`entrada_video`):** `HDMI1`, `HDMI2`, `VGA`, `SEM_SINAL`.

---

## 3. Lógica de Concorrência e Simulação

A simulação de cada laboratório deve ser executada em um contêiner Docker dedicado. O script do simulador (`simulator.py`) deve seguir a seguinte estrutura:

1. **Leitura de Configuração:** Lê variáveis de ambiente (`LAB_ID`, `PROTOCOL`, `GATEWAY_HOST`, `INTERVAL`).
2. **Criação de Threads / Tasks:**
   - Cria uma thread independente (ou corotina `asyncio`) para cada um dos 10 computadores.
   - Cria uma thread independente para o ar-condicionado.
   - Cria uma thread independente para o projetor multimídia.
3. **Loop da Thread de Simulação:**
   - Cada thread mantém o seu estado (ex: se o PC está `ATIVO` e qual app está rodando).
   - Atualiza as variáveis de forma incremental a cada iteração (ex: se a CPU sobe, a temperatura tende a subir).
   - Converte o estado para a mensagem JSON estruturada.
   - Envia para o cliente de protocolo correspondente.
   - Aguarda o intervalo especificado (`INTERVAL` segundos).

---

## 4. Clientes de Protocolos IoT

### 4.1 Cliente MQTT (LAB1 e LAB3)
* **Broker Alvo:** `GATEWAY_HOST` na porta `1883` (LAB1) ou `1884` (LAB3).
* **Tópicos de Publicação:**
  * Computadores: `laboratorio/LABX/dispositivo/LABX-PCYY/telemetria`
  * Ar-Condicionado: `laboratorio/LABX/dispositivo/LABX-AC01/telemetria`
  * Projetor: `laboratorio/LABX/dispositivo/LABX-PROJ01/telemetria`
* **Configuração:** QoS = 1 (garantia de entrega simples).

### 4.2 Cliente CoAP (LAB2)
* **Servidor Alvo:** `coap://GATEWAY_HOST:5683`
* **Recursos CoAP de destino (POST / PUT):**
  * Computadores: `/laboratorio/LAB2/dispositivo/LAB2-PCYY`
  * Ar-Condicionado: `/laboratorio/LAB2/dispositivo/LAB2-AC01`
  * Projetor: `/laboratorio/LAB2/dispositivo/LAB2-PROJ01`
* **Configuração:** Mensagens do tipo `CON` (Confirmable) para simular confiabilidade.

---

## 5. Estrutura do Dockerfile de Simulação

O Dockerfile do simulador deve ser leve, baseado em Python Alpine:

```dockerfile
FROM python:3.11-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simulator.py .
CMD ["python", "simulator.py"]
```
*(As dependências no `requirements.txt` devem incluir `paho-mqtt` e `aiocoap`).*
