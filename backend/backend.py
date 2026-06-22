import asyncio
import os
import json
import sqlite3
import time
import threading
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import pika

# Configurações do Backend
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))

DB_DIR = "data"
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "database.db")

# Dicionários de Estado em Memória
CURRENT_SCENARIO_STORE = {
    "LAB1": "NORMAL",
    "LAB2": "NORMAL",
    "LAB3": "NORMAL"
}
latest_room_temp = {
    "LAB1": 22.0,
    "LAB2": 22.0,
    "LAB3": 22.0
}

# Clientes WebSockets ativos
active_websockets = []
fastapi_loop = None

app = FastAPI(title="Backend Central IoT - Gêmeos Digitais")

# Configuração de CORS para permitir acesso local e externo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Banco de Dados SQLite ---
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS digital_twins (
            device_id TEXT PRIMARY KEY,
            lab_id TEXT NOT NULL,
            device_type TEXT NOT NULL,
            status TEXT NOT NULL,
            online BOOLEAN NOT NULL,
            last_update DATETIME NOT NULL,
            metrics_json TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            lab_id TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lab_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lab_id TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            cpu_avg REAL,
            ram_avg REAL,
            temp_avg REAL,
            active_pcs INTEGER,
            total_energy REAL
        )
    """)
    conn.commit()
    conn.close()
    print("Banco de dados SQLite central inicializado.")

def parse_interval(interval_str: str):
    if not interval_str:
        return None
    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        if unit == 'h':
            return datetime.utcnow() - timedelta(hours=value)
        elif unit == 'm':
            return datetime.utcnow() - timedelta(minutes=value)
        elif unit == 'd':
            return datetime.utcnow() - timedelta(days=value)
    except Exception:
        pass
    return None

def save_event_to_db(device_id, lab_id, event_type, description, severity, timestamp):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events_history (device_id, lab_id, timestamp, event_type, description, severity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (device_id, lab_id, timestamp, event_type, description, severity))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar evento: {e}")

def update_digital_twin_in_db(device_id, lab_id, device_type, status, online, metrics, timestamp):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO digital_twins (device_id, lab_id, device_type, status, online, last_update, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                status=excluded.status,
                online=excluded.online,
                last_update=excluded.last_update,
                metrics_json=excluded.metrics_json
        """, (device_id, lab_id, device_type, status, online, timestamp, json.dumps(metrics)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao atualizar digital twin: {e}")

def save_lab_statistics_to_db(lab_id, timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO lab_statistics (lab_id, timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (lab_id, timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar estatisticas do lab: {e}")

# --- WebSocket Broadcast ---
def broadcast_event(message):
    global fastapi_loop
    if fastapi_loop:
        async def do_broadcast():
            disconnected = []
            for ws in active_websockets:
                try:
                    await ws.send_json(message)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                if ws in active_websockets:
                    active_websockets.remove(ws)
        asyncio.run_coroutine_threadsafe(do_broadcast(), fastapi_loop)

# --- Consumidor RabbitMQ ---
def rabbitmq_consumer():
    global RABBITMQ_HOST, RABBITMQ_PORT, latest_room_temp
    
    credentials = pika.PlainCredentials('guest', 'guest')
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=0
    )

    while True:
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            channel.exchange_declare(exchange='iot_topic_exchange', exchange_type='topic', durable=True)

            # Declara e vincula filas
            channel.queue_declare(queue='alerts_queue', durable=True)
            channel.queue_bind(queue='alerts_queue', exchange='iot_topic_exchange', routing_key='*.alert')

            channel.queue_declare(queue='energy_queue', durable=True)
            channel.queue_bind(queue='energy_queue', exchange='iot_topic_exchange', routing_key='*.energy')

            channel.queue_declare(queue='environment_queue', durable=True)
            channel.queue_bind(queue='environment_queue', exchange='iot_topic_exchange', routing_key='*.environment')

            channel.queue_declare(queue='status_queue', durable=True)
            channel.queue_bind(queue='status_queue', exchange='iot_topic_exchange', routing_key='*.status')

            # Callbacks de Mensagens
            def on_alert(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    save_event_to_db(
                        device_id=payload.get("device_id"),
                        lab_id=payload.get("lab_id"),
                        event_type=payload.get("type"),
                        description=payload.get("msg"),
                        severity=payload.get("severity", "INFO"),
                        timestamp=payload.get("timestamp")
                    )
                    # Envia ao WebSocket
                    broadcast_event({"type": "alert", "data": payload})
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao processar alerta: {e}")

            def on_energy(ch, method, properties, body):
                try:
                    # Dados de energia consolidados
                    payload = json.loads(body.decode("utf-8"))
                    lab_id = payload.get("lab_id")
                    timestamp = payload.get("timestamp")
                    energy_data = payload.get("energia", {})
                    
                    # Atualiza o Digital Twin de consumo geral do laboratório
                    update_digital_twin_in_db(
                        device_id=f"{lab_id}-ENERGY",
                        lab_id=lab_id,
                        device_type="ENERGY_SENSOR",
                        status="ATIVO",
                        online=True,
                        metrics=energy_data,
                        timestamp=timestamp
                    )
                    broadcast_event({"type": "energy", "data": payload})
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao processar energia: {e}")

            def on_environment(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    lab_id = payload.get("lab_id")
                    timestamp = payload.get("timestamp")
                    
                    # Atualiza temperatura ambiente compartilhada
                    temp_amb = payload.get("temperatura_ambiente")
                    if temp_amb is not None:
                        latest_room_temp[lab_id] = temp_amb
                    
                    # Atualiza o Digital Twin do Ar-Condicionado
                    ac_metrics = {
                        "temperatura_ambiente": temp_amb,
                        "modo": payload.get("ar_modo")
                    }
                    update_digital_twin_in_db(
                        device_id=f"{lab_id}-AC01",
                        lab_id=lab_id,
                        device_type="AR_CONDICIONADO",
                        status="LIGADO" if payload.get("ar_ligado") else "DESLIGADO",
                        online=True,
                        metrics=ac_metrics,
                        timestamp=timestamp
                    )
                    broadcast_event({"type": "environment", "data": payload})
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao processar ambiente: {e}")

            def on_status(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    lab_id = payload.get("lab_id")
                    timestamp = payload.get("timestamp")
                    metricas = payload.get("metricas", {})
                    dispositivos = payload.get("dispositivos", [])

                    # 1. Salva estatísticas médias
                    save_lab_statistics_to_db(
                        lab_id=lab_id,
                        timestamp=timestamp,
                        cpu_avg=metricas.get("cpu_media"),
                        ram_avg=metricas.get("ram_media"),
                        temp_avg=metricas.get("temperatura_media"),
                        active_pcs=metricas.get("pcs_ativos"),
                        total_energy=metricas.get("energia_total_kwh")
                    )

                    # 2. Atualiza os Digital Twins individuais recebidos na lista
                    for dev in dispositivos:
                        dev_id = dev.get("id")
                        # Determina tipo do dispositivo com base no ID
                        if "-PC" in dev_id:
                            dev_type = "PC"
                            dev_status = dev.get("status", "ATIVO")
                            dev_metrics = {
                                "cpu": dev.get("cpu"),
                                "ram": dev.get("ram"),
                                "temperatura": dev.get("temperatura"),
                                "aplicacao": dev.get("aplicacao"),
                                "rede_kbps": dev.get("rede_kbps")
                            }
                        elif "-AC" in dev_id:
                            dev_type = "AR_CONDICIONADO"
                            dev_status = "LIGADO" if dev.get("ligado") else "DESLIGADO"
                            dev_metrics = {
                                "temperatura_ambiente": dev.get("temperatura_ambiente"),
                                "consumo_kwh": dev.get("consumo_kwh"),
                                "modo": dev.get("modo")
                            }
                        else:  # PROJ
                            dev_type = "PROJETOR"
                            dev_status = "LIGADO" if dev.get("ligado") else "DESLIGADO"
                            dev_metrics = {
                                "tempo_uso_minutos": dev.get("tempo_uso_minutos"),
                                "temperatura_interna": dev.get("temperatura_interna"),
                                "entrada_video": dev.get("entrada_video"),
                                "consumo_kwh": dev.get("consumo_kwh")
                            }

                        update_digital_twin_in_db(
                            device_id=dev_id,
                            lab_id=lab_id,
                            device_type=dev_type,
                            status=dev_status,
                            online=True,
                            metrics=dev_metrics,
                            timestamp=timestamp
                        )

                    # 3. Correlação de Evento Complexo: Risco de Colapso Térmico
                    cpu_avg = metricas.get("cpu_media", 0)
                    room_temp = latest_room_temp.get(lab_id, 22.0)
                    if cpu_avg > 75.0 and room_temp > 28.0:
                        corr_desc = f"Risco de Colapso Termico: CPU media em {cpu_avg}% e temperatura ambiente em {room_temp}°C"
                        save_event_to_db(
                            device_id=None,
                            lab_id=lab_id,
                            event_type="RISCO_COLAPSO_TERMICO",
                            description=corr_desc,
                            severity="CRITICAL",
                            timestamp=timestamp
                        )
                        broadcast_event({
                            "type": "alert",
                            "data": {
                                "lab_id": lab_id,
                                "device_id": "MULTIPLOS",
                                "type": "RISCO_COLAPSO_TERMICO",
                                "value": room_temp,
                                "severity": "CRITICAL",
                                "timestamp": timestamp,
                                "msg": corr_desc
                            }
                        })

                    # 4. Correlação de Ineficiência Energética
                    pcs_ativos = metricas.get("pcs_ativos", 0)
                    # Verifica se Ar ou Projetor estão ligados
                    ac_twin_active = False
                    proj_twin_active = False
                    
                    conn = sqlite3.connect(DB_PATH, timeout=10.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT status FROM digital_twins WHERE device_id = ?", (f"{lab_id}-AC01",))
                    row_ac = cursor.fetchone()
                    if row_ac and row_ac[0] == "LIGADO":
                        ac_twin_active = True
                        
                    cursor.execute("SELECT status FROM digital_twins WHERE device_id = ?", (f"{lab_id}-PROJ01",))
                    row_proj = cursor.fetchone()
                    if row_proj and row_proj[0] == "LIGADO":
                        proj_twin_active = True
                    conn.close()

                    if pcs_ativos == 0 and (ac_twin_active or proj_twin_active):
                        corr_desc = f"Desperdicio de Energia: Equipamento ligado em sala sem uso (AC={ac_twin_active}, PROJ={proj_twin_active})"
                        save_event_to_db(
                            device_id=None,
                            lab_id=lab_id,
                            event_type="DESPERDICIO_ENERGIA",
                            description=corr_desc,
                            severity="WARNING",
                            timestamp=timestamp
                        )
                        broadcast_event({
                            "type": "alert",
                            "data": {
                                "lab_id": lab_id,
                                "device_id": "AMBIENTE",
                                "type": "DESPERDICIO_ENERGIA",
                                "value": 0,
                                "severity": "WARNING",
                                "timestamp": timestamp,
                                "msg": corr_desc
                            }
                        })

                    # Envia atualização para os websockets
                    broadcast_event({"type": "status", "data": payload})
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao processar status: {e}")

            channel.basic_consume(queue='alerts_queue', on_message_callback=on_alert)
            channel.basic_consume(queue='energy_queue', on_message_callback=on_energy)
            channel.basic_consume(queue='environment_queue', on_message_callback=on_environment)
            channel.basic_consume(queue='status_queue', on_message_callback=on_status)

            print("Consumidor RabbitMQ conectado e ouvindo filas...")
            channel.start_consuming()

        except Exception as e:
            print(f"Erro de conexão com RabbitMQ: {e}. Tentando em 5 segundos...")
            time.sleep(5)

# --- Monitor de Heartbeat (Inatividade de Dispositivos) ---
def heartbeat_monitor():
    while True:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10.0)
            cursor = conn.cursor()
            # Busca twins que constam como online
            cursor.execute("SELECT device_id, lab_id, last_update FROM digital_twins WHERE online = 1")
            rows = cursor.fetchall()
            now = datetime.utcnow()
            for dev_id, lab_id, last_up_str in rows:
                try:
                    # Trata o formato de data (remove Z)
                    last_up = datetime.fromisoformat(last_up_str.replace("Z", ""))
                    # Se inativo por mais de 20 segundos
                    if (now - last_up).total_seconds() > 20.0:
                        cursor.execute("UPDATE digital_twins SET online = 0 WHERE device_id = ?", (dev_id,))
                        
                        desc = f"Dispositivo {dev_id} perdeu conexao (timeout de 20s)."
                        cursor.execute("""
                            INSERT INTO events_history (device_id, lab_id, timestamp, event_type, description, severity)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (dev_id, lab_id, now.isoformat() + "Z", "QUEDA_CONEXAO", desc, "WARNING"))
                        
                        print(f"[{lab_id}] Dispositivo {dev_id} Offline por Inatividade.")
                        
                        # Alerta o dashboard
                        broadcast_event({
                            "type": "alert",
                            "data": {
                                "lab_id": lab_id,
                                "device_id": dev_id,
                                "type": "QUEDA_CONEXAO",
                                "value": 0,
                                "severity": "WARNING",
                                "timestamp": now.isoformat() + "Z",
                                "msg": desc
                            }
                        })
                except Exception as ex:
                    print(f"Erro ao processar data para {dev_id}: {ex}")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Erro no monitor de inatividade: {e}")
        time.sleep(10)

# --- Endpoints REST API ---

@app.get("/labs/{lab_id}/status")
def get_lab_status(lab_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy 
        FROM lab_statistics 
        WHERE lab_id = ? 
        ORDER BY id DESC LIMIT 1
    """, (lab_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {
            "lab_id": lab_id,
            "timestamp": None,
            "cpu_avg": 0,
            "ram_avg": 0,
            "temp_avg": 0,
            "pcs_online": 0,
            "total_energy_kwh": 0
        }
    
    # Busca contagem de computadores online no SQLite
    cursor.execute("SELECT COUNT(*) FROM digital_twins WHERE lab_id = ? AND online = 1 AND device_type = 'PC'", (lab_id,))
    pcs_online = cursor.fetchone()[0]
    conn.close()
    
    return {
        "lab_id": lab_id,
        "timestamp": row[0],
        "cpu_avg": row[1],
        "ram_avg": row[2],
        "temp_avg": row[3],
        "pcs_online": pcs_online,
        "total_energy_kwh": row[5]
    }

@app.get("/labs/{lab_id}/historico")
def get_lab_history(lab_id: str, limit: int = 30, intervalo: str = None):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    threshold = parse_interval(intervalo)
    if threshold:
        threshold_str = threshold.isoformat() + "Z"
        cursor.execute("""
            SELECT timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy 
            FROM lab_statistics 
            WHERE lab_id = ? AND timestamp >= ?
            ORDER BY id DESC
        """, (lab_id, threshold_str))
    else:
        cursor.execute("""
            SELECT timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy 
            FROM lab_statistics 
            WHERE lab_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (lab_id, limit))
        
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for r in reversed(rows):
        history.append({
            "timestamp": r[0],
            "cpu_avg": r[1],
            "ram_avg": r[2],
            "temp_avg": r[3],
            "active_pcs": r[4],
            "total_energy": r[5]
        })
    return history

@app.get("/twins/{device_id}")
def get_digital_twin(device_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT device_id, lab_id, device_type, status, online, last_update, metrics_json 
        FROM digital_twins 
        WHERE device_id = ?
    """, (device_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Digital Twin nao encontrado")
        
    return {
        "id": row[0],
        "lab_id": row[1],
        "tipo": row[2],
        "status": row[3],
        "online": bool(row[4]),
        "last_update": row[5],
        "metrics": json.loads(row[6])
    }

@app.get("/twins")
def list_digital_twins(lab_id: str = None):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    if lab_id:
        cursor.execute("SELECT device_id, lab_id, device_type, status, online, last_update, metrics_json FROM digital_twins WHERE lab_id = ?", (lab_id,))
    else:
        cursor.execute("SELECT device_id, lab_id, device_type, status, online, last_update, metrics_json FROM digital_twins")
    rows = cursor.fetchall()
    conn.close()
    
    twins = []
    for row in rows:
        twins.append({
            "id": row[0],
            "lab_id": row[1],
            "tipo": row[2],
            "status": row[3],
            "online": bool(row[4]),
            "last_update": row[5],
            "metrics": json.loads(row[6])
        })
    return twins

@app.get("/alerts")
def get_alerts(limit: int = 50):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, device_id, lab_id, timestamp, event_type, description, severity 
        FROM events_history 
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    alerts = []
    for r in rows:
        alerts.append({
            "id": r[0],
            "device_id": r[1],
            "lab_id": r[2],
            "timestamp": r[3],
            "type": r[4],
            "msg": r[5],
            "severity": r[6]
        })
    return alerts

# Endpoints de Cenários de Simulação
@app.get("/api/simulation/scenario/{lab_id}")
def get_scenario(lab_id: str):
    scenario = CURRENT_SCENARIO_STORE.get(lab_id, "NORMAL")
    return {"lab_id": lab_id, "scenario": scenario}

@app.post("/api/simulation/scenario")
def update_scenario(payload: dict):
    lab_id = payload.get("lab_id")
    scenario = payload.get("scenario")
    
    if lab_id not in CURRENT_SCENARIO_STORE:
        raise HTTPException(status_code=400, detail="Laboratorio invalido")
        
    CURRENT_SCENARIO_STORE[lab_id] = scenario
    print(f"[{lab_id}] Cenário alterado via REST para: {scenario}")
    
    # Broadcast scenario change notification to update frontend
    broadcast_event({
        "type": "scenario_change",
        "data": {
            "lab_id": lab_id,
            "scenario": scenario
        }
    })
    return {"status": "ok", "lab_id": lab_id, "scenario": scenario}

@app.on_event("startup")
async def startup_event():
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop()
    print(f"FastAPI loop guardado na inicializacao: {fastapi_loop}")

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop()
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        # Envia estado inicial dos cenários ao conectar
        await websocket.send_json({
            "type": "scenarios_state",
            "data": CURRENT_SCENARIO_STORE
        })
        while True:
            # Mantém conexão WebSocket aberta
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

# --- Montagem de Arquivos Estáticos (Dashboard Web) ---
# Tenta montar a pasta estática se ela existir
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    print(f"Erro ao montar arquivos estáticos: {e}")

@app.get("/")
def get_dashboard_root():
    return RedirectResponse(url="/static/index.html")

# --- Inicialização Geral ---
if __name__ == "__main__":
    import uvicorn
    
    init_db()
    
    # Guarda o event loop ativo da FastAPI para o websocket broadcast
    fastapi_loop = asyncio.get_event_loop()
    
    # Inicializa Consumidor RabbitMQ e Monitor Heartbeat em Threads separadas
    threading.Thread(target=rabbitmq_consumer, daemon=True).start()
    threading.Thread(target=heartbeat_monitor, daemon=True).start()
    
    # Roda Servidor Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
