import asyncio
import logging
import uuid
import json
import requests
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db
import urllib3
urllib3.disable_warnings()
import os
os.environ['HTTP_PROXY'] = 'http://144.31.54.21:3128'
os.environ['HTTPS_PROXY'] = 'http://144.31.54.21:3128'

# ========== НАСТРОЙКИ 3X-UI ==========
XUI_HOST = "144.31.54.21"
XUI_PORT = 58763
XUI_USERNAME = "4WMi0f7K9s"
XUI_PASSWORD = "12345678"
INBOUND_ID = 5
# ====================================

# ========== НАСТРОЙКИ ЮKassa ==========
YOOKASSA_SHOP_ID = "1346746"
YOOKASSA_SECRET_KEY = "live_zkv0c-zUwrtk36xvMD6ylyVcKQh06ST5uh9-Cql7-Kg"
YOOKASSA_ENABLED = True  # Поставь False, чтобы отключить реальные платежи
# ====================================

BOT_TOKEN = "8463325671:AAFk8vh9TUf1oBmj2Fip7pxWWK45p579aE0"
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial")],
        [InlineKeyboardButton(text="📊 Мой профиль", callback_data="profile")]
    ])

def create_vpn_client(email: str, days: int):
    session = requests.Session()
    session.verify = False

    login_url = f"https://144.31.54.21:58763/mYLfcCSnMkPJREgznL/login"
    login_resp = session.post(login_url, json={"username": "4WMi0f7K9s", "password": "12345678"})
    if login_resp.status_code != 200:
        print("Ошибка логина")
        return None

    client_uuid = str(uuid.uuid4())
    expiry = int((datetime.now() + timedelta(days=days)).timestamp() * 1000) if days > 0 else 0
    import random
    import string
    sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

    client_data = {
        "id": client_uuid,
        "flow": "",
        "email": email,
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": expiry,
        "enable": True,
        "tgId": "",
        "subId": sub_id,
        "reset": 0
    }

    add_url = f"https://144.31.54.21:58763/mYLfcCSnMkPJREgznL/panel/inbound/addClient"
    resp = session.post(
        add_url,
        data={"id": INBOUND_ID, "settings": json.dumps({"clients": [client_data]})},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )

    if resp.status_code != 200:
        return None

    return f"https://tetrisbot.abrdns.com:2096/sub/{sub_id}"

# ========== ФУНКЦИЯ ДЛЯ РЕАЛЬНОЙ ОПЛАТЫ ==========
def create_yookassa_payment(amount: float, description: str, user_id: int, tariff_id: int):
    """Создаёт платёж в ЮKassa и возвращает URL для оплаты"""
    try:
        from yoomoney import Quickpay
        
        quickpay = Quickpay(
            receiver=YOOKASSA_SHOP_ID,
            quickpay_form="shop",
            targets=description,
            paymentType="SB",
            sum=amount,
            label=f"user_{user_id}_{tariff_id}_{int(datetime.now().timestamp())}",
            successURL="https://t.me/testVPNamirbot"
        )
        return quickpay.redirected_url
    except Exception as e:
        print(f"Ошибка создания платежа: {e}")
        return None

@dp.message(Command("start"))
async def start(message: types.Message):
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    await message.answer(f"👋 Привет, {user.first_name}!\n\nВыбери действие:", reply_markup=main_menu())

@dp.callback_query(F.data == "trial")
async def trial(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    active_sub = db.get_active_subscription(user_id)
    if active_sub and active_sub.days_left() > 0:
        await callback.message.edit_text(
            f"🎁 Твой пробный период активен!\n📅 До {active_sub.end_date.strftime('%d.%m.%Y')}\n⏰ Осталось {active_sub.days_left()} дн.\n\n🔗 <code>{active_sub.vpn_config}</code>",
            parse_mode="HTML", reply_markup=main_menu()
        )
        await callback.answer()
        return
    
    if db.has_trial_used(user_id):
        await callback.message.edit_text("❌ Пробный период уже использован!\nНажми «Купить подписку».", reply_markup=main_menu())
        await callback.answer()
        return
    
    tariffs = db.get_all_tariffs()
    trial_tariff = next((t for t in tariffs if t.price == 0), None)
    if not trial_tariff:
        await callback.message.edit_text("❌ Пробный период недоступен.")
        await callback.answer()
        return
    
    email = f"trial_{user_id}_{int(datetime.now().timestamp())}"
    vless_link = create_vpn_client(email, trial_tariff.days)
    
    if not vless_link:
        await callback.message.edit_text("❌ Ошибка создания VPN-ключа. Попробуй позже.", reply_markup=main_menu())
        await callback.answer()
        return
    
    db.use_trial(user_id)
    subscription = db.create_subscription(user_id, trial_tariff.id, vless_link, email)
    
    await callback.message.edit_text(
        f"🎁 Пробный период активирован!\n📅 До {subscription.end_date.strftime('%d.%m.%Y')}\n⏰ Осталось {subscription.days_left()} дн.\n\n🔗 <code>{vless_link}</code>\n\n📱 Вставь ссылку в V2RayNG и подключись.",
        parse_mode="HTML", reply_markup=main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    sub = db.get_active_subscription(user_id)
    text = f"📊 Профиль\nID: {user.id}\nИмя: {user.first_name or '—'}\n\n"
    if sub:
        tariff = db.get_tariff(sub.tariff_id)
        text += f"✅ Подписка: {tariff.name}\n📅 До {sub.end_date.strftime('%d.%m.%Y')}\n⏰ Осталось {sub.days_left()} дн."
    else:
        text += "❌ Нет активной подписки"
    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "buy")
async def buy(callback: types.CallbackQuery):
    tariffs = db.get_all_tariffs()
    keyboard = []
    for t in tariffs:
        if t.price == 0:
            continue
        keyboard.append([InlineKeyboardButton(text=f"{t.name} - {t.price}₽", callback_data=f"buy_{t.id}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    await callback.message.edit_text("💎 Доступные тарифы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def confirm_buy(callback: types.CallbackQuery):
    tariff_id = int(callback.data.split("_")[1])
    tariff = db.get_tariff(tariff_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да, оплатить", callback_data=f"pay_{tariff_id}")],[InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]])
    await callback.message.edit_text(f"{tariff.name} - {tariff.price}₽\nПодтверждаешь?", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def payment(callback: types.CallbackQuery):
    tariff_id = int(callback.data.split("_")[1])
    tariff = db.get_tariff(tariff_id)
    user_id = callback.from_user.id
    
    # Если включены реальные платежи и есть ключи
    if YOOKASSA_ENABLED and YOOKASSA_SHOP_ID != "ВАШ_SHOP_ID":
        payment_url = create_yookassa_payment(tariff.price, f"Подписка {tariff.name}", user_id, tariff_id)
        if payment_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
            ])
            await callback.message.edit_text(
                f"💳 **Счёт на оплату**\n\nТариф: {tariff.name}\nСумма: {tariff.price}₽\n\n"
                f"После оплаты подписка активируется автоматически.\n\n"
                f"Нажми на кнопку ниже, чтобы перейти к оплате.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
            return
    
    # Если реальные платежи не включены — тестовая активация
    email = f"paid_{user_id}_{int(datetime.now().timestamp())}"
    vless_link = create_vpn_client(email, tariff.days)
    
    if not vless_link:
        await callback.message.edit_text("❌ Ошибка создания VPN-ключа.", reply_markup=main_menu())
        await callback.answer()
        return
    
    subscription = db.create_subscription(user_id, tariff.id, vless_link, email)
    await callback.message.edit_text(
        f"✅ Оплата подтверждена!\n📦 {tariff.name}\n📅 До {subscription.end_date.strftime('%d.%m.%Y')}\n\n🔗 <code>{vless_link}</code>",
        parse_mode="HTML", reply_markup=main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "back")
async def back(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())
    await callback.answer()

async def main():
    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
