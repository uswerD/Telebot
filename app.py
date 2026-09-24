import asyncio
import os
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, request, jsonify

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder


# =========================
# НАСТРОЙКИ
# =========================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_NAME = "tire_service.db"

WORK_START = 9
WORK_END = 19
SLOT_MINUTES = 60


if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN")


# =========================
# FLASK + AIOGRAM
# =========================

app = Flask(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================
# БАЗА ДАННЫХ
# =========================

def get_db():
    return sqlite3.connect(DB_NAME)


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db.commit()
    db.close()


def get_booking(date, time):
    db = get_db()

    row = db.execute(
        """
        SELECT id, user_id, name, phone, date, time
        FROM bookings
        WHERE date = ? AND time = ?
        """,
        (date, time)
    ).fetchone()

    db.close()
    return row


def create_booking(user_id, name, phone, date, time):
    db = get_db()

    db.execute(
        """
        INSERT INTO bookings
        (user_id, name, phone, date, time, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            name,
            phone,
            date,
            time,
            datetime.now().isoformat()
        )
    )

    db.commit()
    db.close()


def get_user_bookings(user_id):
    db = get_db()

    rows = db.execute(
        """
        SELECT id, name, phone, date, time
        FROM bookings
        WHERE user_id = ?
        ORDER BY date, time
        """,
        (user_id,)
    ).fetchall()

    db.close()
    return rows


def get_day_bookings(date):
    db = get_db()

    rows = db.execute(
        """
        SELECT id, user_id, name, phone, date, time
        FROM bookings
        WHERE date = ?
        ORDER BY time
        """,
        (date,)
    ).fetchall()

    db.close()
    return rows


def delete_booking(booking_id):
    db = get_db()

    db.execute(
        "DELETE FROM bookings WHERE id = ?",
        (booking_id,)
    )

    db.commit()
    db.close()


# =========================
# ВРЕМЯ
# =========================

def get_slots():
    slots = []

    current = WORK_START * 60
    end = WORK_END * 60

    while current < end:
        hour = current // 60
        minute = current % 60

        slots.append(
            f"{hour:02d}:{minute:02d}"
        )

        current += SLOT_MINUTES

    return slots


# =========================
# КЛАВИАТУРЫ
# =========================

def main_menu():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🔧 Записаться",
        callback_data="booking"
    )

    kb.button(
        text="📋 Мои записи",
        callback_data="my_bookings"
    )

    kb.button(
        text="📍 Адрес",
        callback_data="address"
    )

    kb.adjust(1)

    return kb.as_markup()


def admin_menu():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="📅 Сегодня",
        callback_data="admin_today"
    )

    kb.button(
        text="📆 Завтра",
        callback_data="admin_tomorrow"
    )

    kb.button(
        text="❌ Удалить запись",
        callback_data="admin_delete"
    )

    kb.adjust(1)

    return kb.as_markup()


# =========================
# ВРЕМЕННОЕ ХРАНИЛИЩЕ
# =========================

pending_bookings = {}


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "🔧 ШИНОМОНТАЖ\n\n"
        "Здравствуйте!\n"
        "Выберите нужное действие:",
        reply_markup=main_menu()
    )


# =========================
# ЗАПИСЬ
# =========================

@dp.callback_query(F.data == "booking")
async def booking_start(callback: CallbackQuery):

    kb = InlineKeyboardBuilder()

    today = datetime.now().date()

    for i in range(7):

        date = today + timedelta(days=i)

        if i == 0:
            text = "Сегодня"
        elif i == 1:
            text = "Завтра"
        else:
            text = date.strftime("%d.%m")

        kb.button(
            text=text,
            callback_data=f"date:{date.isoformat()}"
        )

    kb.adjust(2)

    await callback.message.edit_text(
        "📅 Выберите дату:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


# =========================
# ВЫБОР ДАТЫ
# =========================

@dp.callback_query(F.data.startswith("date:"))
async def choose_date(callback: CallbackQuery):

    date = callback.data.split(":")[1]

    kb = InlineKeyboardBuilder()

    for time in get_slots():

        if get_booking(date, time):
            continue

        kb.button(
            text=time,
            callback_data=f"time:{date}:{time}"
        )

    kb.adjust(3)

    await callback.message.edit_text(
        f"📅 Дата: {date}\n\n"
        "🕐 Выберите свободное время:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


# =========================
# ВЫБОР ВРЕМЕНИ
# =========================

@dp.callback_query(F.data.startswith("time:"))
async def choose_time(callback: CallbackQuery):

    parts = callback.data.split(":")

    date = parts[1]
    time = parts[2]

    if get_booking(date, time):

        await callback.answer(
            "Это время уже занято",
            show_alert=True
        )

        return

    pending_bookings[callback.from_user.id] = {
        "date": date,
        "time": time
    }

    await callback.message.edit_text(
        f"📅 {date}\n"
        f"🕐 {time}\n\n"
        "Введите номер телефона:"
    )

    await callback.answer()


# =========================
# ПОЛУЧЕНИЕ ТЕЛЕФОНА
# =========================

@dp.message()
async def receive_phone(message: Message):

    user_id = message.from_user.id

    if user_id not in pending_bookings:
        return

    phone = message.text.strip()

    booking = pending_bookings[user_id]

    date = booking["date"]
    time = booking["time"]

    # Повторно проверяем свободно ли время
    if get_booking(date, time):

        del pending_bookings[user_id]

        await message.answer(
            "К сожалению, это время уже заняли.\n"
            "Попробуйте выбрать другое.",
            reply_markup=main_menu()
        )

        return

    name = message.from_user.full_name

    create_booking(
        user_id,
        name,
        phone,
        date,
        time
    )

    del pending_bookings[user_id]

    await message.answer(
        "✅ ЗАПИСЬ ПОДТВЕРЖДЕНА\n\n"
        f"📅 Дата: {date}\n"
        f"🕐 Время: {time}\n"
        f"👤 Клиент: {name}\n"
        f"📞 Телефон: {phone}\n\n"
        "Ждём вас!",
        reply_markup=main_menu()
    )

    # Уведомление администратору
    if ADMIN_ID:

        try:
            await bot.send_message(
                ADMIN_ID,
                "🔔 НОВАЯ ЗАПИСЬ\n\n"
                f"📅 {date}\n"
                f"🕐 {time}\n"
                f"👤 {name}\n"
                f"📞 {phone}"
            )

        except Exception as e:
            print("Ошибка отправки админу:", e)


# =========================
# МОИ ЗАПИСИ
# =========================

@dp.callback_query(F.data == "my_bookings")
async def my_bookings(callback: CallbackQuery):

    rows = get_user_bookings(
        callback.from_user.id
    )

    if not rows:

        await callback.message.edit_text(
            "📋 У вас пока нет записей.",
            reply_markup=main_menu()
        )

        await callback.answer()
        return

    text = "📋 ВАШИ ЗАПИСИ\n\n"

    for row in rows:

        booking_id, name, phone, date, time = row

        text += (
            f"🔧 Запись №{booking_id}\n"
            f"📅 {date}\n"
            f"🕐 {time}\n"
            f"📞 {phone}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# АДРЕС
# =========================

@dp.callback_query(F.data == "address")
async def address(callback: CallbackQuery):

    await callback.message.edit_text(
        "📍 АДРЕС ШИНОМОНТАЖА\n\n"
        "г. Челябинск\n"
        "ул. Примерная, 10\n\n"
        "Работаем ежедневно\n"
        "09:00–19:00",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# АДМИН
# =========================

@dp.message(Command("admin"))
async def admin_command(message: Message):

    if message.from_user.id != ADMIN_ID:

        await message.answer(
            "⛔ Доступ запрещён."
        )

        return

    await message.answer(
        "🔧 АДМИН-ПАНЕЛЬ",
        reply_markup=admin_menu()
    )


# =========================
# АДМИН — СЕГОДНЯ
# =========================

@dp.callback_query(F.data == "admin_today")
async def admin_today(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    date = datetime.now().date().isoformat()

    rows = get_day_bookings(date)

    text = f"📅 ЗАПИСИ НА СЕГОДНЯ\n\n"

    if not rows:

        text += "Записей нет."

    else:

        for row in rows:

            booking_id, user_id, name, phone, date, time = row

            text += (
                f"№{booking_id} — {time}\n"
                f"👤 {name}\n"
                f"📞 {phone}\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=admin_menu()
    )

    await callback.answer()


# =========================
# АДМИН — ЗАВТРА
# =========================

@dp.callback_query(F.data == "admin_tomorrow")
async def admin_tomorrow(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    date = (
        datetime.now().date()
        + timedelta(days=1)
    ).isoformat()

    rows = get_day_bookings(date)

    text = f"📆 ЗАПИСИ НА ЗАВТРА\n\n"

    if not rows:

        text += "Записей нет."

    else:

        for row in rows:

            booking_id, user_id, name, phone, date, time = row

            text += (
                f"№{booking_id} — {time}\n"
                f"👤 {name}\n"
                f"📞 {phone}\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=admin_menu()
    )

    await callback.answer()


# =========================
# АДМИН — УДАЛЕНИЕ
# =========================

@dp.callback_query(F.data == "admin_delete")
async def admin_delete(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )
        return

    today = datetime.now().date().isoformat()

    tomorrow = (
        datetime.now().date()
        + timedelta(days=1)
    ).isoformat()

    rows = (
        get_day_bookings(today)
        + get_day_bookings(tomorrow)
    )

    kb = InlineKeyboardBuilder()

    for row in rows:

        booking_id, user_id, name, phone, date, time = row

        kb.button(
            text=f"❌ {date} {time} — {name}",
            callback_data=f"delete:{booking_id}"
        )

    kb.adjust(1)

    if not rows:

        text = "Записей для удаления нет."

    else:

        text = "❌ Выберите запись для удаления:"

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
        if rows
        else admin_menu()
    )

    await callback.answer()


# =========================
# УДАЛЕНИЕ ЗАПИСИ
# =========================

@dp.callback_query(F.data.startswith("delete:"))
async def delete_booking_callback(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Доступ запрещён",
            show_alert=True
        )

        return

    booking_id = int(
        callback.data.split(":")[1]
    )

    delete_booking(booking_id)

    await callback.message.edit_text(
        "✅ Запись удалена.",
        reply_markup=admin_menu()
    )

    await callback.answer()


# =========================
# WEBHOOK
# =========================

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json()

    if not data:
        return jsonify({"ok": False}), 400

    try:

        asyncio.run(
            process_update(data)
        )

        return jsonify({"ok": True})

    except Exception as e:

        print("Ошибка обработки Telegram:", e)

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


async def process_update(data):

    update = Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )


# =========================
# HEALTH CHECK
# =========================

@app.route("/", methods=["GET"])
def home():

    return "Tire bot is running"


# =========================
# ЗАПУСК
# =========================

init_db()

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
