import os
import json
import time
import sqlite3
import pika
import shared_db

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))

latest_room_temp = {
    "LAB1": 22.0,
    "LAB2": 22.0,
    "LAB3": 22.0
}

def publish_cep_alert(channel, lab_id, alert_type, value, msg, severity, timestamp):
    alert_payload = {
        "lab_id": lab_id,
        "device_id": "AMBIENTE" if alert_type == "DESPERDICIO_ENERGIA" else "MULTIPLOS",
        "type": alert_type,
        "value": value,
        "severity": severity,
        "timestamp": timestamp,
        "msg": msg
    }
    try:
        channel.basic_publish(
            exchange='iot_topic_exchange',
            routing_key=f"{lab_id}.alert",
            body=json.dumps(alert_payload),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        print(f"[CEP ALERT] Publicado alerta {alert_type} para {lab_id}")
    except Exception as e:
        print(f"Erro ao publicar alerta CEP: {e}")

def run_twin_worker():
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

            # Garante a existência e vinculação das filas que este worker consome
            channel.queue_declare(queue='energy_queue', durable=True)
            channel.queue_bind(queue='energy_queue', exchange='iot_topic_exchange', routing_key='*.energy')

            channel.queue_declare(queue='environment_queue', durable=True)
            channel.queue_bind(queue='environment_queue', exchange='iot_topic_exchange', routing_key='*.environment')

            channel.queue_declare(queue='status_queue', durable=True)
            channel.queue_bind(queue='status_queue', exchange='iot_topic_exchange', routing_key='*.status')

            # Callbacks de Mensagens
            def on_energy(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    lab_id = payload.get("lab_id")
                    timestamp = payload.get("timestamp")
                    energy_data = payload.get("energia", {})
                    
                    shared_db.update_digital_twin_in_db(
                        device_id=f"{lab_id}-ENERGY",
                        lab_id=lab_id,
                        device_type="ENERGY_SENSOR",
                        status="ATIVO",
                        online=True,
                        metrics=energy_data,
                        timestamp=timestamp
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao tratar energia: {e}")

            def on_environment(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    lab_id = payload.get("lab_id")
                    timestamp = payload.get("timestamp")
                    
                    temp_amb = payload.get("temperatura_ambiente")
                    if temp_amb is not None:
                        latest_room_temp[lab_id] = temp_amb
                    
                    ac_metrics = {
                        "temperatura_ambiente": temp_amb,
                        "modo": payload.get("ar_modo"),
                        "co2_ppm": payload.get("co2_ppm", 450.0),
                        "luminosidade_lux": payload.get("luminosidade_lux", 500.0),
                        "ocupacao_pessoas": payload.get("ocupacao_pessoas", 0)
                    }
                    shared_db.update_digital_twin_in_db(
                        device_id=f"{lab_id}-AC01",
                        lab_id=lab_id,
                        device_type="AR_CONDICIONADO",
                        status="LIGADO" if payload.get("ar_ligado") else "DESLIGADO",
                        online=True,
                        metrics=ac_metrics,
                        timestamp=timestamp
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao tratar ambiente: {e}")

            def on_status(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    lab_id = payload.get("lab_id")
                    timestamp = payload.get("timestamp")
                    metricas = payload.get("metricas", {})
                    dispositivos = payload.get("dispositivos", [])

                    # 1. Salva estatísticas médias no SQLite central
                    shared_db.save_lab_statistics_to_db(
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
                                "modo": dev.get("modo"),
                                "co2_ppm": dev.get("co2_ppm", 450.0),
                                "luminosidade_lux": dev.get("luminosidade_lux", 500.0),
                                "ocupacao_pessoas": dev.get("ocupacao_pessoas", 0)
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

                        shared_db.update_digital_twin_in_db(
                            device_id=dev_id,
                            lab_id=lab_id,
                            device_type=dev_type,
                            status=dev_status,
                            online=True,
                            metrics=dev_metrics,
                            timestamp=timestamp
                        )

                    # 3. CEP: Risco de Colapso Térmico
                    cpu_avg = metricas.get("cpu_media", 0)
                    room_temp = latest_room_temp.get(lab_id, 22.0)
                    if cpu_avg > 75.0 and room_temp > 28.0:
                        corr_desc = f"Risco de Colapso Termico: CPU media em {cpu_avg}% e temperatura ambiente em {room_temp}°C"
                        publish_cep_alert(
                            channel=ch,
                            lab_id=lab_id,
                            alert_type="RISCO_COLAPSO_TERMICO",
                            value=room_temp,
                            msg=corr_desc,
                            severity="CRITICAL",
                            timestamp=timestamp
                        )

                    # 4. CEP: Ineficiência Energética (Desperdício)
                    pcs_ativos = metricas.get("pcs_ativos", 0)
                    ac_twin_active = False
                    proj_twin_active = False
                    
                    conn = shared_db.get_db_connection()
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
                        publish_cep_alert(
                            channel=ch,
                            lab_id=lab_id,
                            alert_type="DESPERDICIO_ENERGIA",
                            value=0,
                            msg=corr_desc,
                            severity="WARNING",
                            timestamp=timestamp
                        )

                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"Erro ao tratar status: {e}")

            channel.basic_consume(queue='energy_queue', on_message_callback=on_energy)
            channel.basic_consume(queue='environment_queue', on_message_callback=on_environment)
            channel.basic_consume(queue='status_queue', on_message_callback=on_status)

            print("Twins & Statistics Worker conectado e consumindo filas...")
            channel.start_consuming()

        except Exception as e:
            print(f"Twins Worker: Erro de conexao com RabbitMQ: {e}. Reconectando em 5 segundos...")
            time.sleep(5)

if __name__ == "__main__":
    # Garante inicialização do DB compartilhado se necessário
    shared_db.init_db()
    run_twin_worker()
