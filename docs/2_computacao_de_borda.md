# Módulo 2: Computação de Borda (Edge Gateway)

Este documento explica o papel crucial do **Gateway de Borda** no processamento de streams, detecção de anomalias com latência zero e resiliência offline.

---

## 1. Agregação por Janela Temporal (Windowing)

Para evitar sobrecarregar o tráfego de rede e o servidor de banco de dados central com 36 dispositivos gerando dados individuais a cada 5 segundos (o que representaria mais de 430 requisições por minuto), o **Gateway de Borda** executa uma agregação local por janela temporal.

### O Algoritmo de Janela
No arquivo [edge_gateway.py](file:///c:/Users/mateus/Documents/projeto_ph/edge_gateway/edge_gateway.py#L257-L339), o loop de agregação roda continuamente a cada `AGGREGATION_WINDOW` segundos (configurado como 5s no `.env`):

1. **Filtragem de Ativos:** Filtra as leituras salvas em memória para considerar apenas as recebidas nos últimos 20 segundos. Isso previne que PCs que caíram abruptamente continuem influenciando as médias.
2. **Cálculo de Averages:**
   * `cpu_media`: Média aritmética de uso de CPU de todos os computadores ativos.
   * `ram_media`: Média aritmética de RAM dos computadores ativos.
   * `temperatura_media`: Média da temperatura física dos processadores.
   * `pcs_ativos`: Contagem das máquinas no estado `ATIVO` ou `EM_PROVA`.
3. **Consumo de Energia Estimado:** O gateway calcula e soma os consumos locais:
   * **PCs:** Estimado dinamicamente com base na CPU:
     $$\text{Consumo PC (kW)} = 0.02 \text{ kW (Ocioso)} + 0.08 \text{ kW} \times \left(\frac{\text{CPU}\%}{100}\right)$$
   * **Ar-Condicionado e Projetores:** Consumo físico real lido de suas respectivas telemetrias.
4. **Envio:** Monta o payload consolidado e envia via AMQP.

---

## 2. Detecção de Anomalias na Borda (Bypass de Latência)

Enquanto os dados operacionais normais aguardam o fechamento da janela de agregação, **anomalias críticas de segurança e hardware burlam a janela e são enviadas na hora** para a central.

No arquivo [edge_gateway.py](file:///c:/Users/mateus/Documents/projeto_ph/edge_gateway/edge_gateway.py#L192-L255), cada telemetria individual recebida é checada em tempo real contra limiares de segurança:

1. **CPU Crítica individual:** Se a CPU de um PC ultrapassar 95% por duas leituras consecutivas (rastreado pelo dicionário `cpu_high_count`), gera um alerta de severidade `WARNING`.
2. **Superaquecimento do Hardware:** Se a temperatura física do processador de qualquer computador ultrapassar 85°C, gera um alerta crítico (`CRITICAL`).
3. **Invasão/Software Proibido:** Se o campo `evento_seguranca` da telemetria vier preenchido com qualquer string (ex: `SOFTWARE_NAO_AUTORIZADO`), gera um alerta crítico de segurança (`CRITICAL`).
4. **Superaquecimento de Sala:** Se o sensor do ar-condicionado reportar temperatura ambiente acima de 30°C, gera um alerta de severidade `WARNING`.

---

## 3. Resiliência Offline e Buffer SQLite Local

Caso o link de internet/rede física caia e impeça a comunicação entre o Gateway de Borda e o RabbitMQ central, o gateway não perde nenhum dado gerado localmente.

```text
       Link com Central Cai
               │
               ▼
┌──────────────────────────────┐
│  Muda para MODO OFFLINE      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Salva no SQLite Local       │
│  Tabela: gateway_buffer.db   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Inicia Loop de Reconexão    │
│  (Tenta de 5s em 5s)         │
└──────────────┬───────────────┘
               │
        Reconectou? ──► Não (Continua tentando)
               │
             Sim
               ▼
┌──────────────────────────────┐
│  Descarrega Buffer (Flush)   │
│  Publica mantendo timestamps │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Limpa Banco Local           │
│  Muda para MODO ONLINE       │
└──────────────────────────────┘
```

### Implementação Técnica
* **Buffer:** Quando a variável global `is_online` torna-se `False`, a função `publish_message` intercepta o payload e o salva via `save_to_buffer` no arquivo SQLite local `gateway_buffer.db`.
* **Flush Ordenado:** A thread `rabbitmq_reconnection_loop` detecta a queda e tenta reconectar. Assim que obtém sucesso, a função `flush_buffer` recupera as mensagens ordenadas pelo ID autoincrementável (cronologicamente corretas) e as publica de volta no RabbitMQ. A exclusão no banco local ocorre após a garantia de envio.
* **Timestamp Original:** As mensagens são gravadas no banco de dados central com a data original em que foram geradas e lidas na borda, mantendo a consistência dos relatórios históricos.
