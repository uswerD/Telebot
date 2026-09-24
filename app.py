import os
import requests
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

@app.route("/")
def home():
    return "BOT IS RUNNING", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data:
        return "OK", 200

    message = data.get("message")

    if not message:
        return "OK", 200

    chat = message.get("chat")

    if not chat:
        return "OK", 200

    chat_id = chat.get("id")
    text = message.get("text", "")

    if text == "/start":
        answer = "Привет! Бот работает 🤖"
    elif text:
        answer = f"Ты написал: {text}"
    else:
        answer = "Я понимаю только текст."

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": answer
        },
        timeout=10
    )

    print("Telegram:", response.status_code, response.text, flush=True)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
