import os
import json
import time
from datetime import datetime
import pika
import shared_db

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))

def publish_timeout_alert(channel, lab_id, dev_id, desc, timestamp):
    alert_payload = {
        "lab_id": lab_id,
        "device_id": dev_id,
        "type": "QUEDA_CONEXAO",
        "value": 0,
        "severity": "WARNING",
        "timestamp": timestamp,
        "msg": desc
    }
    try:
        channel.basic_publish(
            exchange='iot_topic_exchange',
            routing_key=f"{lab_id}.alert",
            body=json.dumps(alert_payload),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        print(f"[MONITOR] Alerta de QUEDA_CONEXAO publicado para {dev_id}")
    except Exception as e:
        print(f"Erro ao publicar alerta de timeout: {e}")

def run_monitor():
    global RABBITMQ_HOST, RABBITMQ_PORT
    
    credentials = pika.PlainCredentials('guest', 'guest')
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=0
    )

    connection = None
    channel = None

    while True:
        try:
            # Garante conexao com RabbitMQ para publicar timeouts
            if not connection or connection.is_closed:
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                channel.exchange_declare(exchange='iot_topic_exchange', exchange_type='topic', durable=True)

            conn = shared_db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT device_id, lab_id, last_update FROM digital_twins WHERE online = 1")
            rows = cursor.fetchall()
            now = datetime.utcnow()

            for dev_id, lab_id, last_up_str in rows:
                try:
                    last_up = datetime.fromisoformat(last_up_str.replace("Z", ""))
                    if (now - last_up).total_seconds() > 20.0:
                        cursor.execute("UPDATE digital_twins SET online = 0 WHERE device_id = ?", (dev_id,))
                        
                        desc = f"Dispositivo {dev_id} perdeu conexao (timeout de 20s)."
                        timestamp_str = now.isoformat() + "Z"
                        
                        # Publica alerta no RabbitMQ (Alert Worker ira salvar no SQLite central e API Gateway ira transmitir ao WS)
                        publish_timeout_alert(channel, lab_id, dev_id, desc, timestamp_str)
                        print(f"[MONITOR] {dev_id} marcado como OFFLINE por inatividade.")
                except Exception as ex:
                    print(f"Erro ao processar heartbeat de {dev_id}: {ex}")

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"Erro no monitor de heartbeat: {e}. Reconectando...")
            try:
                if connection and not connection.is_closed:
                    connection.close()
            except Exception:
                pass
            time.sleep(5)
            continue
            
        time.sleep(10)

if __name__ == "__main__":
    shared_db.init_db()
    run_monitor()
