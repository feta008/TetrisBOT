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
XUI_HOST = "144.31.54.21"
XUI_PORT = 58763
XUI_USERNAME = "4WMi0f7K9s"
XUI_PASSWORD = "12345678"
INBOUND_ID = 5

BOT_TOKEN = "8463325671:AAHlK7p6axwz250jgs3Pc1QAJC2aP5sA5mw"
ADMIN_IDS = [477684311]  # ТВОЙ TELEGRAM ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pending_payments = {}

# ========== КЛАССЫ ДЛЯ FSM (диалоги) ==========
class AdminGiveState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

class AdminBlockState(StatesGroup):
    waiting_for_user_id = State()

class AdminMailState(StatesGroup):
    waiting_for_text = State()

class AdminFindState(StatesGroup):
    waiting_for_query = State()

class AdminTariffEditState(StatesGroup):
    waiting_for_tariff_id = State()
    waiting_for_new_price = State()

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial")],
        [InlineKeyboardButton(text="📊 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]  # НОВАЯ КНОПКА
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_find")],
        [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin_give")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unblock")],
        [InlineKeyboardButton(text="💰 Управление тарифами", callback_data="admin_tariffs")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_mail")],
        [InlineKeyboardButton(text="💾 Резервная копия", callback_data="admin_backup")],
        [InlineKeyboardButton(text="❓ Команды", callback_data="admin_help")],
        [InlineKeyboardButton(text="◀️ Выход", callback_data="back")]
    ])

def tariffs_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список тарифов", callback_data="tariffs_list")],
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data="tariffs_edit")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])

# ========== ФУНКЦИИ VPN ==========
def create_vpn_client(email: str, days: int):
    session = requests.Session()
    session.verify = False
    login_url = f"https://{XUI_HOST}:{XUI_PORT}/mYLfcCSnMkPJREgznL/login"
    login_resp = session.post(login_url, json={"username": XUI_USERNAME, "password": XUI_PASSWORD})
    if login_resp.status_code != 200:
        return None
    client_uuid = str(uuid.uuid4())
    expiry = int((datetime.now() + timedelta(days=days)).timestamp() * 1000) if days > 0 else 0
    sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    client_data = {
        "id": client_uuid, "flow": "", "email": email, "limitIp": 0, "totalGB": 0,
        "expiryTime": expiry, "enable": True, "tgId": "", "subId": sub_id, "reset": 0
    }
    add_url = f"https://{XUI_HOST}:{XUI_PORT}/mYLfcCSnMkPJREgznL/panel/inbound/addClient"
    resp = session.post(
        add_url,
        data={"id": INBOUND_ID, "settings": json.dumps({"clients": [client_data]})},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    if resp.status_code != 200:
        return None
    return f"https://tetrisbot.abrdns.com:2096/sub/{sub_id}"

# ========== ПЛАТЕЖИ ==========
def create_yookassa_payment_with_id(amount, description, user_id, tariff_id):
    try:
        response = requests.post(
            'http://194.87.235.120:5000/create_payment',
            json={'amount': amount, 'description': description, 'user_id': user_id, 'tariff_id': tariff_id},
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('payment_url'), data.get('payment_id')
    except Exception as e:
        print(f"Ошибка: {e}")
    return None, None

# ========== ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ ==========
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
❓ **Помощь**

🔐 Быстрый и безопасный VPN. Работает на всех устройствах.

📌 **Как купить:**
Купить → Оплатить → Я оплатил → Скопировать ссылку

📌 **Как подключиться:**
1. Скачай Happ, V2RayNG или Streisand (для iOS)
2. Нажми «+» → «Импорт из буфера обмена»
3. Вставь ссылку → Подключись

🎁 **Пробный период:** 3 дня бесплатно

🆘 **Поддержка:** (https://t.me/tetris_mhk)
    """
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
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
    vless_link = create_vpn_client(email, trial_tariff.days)
    if not vless_link:
        await callback.message.edit_text("❌ Ошибка создания VPN-ключа.", reply_markup=main_menu())
        await callback.answer()
        return
    db.use_trial(user_id)
    subscription = db.create_subscription(user_id, trial_tariff.id, vless_link, email)
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
async def confirm_buy(callback: types.CallbackQuery):
    tariff_id = int(callback.data.split("_")[1])
    tariff = db.get_tariff(tariff_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, оплатить", callback_data=f"pay_{tariff_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
    ])
    await callback.message.edit_text(f"{tariff.name} - {tariff.price}₽\nПодтверждаешь?", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def payment(callback: types.CallbackQuery):
    tariff_id = int(callback.data.split("_")[1])
    tariff = db.get_tariff(tariff_id)
    user_id = callback.from_user.id
    
    payment_url, payment_id = create_yookassa_payment_with_id(tariff.price, f"Подписка {tariff.name}", user_id, tariff_id)
    
    if payment_url:
        pending_payments[payment_id] = {"user_id": user_id, "tariff_id": tariff_id}
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
    
    try:
        resp = requests.get(f"http://194.87.235.120:5000/check_payment?payment_id={payment_id}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'succeeded':
                vless_link = data.get('vless_link')
                if vless_link:
                    tariff_id = pending_payments.get(payment_id, {}).get('tariff_id', 2)
                    db.create_subscription(user_id, tariff_id, vless_link, f"paid_{user_id}")
                    await callback.message.edit_text(
                        f"✅ Оплата подтверждена!\n\n🔗 <code>{vless_link}</code>\n\n📱 Вставь ссылку в V2RayNG.",
                        parse_mode="HTML",
                        reply_markup=main_menu()
                    )
                else:
                    await callback.message.edit_text("❌ Ошибка создания VPN-ключа.", reply_markup=main_menu())
            else:
                await callback.message.edit_text(f"⏳ Статус платежа: {data.get('status')}", reply_markup=main_menu())
        else:
            await callback.message.edit_text("❌ Ошибка проверки. Попробуйте позже.", reply_markup=main_menu())
    except Exception as e:
        await callback.message.edit_text("❌ Ошибка соединения с платёжным сервером.", reply_markup=main_menu())
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

@dp.callback_query(F.data == "back")
async def back(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    total_users = db.get_total_users_count()
    active_subs = db.get_active_subscriptions_count()
    total_earnings = db.get_total_earnings()
    await callback.message.edit_text(
        f"📊 **Статистика**\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Активных подписок: {active_subs}\n"
        f"💰 Общий доход: {total_earnings}₽",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    users = db.get_all_users(limit=20)
    text = "👥 **Последние 20 пользователей:**\n\n"
    for u in users:
        sub = db.get_active_subscription(u.id)
        status = "✅" if sub else "❌"
        name = u.first_name or u.username or str(u.id)
        text += f"{status} `{u.id}` | {name}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_find")
async def admin_find_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text(
        "🔍 Введи ID пользователя или часть username/имени для поиска:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")]])
    )
    await state.set_state(AdminFindState.waiting_for_query)
    await callback.answer()

@dp.message(AdminFindState.waiting_for_query)
async def admin_find_result(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    query = message.text.strip()
    users = db.get_all_users(limit=100)
    found = []
    for u in users:
        if query.isdigit() and int(query) == u.id:
            found = [u]
            break
        elif u.username and query.lower() in u.username.lower():
            found.append(u)
        elif u.first_name and query.lower() in u.first_name.lower():
            found.append(u)
    if not found:
        await message.answer("❌ Ничего не найдено")
        await state.clear()
        return
    text = f"🔍 **Результаты поиска:**\n\n"
    for u in found[:10]:
        sub = db.get_active_subscription(u.id)
        status = "✅" if sub else "❌"
        text += f"{status} ID: `{u.id}` | {u.first_name or u.username or 'Без имени'}\n"
        if sub:
            tariff = db.get_tariff(sub.tariff_id)
            text += f"   📅 До {sub.end_date.strftime('%d.%m.%Y')} ({sub.days_left()} дн.)\n"
    await message.answer(text, parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "admin_give")
async def admin_give_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text(
        "➕ Введи **ID пользователя** Telegram:\n(можно скопировать из /users)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")]])
    )
    await state.set_state(AdminGiveState.waiting_for_user_id)
    await callback.answer()

@dp.message(AdminGiveState.waiting_for_user_id)
async def admin_give_user(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.strip())
        await state.update_data(user_id=user_id)
        await message.answer("📅 Введи **количество дней** подписки:")
        await state.set_state(AdminGiveState.waiting_for_days)
    except:
        await message.answer("❌ Неверный ID. Попробуй ещё раз.")
        await state.clear()

@dp.message(AdminGiveState.waiting_for_days)
async def admin_give_days(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        days = int(message.text.strip())
        data = await state.get_data()
        user_id = data.get('user_id')
        
        user = db.get_user(user_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            await state.clear()
            return
        
        tariffs = db.get_all_tariffs()
        trial_tariff = next((t for t in tariffs if t.price == 0), None)
        if not trial_tariff:
            await message.answer("❌ Тариф не найден")
            await state.clear()
            return
        
        email = f"admin_give_{user_id}_{int(datetime.now().timestamp())}"
        vless_link = create_vpn_client(email, days)
        
        if not vless_link:
            await message.answer("❌ Ошибка создания VPN-ключа")
            await state.clear()
            return
        
        subscription = db.create_subscription(user_id, trial_tariff.id, vless_link, email)
        if subscription:
            await message.answer(f"✅ Подписка выдана пользователю {user_id}\n📅 На {days} дней\n🔗 {vless_link}")
            try:
                await bot.send_message(user_id, f"🎁 Администратор выдал тебе подписку на {days} дней!\n🔗 <code>{vless_link}</code>", parse_mode="HTML")
            except:
                pass
        else:
            await message.answer("❌ Ошибка создания подписки")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.callback_query(F.data == "admin_block")
async def admin_block_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text(
        "🚫 Введи **ID пользователя** для блокировки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")]])
    )
    await state.set_state(AdminBlockState.waiting_for_user_id)
    await callback.answer()

@dp.message(AdminBlockState.waiting_for_user_id)
async def admin_block_execute(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.strip())
        result = db.toggle_user_block(user_id)
        if result is not None:
            await message.answer(f"✅ Пользователь {user_id} {'ЗАБЛОКИРОВАН' if result else 'РАЗБЛОКИРОВАН'}")
        else:
            await message.answer("❌ Пользователь не найден")
    except:
        await message.answer("❌ Неверный ID")
    await state.clear()

@dp.callback_query(F.data == "admin_unblock")
async def admin_unblock_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text(
        "✅ Введи **ID пользователя** для разблокировки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")]])
    )
    await state.set_state(AdminBlockState.waiting_for_user_id)
    await callback.answer()

@dp.callback_query(F.data == "admin_tariffs")
async def admin_tariffs_menu_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    tariffs = db.get_all_tariffs(active_only=False)
    text = "💰 **Текущие тарифы:**\n\n"
    for t in tariffs:
        traffic = "Безлимит" if t.traffic_gb is None else f"{t.traffic_gb} ГБ"
        status = "✅" if t.is_active else "❌"
        text += f"{status} ID `{t.id}`: {t.name} — {t.price}₽ ({t.days} дн., {traffic})\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=tariffs_menu())
    await callback.answer()

@dp.callback_query(F.data == "tariffs_list")
async def tariffs_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    tariffs = db.get_all_tariffs(active_only=False)
    text = "💰 **Список тарифов:**\n\n"
    for t in tariffs:
        traffic = "Безлимит" if t.traffic_gb is None else f"{t.traffic_gb} ГБ"
        text += f"ID `{t.id}`: {t.name}\n   Цена: {t.price}₽, {t.days} дн., трафик: {traffic}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=tariffs_menu())
    await callback.answer()

@dp.callback_query(F.data == "tariffs_edit")
async def tariffs_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    tariffs = db.get_all_tariffs(active_only=False)
    text = "✏️ **Выбери ID тарифа для изменения цены:**\n\n"
    for t in tariffs:
        text += f"ID `{t.id}`: {t.name} — {t.price}₽\n"
    text += "\nВведи `ID НОВАЯ_ЦЕНА` (пример: `2 299`)"
    await callback.message.edit_text(text, parse_mode="Markdown")
    await state.set_state(AdminTariffEditState.waiting_for_tariff_id)
    await callback.answer()

@dp.message(AdminTariffEditState.waiting_for_tariff_id)
async def tariffs_edit_execute(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.split()
        tariff_id = int(parts[0])
        new_price = int(parts[1])
        db.update_tariff_price(tariff_id, new_price)
        await message.answer(f"✅ Цена тарифа ID {tariff_id} изменена на {new_price}₽")
    except:
        await message.answer("❌ Неверный формат. Используй: `ID НОВАЯ_ЦЕНА`")
    await state.clear()

@dp.callback_query(F.data == "admin_mail")
async def admin_mail_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text(
        "📨 Введи текст сообщения для рассылки всем пользователям:\n(только текст, без команд)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")]])
    )
    await state.set_state(AdminMailState.waiting_for_text)
    await callback.answer()

@dp.message(AdminMailState.waiting_for_text)
async def admin_mail_execute(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    text = message.text
    users = db.get_all_users(limit=1000)
    success = 0
    failed = 0
    await message.answer(f"📨 Начинаю рассылку {len(users)} пользователям...")
    for u in users:
        try:
            await bot.send_message(u.id, f"📢 **Рассылка от администратора:**\n\n{text}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await message.answer(f"✅ Рассылка завершена!\n📤 Отправлено: {success}\n❌ Ошибок: {failed}")
    await state.clear()

@dp.callback_query(F.data == "admin_backup")
async def admin_backup(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    import os
    backup_name = f"/root/vpn_bot/database/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    os.system(f"cp /root/vpn_bot/database/vpn_bot.db {backup_name}")
    await callback.message.edit_text(
        f"💾 Резервная копия создана:\n`{backup_name}`\n\nДля скачивания используй SCP или SFTP.",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_help")
async def admin_help(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    text = """
📋 **АДМИН-ПАНЕЛЬ — КОМАНДЫ И КНОПКИ**

🔹 **Статистика** — общая информация о боте
🔹 **Список пользователей** — последние 20 пользователей
🔹 **Найти пользователя** — поиск по ID, username или имени
🔹 **Выдать подписку** — выдать VPN-ключ вручную
🔹 **Заблокировать / Разблокировать** — блокировка пользователя
🔹 **Управление тарифами** — просмотр и изменение цен
🔹 **Рассылка** — отправить сообщение всем пользователям
🔹 **Резервная копия** — создать бэкап базы данных
🔹 **Команды** — это сообщение

💡 **Текстовые команды:**
/admin — открыть админ-панель
/start — главное меню
    """
    await callback.message.edit_text(text, reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text("👑 Админ-панель", reply_markup=admin_menu())
    await callback.answer()

# ========== ЗАПУСК ==========
async def main():
    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
