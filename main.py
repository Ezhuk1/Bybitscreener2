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

def build_bybit
