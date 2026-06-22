import os
import json
import time
import pika
import shared_db

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))

def run_alerts_worker():
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
            channel.queue_declare(queue='alerts_queue', durable=True)
            channel.queue_bind(queue='alerts_queue', exchange='iot_topic_exchange', routing_key='*.alert')

            def on_alert(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    print(f"[ALERT WORKER] Processando alerta recebido: {payload}")
                    
                    shared_db.save_event_to_db(
                        device_id=payload.get("device_id"),
                        lab_id=payload.get("lab_id"),
                        event_type=payload.get("type"),
                        description=payload.get("msg"),
                        severity=payload.get("severity", "INFO"),
                        timestamp=payload.get("timestamp")
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao processar alerta: {e}")

            channel.basic_consume(queue='alerts_queue', on_message_callback=on_alert)
            print("Alerts Worker conectado e ouvindo alertas...")
            channel.start_consuming()

        except Exception as e:
            print(f"Alerts Worker: Erro de conexao com RabbitMQ: {e}. Reconectando em 5 segundos...")
            time.sleep(5)

if __name__ == "__main__":
    shared_db.init_db()
    run_alerts_worker()
