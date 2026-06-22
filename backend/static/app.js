// Configuração do WebSocket
let socket = null;
const labs = ["LAB1", "LAB2", "LAB3"];
let lastUpdateTime = null;
let historyActiveLab = null;

// Dispositivo atualmente selecionado para inspeção
let selectedDeviceId = null;
// Dicionário local para armazenar o estado atual dos Digital Twins na tela
// Estrutura: { device_id: { ... } }
const twinState = {};

// Inicializa a grade de PCs na tela
function buildGrids() {
    labs.forEach(labId => {
        const grid = document.getElementById(`${labId}-pc-grid`);
        grid.innerHTML = ""; // Limpa

        for (let i = 1; i <= 10; i++) {
            const pcNum = String(i).padStart(2, '0');
            const pcId = `${labId}-PC${pcNum}`;
            
            // Cria o card visual do PC
            const square = document.createElement("div");
            square.className = "pc-square state-offline";
            square.id = `square-${pcId}`;
            square.setAttribute("data-id", pcId);
            
            square.innerHTML = `
                <i class="fa-solid fa-desktop"></i>
                <span>PC ${pcNum}</span>
            `;
            
            // Evento de clique para inspecionar o Digital Twin
            square.addEventListener("click", () => selectDevice(pcId));
            
            grid.appendChild(square);
        }
    });
}

// Seleciona um dispositivo para o Inspetor
async function selectDevice(deviceId) {
    // Remove seleção anterior
    if (selectedDeviceId) {
        const prevSquare = document.getElementById(`square-${selectedDeviceId}`);
        if (prevSquare) prevSquare.classList.remove("selected");
    }

    selectedDeviceId = deviceId;
    const currentSquare = document.getElementById(`square-${deviceId}`);
    if (currentSquare) currentSquare.classList.add("selected");

    // Exibe painel
    document.getElementById("inspector-placeholder").classList.add("hidden");
    document.getElementById("inspector-content").classList.remove("hidden");

    await updateInspectorDetails(deviceId);
}

// Busca detalhes do Digital Twin e atualiza o painel do inspetor
async function updateInspectorDetails(deviceId) {
    if (selectedDeviceId !== deviceId) return;

    try {
        const response = await fetch(`/twins/${deviceId}`);
        if (response.status === 200) {
            const data = await response.json();
            
            document.getElementById("inspect-id").textContent = data.id;
            
            // PC
            if (data.tipo === "PC") {
                document.getElementById("inspect-cpu").textContent = `${data.metrics.cpu || 0}%`;
                document.getElementById("inspect-ram").textContent = `${data.metrics.ram || 0}%`;
                document.getElementById("inspect-temp").textContent = `${data.metrics.temperatura || 0}°C`;
                document.getElementById("inspect-network").textContent = `${data.metrics.rede_kbps || 0} kbps`;
                document.getElementById("inspect-app").textContent = data.metrics.aplicacao || "Nenhuma";
            }
            
            // Status
            const statusBadge = document.getElementById("inspect-status");
            statusBadge.textContent = data.status;
            statusBadge.className = `badge ${data.status.toLowerCase()}`;
            
            // Conectividade
            const connBadge = document.getElementById("inspect-conn");
            connBadge.textContent = data.online ? "ONLINE" : "OFFLINE";
            connBadge.className = `badge ${data.online ? "online" : "offline"}`;
            
            // Data
            const lastUp = new Date(data.last_update);
            document.getElementById("inspect-update").textContent = lastUp.toLocaleTimeString();
        }
    } catch (error) {
        console.error("Erro ao buscar Digital Twin no inspetor:", error);
    }
}

// Associa os botões de cenários com requisições REST
function setupScenarioButtons() {
    document.querySelectorAll(".btn-scenario").forEach(button => {
        button.addEventListener("click", async () => {
            const lab_id = button.getAttribute("data-lab");
            const scenario = button.getAttribute("data-scenario");

            try {
                const response = await fetch("/api/simulation/scenario", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ lab_id, scenario })
                });
                
                if (response.status === 200) {
                    // Atualiza visual local do grupo de botões deste lab
                    document.querySelectorAll(`.btn-scenario[data-lab="${lab_id}"]`).forEach(btn => {
                        btn.classList.remove("active");
                    });
                    button.classList.add("active");
                }
            } catch (error) {
                console.error("Erro ao alterar cenário:", error);
            }
        });
    });
}

// Adiciona um alerta no feed de logs
function addAlertToFeed(alert) {
    const feed = document.getElementById("alert-feed");
    
    // Remove placeholder se for o primeiro
    const placeholder = feed.querySelector(".no-alerts-placeholder");
    if (placeholder) placeholder.remove();

    const timeStr = new Date(alert.timestamp).toLocaleTimeString();
    const severityClass = `severity-${alert.severity.toLowerCase()}`;
    const icon = alert.severity === "CRITICAL" ? "fa-circle-xmark" : "fa-triangle-exclamation";

    const alertRow = document.createElement("div");
    alertRow.className = `alert-item ${severityClass}`;
    alertRow.innerHTML = `
        <div class="alert-item-body">
            <span class="alert-time">[${timeStr}]</span>
            <span><i class="fa-solid ${icon}"></i> <strong>${alert.lab_id} (${alert.device_id || 'AMBIENTE'}):</strong> ${alert.msg}</span>
        </div>
    `;

    // Insere no topo
    feed.insertBefore(alertRow, feed.firstChild);

    // Limita o feed a 50 alertas para não quebrar a UI
    if (feed.children.length > 50) {
        feed.lastChild.remove();
    }
}

// Processa as atualizações de telemetria recebidas via WebSocket
function handleStatusUpdate(status) {
    const labId = status.lab_id;
    const metrics = status.metricas;
    const devices = status.dispositivos || [];

    // 1. Atualiza médias gerais
    document.getElementById(`${labId}-cpu-avg`).textContent = `${metrics.cpu_media}%`;
    document.getElementById(`${labId}-cpu-bar`).style.width = `${metrics.cpu_media}%`;
    
    document.getElementById(`${labId}-ram-avg`).textContent = `${metrics.ram_media}%`;
    document.getElementById(`${labId}-ram-bar`).style.width = `${metrics.ram_media}%`;
    
    document.getElementById(`${labId}-temp-avg`).textContent = `${status.temperatura_ambiente || metrics.temperatura_media}°C`;
    document.getElementById(`${labId}-energy`).textContent = `${metrics.energia_total_kwh} kW`;

    let onlineCount = 0;

    // 2. Atualiza PCs na grade e infra
    devices.forEach(device => {
        const devId = device.id;
        twinState[devId] = device;

        if (devId.includes("-PC")) {
            const square = document.getElementById(`square-${devId}`);
            if (square) {
                // Remove estados anteriores
                square.className = "pc-square";
                if (selectedDeviceId === devId) square.classList.add("selected");

                const cpu = device.cpu || 0;
                const temp = device.temperatura || 0;
                const isSec = device.evento_seguranca;

                // Define cor com base no status/alerta
                if (cpu > 95.0 || temp > 85.0 || isSec) {
                    square.classList.add("state-alert");
                } else if (device.status === "ATIVO" || device.status === "EM_PROVA") {
                    square.classList.add("state-active");
                } else {
                    square.classList.add("state-idle");
                }
                onlineCount++;
            }
        } else if (devId.includes("-AC")) {
            const card = document.getElementById(`${labId}-ac-status`);
            const value = document.getElementById(`${labId}-ac-value`);
            if (card && value) {
                const ligado = device.ligado;
                value.textContent = ligado ? `Ligado (${device.temperatura_ambiente}°C)` : "Desligado";
                if (ligado) {
                    card.classList.add("active", "ac-card");
                } else {
                    card.classList.remove("active", "ac-card");
                }
            }
        } else if (devId.includes("-PROJ")) {
            const card = document.getElementById(`${labId}-proj-status`);
            const value = document.getElementById(`${labId}-proj-value`);
            if (card && value) {
                const ligado = device.ligado;
                value.textContent = ligado ? `Ligado (${device.entrada_video})` : "Desligado";
                if (ligado) {
                    card.classList.add("active");
                } else {
                    card.classList.remove("active");
                }
            }
        }
    });

    // Atualiza contagem
    document.getElementById(`${labId}-pcs-count`).textContent = onlineCount;

    // Se o computador selecionado no inspetor acabou de atualizar, atualiza a tela
    if (selectedDeviceId && selectedDeviceId.startsWith(labId)) {
        updateInspectorDetails(selectedDeviceId);
    }
}

// Conexão WebSocket
function connectWS() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("WebSocket conectado.");
        const badge = document.getElementById("ws-status");
        badge.className = "status-indicator online";
        badge.innerHTML = `<i class="fa-solid fa-circle"></i> Conectado`;
    };

    socket.onmessage = (event) => {
        lastUpdateTime = Date.now();
        const msg = JSON.parse(event.data);
        
        switch (msg.type) {
            case "scenarios_state":
                // Seta os cenários iniciais ativos
                Object.entries(msg.data).forEach(([labId, scenario]) => {
                    document.querySelectorAll(`.btn-scenario[data-lab="${labId}"]`).forEach(btn => {
                        btn.classList.remove("active");
                        if (btn.getAttribute("data-scenario") === scenario) {
                            btn.classList.add("active");
                        }
                    });
                });
                break;
                
            case "status":
                handleStatusUpdate(msg.data);
                break;
                
            case "alert":
                addAlertToFeed(msg.data);
                
                // Força o PC a ir para alerta na tela imediatamente
                if (msg.data.device_id) {
                    const square = document.getElementById(`square-${msg.data.device_id}`);
                    if (square) {
                        square.className = "pc-square state-alert";
                        if (selectedDeviceId === msg.data.device_id) square.classList.add("selected");
                    }
                }
                break;

            case "environment":
                // Atualiza a temperatura ambiente dinamicamente na UI
                const tempLabel = document.getElementById(`${msg.data.lab_id}-temp-avg`);
                if (tempLabel) {
                    tempLabel.textContent = `${msg.data.temperatura_ambiente}°C`;
                }
                break;
                
            case "scenario_change":
                const { lab_id, scenario } = msg.data;
                document.querySelectorAll(`.btn-scenario[data-lab="${lab_id}"]`).forEach(btn => {
                    btn.classList.remove("active");
                    if (btn.getAttribute("data-scenario") === scenario) {
                        btn.classList.add("active");
                    }
                });
                break;
        }
    };

    socket.onclose = () => {
        console.log("WebSocket desconectado. Tentando reconectar...");
        const badge = document.getElementById("ws-status");
        badge.className = "status-indicator offline";
        badge.innerHTML = `<i class="fa-solid fa-circle"></i> Desconectado`;
        
        // Tenta reconectar em 3 segundos
        setTimeout(connectWS, 3000);
    };

    socket.onerror = (error) => {
        console.error("Erro no WebSocket:", error);
        socket.close();
    };
}

// Inicia relógio
function startClock() {
    setInterval(() => {
        document.getElementById("clock").textContent = new Date().toLocaleTimeString();
    }, 1000);
}

// Inicia o timer que mostra o tempo desde o último refresh de dados
function startLastUpdateTimer() {
    const timerLabel = document.getElementById("last-update-timer");
    setInterval(() => {
        if (!lastUpdateTime) {
            timerLabel.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i> Sem dados recentes`;
            timerLabel.className = "last-update-timer warning";
            return;
        }

        const elapsed = Math.round((Date.now() - lastUpdateTime) / 1000);
        timerLabel.innerHTML = `<i class="fa-solid fa-arrows-rotate ${elapsed <= 5 ? 'animate-spin' : ''}"></i> Atualizado há ${elapsed}s`;

        if (elapsed >= 30) {
            timerLabel.className = "last-update-timer danger";
        } else if (elapsed >= 15) {
            timerLabel.className = "last-update-timer warning";
        } else {
            timerLabel.className = "last-update-timer";
        }
    }, 1000);
}

// Carrega os últimos alertas ao iniciar
async function loadRecentAlerts() {
    try {
        const response = await fetch("/alerts");
        if (response.status === 200) {
            const alerts = await response.json();
            // Inverte para exibir cronológico de baixo para cima ou apenas renderiza
            alerts.reverse().forEach(alert => addAlertToFeed(alert));
        }
    } catch (e) {
        console.error("Falha ao buscar alertas iniciais:", e);
    }
}

// Abre o modal de histórico e carrega os dados
async function openHistoryModal(labId) {
    historyActiveLab = labId;
    document.getElementById("history-lab-title").textContent = labId === "LAB1" ? "Laboratório 01" : labId === "LAB2" ? "Laboratório 02" : "Laboratório 03";
    document.getElementById("history-modal").classList.remove("hidden");
    await loadHistoryData();
}

// Fecha o modal de histórico
function closeHistoryModal() {
    document.getElementById("history-modal").classList.add("hidden");
    historyActiveLab = null;
}

// Carrega os dados de histórico do backend e renderiza na tabela
async function loadHistoryData() {
    if (!historyActiveLab) return;
    
    const interval = document.getElementById("history-interval").value;
    const tbody = document.getElementById("history-table-body");
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #94a3b8;"><i class="fa-solid fa-spinner animate-spin"></i> Carregando dados...</td></tr>`;

    try {
        const response = await fetch(`/labs/${historyActiveLab}/historico?intervalo=${interval}`);
        if (response.status === 200) {
            const data = await response.json();
            tbody.innerHTML = ""; // Limpa carregamento

            if (data.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #94a3b8;">Nenhum registro encontrado para este intervalo.</td></tr>`;
                return;
            }

            // Mostra os mais recentes primeiro
            data.reverse().forEach(row => {
                const tr = document.createElement("tr");
                const date = new Date(row.timestamp);
                const timeStr = date.toLocaleString('pt-BR');

                tr.innerHTML = `
                    <td>${timeStr}</td>
                    <td>${row.cpu_avg}%</td>
                    <td>${row.ram_avg}%</td>
                    <td>${row.temp_avg}°C</td>
                    <td>${row.active_pcs} / 10</td>
                    <td>${row.total_energy} kW</td>
                `;
                tbody.appendChild(tr);
            });
        } else {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #f87171;">Erro ao carregar dados do servidor (${response.status}).</td></tr>`;
        }
    } catch (error) {
        console.error("Erro ao buscar histórico:", error);
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #f87171;">Erro de conexão com o servidor.</td></tr>`;
    }
}

// Inicialização geral
window.addEventListener("DOMContentLoaded", () => {
    buildGrids();
    setupScenarioButtons();
    startClock();
    startLastUpdateTimer();
    connectWS();
    loadRecentAlerts();

    // Registra cliques dos triggers de histórico
    document.querySelectorAll(".btn-history-trigger").forEach(button => {
        button.addEventListener("click", () => {
            const labId = button.getAttribute("data-lab");
            openHistoryModal(labId);
        });
    });

    // Registra cliques de fechamento do modal
    document.getElementById("close-history-modal").addEventListener("click", closeHistoryModal);
    document.getElementById("history-modal").addEventListener("click", (e) => {
        if (e.target.id === "history-modal") closeHistoryModal();
    });

    // Registra clique de atualizar
    document.getElementById("refresh-history-btn").addEventListener("click", loadHistoryData);
    document.getElementById("history-interval").addEventListener("change", loadHistoryData);

    // Configura botão de limpar alertas
    document.getElementById("clear-alerts").addEventListener("click", () => {
        const feed = document.getElementById("alert-feed");
        feed.innerHTML = `<div class="no-alerts-placeholder">Nenhum alerta crítico registrado no momento.</div>`;
    });
});
