import json
import argparse
import sys
from datetime import datetime
import paho.mqtt.client as mqtt
from colorama import init, Fore, Style

# Inicializa o colorama para colorização multiplataforma (Windows/Linux)
init(autoreset=True)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"{Fore.GREEN}[CONECTADO]{Style.RESET_ALL} Conexão estabelecida com o Broker MQTT.")
        # Subscreve para todos os tópicos relativos aos laboratórios
        client.subscribe("laboratorio/#")
        print(f"{Fore.BLUE}[INSCRIÇÃO]{Style.RESET_ALL} Ouvindo eventos em 'laboratorio/#'...")
    else:
        print(f"{Fore.RED}[ERRO]{Style.RESET_ALL} Falha na conexão. Código de retorno: {rc}")
        sys.exit(1)

def on_message(client, userdata, msg):
    topic = msg.topic
    payload_str = msg.payload.decode("utf-8")
    
    try:
        payload = json.loads(payload_str)
    except Exception:
        print(f"{Fore.RED}[FORMATO INVÁLIDO]{Style.RESET_ALL} Mensagem recebida no tópico {topic} não é um JSON válido.")
        return

    timestamp = payload.get("timestamp", datetime.now().isoformat())
    time_str = timestamp
    try:
        # Tenta formatar a hora de forma mais legível
        dt = datetime.fromisoformat(timestamp.replace("Z", ""))
        time_str = dt.strftime("%H:%M:%S")
    except Exception:
        pass

    # Processa tópicos de alerta
    if "alert" in topic or "alerts" in topic or payload.get("type") in ["CPU_CRITICA", "SUPERAQUECIMENTO", "SEGURANCA", "TEMPERATURA_SALA"]:
        severity = payload.get("severity", "WARNING").upper()
        msg_text = payload.get("msg", "Alerta sem descrição")
        device_id = payload.get("device_id", "SALA")
        lab_id = payload.get("lab_id", "DESCONHECIDO")

        color = Fore.YELLOW
        if severity == "CRITICAL":
            color = Fore.RED + Style.BRIGHT

        print(f"[{time_str}] {color}[ALERTA {severity}] {lab_id} ({device_id}): {msg_text}{Style.RESET_ALL}")

    # Processa status consolidado
    elif "status" in topic:
        lab_id = payload.get("lab_id", "DESCONHECIDO")
        metrics = payload.get("metricas", {})
        
        cpu = metrics.get("cpu_media", 0)
        ram = metrics.get("ram_media", 0)
        temp = metrics.get("temperatura_media", 0)
        pcs = metrics.get("pcs_ativos", 0)
        energy = metrics.get("energia_total_kwh", 0)

        print(
            f"[{time_str}] {Fore.CYAN}[STATUS]{Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}{lab_id}{Style.RESET_ALL} -> "
            f"CPU Média: {cpu}%, RAM Média: {ram}%, Temp Média: {temp}°C, PCs Ativos: {pcs}/10, Energia: {energy} kW"
        )

    # Processa telemetrias individuais (se o cliente se inscrever direto nelas)
    elif "dispositivo" in topic and "telemetria" in topic:
        device_id = payload.get("id", "DESCONHECIDO")
        
        # PC
        if "cpu" in payload:
            cpu = payload.get("cpu")
            ram = payload.get("ram")
            status = payload.get("status")
            print(f"[{time_str}] {Fore.BLACK}{Style.BRIGHT}[TELEMETRIA]{Style.RESET_ALL} {device_id} -> CPU: {cpu}%, RAM: {ram}%, Status: {status}")
        # AC
        elif "temperatura_ambiente" in payload:
            temp = payload.get("temperatura_ambiente")
            ligado = "LIGADO" if payload.get("ligado") else "DESLIGADO"
            co2 = payload.get("co2_ppm", 450.0)
            lux = payload.get("luminosidade_lux", 500.0)
            ocup = payload.get("ocupacao_pessoas", 0)
            print(
                f"[{time_str}] {Fore.BLACK}{Style.BRIGHT}[TELEMETRIA]{Style.RESET_ALL} {device_id} -> "
                f"Ar: {ligado}, Temp Ambiente: {temp}°C, CO2: {co2} ppm, Luminosidade: {lux} lux, Ocupação: {ocup} pessoas"
            )
        # Projetor
        elif "tempo_uso_minutos" in payload:
            ligado = "LIGADO" if payload.get("ligado") else "DESLIGADO"
            print(f"[{time_str}] {Fore.BLACK}{Style.BRIGHT}[TELEMETRIA]{Style.RESET_ALL} {device_id} -> Projetor: {ligado}, Entrada: {payload.get('entrada_video')}")

def main():
    parser = argparse.ArgumentParser(description="Cliente MQTT de Tempo Real - Monitoramento de Laboratórios")
    parser.add_argument("--host", type=str, default="localhost", help="Endereço do Broker MQTT (padrão: localhost)")
    parser.add_argument("--port", type=int, default=1883, help="Porta do Broker MQTT (padrão: 1883)")
    args = parser.parse_args()

    print(f"{Fore.BLUE}=== CLI MQTT CLIENT - INICIANDO ==={Style.RESET_ALL}")
    print(f"Conectando a {args.host}:{args.port}...")

    client = mqtt.Client(client_id="CLI_Realtime_Client")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(args.host, args.port, 60)
    except Exception as e:
        print(f"{Fore.RED}[FALHA]{Style.RESET_ALL} Não foi possível conectar ao broker {args.host}:{args.port}. Detalhes: {e}")
        sys.exit(1)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[ENCERRANDO]{Style.RESET_ALL} Desconectando do broker...")
        client.disconnect()
        print("Finalizado.")

if __name__ == "__main__":
    main()
