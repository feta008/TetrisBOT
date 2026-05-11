from flask import Flask, request, jsonify, render_template_string
import requests
import uuid
import json
import random
import string
from datetime import datetime, timedelta

app = Flask(__name__)

# ========== НАСТРОЙКИ ==========
YOOKASSA_SHOP_ID = "1346746"
YOOKASSA_SECRET_KEY = "live_zkv0c-zUwrtk36xvMD6ylyVcKQh06ST5uh9-Cql7-Kg"

XUI_HOST = "91.124.19.122"
XUI_PORT = 58763
XUI_USERNAME = "4WMi0f7K9s"
XUI_PASSWORD = "12345678"
INBOUND_ID = 1
XUI_API_PATH = "/7ZnLQd7YIq9uEDbBwy"

BOT_TOKEN = "8272029706:AAHzpsU6RtmnACgOs6luOaTTy8V0CFXa0Rk"
BOT_USERNAME = "TetrisVPN"  # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ USERNAME

# ========== ТАРИФЫ ==========
TARIFF_DAYS = {
    1: 3,
    2: 30,
    3: 90,
    4: 180,
    5: 365
}

# ========== HTML ШАБЛОН (встроенный) ==========
PAYMENT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Оплата TetrisVPN</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
    <script src="https://yookassa.ru/checkout-widget/v1/checkout-widget.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .payment-card {
            background: white;
            border-radius: 24px;
            padding: 32px 24px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
        }
        h1 { font-size: 28px; color: #1a1a2e; margin-bottom: 8px; }
        .subtitle { color: #666; margin-bottom: 32px; font-size: 14px; }
        .amount {
            background: #f8f9fa;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 24px;
        }
        .amount-label { font-size: 14px; color: #666; }
        .amount-value { font-size: 36px; font-weight: bold; color: #1a1a2e; }
        .amount-currency { font-size: 18px; font-weight: normal; }
        #payment-form { min-height: 400px; }
        .loader {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 200px;
        }
        .loader-spinner {
            width: 48px;
            height: 48px;
            border: 4px solid #e0e0e0;
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .footer { margin-top: 24px; font-size: 12px; color: #999; }
        .error { color: red; padding: 20px; }
    </style>
</head>
<body>
    <div class="payment-card">
        <h1>💎 TetrisVPN</h1>
        <div class="subtitle">Оплата подписки</div>
        <div class="amount">
            <div class="amount-label">Сумма к оплате</div>
            <div class="amount-value">{{ amount }} <span class="amount-currency">₽</span></div>
        </div>
        <div id="payment-form">
            <div class="loader"><div class="loader-spinner"></div></div>
        </div>
        <div class="footer">🔒 Безопасная оплата через ЮKassa<br>Поддержка: @tetris_mhk</div>
    </div>
    <script>
        const checkout = new YooKassaCheckoutWidget({
            confirmation_token: '{{ confirmation_token }}',
            return_url: '{{ return_url }}',
            error_callback: function(error) {
                document.getElementById('payment-form').innerHTML = '<div class="error">❌ Ошибка загрузки оплаты. Попробуйте позже.</div>';
            }
        });
        checkout.render('payment-form');
        checkout.on('success', function() {
            window.location.href = '{{ success_url }}';
        });
    </script>
</body>
</html>
"""

# ========== ФУНКЦИИ ==========
def get_3xui_session():
    session = requests.Session()
    session.verify = False
    login_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/login"
    session.post(login_url, json={"username": XUI_USERNAME, "password": XUI_PASSWORD})
    return session

def create_vpn_client(email: str, days: int):
    try:
        session = get_3xui_session()
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
            headers={'X-Requested-With': 'XMLHttpRequest'},
            timeout=30
        )
        
        if resp.status_code == 200:
            return f"https://tetrisbot.abrdns.com:2096/sub/{sub_id}", client_uuid
        return None, None
    except Exception as e:
        print(f"Ошибка: {e}")
        return None, None

# ========== СОЗДАНИЕ ПЛАТЕЖА (возвращает страницу с виджетом) ==========
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
        "confirmation": {"type": "embedded"},  # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ!
        "description": description,
        "capture": True,
        "metadata": {"user_id": str(user_id), "tariff_id": str(tariff_id)}
    }
    
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    headers = {"Idempotence-Key": idempotence_key, "Content-Type": "application/json"}
    response = requests.post("https://api.yookassa.ru/v3/payments", json=payment_data, headers=headers, auth=auth, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        # Возвращаем URL страницы с виджетом
        payment_page_url = f"https://194.87.235.120:8443/pay/{result['id']}?amount={amount}"
        return jsonify({
            "payment_url": payment_page_url,
            "payment_id": result['id']
        })
    return jsonify({"error": response.text}), 400

# ========== СТРАНИЦА ОПЛАТЫ С ВИДЖЕТОМ ==========
@app.route('/pay/<payment_id>', methods=['GET'])
def payment_page(payment_id):
    amount = request.args.get('amount', '0')
    
    # Получаем информацию о платеже из ЮKassa
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    resp = requests.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=auth, timeout=30)
    
    if resp.status_code != 200:
        return "Платёж не найден", 404
    
    payment_data = resp.json()
    confirmation_token = payment_data.get('confirmation', {}).get('confirmation_token')
    
    if not confirmation_token:
        return "Ошибка: нет токена для оплаты", 500
    
    return render_template_string(
        PAYMENT_HTML,
        amount=amount,
        confirmation_token=confirmation_token,
        return_url=f"https://t.me/{BOT_USERNAME}",
        success_url=f"https://t.me/{BOT_USERNAME}"
    )

# ========== ПРОВЕРКА ПЛАТЕЖА ==========
@app.route('/check_payment', methods=['GET'])
def check_payment():
    payment_id = request.args.get('payment_id')
    if not payment_id:
        return jsonify({"error": "missing payment_id"}), 400
    
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    response = requests.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=auth, timeout=30)
    
    if response.status_code != 200:
        return jsonify({"error": "yookassa error"}), 500
    
    data = response.json()
    status = data.get('status')
    
    if status == 'succeeded':
        metadata = data.get('metadata', {})
        user_id = int(metadata.get('user_id', 0))
        tariff_id = int(metadata.get('tariff_id', 2))
        days = TARIFF_DAYS.get(tariff_id, 30)
        
        email = f"paid_{user_id}_{int(datetime.now().timestamp())}"
        vless_link, vpn_uuid = create_vpn_client(email, days)
        
        if vless_link:
            # Отправляем ссылку пользователю в Telegram
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": f"✅ Оплата подтверждена!\n\n🔗 <code>{vless_link}</code>\n\n📱 Вставь ссылку в V2RayNG или Happ", "parse_mode": "HTML"},
                timeout=10
            )
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
        days = TARIFF_DAYS.get(tariff_id, 30)
        
        email = f"webhook_{user_id}_{int(datetime.now().timestamp())}"
        vless_link, _ = create_vpn_client(email, days)
        
        if vless_link:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": f"✅ Оплата подтверждена!\n\n🔗 <code>{vless_link}</code>", "parse_mode": "HTML"},
                timeout=10
            )
    return "OK", 200

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8444)
