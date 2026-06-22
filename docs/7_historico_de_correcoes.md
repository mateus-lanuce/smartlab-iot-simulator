# Módulo 7: Histórico de Alterações e Correções

Este documento serve como histórico de engenharia, explicando as principais correções aplicadas e a arquitetura das soluções adotadas.

---

## 1. O Bug do Event Loop do Uvicorn / FastAPI

Durante o desenvolvimento inicial, o dashboard conectava-se via WebSocket e o status constava como "Conectado", mas **nenhuma informação de telemetria era exibida na tela**.

### Investigação Técnica
1. No arquivo [backend_api.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/backend_api.py) (anteriormente `backend.py`), o consumidor do RabbitMQ roda em uma thread separada para não bloquear o servidor web.
2. Quando a thread consome uma mensagem, ela precisa avisar o loop do asyncio principal (que gerencia o WebSocket do FastAPI) para enviar o dado aos navegadores ativos.
3. Isso era feito usando a função `asyncio.run_coroutine_threadsafe(..., fastapi_loop)`.
4. **O Erro:** A variável `fastapi_loop` era instanciada na thread principal chamando `fastapi_loop = asyncio.get_event_loop()` antes da execução do servidor ASGI Uvicorn:
   ```python
   # ANTIGO (Com Bug)
   if __name__ == "__main__":
       fastapi_loop = asyncio.get_event_loop() # Loop antigo e inativo
       uvicorn.run(app, host="0.0.0.0", port=8000)
   ```
5. Quando o `uvicorn.run(...)` era disparado, ele descartava o event loop atual, criava um **novo loop ativo do zero** e executava o FastAPI sobre ele.
6. A thread do RabbitMQ tentava empacotar dados chamando o loop antigo, que estava parado e adormecido. Como resultado, as mensagens eram perdidas de forma silenciosa e nada era enviado ao WebSocket.

### Solução Arquitetural
Capturamos o loop dinamicamente assim que a aplicação de fato inicia e quando conexões de rede ocorrem no servidor:
```python
# NOVO (Corrigido)
@app.on_event("startup")
async def startup_event():
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop() # Captura o loop ativo do Uvicorn

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop() # Assegura loop correto
    ...
```
Esta alteração sincronizou as threads e fez as telemetrias reaparecerem no Dashboard Web.

---

## 2. Parser Temporal e Filtro Histórico SQLite

O histórico do laboratório é persistido com timestamps no formato de string ISO8601 (ex: `2026-06-22T01:10:00Z`). Para implementar filtros flexíveis como `10m`, `1h` ou `24h` diretamente na tabela do SQLite, criamos um interpretador dinâmico:

### O Interpretador Dinâmico (`parse_interval`)
   Em [backend_api.py](file:///c:/Users/mateus/Documents/projeto_ph/backend/backend_api.py), a função traduz strings em datas relativas usando offsets em UTC:
* `10m` -> `datetime.utcnow() - timedelta(minutes=10)`
* `1h` -> `datetime.utcnow() - timedelta(hours=1)`
* `24h` -> `datetime.utcnow() - timedelta(hours=24)`
* `7d` -> `datetime.utcnow() - timedelta(days=7)`

### A Consulta SQL
A data limite gerada é convertida de volta para formato de texto ISO8601 e enviada ao motor do SQLite:
```sql
SELECT timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy 
FROM lab_statistics 
WHERE lab_id = ? AND timestamp >= ? 
ORDER BY id DESC
```
Como o formato de data ISO8601 é alfanumericamente ordenável, o SQLite consegue rodar o filtro `timestamp >= threshold_str` de forma rápida e eficiente.

---

## 3. Limpeza de Rotas HTTP REST

Inicialmente, existiam rotas com o prefixo duplicado `/api` (ex: `/api/labs/{id}/status`) misturadas com rotas limpas. 
* **Ação Corretiva:** Removemos todas as rotas duplicadas com `/api` para respeitar as especificações originais do PDF da prática, mantendo apenas a pasta `/static` para arquivos de frontend e expondo as APIs de consumo de forma limpa diretamente na raiz:
  * `GET /labs/{lab_id}/status`
  * `GET /labs/{lab_id}/historico`
  * `GET /twins/{device_id}`
  * `GET /alerts`
* **Exceção de Simulação:** As rotas internas de orquestração de cenários da simulação foram mantidas separadas em `/api/simulation/scenario` para evitar conflito com os dados dos Digital Twins.
