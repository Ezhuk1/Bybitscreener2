# coding=utf-8
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "Futures pump bot is alive"

def _run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    Thread(target=_run, daemon=True).start()
