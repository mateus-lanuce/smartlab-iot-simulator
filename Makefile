# SmartLab IoT - Makefile

.PHONY: help up down restart logs cli-lab1 cli-lab3 cli-local-lab1 cli-local-lab3 clean

# Comando padrão
help:
	@echo "======================================================================"
	@echo "                     SmartLab IoT - Makefile                          "
	@echo "======================================================================"
	@echo "Comandos disponíveis:"
	@echo "  make up              - Inicializa toda a infraestrutura no Docker"
	@echo "  make down            - Encerra todos os contêineres do Docker"
	@echo "  make restart         - Reinicia os contêineres do Docker"
	@echo "  make logs            - Exibe e acompanha os logs em tempo real"
	@echo "  make cli-lab1        - Executa o Cliente CLI MQTT (LAB1) via Docker"
	@echo "  make cli-lab3        - Executa o Cliente CLI MQTT (LAB3) via Docker"
	@echo "  make cli-local-lab1  - Executa o Cliente CLI (LAB1) no host (requer Python)"
	@echo "  make cli-local-lab3  - Executa o Cliente CLI (LAB3) no host (requer Python)"
	@echo "  make clean           - Remove volumes do Docker e bancos temporários"
	@echo "======================================================================"

# Docker Compose
up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

# Execução do CLI usando contêiner temporário Docker (Sem dependências no host)
cli-lab1:
	docker run -it --rm --network projeto_ph_iot_network -v "$(CURDIR):/app" -w /app python:3.11-alpine sh -c "pip install colorama paho-mqtt && python cli_client/cli_mqtt_client.py --host mosquitto-lab1 --port 1883"

cli-lab3:
	docker run -it --rm --network projeto_ph_iot_network -v "$(CURDIR):/app" -w /app python:3.11-alpine sh -c "pip install colorama paho-mqtt && python cli_client/cli_mqtt_client.py --host mosquitto-lab3 --port 1883"

# Execução do CLI Local no Host (Exige instalação local prévia: pip install colorama paho-mqtt)
cli-local-lab1:
	python cli_client/cli_mqtt_client.py --host localhost --port 1883

cli-local-lab3:
	python cli_client/cli_mqtt_client.py --host localhost --port 1884

# Limpeza
clean:
	docker compose down -v
	rm -rf backend/data/database.db
	rm -rf edge_gateway/gateway_buffer.db
	@echo "Limpeza concluída!"
