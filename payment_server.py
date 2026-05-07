from flask import Flask, request, jsonify
import requests
import uuid
import json
import random
import string
from datetime import datetime, timedelta

app = Flask(__name__)

# ========== НАСТРОЙКИ ЮKASSA ==========
YOOKASSA_SHOP_ID = "1346746"
YOOKASSA_SECRET_KEY = "live_zkv0c-zUwrtk36xvMD6ylyVcKQh06ST5uh9-Cql7-Kg"

# ========== НАСТРОЙКИ НОВОГО СЕРВЕРА (Нидерланды) ==========
XUI_HOST = "91.124.19.122"           # НОВЫЙ IP!
XUI_PORT = 58763
XUI_USERNAME = "4WMi0f7K9s"
XUI_PASSWORD = "12345678"
INBOUND_ID = 1                       # ID инбаунда на новом сервере
XUI_API_PATH = "/7ZnLQd7YIq9uEDbBwy" # webBasePath с нового сервера

# ========== НАСТРОЙКИ БОТА (НОВЫЙ) ==========
BOT_TOKEN = "8272029706:AAHzpsU6RtmnACgOs6luOaTTy8V0CFXa0Rk"  # НОВЫЙ токен!

# ========== ФУНКЦИЯ СОЗДАНИЯ VPN КЛИЕНТА ==========
def create_vpn_client(email: str, days: int):
    session = requests.Session()
    session.verify = False
    login_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/login"
    session.post(login_url, json={"username": XUI_USERNAME, "password": XUI_PASSWORD})
    
    client_uuid = str(uuid.uuid4())
    expiry = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
    sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    client_data = {
        "id": client_uuid, "flow": "", "email": email, "limitIp": 3,
        "totalGB": 0, "expiryTime": expiry, "enable": True,
        "tgId": "", "subId": sub_id, "reset": 0
    }
    add_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/panel/api/inbounds/addClient"
    resp = session.post(
        add_url,
        data={"id": INBOUND_ID, "settings": json.dumps({"clients": [client_data]})},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    if resp.status_code == 200:
        return f"https://tetrisbot.abrdns.com:2096/sub/{sub_id}"
    return None

# ========== СОЗДАНИЕ ПЛАТЕЖА ==========
@app.route('/create_payment', methods=['POST'])
def create_payment():
    data = request.json
    amount = data.get('amount')
    description = data.get('description')
    user_id = data.get('user_id')
    tariff_id = data.get('tariff_id')
    
    idempotence_key = str(uuid.uuid4())
    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "payment_method_data": {"type": "bank_card"},
        "confirmation": {"type": "redirect", "return_url": "https://t.me/ТВОЙ_НОВЫЙ_БОТ"},
        "description": description,
        "capture": True,
        "metadata": {"user_id": str(user_id), "tariff_id": str(tariff_id)}
    }
    
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    headers = {"Idempotence-Key": idempotence_key, "Content-Type": "application/json"}
    response = requests.post("https://api.yookassa.ru/v3/payments", json=payment_data, headers=headers, auth=auth)
    
    if response.status_code == 200:
        result = response.json()
        return jsonify({"payment_url": result["confirmation"]["confirmation_url"], "payment_id": result["id"]})
    return jsonify({"error": response.text}), 400

# ========== ПРОВЕРКА ПЛАТЕЖА ==========
@app.route('/check_payment', methods=['GET'])
def check_payment():
    payment_id = request.args.get('payment_id')
    if not payment_id:
        return jsonify({"error": "missing payment_id"}), 400
    
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    response = requests.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=auth)
    if response.status_code != 200:
        return jsonify({"error": "yookassa error"}), 500
    
    data = response.json()
    status = data.get('status')
    if status == 'succeeded':
        metadata = data.get('metadata', {})
        user_id = int(metadata.get('user_id', 0))
        tariff_id = int(metadata.get('tariff_id', 2))
        days = 30 if tariff_id == 2 else 90
        email = f"paid_{user_id}_{int(datetime.now().timestamp())}"
        vless_link = create_vpn_client(email, days)
        if vless_link:
            return jsonify({"status": "succeeded", "vless_link": vless_link})
        return jsonify({"status": "succeeded", "vless_link": None})
    return jsonify({"status": status})

# ========== ВЕБХУК ОТ ЮKASSA ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if data.get('event') == 'payment.succeeded':
        payment = data['object']
        metadata = payment.get('metadata', {})
        user_id = int(metadata.get('user_id', 0))
        tariff_id = int(metadata.get('tariff_id', 2))
        days = 30 if tariff_id == 2 else 90
        email = f"webhook_{user_id}_{int(datetime.now().timestamp())}"
        vless_link = create_vpn_client(email, days)
        if vless_link:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": f"✅ Оплата подтверждена!\n🔗 <code>{vless_link}</code>", "parse_mode": "HTML"}
            )
    return "OK", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
