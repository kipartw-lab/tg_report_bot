# schedule_manager.py
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

SCHEDULE_FILE = "schedule.json"

# ============================
# Загрузка / сохранение графика
# ============================

def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_schedule(schedule):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

schedule = load_schedule()

# ============================
# Команда /schedule
# ============================

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Аслан", callback_data="edit_aslan_stech")],
        [InlineKeyboardButton("Сергей", callback_data="edit_Stech_Sergei")],
    ]

    await update.message.reply_text(
        "Выберите сотрудника для редактирования графика:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================
# Обработка кнопок
# ============================

async def schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # --------------------------
    # Выбор сотрудника
    # --------------------------
    if data.startswith("edit_"):
        username = data.replace("edit_", "")
        context.user_data["editing_user"] = username

        days_keyboard = [
            [
                InlineKeyboardButton("Пн", callback_data="day_0"),
                InlineKeyboardButton("Вт", callback_data="day_1"),
                InlineKeyboardButton("Ср", callback_data="day_2"),
            ],
            [
                InlineKeyboardButton("Чт", callback_data="day_3"),
                InlineKeyboardButton("Пт", callback_data="day_4"),
                InlineKeyboardButton("Сб", callback_data="day_5"),
            ],
            [
                InlineKeyboardButton("Вс", callback_data="day_6"),
            ],
            [InlineKeyboardButton("СОХРАНИТЬ", callback_data="save_days")]
        ]

        # очищаем временный выбор
        context.user_data["selected_days"] = set(schedule.get(username, []))

        await query.edit_message_text(
            f"Вы редактируете график сотрудника @{username}\n"
            f"Выберите рабочие дни недели (можно несколько):",
            reply_markup=InlineKeyboardMarkup(days_keyboard)
        )
        return

    # --------------------------
    # Переключение дня недели
    # --------------------------
    if data.startswith("day_"):
        day = int(data.split("_")[1])
        selected = context.user_data.get("selected_days", set())

        # toggle (вкл/выкл)
        if day in selected:
            selected.remove(day)
        else:
            selected.add(day)

        context.user_data["selected_days"] = selected

        await query.answer("День переключён")
        return

    # --------------------------
    # Сохранение графика
    # --------------------------
    if data == "save_days":
        username = context.user_data.get("editing_user")
        selected_days = sorted(list(context.user_data.get("selected_days", [])))

        schedule[username] = selected_days
        save_schedule(schedule)

        # Текст красивого вывода дней недели
        days_map = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        days_text = ", ".join(days_map[d] for d in selected_days) if selected_days else "Нет рабочих дней"

        keyboard = [
            [InlineKeyboardButton("Выбрать другого сотрудника", callback_data="restart_schedule")]
        ]

        await query.edit_message_text(
            f"✔ График обновлён!\n\n@{username} работает: {days_text}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # --------------------------
    # Возврат к сотрудникам
    # --------------------------
    if data == "restart_schedule":
        await schedule_command(update, context)
