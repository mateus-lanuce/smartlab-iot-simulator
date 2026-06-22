import asyncio
import os
import json
import sqlite3
from datetime import datetime
import pika
import paho.mqtt.client as mqtt
import aiocoap
from aiocoap import Code
import aiocoap.resource as resource
import threading

# Configurações do Gateway
LAB_ID = os.getenv("LAB_ID", "LAB1")
PROTOCOL = os.getenv("PROTOCOL", "MQTT")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
COAP_PORT = int(os.getenv("COAP_PORT", "5683"))
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
AGGREGATION_WINDOW = float(os.getenv("AGGREGATION_WINDOW", "5.0"))

# Estado Local do Gateway
DB_PATH = "gateway_buffer.db"
is_online = False
rabbitmq_conn = None
rabbitmq_channel = None
rabbitmq_lock = threading.Lock()

# Últimas leituras recebidas dos sensores (para agregação)
# Estrutura: { device_id: { "timestamp": datetime, "type": "PC"/"AC"/"PROJ", "data": {...} } }
active_readings = {}

# Dicionário de contador para CPU consecutiva (para alertas de CPU alta)
cpu_high_count = {}

# --- Banco de Dados SQLite Local (Buffer Offline) ---
def init_local_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routing_key TEXT,
            payload TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("Banco de dados SQLite do buffer inicializado.")

def save_to_buffer(routing_key, payload):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO buffer (routing_key, payload) VALUES (?, ?)",
            (routing_key, json.dumps(payload))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar no buffer SQLite: {e}")

def get_buffered_messages():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, routing_key, payload FROM buffer ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Erro ao ler buffer SQLite: {e}")
        return []

def delete_from_buffer(msg_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM buffer WHERE id = ?", (msg_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao deletar do buffer SQLite: {e}")

# --- Conexão e Publicação RabbitMQ ---
def connect_rabbitmq():
    global rabbitmq_conn, rabbitmq_channel, is_online, RABBITMQ_HOST
    with rabbitmq_lock:
        try:
            if rabbitmq_conn and not rabbitmq_conn.is_closed:
                try:
                    rabbitmq_conn.close()
                except Exception:
                    pass
            credentials = pika.PlainCredentials('guest', 'guest')
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                credentials=credentials,
                connection_attempts=3,
                retry_delay=2,
                heartbeat=0
            )
            rabbitmq_conn = pika.BlockingConnection(parameters)
            rabbitmq_channel = rabbitmq_conn.channel()
            # Declara a exchange de tópicos
            rabbitmq_channel.exchange_declare(
                exchange='iot_topic_exchange',
                exchange_type='topic',
                durable=True
            )
            is_online = True
            print(f"[{LAB_ID}] Conectado ao RabbitMQ Central ({RABBITMQ_HOST})!")
            return True
        except Exception as e:
            print(f"[{LAB_ID}] Falha ao conectar ao RabbitMQ Central: {e}")
            is_online = False
            return False

async def publish_message(routing_key, payload):
    global is_online, rabbitmq_channel
    
    if not is_online:
        print(f"[{LAB_ID}] Offline: Salvando mensagem ({routing_key}) no buffer local.")
        await asyncio.to_thread(save_to_buffer, routing_key, payload)
        return

    try:
        payload_str = json.dumps(payload)
        def do_publish():
            with rabbitmq_lock:
                rabbitmq_channel.basic_publish(
                    exchange='iot_topic_exchange',
                    routing_key=routing_key,
                    body=payload_str,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Mensagem persistente
                    )
                )
        await asyncio.to_thread(do_publish)
    except Exception as e:
        print(f"[{LAB_ID}] Erro ao publicar. Mudando para OFFLINE. Detalhes: {e}")
        with rabbitmq_lock:
            is_online = False
        await asyncio.to_thread(save_to_buffer, routing_key, payload)

async def rabbitmq_reconnection_loop():
    global is_online
    while True:
        if not is_online:
            print(f"[{LAB_ID}] Tentando restabelecer conexão com RabbitMQ...")
            connected = await asyncio.to_thread(connect_rabbitmq)
            if connected:
                await flush_buffer()
        await asyncio.sleep(5)

async def flush_buffer():
    global is_online
    messages = await asyncio.to_thread(get_buffered_messages)
    if messages:
        print(f"[{LAB_ID}] Descarregando {len(messages)} mensagens do buffer local...")
    for msg_id, routing_key, payload_str in messages:
        if not is_online:
            break
        try:
            payload = json.loads(payload_str)
            await publish_message(routing_key, payload)
            await asyncio.to_thread(delete_from_buffer, msg_id)
        except Exception as e:
            print(f"Erro ao descarregar mensagem {msg_id}: {e}")
            break

# --- Processamento e Detecção de Anomalias na Borda ---
async def process_device_reading(payload):
    global LAB_ID, cpu_high_count
    device_id = payload.get("id", "UNKNOWN")
    
    # Armazena a leitura atual para agregação periódica
    device_type = "PC"
    if "temperatura_ambiente" in payload:
        device_type = "AC"
    elif "tempo_uso_minutos" in payload:
        device_type = "PROJ"

    active_readings[device_id] = {
        "timestamp": datetime.utcnow(),
        "type": device_type,
        "data": payload
    }

    # Anomalias Imediatas (Bypass de Latência)
    if device_type == "PC":
        cpu = payload.get("cpu", 0)
        temp = payload.get("temperatura", 0)
        evento_seg = payload.get("evento_seguranca")

        # 1. CPU Crítica (>95% por 2 leituras seguidas)
        if cpu > 95.0:
            cpu_high_count[device_id] = cpu_high_count.get(device_id, 0) + 1
            if cpu_high_count[device_id] >= 2:
                alert = {
                    "lab_id": LAB_ID,
                    "device_id": device_id,
                    "type": "CPU_CRITICA",
                    "value": cpu,
                    "severity": "WARNING",
                    "timestamp": payload.get("timestamp"),
                    "msg": f"Computador {device_id} com uso de CPU crítico: {cpu}% por leituras consecutivas"
                }
                await publish_message(f"{LAB_ID}.alert", alert)
        else:
            cpu_high_count[device_id] = 0

        # 2. Superaquecimento do Hardware (>85°C)
        if temp > 85.0:
            alert = {
                "lab_id": LAB_ID,
                "device_id": device_id,
                "type": "SUPERAQUECIMENTO",
                "value": temp,
                "severity": "CRITICAL",
                "timestamp": payload.get("timestamp"),
                "msg": f"Hardware {device_id} superaquecido: {temp}°C!"
            }
            await publish_message(f"{LAB_ID}.alert", alert)

        # 3. Evento de Segurança
        if evento_seg:
            alert = {
                "lab_id": LAB_ID,
                "device_id": device_id,
                "type": "SEGURANCA",
                "value": evento_seg,
                "severity": "CRITICAL",
                "timestamp": payload.get("timestamp"),
                "msg": f"Computador {device_id} reportou evento de seguranca: {evento_seg}"
            }
            await publish_message(f"{LAB_ID}.alert", alert)

    elif device_type == "AC":
        temp_amb = payload.get("temperatura_ambiente", 0)
        # 4. Superaquecimento de Sala
        if temp_amb > 30.0:
            alert = {
                "lab_id": LAB_ID,
                "device_id": device_id,
                "type": "TEMPERATURA_SALA",
                "value": temp_amb,
                "severity": "WARNING",
                "timestamp": payload.get("timestamp"),
                "msg": f"Sala {LAB_ID} com temperatura ambiente elevada: {temp_amb}°C"
            }
            await publish_message(f"{LAB_ID}.alert", alert)

# --- Agregação Periódica por Janela ---
async def aggregation_loop():
    global LAB_ID, AGGREGATION_WINDOW, active_readings
    while True:
        await asyncio.sleep(AGGREGATION_WINDOW)
        
        now = datetime.utcnow()
        # Filtra dispositivos ativos (enviaram nos últimos 20 segundos)
        recent_readings = {
            dev_id: info for dev_id, info in active_readings.items()
            if (now - info["timestamp"]).total_seconds() <= 20.0
        }

        # Separa por categoria
        pcs = [info["data"] for info in recent_readings.values() if info["type"] == "PC"]
        ac = next((info["data"] for info in recent_readings.values() if info["type"] == "AC"), None)
        proj = next((info["data"] for info in recent_readings.values() if info["type"] == "PROJ"), None)

        if not pcs and not ac and not proj:
            continue

        # 1. Cálculos de Médias de PC
        cpu_avg = 0.0
        ram_avg = 0.0
        temp_avg = 0.0
        pcs_ativos = 0
        pc_energy_kw = 0.0

        if pcs:
            cpu_avg = sum(pc.get("cpu", 0) for pc in pcs) / len(pcs)
            ram_avg = sum(pc.get("ram", 0) for pc in pcs) / len(pcs)
            temp_avg = sum(pc.get("temperatura", 0) for pc in pcs) / len(pcs)
            pcs_ativos = sum(1 for pc in pcs if pc.get("status") in ["ATIVO", "EM_PROVA"])
            
            # Estimativa de consumo de energia do PC com base na CPU:
            # 20W ocioso, 100W ativo em carga máxima (cpu=100) -> de 0.02kW a 0.10kW
            pc_energy_kw = sum(0.02 + 0.08 * (pc.get("cpu", 0) / 100.0) for pc in pcs)

        # 2. Consumos do AC e Projetor
        ac_energy_kwh = ac.get("consumo_kwh", 0) if ac else 0.0
        proj_energy_kwh = proj.get("consumo_kwh", 0) if proj else 0.0
        
        # Consumo Total Estimado da Sala nesta janela
        total_energy = round(pc_energy_kw + ac_energy_kwh + proj_energy_kwh, 3)

        # 3. Geração do Status Consolidado do Laboratório
        status_payload = {
            "lab_id": LAB_ID,
            "timestamp": now.isoformat() + "Z",
            "metricas": {
                "cpu_media": round(cpu_avg, 1),
                "ram_media": round(ram_avg, 1),
                "temperatura_media": round(temp_avg, 1),
                "pcs_ativos": pcs_ativos,
                "energia_total_kwh": total_energy
            },
            "dispositivos": [info["data"] for info in recent_readings.values()]
        }
        await publish_message(f"{LAB_ID}.status", status_payload)

        # 4. Geração do Payload de Energia
        energy_payload = {
            "lab_id": LAB_ID,
            "timestamp": now.isoformat() + "Z",
            "energia": {
                "total": total_energy,
                "pcs": round(pc_energy_kw, 3),
                "ar_condicionado": round(ac_energy_kwh, 3),
                "projetor": round(proj_energy_kwh, 3)
            }
        }
        await publish_message(f"{LAB_ID}.energy", energy_payload)

        # 5. Geração do Payload de Climatização/Ambiente
        if ac:
            env_payload = {
                "lab_id": LAB_ID,
                "timestamp": now.isoformat() + "Z",
                "temperatura_ambiente": ac.get("temperatura_ambiente"),
                "ar_ligado": ac.get("ligado"),
                "ar_modo": ac.get("modo")
            }
            await publish_message(f"{LAB_ID}.environment", env_payload)

# --- Servidores / Coletores Locais de Telemetria ---
def run_mqtt_collector(loop):
    global MQTT_HOST, MQTT_PORT, LAB_ID
    client = mqtt.Client(client_id=f"EdgeGateway_{LAB_ID}")
    
    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            # Agenda o processamento no event loop do asyncio
            asyncio.run_coroutine_threadsafe(process_device_reading(payload), loop)
        except Exception as e:
            print(f"Erro ao ler mensagem MQTT local: {e}")

    client.on_message = on_message
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        # Ouve todos os dispositivos deste lab
        client.subscribe(f"laboratorio/{LAB_ID}/dispositivo/+/telemetria", qos=1)
        client.loop_start()
        print(f"Coletor MQTT local inscrito no Mosquitto ({MQTT_HOST}:{MQTT_PORT})")
    except Exception as e:
        print(f"Erro ao iniciar coletor MQTT local: {e}")

async def run_coap_collector():
    global COAP_PORT, LAB_ID
    root = resource.Site()

    class TelemetrySite(resource.Resource):
        async def render_post(self, request):
            try:
                payload_str = request.payload.decode('utf-8')
                payload = json.loads(payload_str)
                print(f"[{LAB_ID}] Recebido CoAP do dispositivo: {payload.get('id')}")
                await process_device_reading(payload)
                return aiocoap.Message(code=Code.CHANGED, payload=b"OK")
            except Exception as e:
                print(f"CoAP server error: {e}")
                return aiocoap.Message(code=Code.BAD_REQUEST, payload=str(e).encode('utf-8'))

    telemetry_resource = TelemetrySite()
    # Registra dinamicamente recursos para PCs 1..10, AC01 e PROJ01
    for i in range(1, 11):
        root.add_resource(['laboratorio', LAB_ID, 'dispositivo', f'{LAB_ID}-PC{i:02d}'], telemetry_resource)
    root.add_resource(['laboratorio', LAB_ID, 'dispositivo', f'{LAB_ID}-AC01'], telemetry_resource)
    root.add_resource(['laboratorio', LAB_ID, 'dispositivo', f'{LAB_ID}-PROJ01'], telemetry_resource)

    await aiocoap.Context.create_server_context(root, bind=('0.0.0.0', COAP_PORT))
    print(f"Coletor/Servidor CoAP local rodando na porta {COAP_PORT}")

# --- Ponto de Entrada Principal ---
async def main():
    global PROTOCOL, RABBITMQ_HOST
    print(f"=== Iniciando Gateway {LAB_ID} ({PROTOCOL}) ===")
    
    init_local_db()
    
    # Inicia conexão inicial com RabbitMQ
    await asyncio.to_thread(connect_rabbitmq)

    # loop do asyncio ativo
    loop = asyncio.get_running_loop()

    # Inicia Coletores
    if PROTOCOL == "MQTT":
        run_mqtt_collector(loop)
    else:  # CoAP
        await run_coap_collector()

    # Inicia Loops de Fundo
    tasks = [
        asyncio.create_task(rabbitmq_reconnection_loop()),
        asyncio.create_task(aggregation_loop())
    ]

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
