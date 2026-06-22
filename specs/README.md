# Especificações Técnicas - Sistema de Monitoramento Inteligente de Laboratórios (IoT, Edge, Digital Twins)

Bem-vindo ao diretório de especificações técnicas do projeto. Este conjunto de documentos define detalhadamente a arquitetura, protocolos, fluxos de dados, banco de dados e cenários de testes que servem como a base técnica de design do sistema.

Todos os detalhes foram modelados com base no PDF das Práticas Offline 2 e 3 e refinados para garantir uma implementação de alta performance utilizando **Python**, **SQLite**, **RabbitMQ** e **Docker**.

---

## Índice das Especificações

1. **[Spec 0: Arquitetura Geral do Sistema](file:///c:/Users/mateus/Documents/projeto_ph/specs/0_arquitetura_geral.md)**
   * Visão macro do fluxo de dados das 4 camadas.
   * Definição de portas de rede (TCP/UDP) e divisão de protocolos (MQTT para LAB1/LAB3, CoAP para LAB2).
   * Tecnologias e bibliotecas adotadas (Python, Mosquitto, FastAPI, SQLite, Pika, aiocoap).

2. **[Spec 1: Camada de Dispositivos e Simulação IoT](file:///c:/Users/mateus/Documents/projeto_ph/specs/1_simulacao_iot.md)**
   * Detalhamento do gerador de telemetria concorrente (Threads) para os 30 PCs, 3 Ar-Condicionados e 3 Projetores.
   * Contratos de dados e schemas JSON detalhados para cada dispositivo.
   * Convenções de tópicos MQTT e endpoints/recursos CoAP.

3. **[Spec 2: Gateway de Borda (Edge Computing)](file:///c:/Users/mateus/Documents/projeto_ph/specs/2_edge_gateway.md)**
   * Definição do processamento de stream na borda (windowing de 15s) e cálculo de métricas médias locais.
   * Regras para detecção local e imediata de anomalias (CPU crítica, superaquecimento, eventos de segurança).
   * Mecanismo de resiliência e buffering local em banco SQLite para operação offline.

4. **[Spec 3: Mensageria e Microsserviços (Backend)](file:///c:/Users/mateus/Documents/projeto_ph/specs/3_backend_rabbitmq.md)**
   * Configuração das filas, exchanges e bindings do RabbitMQ.
   * Modelagem lógica das tabelas do banco de dados SQLite (`digital_twins`, `events_history`, `lab_statistics`).
   * Lógica de processamento e correlação de eventos complexos no backend (Risco de Colapso Térmico, Ineficiência Energética, Heartbeat dos Digital Twins).

5. **[Spec 4: Clientes de Consumo (Tempo Real e REST)](file:///c:/Users/mateus/Documents/projeto_ph/specs/4_clientes_consumo.md)**
   * Cliente CLI MQTT para exibição em tempo real de logs coloridos no terminal.
   * Especificação da API REST do backend (FastAPI) e endpoints de consulta de twins e histórico.
   * Definição visual e de requisitos do Dashboard Web (Dark Mode, Glassmorphism, WebSockets).

6. **[Spec 5: Orquestração de Cenários e Apresentação](file:///c:/Users/mateus/Documents/projeto_ph/specs/5_cenarios_teste.md)**
   * Detalhamento dos 5 cenários exigidos (Normal, Pico, Falha de Ar, Sobrecarga, Anomalia).
   * Docker Compose completo integrando todos os serviços.
   * Roteiro de configuração para apresentação em duas máquinas físicas.
