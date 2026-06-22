# Módulo 5: Cenários Dinâmicos de Simulação

Este documento explica os 5 cenários dinâmicos de simulação e como o comportamento físico de geração de métricas se altera no sistema.

---

## 1. Funcionamento Físico das Métricas e Cenários

O script [simulator.py](file:///c:/Users/mateus/Documents/projeto_ph/simulator/simulator.py) altera suas regras matemáticas de variação de telemetria com base no cenário que estiver ativo para o seu laboratório. A temperatura dos PCs é calculada de forma reativa:
$$\text{Temperatura PC} = \text{Temperatura Ambiente} + (\text{CPU} \times 0.5) \pm 1^\circ\text{C}$$

Abaixo está o mapeamento físico e as consequências de cada um dos 5 cenários exigidos:

### Cenário 1: Uso Normal (`NORMAL`)
* **Simulação:** Laboratório funcionando sob demanda rotineira.
* **Comportamento das Métricas:**
  * PCs: Carga de CPU variando de 5% a 40%, RAM de 20% a 50%, temperatura estável entre 40°C e 55°C. Aplicações variadas (Chrome, VS Code, Slack).
  * Ar-Condicionado: Ligado, trabalhando para manter a temperatura do laboratório estabilizada em 22.0°C.
  * Consumo Total: Baixo/moderado.

### Cenário 2: Pico de Uso (`PICO`)
* **Simulação:** Todos os computadores em uso concorrente pesado (provas ou aulas práticas).
* **Comportamento das Métricas:**
  * PCs: Todos os computadores mudam o status para `EM_PROVA`. CPU constante entre 70% e 90%, RAM entre 60% e 85%. Temperatura física sobe para 65°C a 75°C. Alto fluxo de rede de dados.
  * Ar-Condicionado: Forçado ao máximo (`RESFRIAR`), mas a temperatura da sala sobe levemente devido à alta carga térmica de calor dissipado pelas máquinas e alunos.
  * Alerta: Ajusta médias móveis e sinaliza ocupação completa no painel.

### Cenário 3: Falha de Infraestrutura (`FALHA`)
* **Simulação:** Pane ou desligamento do ar-condicionado local.
* **Comportamento das Métricas:**
  * Ar-Condicionado: Muda para `ligado = False` e entra em modo ventilação simples.
  * Temperatura Ambiente: Começa a subir progressivamente a cada leitura (+0.3°C a +0.7°C a cada 5s) até se estabilizar em 35°C.
  * PCs: Como a temperatura ambiente sobe, os processadores de todos os PCs esquentam proporcionalmente.
  * Alertas Gerados:
    1. Gateway de borda detecta Temperatura de Sala > 30°C e emite o alerta de aviso de falha do ar.
    2. Logo em seguida, os processadores dos PCs ultrapassam 85°C, disparando múltiplos alertas críticos de superaquecimento individuais.

### Cenário 4: Sobrecarga e Estresse (`SOBRECARGA`)
* **Simulação:** Ataque ou processamento de estresse induzido nas CPUs.
* **Comportamento das Métricas:**
  * PCs: Uso de CPU constante entre 95% e 100% (simulando comando `stress-ng --cpu 4`). RAM atinge 85-95%. Temperatura atinge picos de superaquecimento (>85°C).
  * Alertas Gerados: Alertas imediatos de CPU Crítica e superaquecimento físico dos computadores.

### Cenário 5: Comportamento Anômalo (`ANOMALO`)
* **Simulação:** Incidentes de segurança cibernética e softwares não autorizados.
* **Comportamento das Métricas:**
  * **PC03 e PC07:** Elevam o uso de CPU para 90-98%, executando secretamente mineração de criptomoedas (`xmrig`). O campo `evento_seguranca` da telemetria é preenchido com a string `"SOFTWARE_NAO_AUTORIZADO"`.
  * **PC10:** Liga-se simulando atividade de invasão noturna fora do expediente. O campo `evento_seguranca` da telemetria é preenchido com a string `"USO_FORA_DO_HORARIO"`.
  * Alertas Gerados: Alertas de segurança imediata de severidade `CRITICAL`.

---

## 2. Propagação e Sincronização do Cenário em Tempo Real

A alteração do cenário ocorre de forma integrada:

1. **Seleção na UI:** O usuário clica em um botão de cenário (ex: "Falha AC") no laboratório correspondente do Dashboard Web.
2. **Requisição HTTP:** O JavaScript faz um POST HTTP `POST /api/simulation/scenario` com o payload `{"lab_id": "LAB1", "scenario": "FALHA"}`.
3. **Backend Central:** O backend recebe o comando, grava o estado em memória na variável `CURRENT_SCENARIO_STORE` e emite uma notificação WebSocket (`scenario_change`) para atualizar as telas de outros administradores conectados.
4. **Simulador Polling:** Os simuladores de dispositivos executam uma thread assíncrona paralela `poll_scenario_task` que consulta o backend central a cada 3 segundos via `GET /api/simulation/scenario/{lab_id}`. Ao detectarem a mudança de cenário, adaptam imediatamente suas fórmulas matemáticas para começar a gerar métricas no novo padrão.
