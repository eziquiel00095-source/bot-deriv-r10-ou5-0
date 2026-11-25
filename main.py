import os
import json
import time
import logging
import websocket

# ================= CONFIGURAÇÕES =================
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089")
DERIV_TOKEN = os.getenv("DERIV_TOKEN", "COLE_SEU_TOKEN_DEMO_AQUI")

SYMBOL = "R_10"                # Volatility 10 Index (normal)
BARRIER = "5"                  # Barreira Over/Under 5
DURATION = 1                   # 1 tick
DURATION_UNIT = "t"

STAKE_INICIAL = 1.0            # Stake base ($1.00)
MARTINGALE = 2.1               # Multiplicador apenas na derrota
TRIGGER_TICKS = 3              # 3 ticks seguidos a favor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot_r10_ou5.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ================= ESTADO DO ROBÔ =================
aposta_atual = STAKE_INICIAL
cont_baixo = 0
cont_alto = 0
aguardando_contrato = False


def send_json(ws, payload):
    ws.send(json.dumps(payload))


def comprar_contrato(ws, contract_type):
    global aguardando_contrato

    aguardando_contrato = True
    stake_formatada = round(aposta_atual, 2)

    logging.info(
        f"SINAL BATIDO -> {contract_type} | Ativo: {SYMBOL} | Barreira: {BARRIER} | Stake: ${stake_formatada:.2f}"
    )

    send_json(ws, {
        "proposal": 1,
        "amount": stake_formatada,
        "basis": "stake",
        "contract_type": contract_type,
        "currency": "USD",
        "duration": DURATION,
        "duration_unit": DURATION_UNIT,
        "symbol": SYMBOL,
        "barrier": BARRIER
    })


def processar_tick(ws, tick_value):
    global cont_baixo, cont_alto, aguardando_contrato

    tick_str = f"{tick_value:.2f}" if isinstance(tick_value, float) else str(tick_value)
    ultimo_digito = int(tick_str.replace(".", "")[-1])

    if ultimo_digito < 5:
        cont_baixo += 1
        cont_alto = 0
    elif ultimo_digito > 5:
        cont_alto += 1
        cont_baixo = 0
    else:
        cont_baixo = 0
        cont_alto = 0

    if aguardando_contrato:
        return

    if cont_baixo >= TRIGGER_TICKS:
        cont_baixo = 0
        comprar_contrato(ws, "DIGITUNDER")

    elif cont_alto >= TRIGGER_TICKS:
        cont_alto = 0
        comprar_contrato(ws, "DIGITOVER")


def processar_contrato_encerrado(contract):
    global aposta_atual, aguardando_contrato

    if not contract.get("is_sold"):
        return

    profit = float(contract.get("profit", 0.0))
    won = profit > 0

    if won:
        logging.info(
            f"VITÓRIA (+${profit:.2f}) -> Stake volta para ${STAKE_INICIAL:.2f}. Aguardando próximo filtro de 3 ticks."
        )
        aposta_atual = STAKE_INICIAL
    else:
        aposta_atual = round(aposta_atual * MARTINGALE, 2)
        logging.warning(
            f"DERROTA (${profit:.2f}) -> Martingale {MARTINGALE}x: próxima stake será ${aposta_atual:.2f}. Aguardando próximo filtro."
        )

    aguardando_contrato = False


def on_open(ws):
    logging.info("Conectado à Deriv. Autorizando token...")
    send_json(ws, {"authorize": DERIV_TOKEN})


def on_message(ws, message):
    global aguardando_contrato

    data = json.loads(message)
    msg_type = data.get("msg_type")

    if "error" in data:
        logging.error(f"Erro da API Deriv ({msg_type}): {data['error'].get('message')}")
        if msg_type in ("proposal", "buy"):
            aguardando_contrato = False
        return

    if msg_type == "authorize":
        loginid = data["authorize"].get("loginid")
        balance = data["authorize"].get("balance")
        logging.info(f"Autorizado em {loginid} | Saldo: ${balance}")

        send_json(ws, {"ticks": SYMBOL, "subscribe": 1})
        send_json(ws, {"proposal_open_contract": 1, "subscribe": 1})

    elif msg_type == "tick":
        processar_tick(ws, data["tick"]["quote"])

    elif msg_type == "proposal":
        proposal_id = data["proposal"]["id"]
        ask_price = data["proposal"].get("ask_price")
        send_json(ws, {
            "buy": proposal_id,
            "price": ask_price
        })

    elif msg_type == "buy":
        contract_id = data["buy"]["contract_id"]
        buy_price = data["buy"].get("buy_price")
        logging.info(f"Compra confirmada | ID: {contract_id} | Stake: ${buy_price}")

    elif msg_type == "proposal_open_contract":
        processar_contrato_encerrado(data["proposal_open_contract"])


def on_error(ws, error):
    logging.error(f"Erro no WebSocket: {error}")


def on_close(ws, close_status_code, close_msg):
    logging.warning(f"Conexão fechada (código={close_status_code}, msg={close_msg}).")


def iniciar_robo():
    if not DERIV_TOKEN or DERIV_TOKEN == "COLE_SEU_TOKEN_DEMO_AQUI":
        logging.error("Configure a variável de ambiente DERIV_TOKEN antes de rodar!")
        return

    ws_url = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    espera = 15

    while True:
        inicio = time.monotonic()
        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(
                ping_interval=30,
                ping_timeout=10,
                origin="https://app.deriv.com"
            )
        except Exception as exc:
            logging.exception(f"Erro inesperado: {exc}")

        # Se ficou conectado por mais de 30s, reseta a espera; senão aumenta até 60s
        if time.monotonic() - inicio > 30:
            espera = 15
        else:
            espera = min(espera * 2, 60)

        logging.info(f"Reconectando em {espera} segundos...")
        time.sleep(espera)


if __name__ == "__main__":
    iniciar_robo()
