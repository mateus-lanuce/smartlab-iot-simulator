# Módulo 4: Camada de Apresentação e Clientes

Este documento detalha o funcionamento da camada visual e interativa do projeto, abordando o Painel Administrativo Web (SPA) e o Cliente MQTT CLI.

---

## 1. Dashboard Web SPA Premium

A interface de monitoramento foi construída como uma Single Page Application (SPA) moderna, utilizando HTML5 semântico, Vanilla CSS e Vanilla JavaScript.

### Design Visual (Aesthetics)
Para passar uma sensação altamente premium, o design segue as seguintes especificações:
* **Fundo:** Azul escuro/grafite (`#0F172A`) simulando painéis de controle industriais modernos.
* **Glassmorphism:** Os cards de laboratório e modais usam efeitos translúcidos combinando `background-color: rgba(30, 41, 59, 0.7)` com `backdrop-filter: blur(12px)`.
* **Cores de Destaque Semântico:**
  * **Verde (`#10B981`):** Dispositivo funcionando perfeitamente ou online.
  * **Amarelo (`#F59E0B`):** Aviso, CPU sob atenção ou ociosidade.
  * **Vermelho (`#EF4444`):** Alertas críticos, segurança ou superaquecimento.
  * **Cinza (`#64748B`):** Dispositivos offline ou desligados.

---

## 2. Comunicação e Atualizações em Tempo Real (WebSockets)

O dashboard não utiliza polling curto (ficar fazendo requisições repetidas de segundo em segundo) para atualizar a grade geral. Em vez disso, ele usa uma conexão persistente **WebSocket** bidirecional conectada na rota `/ws` do backend FastAPI.

```text
    Dashboard Web                   FastAPI Server (Backend)
          │                                   │
          │────── Conecta via WebSocket ─────►│
          │◄───── Envia cenários iniciais ────│
          │                                   │
          │       (Mensagem AMQP no RabbitMQ) │
          │                   │               │
          │                   ▼               │
          │           Consumidor lê           │
          │          RabbitMQ Status          │
          │                   │               │
          │                   ▼               │
          │◄────── Propaga status atualizado ─│ (WebSocket Broadcast)
          │                                   │
```

### Tipos de Mensagem Tratadas no `app.js`
* **`scenarios_state`:** Sincroniza o estado inicial dos botões de cenários dinâmicos ao carregar a página.
* **`status`:** Transmite as médias do laboratório e os estados de todos os computadores periféricos locais. O script [app.js](file:///c:/Users/mateus/Documents/projeto_ph/backend/static/app.js) mapeia e renderiza as cores de status dos 10 PCs correspondentes instantaneamente.
* **`alert`:** Dispara a exibição no feed dinâmico inferior do alerta recebido e coloca a cor vermelha de perigo no PC gerador do evento.
* **`environment`:** Atualiza instantaneamente a temperatura ambiente da sala (medida pelo ar-condicionado) no painel superior.
* **`scenario_change`:** Sincroniza a mudança visual dos botões de cenário quando outro usuário altera o modo de simulação do laboratório.

---

## 3. Inspetor de Gêmeos Digitais

Ao clicar em qualquer caixa de computador na grade ou em qualquer cartão de infraestrutura (Ar-Condicionado ou Projetor), o painel lateral do **Inspetor de Gêmeo Digital** é carregado em tempo real.
* **Funcionamento:** O JavaScript executa uma chamada REST `GET /twins/{device_id}`.
* **Detecção de Tipo e Renderização Dinâmica:** Com base na propriedade `data.tipo` retornada, o JavaScript gera a estrutura HTML dos campos sob o contêiner `#inspect-dynamic-fields`:
  * **PC:** Exibe métricas de uso de CPU (%), uso de RAM (%), temperatura física do chip (°C), tráfego de rede (kbps), aplicação ativa em execução e status operacional (badge colorido).
  * **Ar-Condicionado:** Exibe a temperatura ambiente da sala (°C), o estado de funcionamento (Ligado/Desligado), o consumo acumulado (kWh) e o modo de operação ativo (Resfriar, Aquecer, etc.).
  * **Projetor:** Exibe a temperatura de funcionamento interno (°C), o tempo de uso acumulado (minutos), a entrada de vídeo selecionada (HDMI1, HDMI2, VGA, etc.) e o consumo energético (kWh).


---

## 4. Modal de Histórico de Uso

Cada laboratório possui um botão "Histórico" no cabeçalho do seu card. Ao clicá-lo:
1. Um modal com blur de fundo é exibido.
2. É feita uma chamada à rota HTTP `GET /labs/{lab_id}/historico?intervalo={intervalo}`, onde o intervalo é selecionado em um menu dropdown (`10m`, `1h`, `24h`, `7d`).
3. O backend filtra os dados do SQLite, calculando a janela temporal baseada na hora atual do sistema em formato UTC.
4. A tabela do modal é populada mostrando o horário do registro, CPU média, RAM média, temperatura, PCs ativos e consumo de energia total da sala naquele instante.

---

## 5. Cliente MQTT em Tempo Real (CLI)

O script [cli_mqtt_client.py](file:///c:/Users/mateus/Documents/projeto_ph/cli_client/cli_mqtt_client.py) é um utilitário alternativo de console:
* **Inscrição:** Assina o tópico `laboratorio/#` conectando-se diretamente ao broker local.
* **Saída Colorida:** Utiliza a biblioteca `colorama` para pintar de vermelho/laranja alertas críticos no terminal e formatar logs contínuos das telemetrias recebidas.
* **Integração de Sensores Ambientais:** O CLI formata e exibe todos os sensores ambientais opcionais (CO2, Luminosidade e Ocupação) em tempo real quando telemetrias do Ar-Condicionado são consumidas.

---

## 6. Exibição de Sensores Ambientais Opcionais no Dashboard (General View)
Além do Inspetor detalhado, o Dashboard exibe os sensores adicionais de forma resumida diretamente sob o nome do **Ar-Condicionado** em cada lab card:
* Exemplo: `CO2: 450ppm | Lum: 500lx | Ocup: 6p`
* **Benefício:** Permite que o professor visualize as condições físicas gerais da sala de forma imediata sem a necessidade de cliques.
