import asyncio
import os
import json
import time
import threading
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import pika

import shared_db

# Configurações do Backend API
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))

CURRENT_SCENARIO_STORE = {
    "LAB1": "NORMAL",
    "LAB2": "NORMAL",
    "LAB3": "NORMAL"
}

active_websockets = []
fastapi_loop = None

app = FastAPI(title="API Gateway Central - SmartLab IoT")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# --- Consumidor de Eventos para WebSockets ---
def rabbitmq_broadcast_listener():
    global RABBITMQ_HOST, RABBITMQ_PORT
    
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

            # Declara fila temporária exclusiva
            result = channel.queue_declare(queue='', exclusive=True)
            queue_name = result.method.queue

            # Assina todas as rotas (status, energy, environment, alerts)
            channel.queue_bind(queue=queue_name, exchange='iot_topic_exchange', routing_key='#')

            def callback(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    routing_key = method.routing_key
                    
                    msg_type = "unknown"
                    if "status" in routing_key:
                        msg_type = "status"
                    elif "alert" in routing_key:
                        msg_type = "alert"
                    elif "energy" in routing_key:
                        msg_type = "energy"
                    elif "environment" in routing_key:
                        msg_type = "environment"
                    
                    if msg_type != "unknown":
                        broadcast_event({"type": msg_type, "data": payload})
                except Exception as e:
                    print(f"Erro ao decodificar mensagem de broadcast: {e}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=queue_name, on_message_callback=callback)
            print("API Gateway: Ouvinte do RabbitMQ conectado e capturando eventos...")
            channel.start_consuming()

        except Exception as e:
            print(f"API Gateway: Erro de conexao com RabbitMQ: {e}. Reconfigurando em 5 segundos...")
            time.sleep(5)

# --- Endpoints REST API ---

@app.get("/labs/{lab_id}/status")
def get_lab_status(lab_id: str):
    conn = shared_db.get_db_connection()
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
    conn = shared_db.get_db_connection()
    cursor = conn.cursor()
    
    threshold = shared_db.parse_interval(intervalo)
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
    conn = shared_db.get_db_connection()
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
    conn = shared_db.get_db_connection()
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
    conn = shared_db.get_db_connection()
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
    print(f"API Gateway: loop guardado na inicializacao: {fastapi_loop}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop()
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        await websocket.send_json({
            "type": "scenarios_state",
            "data": CURRENT_SCENARIO_STORE
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

# Monta arquivos estáticos do Dashboard Web
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    print(f"Erro ao montar static: {e}")

@app.get("/")
def get_dashboard_root():
    return RedirectResponse(url="/static/index.html")

if __name__ == "__main__":
    import uvicorn
    shared_db.init_db()
    
    fastapi_loop = asyncio.get_event_loop()
    threading.Thread(target=rabbitmq_broadcast_listener, daemon=True).start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
