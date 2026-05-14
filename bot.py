import asyncio
import logging
import uuid
import json
import requests
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import db
import urllib3
urllib3.disable_warnings()

# ========== НАСТРОЙКИ ==========
XUI_HOST = "91.124.19.122"
XUI_PORT = 58763
XUI_API_PATH = "/7ZnLQd7YIq9uEDbBwy"
XUI_USERNAME = "4WMi0f7K9s"
XUI_PASSWORD = "12345678"
INBOUND_ID = 1
MAX_DEVICES = 3

BOT_TOKEN = "8272029706:AAHzpsU6RtmnACgOs6luOaTTy8V0CFXa0Rk"
ADMIN_IDS = [477684311]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pending_payments = {}

# ========== FSM СОСТОЯНИЯ ==========
class AdminGiveState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

class AdminMailState(StatesGroup):
    waiting_for_text = State()

class AdminTariffEditState(StatesGroup):
    waiting_for_tariff_id = State()
    waiting_for_new_price = State()

class AdminFindState(StatesGroup):
    waiting_for_query = State()

class GiveOneState(StatesGroup):
    waiting_for_id = State()
    waiting_for_days = State()

class GiveAllState(StatesGroup):
    waiting_for_days = State()

class EditPriceState(StatesGroup):
    waiting_for_input = State()

class MailState(StatesGroup):
    waiting_for_text = State()

class FindUserState(StatesGroup):
    waiting_for_id = State()

# ========== АДМИН-ПАНЕЛЬ ==========
def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_give")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton(text="◀️ Выход", callback_data="back")]
    ])

def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Тарифы", callback_data="admin_tariffs")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_mail")],
        [InlineKeyboardButton(text="💾 Бэкап", callback_data="admin_backup")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])

def user_action_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Выдать", callback_data=f"give_{user_id}"),
            InlineKeyboardButton(text="🔴 Деактив", callback_data=f"deactivate_{user_id}")
        ],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_users")]
    ])

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С 3X-UI ==========
def get_3xui_session():
    session = requests.Session()
    session.verify = False
    login_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/login"
    session.post(login_url, json={"username": XUI_USERNAME, "password": XUI_PASSWORD})
    return session

def get_client_devices(uuid_str: str) -> list:
    session = get_3xui_session()
    list_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/panel/api/inbounds/list"
    try:
        resp = session.get(list_url, headers={'X-Requested-With': 'XMLHttpRequest'})
        if resp.status_code != 200:
            return []
        data = resp.json()
        devices = []
        for inbound in data.get('obj', []):
            for client in inbound.get('clientStats', []):
                if client.get('id') == uuid_str:
                    ips = client.get('ips', {})
                    for ip, info in ips.items():
                        devices.append({
                            'ip': ip,
                            'last_seen_ts': info.get('lastTime', 0)
                        })
                    break
        devices.sort(key=lambda x: x['last_seen_ts'])
        return devices
    except Exception as e:
        print(f"Ошибка get_client_devices: {e}")
        return []

def kick_device(uuid_str: str, ip: str) -> bool:
    session = get_3xui_session()
    kick_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/panel/api/inbounds/kickClient"
    try:
        resp = session.post(kick_url, json={"id": uuid_str, "ip": ip}, headers={'X-Requested-With': 'XMLHttpRequest'})
        return resp.status_code == 200
    except:
        return False

def create_vpn_client(email: str, days: int):
    session = get_3xui_session()
    client_uuid = str(uuid.uuid4())  # Генерируем UUID
    expiry = int((datetime.now() + timedelta(days=days)).timestamp() * 1000) if days > 0 else 0
    sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    client_data = {
        "id": client_uuid,  # ← Теперь не пустой
        "flow": "",
        "email": email,
        "limitIp": MAX_DEVICES,
        "totalGB": 0,
        "expiryTime": expiry,
        "enable": True,
        "tgId": "",
        "subId": sub_id,
        "reset": 0
    }
    add_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/panel/api/inbounds/addClient"
    resp = session.post(
        add_url,
        data={"id": INBOUND_ID, "settings": json.dumps({"clients": [client_data]})},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    
    if resp.status_code != 200:
        print(f"Ошибка создания клиента: {resp.status_code}, {resp.text}")
        return None, None
    
    result = resp.json()
    if not result.get('success'):
        print(f"Ошибка API: {result.get('msg')}")
        return None, None
    
    vless_link = f"https://tetrisbot.abrdns.com:2096/sub/{sub_id}"
    return vless_link, client_uuid

def extend_client_in_3xui(uuid_str: str, extra_days: int) -> bool:
    session = get_3xui_session()
    list_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/panel/api/inbounds/list"
    resp = session.get(list_url, headers={'X-Requested-With': 'XMLHttpRequest'})
    if resp.status_code != 200:
        return False
    data = resp.json()
    for inbound in data.get('obj', []):
        for client in inbound.get('clientStats', []):
            if client.get('id') == uuid_str:
                old_expiry = client.get('expiryTime', 0)
                new_expiry = old_expiry + (extra_days * 24 * 60 * 60 * 1000)
                update_url = f"https://{XUI_HOST}:{XUI_PORT}{XUI_API_PATH}/panel/api/inbounds/updateClient"
                payload = {"id": inbound['id'], "client": {"id": uuid_str, "expiryTime": new_expiry}}
                resp2 = session.post(update_url, json=payload, headers={'X-Requested-With': 'XMLHttpRequest'})
                return resp2.status_code == 200
    return False

# ========== ПЛАТЕЖИ ==========
def create_yookassa_payment_with_id(amount, description, user_id, tariff_id):
    try:
        response = requests.post(
            'https://payment.tetrisbot.abrdns.com:8443/create_payment',
            json={'amount': amount, 'description': description, 'user_id': user_id, 'tariff_id': tariff_id},
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('payment_url'), data.get('payment_id')
    except Exception as e:
        print(f"Ошибка: {e}")
    return None, None

# ========== ОСНОВНЫЕ КОМАНДЫ ==========
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial")],
        [InlineKeyboardButton(text="📊 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])

@dp.message(Command("start"))
async def start(message: types.Message):
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    await message.answer(f"👋 Привет, {user.first_name}!\n\nВыбери действие:", reply_markup=main_menu())

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("👑 Админ-панель", reply_markup=admin_menu())

@dp.callback_query(F.data == "help")
async def help_callback(callback: types.CallbackQuery):
    text = """
❓ Помощь

🔐 Быстрый и безопасный VPN. Работает на всех устройствах.

Как купить:
Купить → Оплатить → Я оплатил → Скопировать ссылку

Как подключиться:
1. Скачай Happ, V2RayNG или Streisand (для iOS)
2. Нажми «+» → «Импорт из буфера обмена»
3. Вставь ссылку → Подключись

Пробный период: 3 дня бесплатно

Поддержка: https://t.me/tetris_mhk
    """
    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()

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
    vless_link, client_uuid = create_vpn_client(email, trial_tariff.days)
    if not vless_link:
        await callback.message.edit_text("❌ Ошибка создания VPN-ключа.", reply_markup=main_menu())
        await callback.answer()
        return
    db.use_trial(user_id)
    subscription = db.create_subscription(user_id, trial_tariff.id, vless_link, client_uuid)
    await callback.message.edit_text(
        f"🎁 Пробный период активирован!\n📅 До {subscription.end_date.strftime('%d.%m.%Y')}\n⏰ Осталось {subscription.days_left()} дн.\n\n🔗 <code>{vless_link}</code>\n\n📱 Вставь ссылку в Happ, V2RayNG и подключись.",
        parse_mode="HTML", reply_markup=main_menu()
    )
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
async def confirm_buy(callback: types.CallbackQuery, state: FSMContext):
    tariff_id = int(callback.data.split("_")[1])
    tariff = db.get_tariff(tariff_id)
    user_id = callback.from_user.id
    
    active_sub = db.get_active_subscription(user_id)
    
    if active_sub:
        current_tariff = db.get_tariff(active_sub.tariff_id)
        
        if current_tariff.price == 0:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, оплатить", callback_data=f"pay_{tariff_id}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
            ])
            await callback.message.edit_text(
                f"{tariff.name} - {tariff.price}₽\n"
                f"У вас активен пробный период. При покупке пробный будет заменён на новый платный конфиг.\n\n"
                f"Подтверждаешь покупку?",
                reply_markup=keyboard
            )
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Продлить текущую", callback_data=f"renew_{tariff_id}")],
                [InlineKeyboardButton(text="➕ Создать новый конфиг", callback_data=f"pay_{tariff_id}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
            ])
            await callback.message.edit_text(
                f"📌 У вас уже есть активная подписка.\n\n"
                f"**Текущий тариф:** {current_tariff.name}\n"
                f"**Действует до:** {active_sub.end_date.strftime('%d.%m.%Y')}\n\n"
                f"Как поступить?",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await state.set_state(RenewState.waiting_for_choice)
            await state.update_data(tariff_id=tariff_id, tariff=tariff)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, оплатить", callback_data=f"pay_{tariff_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
        ])
        await callback.message.edit_text(
            f"{tariff.name} - {tariff.price}₽\nПодтверждаешь покупку?",
            reply_markup=keyboard
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("renew_"))
async def renew_subscription(callback: types.CallbackQuery, state: FSMContext):
    tariff_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    active_sub = db.get_active_subscription(user_id)
    if not active_sub:
        await callback.answer("❌ Активная подписка не найдена")
        return
    
    tariff = db.get_tariff(tariff_id)
    
    payment_url, payment_id = create_yookassa_payment_with_id(
        tariff.price, f"Продление {tariff.name}", user_id, tariff_id
    )
    
    if payment_url:
        pending_payments[payment_id] = {"user_id": user_id, "tariff_id": tariff_id, "renew": True}
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_{payment_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
        ])
        await callback.message.edit_text(
            f"💳 Счёт на **продление** подписки\n\n"
            f"Тариф: {tariff.name}\n"
            f"Сумма: {tariff.price}₽\n\n"
            f"После оплаты нажми «Я оплатил».",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text("❌ Ошибка создания платежа", reply_markup=main_menu())
    
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def payment(callback: types.CallbackQuery):
    tariff_id = int(callback.data.split("_")[1])
    tariff = db.get_tariff(tariff_id)
    user_id = callback.from_user.id
    
    payment_url, payment_id = create_yookassa_payment_with_id(tariff.price, f"Подписка {tariff.name}", user_id, tariff_id)
    
    if payment_url:
        pending_payments[payment_id] = {"user_id": user_id, "tariff_id": tariff_id, "renew": False}
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_{payment_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
        ])
        await callback.message.edit_text(
            f"💳 Счёт на оплату\nТариф: {tariff.name}\nСумма: {tariff.price}₽\n\nПосле оплаты нажми «Я оплатил».",
            reply_markup=keyboard
        )
    else:
        await callback.message.edit_text("❌ Ошибка создания платежа", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment_callback(callback: types.CallbackQuery):
    payment_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                f"https://payment.tetrisbot.abrdns.com:8443/check_payment?payment_id={payment_id}",
                timeout=15
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'succeeded':
                    vless_link = data.get('vless_link')
                    if vless_link:
                        payment_data = pending_payments.get(payment_id, {})
                        tariff_id = payment_data.get('tariff_id', 2)
                        tariff = db.get_tariff(tariff_id)
                        
                        if payment_data.get('renew'):
                            active_sub = db.get_active_subscription(user_id)
                            if active_sub:
                                new_end = active_sub.end_date + timedelta(days=tariff.days)
                                with db.get_session() as session:
                                    from database import Subscription
                                    session.query(Subscription).filter(Subscription.id == active_sub.id).update({"end_date": new_end})
                                    session.commit()
                                
                                extend_client_in_3xui(active_sub.vpn_uuid, tariff.days)
                                
                                await callback.message.edit_text(
                                    f"✅ Подписка **продлена**!\n\n"
                                    f"📦 Тариф: {tariff.name}\n"
                                    f"📅 Новая дата окончания: {new_end.strftime('%d.%m.%Y')}\n"
                                    f"🔗 Ссылка осталась прежней:\n<code>{active_sub.vpn_config}</code>",
                                    parse_mode="HTML",
                                    reply_markup=main_menu()
                                )
                            else:
                                await callback.message.edit_text("❌ Активная подписка не найдена", reply_markup=main_menu())
                        else:
                            email = f"paid_{user_id}_{int(datetime.now().timestamp())}"
                            vless_link_new, client_uuid = create_vpn_client(email, tariff.days)
                            if vless_link_new:
                                db.create_subscription(user_id, tariff_id, vless_link_new, client_uuid)
                                await callback.message.edit_text(
                                    f"✅ Оплата подтверждена!\n\n"
                                    f"📦 Тариф: {tariff.name}\n"
                                    f"📅 Действует до: {(datetime.now() + timedelta(days=tariff.days)).strftime('%d.%m.%Y')}\n\n"
                                    f"🔗 <code>{vless_link_new}</code>\n\n"
                                    f"📱 Вставь ссылку в V2RayNG.",
                                    parse_mode="HTML",
                                    reply_markup=main_menu()
                                )
                            else:
                                await callback.message.edit_text("❌ Ошибка создания VPN-ключа.", reply_markup=main_menu())
                    else:
                        await callback.message.edit_text("❌ Ошибка создания VPN-ключа.", reply_markup=main_menu())
                else:
                    await callback.message.edit_text(f"⏳ Статус платежа: {data.get('status')}", reply_markup=main_menu())
            else:
                if attempt == max_retries - 1:
                    await callback.message.edit_text("❌ Ошибка проверки. Попробуйте позже.", reply_markup=main_menu())
                else:
                    await asyncio.sleep(retry_delay)
                    continue
            return
            
        except Exception as e:
            print(f"Ошибка (попытка {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                await callback.message.edit_text("❌ Ошибка соединения с платёжным сервером. Попробуйте позже.", reply_markup=main_menu())
            else:
                await asyncio.sleep(retry_delay)
    
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    sub = db.get_active_subscription(user_id)
    
    text = f"📊 **Профиль**\n\n"
    text += f"🆔 ID: {user.id}\n"
    text += f"👤 Имя: {user.first_name or '—'}\n\n"
    
    if sub:
        tariff = db.get_tariff(sub.tariff_id)
        text += f"✅ **Активная подписка**\n"
        text += f"📦 Тариф: {tariff.name}\n"
        text += f"📅 До: {sub.end_date.strftime('%d.%m.%Y')}\n"
        text += f"⏰ Осталось: {sub.days_left()} дн.\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Показать ссылку", callback_data=f"show_config_{sub.id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
        
        devices = get_client_devices(sub.vpn_uuid)
        if devices:
            text += f"📱 **Активные устройства ({len(devices)}/{MAX_DEVICES})**\n\n"
            for i, dev in enumerate(devices, 1):
                last_seen = datetime.fromtimestamp(dev['last_seen_ts']).strftime('%d.%m.%Y %H:%M') if dev['last_seen_ts'] else 'неизвестно'
                text += f"{i}. IP: `{dev['ip']}`\n   Последний раз: {last_seen}\n"
                keyboard.inline_keyboard.insert(i-1, [
                    InlineKeyboardButton(text=f"❌ Отвязать {dev['ip']}", callback_data=f"kick_{sub.vpn_uuid}_{dev['ip']}")
                ])
            
            if len(devices) >= MAX_DEVICES:
                text += f"\n⚠️ **Лимит устройств исчерпан!**\n"
                text += f"Нажмите кнопку ниже, чтобы отвязать самое старое устройство и освободить место.\n"
                keyboard.inline_keyboard.append(
                    [InlineKeyboardButton(text="🚀 Освободить место", callback_data=f"free_slot_{sub.vpn_uuid}")]
                )
        else:
            text += f"📱 **Активные устройства: 0/{MAX_DEVICES}**\n\n"
    else:
        text += f"❌ **Нет активной подписки**\n\nНажми «Купить подписку» в меню."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("kick_"))
async def kick_device_callback(callback: types.CallbackQuery):
    _, uuid_str, ip = callback.data.split("_", 2)
    if kick_device(uuid_str, ip):
        await callback.answer("✅ Устройство отвязано")
        await profile(callback)
    else:
        await callback.answer("❌ Ошибка отвязки")

@dp.callback_query(F.data.startswith("free_slot_"))
async def free_slot_callback(callback: types.CallbackQuery):
    uuid_str = callback.data.split("_", 2)[2]
    devices = get_client_devices(uuid_str)
    if devices:
        oldest = devices[0]
        if kick_device(uuid_str, oldest['ip']):
            await callback.answer(f"✅ Освобождено место: отвязано устройство {oldest['ip']}")
            await profile(callback)
        else:
            await callback.answer("❌ Не удалось отвязать устройство")
    else:
        await callback.answer("❌ Нет активных устройств")

@dp.callback_query(F.data.startswith("show_config_"))
async def show_config(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    with db.get_session() as session:
        from database import Subscription
        sub = session.query(Subscription).filter(Subscription.id == sub_id, Subscription.user_id == user_id).first()
    
    if sub and sub.vpn_config:
        text = f"🔗 **Твоя ссылка:**\n\n<code>{sub.vpn_config}</code>\n\nНажми на неё → «Копировать»"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Вернуться в профиль", callback_data="profile")]
        ]))
    else:
        await callback.answer("❌ Ссылка не найдена")
    await callback.answer()

@dp.callback_query(F.data == "back")
async def back(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ (ФУНКЦИИ) ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    total_users = db.get_total_users_count()
    active_subs = db.get_active_subscriptions_count()
    total_earnings = db.get_total_earnings()
    text = f"📊 **СТАТИСТИКА**\n\n👥 Всего: `{total_users}`\n✅ Активных: `{active_subs}`\n💰 Доход: `{total_earnings}₽`"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery, page: int = 0):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    users = db.get_all_users(limit=10, offset=page * 10)
    total_users = db.get_total_users_count()
    total_pages = (total_users + 9) // 10
    if not users:
        await callback.message.edit_text("❌ Нет пользователей", reply_markup=admin_menu())
        return
    text = f"👥 **ПОЛЬЗОВАТЕЛИ** ({page + 1}/{total_pages})\n\n"
    for u in users:
        sub = db.get_active_subscription(u.id)
        status = "✅" if sub else "❌"
        name = u.first_name or u.username or str(u.id)
        text += f"{status} `{u.id}` | {name}\n"
        if sub:
            text += f"   📅 До {sub.end_date.strftime('%d.%m.%Y')} ({sub.days_left()} дн.)\n"
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"users_page_{page-1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"users_page_{page+1}"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_find")],
        nav,
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("users_page_"))
async def users_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await admin_users(callback, page)

@dp.callback_query(F.data == "admin_find")
async def admin_find(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text("🔍 Введи ID пользователя:")
    await state.set_state(AdminFindState.waiting_for_query)

@dp.message(AdminFindState.waiting_for_query)
async def admin_find_result(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.strip())
        user = db.get_user(user_id)
        if not user:
            await message.answer("❌ Не найден")
            await state.clear()
            return
        sub = db.get_active_subscription(user_id)
        name = user.first_name or user.username or str(user.id)
        text = f"👤 **{name}**\n🆔 `{user_id}`\n"
        if sub:
            tariff = db.get_tariff(sub.tariff_id)
            text += f"📦 {tariff.name}\n📅 До {sub.end_date.strftime('%d.%m.%Y')} ({sub.days_left()} дн.)"
        else:
            text += "❌ Нет активной подписки"
        await message.answer(text, parse_mode="Markdown", reply_markup=user_action_keyboard(user_id))
    except:
        await message.answer("❌ Ошибка")
    await state.clear()

@dp.callback_query(F.data == "admin_give")
async def admin_give(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Одному", callback_data="give_one")],
        [InlineKeyboardButton(text="👥 Всем активным", callback_data="give_all")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text("🎁 **Выдача подписки**\n\nКому?", parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "give_one")
async def give_one(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("➕ Введи ID пользователя:")
    await state.set_state(GiveOneState.waiting_for_id)

@dp.message(GiveOneState.waiting_for_id)
async def give_one_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        await state.update_data(user_id=user_id)
        await message.answer("📅 Введи количество дней:")
        await state.set_state(GiveOneState.waiting_for_days)
    except:
        await message.answer("❌ Ошибка")

@dp.message(GiveOneState.waiting_for_days)
async def give_one_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        data = await state.get_data()
        user_id = data.get('user_id')
        user = db.get_user(user_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            await state.clear()
            return
        
        active_sub = db.get_active_subscription(user_id)
        
        if active_sub:
            new_end = active_sub.end_date + timedelta(days=days)
            with db.get_session() as session:
                from database import Subscription
                session.query(Subscription).filter(Subscription.id == active_sub.id).update({"end_date": new_end})
                session.commit()
            
            result = extend_client_in_3xui(active_sub.vpn_uuid, days)
            print(f"Продление 3X-UI: {'✅' if result else '❌'}, UUID={active_sub.vpn_uuid}, дней={days}")
            
            await message.answer(f"✅ Подписка **продлена** пользователю {user_id}\n📅 Добавлено {days} дней\n📅 Новая дата: {new_end.strftime('%d.%m.%Y')}")
            try:
                await bot.send_message(user_id, f"🎁 Администратор продлил подписку на {days} дней!\n📅 Новая дата окончания: {new_end.strftime('%d.%m.%Y')}")
            except:
                pass
        else:
            tariffs = db.get_all_tariffs()
            trial = next((t for t in tariffs if t.price == 0), None)
            if not trial:
                await message.answer("❌ Тариф не найден")
                await state.clear()
                return
            email = f"admin_{user_id}_{int(datetime.now().timestamp())}"
            link, client_uuid = create_vpn_client(email, days)
            if not link:
                await message.answer("❌ Ошибка создания ключа")
                await state.clear()
                return
            db.create_subscription(user_id, trial.id, link, client_uuid)
            await message.answer(f"✅ Создана новая подписка для {user_id}\n📅 На {days} дней\n🔗 {link}")
            try:
                await bot.send_message(user_id, f"🎁 Администратор выдал подписку на {days} дней!\n🔗 <code>{link}</code>", parse_mode="HTML")
            except:
                pass
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.callback_query(F.data == "give_all")
async def give_all(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📅 Введи количество дней для ВСЕХ активных:")
    await state.set_state(GiveAllState.waiting_for_days)

@dp.message(GiveAllState.waiting_for_days)
async def give_all_execute(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        users = db.get_all_users()
        active = []
        for u in users:
            sub = db.get_active_subscription(u.id)
            if sub and sub.days_left() > 0:
                active.append(u)
        if not active:
            await message.answer("❌ Нет активных пользователей")
            await state.clear()
            return
        success = 0
        failed = 0
        tariffs = db.get_all_tariffs()
        trial = next((t for t in tariffs if t.price == 0), None)
        if not trial:
            await message.answer("❌ Тариф не найден")
            await state.clear()
            return
        status_msg = await message.answer(f"📨 Выдаю {len(active)} пользователям...")
        for u in active:
            try:
                email = f"admin_all_{u.id}_{int(datetime.now().timestamp())}"
                link, client_uuid = create_vpn_client(email, days)
                if link:
                    db.create_subscription(u.id, trial.id, link, client_uuid)
                    try:
                        await bot.send_message(u.id, f"🎁 Админ выдал {days} дней!\n🔗 <code>{link}</code>", parse_mode="HTML")
                    except:
                        pass
                    success += 1
                else:
                    failed += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        await status_msg.edit_text(f"✅ Выдано {success}/{len(active)} пользователям")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.callback_query(F.data.startswith("deactivate_"))
async def deactivate_subscription(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    user_id = int(callback.data.split("_")[1])
    sub = db.get_active_subscription(user_id)
    if not sub:
        await callback.answer("❌ Нет активной подписки")
        return
    with db.get_session() as session:
        from database import Subscription
        session.query(Subscription).filter(Subscription.id == sub.id).update({"is_active": False})
        session.commit()
    await callback.answer("✅ Подписка деактивирована")
    await admin_users(callback)

@dp.callback_query(F.data.startswith("give_"))
async def give_from_list(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    user_id = int(callback.data.split("_")[1])
    await state.update_data(user_id=user_id)
    await callback.message.edit_text("📅 Введи количество дней для добавления к текущей подписке:")
    await state.set_state(GiveOneState.waiting_for_days)

@dp.callback_query(F.data == "admin_settings")
async def admin_settings(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ **Настройки**", parse_mode="Markdown", reply_markup=settings_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_tariffs")
async def admin_tariffs(callback: types.CallbackQuery):
    tariffs = db.get_all_tariffs(active_only=False)
    text = "💰 **Тарифы**\n\n"
    for t in tariffs:
        traffic = "Безлимит" if t.traffic_gb is None else f"{t.traffic_gb} ГБ"
        text += f"ID `{t.id}`: {t.name} — {t.price}₽ ({t.days} дн., {traffic})\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data="edit_price")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_settings")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "edit_price")
async def edit_price(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Введи `ID НОВАЯ_ЦЕНА`\nПример: `2 299`")
    await state.set_state(EditPriceState.waiting_for_input)

@dp.message(EditPriceState.waiting_for_input)
async def edit_price_execute(message: types.Message, state: FSMContext):
    try:
        parts = message.text.split()
        tariff_id, new_price = int(parts[0]), int(parts[1])
        db.update_tariff_price(tariff_id, new_price)
        await message.answer(f"✅ Цена тарифа {tariff_id} изменена на {new_price}₽")
    except:
        await message.answer("❌ Ошибка. Формат: `ID НОВАЯ_ЦЕНА`")
    await state.clear()

@dp.callback_query(F.data == "admin_mail")
async def admin_mail(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📨 Введи текст рассылки:")
    await state.set_state(MailState.waiting_for_text)

@dp.message(MailState.waiting_for_text)
async def admin_mail_send(message: types.Message, state: FSMContext):
    text = message.text
    users = db.get_all_users(limit=10000)
    success = 0
    status_msg = await message.answer(f"📨 Рассылка {len(users)} пользователям...")
    for u in users:
        try:
            await bot.send_message(u.id, f"📢 **Рассылка**\n\n{text}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await status_msg.edit_text(f"✅ Отправлено: {success}/{len(users)}")
    await state.clear()

@dp.callback_query(F.data == "admin_backup")
async def admin_backup(callback: types.CallbackQuery):
    import os
    backup_name = f"/root/vpn_bot/database/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    os.system(f"cp /root/vpn_bot/database/vpn_bot.db {backup_name}")
    await callback.message.edit_text(f"💾 Бэкап: `{backup_name}`", parse_mode="Markdown", reply_markup=settings_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    await callback.message.edit_text("👑 **Админ-панель**", parse_mode="Markdown", reply_markup=admin_menu())
    await callback.answer()

class RenewState(StatesGroup):
    waiting_for_choice = State()

async def main():
    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
