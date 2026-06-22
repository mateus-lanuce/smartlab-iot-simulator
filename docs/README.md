# Documentação Técnica do Projeto: SmartLab IoT

Bem-vindo à documentação oficial do **SmartLab IoT - Sistema Distribuído de Monitoramento Inteligente de Laboratórios (IoT, Edge Computing, Digital Twins e Mensageria)**.    

---

## 📚 Índice de Estudos para Apresentação

Para facilitar a navegação e o aprendizado progressivo, a documentação está dividida nos seguintes módulos detalhados:

1. **[Módulo 1: Arquitetura do Sistema e Fluxo de Dados](file:///c:/Users/mateus/Documents/projeto_ph/docs/1_arquitetura_e_fluxo.md)**
   * A divisão em 4 camadas físicas/lógicas.
   * Por que usamos MQTT (LAB1 e LAB3) e CoAP (LAB2)?
   * Tabela de portas expostas e fluxos de dados ponta a ponta.

2. **[Módulo 2: Computação de Borda (Edge Gateway)](file:///c:/Users/mateus/Documents/projeto_ph/docs/2_computacao_de_borda.md)**
   * Como funciona a redução de volume de dados na borda (Agregação por Janela Temporal).
   * Bypass de latência para alarmes críticos (CPU, temperatura e segurança).
   * Resiliência offline e buffer local SQLite com mecanismo de flush ordenado.

3. **[Módulo 3: Backend Central e Gêmeos Digitais (Digital Twins)](file:///c:/Users/mateus/Documents/projeto_ph/docs/3_backend_e_gemeos_digitais.md)**
   * A nova arquitetura orientada a eventos dividida em **4 microsserviços**.
   * Estratégia de concorrência com **SQLite WAL (Write-Ahead Logging)** e timeout para evitar bloqueios.
   * Estrutura das filas no RabbitMQ central e garantias de entrega (`basic_ack`).
   * Lógica de ciclo de vida online/offline dos gêmeos digitais (Heartbeat/Timeout).
   * Correlação Complexa de Eventos (Risco de Colapso Térmico e Desperdício Energético).

4. **[Módulo 4: Camada de Apresentação e Clientes](file:///c:/Users/mateus/Documents/projeto_ph/docs/4_apresentacao_e_dashboard.md)**
   * Painel Administrativo Web (SPA) moderno com design Glassmorphism.
   * Como as atualizações chegam em tempo real pelo WebSocket.
   * Funcionamento do Inspetor de Gêmeo Digital e do Modal de Histórico.
   * Cliente MQTT de terminal (CLI) colorido.

5. **[Módulo 5: Cenários Dinâmicos de Simulação](file:///c:/Users/mateus/Documents/projeto_ph/docs/5_cenarios_e_simulacao.md)**
   * Detalhamento dos 5 cenários exigidos (Normal, Pico, Falha de Ar, Sobrecarga, Anomalia).
   * Como os simuladores variam fisicamente as métricas em tempo real.
   * Mecanismo de propagação de cenários via API REST e WebSocket.

6. **[Módulo 6: Orquestração Docker e Implantação Distribuída](file:///c:/Users/mateus/Documents/projeto_ph/docs/6_guia_de_implantacao.md)**
   * A rede interna virtual no Docker Compose.
   * Configuração de variáveis de ambiente via `.env`.
   * Guia passo a passo para rodar a simulação em duas máquinas físicas na mesma subrede.

7. **[Módulo 7: Histórico de Alterações e Correções](file:///c:/Users/mateus/Documents/projeto_ph/docs/7_historico_de_correcoes.md)**
   * O bug do loop de eventos do FastAPI/Uvicorn e como ele foi resolvido.
   * Limpeza de rotas HTTP REST redundantes.
   * Filtro temporal e parser do histórico de uso no SQLite.

---

## 🎯 Dicas de Apresentação para o Professor

Quando vocês forem demonstrar o projeto, foquem nos seguintes pilares de engenharia:
1. **Desacoplamento:** Mostrem que o Backend central não sabe que os simuladores existem; ele apenas consome mensagens do RabbitMQ.
2. **Computação de Borda (Edge):** Enfatizem a inteligência na borda. Os gateways filtram pings desnecessários, calculam médias para economizar rede e lidam com quedas de conexão de forma totalmente autônoma.
3. **Resiliência (Buffer offline):** Desliguem o RabbitMQ temporariamente, mostrem o banco SQLite local do gateway se enchendo e, ao religar o RabbitMQ, mostrem os dados sendo transmitidos com os timestamps originais corretos.
4. **Complexidade de Eventos (CEP):** Expliquem que o backend correlaciona métricas de filas diferentes (climatização + CPU) para prever um perigo iminente (Colapso Térmico).
