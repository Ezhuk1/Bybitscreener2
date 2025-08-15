# coding=utf-8
import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
import websockets

from keep_alive import keep_alive

# === Telegram config ===
TG_TOKEN = os.getenv("TG_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()

# === Bybit config ===
WS_URL = "wss://stream.bybit.com/v5/public/linear"
SUB_CHUNK = 10
REFRESH_SYMBOLS_EVERY_MIN = 30

# === Signal filters ===
MIN_CHANGE = {
    "BTC_ETH": 0.004,
    "TOP_ALT": 0.005,
    "MID_ALT": 0.008,
    "LOW_ALT": 0.015
}
MIN_TURNOVER = {
    "BTC_ETH": 1_000_000,
    "TOP_ALT": 300_000,
    "MID_ALT": 100_000,
    "LOW_ALT": 50_000
}
ATR_MULT = {
    "BTC_ETH": 1.2,
    "TOP_ALT": 1.5,
    "MID_ALT": 2.0,
    "LOW_ALT": 2.5
}
ATR_PERIOD = 15

TOP_ALT = {"SOLUSDT", "BNBUSDT", "XRPUSDT", "TONUSDT", "ADAUSDT", "DOGEUSDT", "TRXUSDT", "LINKUSDT"}
MID_ALT = {"ATOMUSDT", "AVAXUSDT", "LTCUSDT", "MATICUSDT", "DOTUSDT", "ALGOUSDT", "FILUSDT"}

def classify_symbol(symbol: str) -> str:
    if symbol in {"BTCUSDT", "ETHUSDT"}:
        return "BTC_ETH"
    elif symbol in TOP_ALT:
        return "TOP_ALT"
    elif symbol in MID_ALT:
        return "MID_ALT"
    else:
        return "LOW_ALT"

def now_utc():
    return datetime.now(timezone.utc)

def send_tg_signal(symbol: str, change: float, close_price: float, turnover: float):
    url_bybit = f"https://www.bybit.com/trade/usdt/{symbol}"
    url_cmc = f"https://coinmarketcap.com/currencies/{symbol.replace('USDT','').lower()}/"
    ts = now_utc().strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f"🔥 <a href='{url_bybit}'>{symbol}</a> +{change*100:.2f}%\n"
        f"Цена: {close_price}\n"
        f"Оборот: ${turnover:,.0f}\n"
        f"Время: {ts}"
    )
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "📈 Открыть график", "url": url_bybit},
                {"text": "📊 CoinMarketCap", "url": url_cmc}
            ]]
        }
    }
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json=payload,
            timeout=10
        )
    except Exception as e:
        print("TG error:", e)

def fetch_symbols_linear_usdt() -> list[str]:
    url = "https://api.bybit.com/v5/market/instruments-info"
    params = {"category": "linear", "limit": 500}
    out = []
    cursor = None
    while True:
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            res = r.json().get("result", {})
            items = res.get("list", []) or []
            for s in items:
                if s.get("quoteCoin") == "USDT" and s.get("status") == "Trading":
                    out.append(s.get("symbol"))
            cursor = res.get("nextPageCursor") or res.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print("Symbol fetch error:", e)
            break
    return sorted(set(out))

async def subscribe_klines(ws, symbols: list[str]):
    for i in range(0, len(symbols), SUB_CHUNK):
        args = [f"kline.1.{s}" for s in symbols[i:i+SUB_CHUNK]]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))
        await asyncio.sleep(0.25)

class ATRState:
    def __init__(self, period: int):
        self.ema = None
        self.alpha = 2 / (period + 1)
        self.warmup = 0

    def update(self, rng: float) -> float:
        if rng is None:
            return self.ema if self.ema else 0.0
        if self.ema is None:
            self.ema = rng
        else:
            self.ema = self.alpha * rng + (1 - self.alpha) * self.ema
        self.warmup = min(self.warmup + 1, ATR_PERIOD)
        return self.ema

    @property
    def ready(self) -> bool:
        return self.warmup >= max(3, ATR_PERIOD // 3)

atr_map = defaultdict(lambda: ATRState(ATR_PERIOD))

async def run_bot():
    symbols = fetch_symbols_linear_usdt()
    print(f"Loaded {len(symbols)} symbols")
    next_refresh = now_utc() + timedelta(minutes=REFRESH_SYMBOLS_EVERY_MIN)

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                await subscribe_klines(ws, symbols)
                print("Subscribed. Monitoring...")

                while True:
                    if now_utc() >= next_refresh:
                        new_symbols = fetch_symbols_linear_usdt()
                        if set(new_symbols) != set(symbols):
                            symbols = new_symbols
                            break
                        next_refresh = now_utc() + timedelta(minutes=REFRESH_SYMBOLS_EVERY_MIN)

                    msg = await ws.recv()
                    data = json.loads(msg)
                    topic = data.get("topic", "")
                    if not topic.startswith("kline.1."):
                        continue

                    symbol = topic.split(".", 2)[2]
                    klines = data.get("data") or []
                    for k in klines:
                        if str(k.get("confirm")).lower() != "true":
                            continue
                        try:
                            o = float(k["open"])
                            h = float(k["high"])
                            l = float(k["low"])
                            c = float(k["close"])
                            turnover = float(k.get("turnover", 0.0))
                        except:
                            continue
                        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                            continue

                        rng = abs(h - l)
                        atr_val = atr_map[symbol].update(rng)
                        change = (c - o) / o
                        sym_type = classify_symbol(symbol)

                        passes = (
                            change >= MIN_CHANGE[sym_type] and
                            turnover >= MIN_TURNOVER[sym_type] and
                            atr_map[symbol].ready and
                            change >= (atr_val * ATR_MULT[sym_type])
                        )

                        if passes:
                            send_tg_signal(symbol, change, c, turnover)

        except Exception as e:
            print("Reconnect in 5s:", e)
            await asyncio.sleep(5)

def main():
    keep_alive()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
