from flask import Flask, request, jsonify
import requests
import uuid

app = Flask(__name__)

YOOKASSA_SHOP_ID = "1346746"
YOOKASSA_SECRET_KEY = "live_zkv0c-zUwrtk36xvMD6ylyVcKQh06ST5uh9-Cql7-Kg"

@app.route('/create_payment', methods=['POST'])
def create_payment():
    data = request.json
    amount = data.get('amount')
    description = data.get('description')
    user_id = data.get('user_id')
    tariff_id = data.get('tariff_id')
    
    idempotence_key = str(uuid.uuid4())
    
    payment_data = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB"
        },
        "payment_method_data": {
            "type": "bank_card"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/testVPNamirbot"
        },
        "description": description,
        "capture": True,
        "metadata": {
            "user_id": str(user_id),
            "tariff_id": str(tariff_id)
        }
    }
    
    auth = (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
    headers = {
        "Idempotence-Key": idempotence_key,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            "https://api.yookassa.ru/v3/payments",
            json=payment_data,
            headers=headers,
            auth=auth
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                "payment_url": result["confirmation"]["confirmation_url"],
                "payment_id": result["id"]
            })
        else:
            return jsonify({"error": f"Ошибка ЮKassa: {response.status_code}", "details": response.text}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)