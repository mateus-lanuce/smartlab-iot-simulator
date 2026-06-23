import asyncio
import os
import json
import random
from datetime import datetime
import requests
import paho.mqtt.client as mqtt
from aiocoap import Message, Context, POST

# Configurações do Ambiente
LAB_ID = os.getenv("LAB_ID", "LAB1")
PROTOCOL = os.getenv("PROTOCOL", "MQTT")
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "localhost")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "1883"))
INTERVAL = float(os.getenv("INTERVAL", "5.0"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "backend")

CURRENT_SCENARIO = "NORMAL"
ROOM_TEMPERATURE = 22.0

# Cliente MQTT global
mqtt_client = None
# Contexto CoAP global
coap_context = None

def init_mqtt(host, port):
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=f"Simulador_{LAB_ID}")
    try:
        mqtt_client.connect(host, port, 60)
        mqtt_client.loop_start()
        print(f"MQTT conectado ao gateway {host}:{port}")
    except Exception as e:
        print(f"Erro ao conectar MQTT: {e}")

async def init_coap():
    global coap_context
    coap_context = await Context.create_client_context()
    print("Contexto CoAP criado com sucesso.")

async def send_data(topic, path, payload):
    global PROTOCOL, GATEWAY_HOST, GATEWAY_PORT, mqtt_client, coap_context
    payload["timestamp"] = datetime.utcnow().isoformat() + "Z"

    if PROTOCOL == "MQTT":
        if mqtt_client:
            try:
                mqtt_client.publish(topic, json.dumps(payload), qos=1)
            except Exception as e:
                print(f"Falha ao enviar MQTT: {e}")
    else:  # CoAP
        if coap_context is None:
            await init_coap()
        # CoAP URL: coap://host:port/path
        uri = f"coap://{GATEWAY_HOST}:{GATEWAY_PORT}{path}"
        payload_bytes = json.dumps(payload).encode("utf-8")
        request = Message(code=POST, payload=payload_bytes, uri=uri)
        try:
            await asyncio.wait_for(coap_context.request(request).response, timeout=4.0)
            if "AC" in uri or "PROJ" in uri:
                print(f"CoAP enviado com sucesso para {uri}")
        except Exception as e:
            print(f"Falha ao enviar CoAP para {uri}: {e}")
            coap_context = None

# Tarefa de polling para buscar cenário do backend central
async def poll_scenario_task():
    global CURRENT_SCENARIO, BACKEND_HOST
    while True:
        try:
            # Busca o cenário atual no Backend Central
            r = await asyncio.to_thread(requests.get, f"http://{BACKEND_HOST}:8000/api/simulation/scenario/{LAB_ID}", timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                new_scenario = data.get("scenario", "NORMAL")
                if new_scenario != CURRENT_SCENARIO:
                    print(f"[{LAB_ID}] Mudando cenário de {CURRENT_SCENARIO} para {new_scenario}")
                    CURRENT_SCENARIO = new_scenario
        except Exception:
            # Backend pode estar fora do ar temporariamente, ignora
            pass
        await asyncio.sleep(3)

# Atualização da temperatura ambiente compartilhada do lab
async def update_room_temp_task():
    global CURRENT_SCENARIO, ROOM_TEMPERATURE
    while True:
        if CURRENT_SCENARIO == "FALHA":
            # Sem ar-condicionado, temperatura sobe progressivamente
            if ROOM_TEMPERATURE < 35.0:
                ROOM_TEMPERATURE += random.uniform(0.3, 0.7)
        elif CURRENT_SCENARIO == "PICO":
            # Sala cheia, temperatura tende a subir levemente mesmo com ar
            target_temp = 24.5
            ROOM_TEMPERATURE += (target_temp - ROOM_TEMPERATURE) * 0.1 + random.uniform(-0.1, 0.1)
        else:
            # Uso normal, ar-condicionado mantém ~22.0
            target_temp = 22.0
            ROOM_TEMPERATURE += (target_temp - ROOM_TEMPERATURE) * 0.2 + random.uniform(-0.1, 0.1)
        
        await asyncio.sleep(5)

# Simulação de um Computador (PC)
async def simulate_pc(pc_id):
    global CURRENT_SCENARIO, ROOM_TEMPERATURE, INTERVAL
    topic = f"laboratorio/{LAB_ID}/dispositivo/{pc_id}/telemetria"
    path = f"/laboratorio/{LAB_ID}/dispositivo/{pc_id}"

    # Variáveis de estado persistentes do PC para simular variações realistas
    cpu_base = 10.0
    ram_base = 30.0

    while True:
        # Define métricas de acordo com o cenário
        if CURRENT_SCENARIO == "PICO":
            status = "EM_PROVA"
            aplicacao = "VS Code + Docker"
            cpu = random.uniform(70.0, 90.0)
            ram = random.uniform(65.0, 85.0)
            rede = random.uniform(500.0, 1500.0)
            evento_seg = None
        elif CURRENT_SCENARIO == "SOBRECARGA":
            status = "ATIVO"
            aplicacao = "stress-ng --cpu 4"
            cpu = random.uniform(95.0, 100.0)
            ram = random.uniform(85.0, 95.0)
            rede = random.uniform(100.0, 300.0)
            evento_seg = None
        elif CURRENT_SCENARIO == "ANOMALO" and pc_id in [f"{LAB_ID}-PC03", f"{LAB_ID}-PC07"]:
            # Simula software não autorizado
            status = "ATIVO"
            aplicacao = "xmrig (Crypto Miner)"
            cpu = random.uniform(90.0, 98.0)
            ram = random.uniform(40.0, 60.0)
            rede = random.uniform(10.0, 30.0)
            evento_seg = "SOFTWARE_NAO_AUTORIZADO"
        else:  # NORMAL ou FALHA
            # Pequeno ruído aleatório
            status = "ATIVO" if random.random() > 0.15 else "OCIOSO"
            if status == "ATIVO":
                aplicacao = random.choice(["Chrome", "VS Code", "Terminal", "Slack"])
                cpu = max(2.0, min(95.0, cpu_base + random.gauss(5, 10)))
                ram = max(10.0, min(95.0, ram_base + random.gauss(2, 5)))
                rede = random.uniform(20.0, 150.0)
            else:
                aplicacao = "Nenhuma"
                cpu = random.uniform(1.0, 5.0)
                ram = random.uniform(15.0, 25.0)
                rede = random.uniform(0.1, 2.0)
            evento_seg = None

        # Temperatura do PC é influenciada pelo uso de CPU e temperatura da sala
        temperatura = ROOM_TEMPERATURE + (cpu * 0.5) + random.uniform(-1.0, 1.0)

        payload = {
            "id": pc_id,
            "cpu": round(cpu, 1),
            "ram": round(ram, 1),
            "temperatura": round(temperatura, 1),
            "status": status,
            "aplicacao": aplicacao,
            "rede_kbps": round(rede, 1),
            "evento_seguranca": evento_seg
        }

        await send_data(topic, path, payload)
        await asyncio.sleep(INTERVAL)

# Simulação do Ar-Condicionado (AC)
async def simulate_ac(ac_id):
    global CURRENT_SCENARIO, ROOM_TEMPERATURE, INTERVAL
    topic = f"laboratorio/{LAB_ID}/dispositivo/{ac_id}/telemetria"
    path = f"/laboratorio/{LAB_ID}/dispositivo/{ac_id}"

    while True:
        if CURRENT_SCENARIO == "FALHA":
            ligado = False
            modo = "VENTILAR"
            consumo = 0.1
            co2 = random.uniform(600.0, 800.0)
            lux = random.uniform(400.0, 500.0)
            ocupacao = random.randint(1, 3)
        elif CURRENT_SCENARIO == "PICO":
            ligado = True
            modo = "RESFRIAR"
            consumo = 2.2
            co2 = random.uniform(1200.0, 1600.0)
            lux = random.uniform(120.0, 180.0)
            ocupacao = random.randint(10, 12)
        elif CURRENT_SCENARIO == "SOBRECARGA":
            ligado = True
            modo = "RESFRIAR"
            consumo = 1.8
            co2 = random.uniform(850.0, 1100.0)
            lux = random.uniform(350.0, 450.0)
            ocupacao = random.randint(6, 10)
        else: # NORMAL ou ANOMALO
            ligado = True
            modo = "RESFRIAR"
            consumo = 1.4
            co2 = random.uniform(400.0, 550.0)
            lux = random.uniform(450.0, 550.0)
            ocupacao = random.randint(3, 8)

        payload = {
            "id": ac_id,
            "ligado": ligado,
            "temperatura_ambiente": round(ROOM_TEMPERATURE, 1),
            "consumo_kwh": round(consumo + random.uniform(-0.05, 0.05), 2),
            "modo": modo,
            "co2_ppm": round(co2, 1),
            "luminosidade_lux": round(lux, 1),
            "ocupacao_pessoas": ocupacao
        }

        await send_data(topic, path, payload)
        await asyncio.sleep(INTERVAL)

# Simulação do Projetor Multimídia
async def simulate_projector(proj_id):
    global CURRENT_SCENARIO, INTERVAL
    topic = f"laboratorio/{LAB_ID}/dispositivo/{proj_id}/telemetria"
    path = f"/laboratorio/{LAB_ID}/dispositivo/{proj_id}"

    tempo_uso = 0

    while True:
        # Projetor ligado em uso normal ou pico
        ligado = CURRENT_SCENARIO in ["NORMAL", "PICO", "SOBRECARGA", "ANOMALO"]
        
        if ligado:
            tempo_uso += int(INTERVAL / 60) or 1
            temp_interna = 55.0 + (tempo_uso * 0.05 if tempo_uso < 120 else 6.0) + random.uniform(-0.5, 0.5)
            consumo = 0.35
            entrada = "HDMI1"
        else:
            tempo_uso = 0
            temp_interna = ROOM_TEMPERATURE + random.uniform(0.0, 1.0)
            consumo = 0.01
            entrada = "SEM_SINAL"

        payload = {
            "id": proj_id,
            "ligado": ligado,
            "tempo_uso_minutos": tempo_uso,
            "temperatura_interna": round(temp_interna, 1),
            "entrada_video": entrada,
            "consumo_kwh": round(consumo + random.uniform(-0.01, 0.01), 3)
        }

        await send_data(topic, path, payload)
        await asyncio.sleep(INTERVAL)

async def main():
    global PROTOCOL, GATEWAY_HOST, GATEWAY_PORT
    print(f"=== Iniciando Simulador {LAB_ID} ({PROTOCOL}) ===")
    
    if PROTOCOL == "MQTT":
        init_mqtt(GATEWAY_HOST, GATEWAY_PORT)
    else:
        await init_coap()

    # Inicia tarefas auxiliares
    tasks = [
        asyncio.create_task(poll_scenario_task()),
        asyncio.create_task(update_room_temp_task()),
        asyncio.create_task(simulate_ac(f"{LAB_ID}-AC01")),
        asyncio.create_task(simulate_projector(f"{LAB_ID}-PROJ01"))
    ]

    # Inicia os 10 computadores
    for i in range(1, 11):
        pc_id = f"{LAB_ID}-PC{i:02d}"
        tasks.append(asyncio.create_task(simulate_pc(pc_id)))

    # Mantém a execução
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
