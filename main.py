import os
import json
import logging
import datetime
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)
from schedule_manager import schedule_command, schedule_callback, schedule

# ------------------ БАЗОВЫЕ НАСТРОЙКИ ------------------

TZ = ZoneInfo("Europe/Moscow")

# Чаты и пользователи (подставлены ваши значения)
CHAT_ID = int(os.getenv("CHAT_ID", "-1002356032898"))          # рабочий чат КУ
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "-1003442921980"))  # админская группа
DIRECTOR_ID = int(os.getenv("DIRECTOR_ID", "7336512345"))      # личка директора
ADMIN_USERNAME = "Controlstech"                               # чтобы тегать тебя

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Файлы с данными
DATA_FILE = "data.json"
EMPLOYEES_FILE = "employees.json"
SCHEDULE_FILE = "schedule.json"   # сейчас хранит рабочие дни по дням недели

# Теги
REPORT_TAGS = ["#отчет", "#отчёт"]
CONCLUSION_TAGS = ["#выводы", "#вывод"]
SLICE_TAG = "#срез"

# Реакция бота на принятые сообщения
REACTION = "👍"

# Участники по задачам (username’ы)
# Список сотрудников берём из employees.json, но здесь фиксируем группы
CONCLUSION_USERS = [
    "Aikyrie_STech",   # Тимур
    "nikitos_stech",   # Никита
    "semen_stech",     # Семён
    "Tony_stech",      # Антон
    "Controlstech",    # Анастасия
    "Stech_Sergei",    # Сергей
    "aslan_stech",     # Аслан
]

SLICE_USERS_1600 = [
    "nikitos_stech",
    "semen_stech",
    "Tony_stech",
    "Controlstech",
]

TIMUR_USERNAME = "Aikyrie_STech"

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ------------------ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ФАЙЛОВ ------------------


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Не удалось загрузить %s: %s", path, e)
        return default


# сотрудники: { "username": "Имя" }
employees: dict[str, str] = load_json(EMPLOYEES_FILE, {})

# данные по отчётам/выводам/срезам
data = load_json(DATA_FILE, {"reports": {}, "conclusions": {}, "slices": {}})

# расписание берём из schedule_manager.schedule


def normalize_data():
    """Гарантируем корректный формат data после загрузки."""
    data.setdefault("reports", {})
    data.setdefault("conclusions", {})
    data.setdefault("slices", {})

    # reports: date -> list
    for d, v in list(data["reports"].items()):
        if isinstance(v, list):
            continue
        elif isinstance(v, set):
            data["reports"][d] = list(v)
        else:
            # на всякий случай
            data["reports"][d] = list(v)

    # conclusions: date -> {username: text}
    for d, v in list(data["conclusions"].items()):
        if not isinstance(v, dict):
            data["conclusions"][d] = {}

    # slices: date -> {username: text}
    for d, v in list(data["slices"].items()):
        if not isinstance(v, dict):
            data["slices"][d] = {}


normalize_data()


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Не удалось сохранить %s: %s", DATA_FILE, e)


def clear_old(days: int = 2):
    """Чистим старые данные старше N дней."""
    today = datetime.date.today()
    limit = today - datetime.timedelta(days=days)

    for section in ("reports", "conclusions", "slices"):
        for d in list(data[section].keys()):
            try:
                dt = datetime.date.fromisoformat(d)
            except ValueError:
                del data[section][d]
                continue
            if dt < limit:
                del data[section][d]


# ------------------ РАСПИСАНИЕ / РОЛИ ------------------
# schedule.json хранит рабочие дни недели по username:
# {
#   "aslan_stech": [0, 2, 4],    # Пн, Ср, Пт
#   "Stech_Sergei": [1, 3]       # Вт, Чт
# }
#
# Для Аслана/Сергея:
#   будний день (Пн–Пт) в списке → "full"
#   выходной (Сб/Вс) в списке → "report"
#   нет в списке → "off"
#
# Для остальных:
#   Пн–Пт → "full"
#   Сб–Вс → "off"


def get_role(username: str, day: datetime.date) -> str:
    """Возвращает роль: 'full', 'report', 'off' для данного дня."""
    weekday = day.weekday()  # 0=понедельник ... 6=воскресенье

    # Для Аслана и Сергея используем расписание из schedule.json
    if username in ("aslan_stech", "Stech_Sergei"):
        days = schedule.get(username, []) or []
        if weekday not in days:
            return "off"
        # Если рабочий день приходится на будний (пн–пт) → полный день
        if weekday < 5:
            return "full"
        # Если рабочий день приходится на выходной (сб или вс) → только отчёт
        return "report"

    # Для остальных действуем по умолчанию: 5/2
    if weekday < 5:
        return "full"
    return "off"


def must_do_report(username: str, day: datetime.date) -> bool:
    return get_role(username, day) in ("full", "report")


def must_do_full(username: str, day: datetime.date) -> bool:
    return get_role(username, day) == "full"


# ------------------ ЗАПИСЬ СОБЫТИЙ ------------------


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return

    msg = update.effective_message
    text_raw = msg.text or ""
    text = text_raw.lower()
    user = update.effective_user

    if not user or not user.username:
        return

    username = user.username
    today = datetime.datetime.now(TZ).date()
    date_key = today.isoformat()

    # Отчёт
    if any(tag in text for tag in REPORT_TAGS):
        if not must_do_report(username, today):
            # этот пользователь сегодня не обязан сдавать отчет - но можно просто молча
            pass
        data.setdefault("reports", {}).setdefault(date_key, [])
        if username not in data["reports"][date_key]:
            data["reports"][date_key].append(username)
        save_data()
        try:
            await msg.set_reaction(REACTION)
        except Exception:
            pass
        return

    # Выводы
    if any(tag in text for tag in CONCLUSION_TAGS):
        if not must_do_full(username, today):
            # сегодня от него выводы не требуются
            pass
        data.setdefault("conclusions", {}).setdefault(date_key, {})
        data["conclusions"][date_key][username] = text_raw
        save_data()
        try:
            await msg.set_reaction(REACTION)
        except Exception:
            pass
        return

    # Срез
    if SLICE_TAG in text:
        if not must_do_full(username, today):
            # сегодня срез не обязателен (например, выходной или только отчёт)
            pass
        data.setdefault("slices", {}).setdefault(date_key, {})
        data["slices"][date_key][username] = text_raw
        save_data()
        try:
            await msg.set_reaction(REACTION)
        except Exception:
            pass
        return


# ------------------ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПРОВЕРОК ------------------


def missing_conclusions_for(day: datetime.date) -> list[str]:
    """Кто из CONCLUSION_USERS должен был и не выложил выводы."""
    date_key = day.isoformat()
    done_users = set(data["conclusions"].get(date_key, {}).keys())
    required = [
        u for u in CONCLUSION_USERS
        if must_do_full(u, day)
    ]
    return [u for u in required if u not in done_users]


def missing_slices_1600_for(day: datetime.date) -> list[str]:
    """Кто из группы 16:00 должен был и не выложил срез."""
    date_key = day.isoformat()
    done_users = set(data["slices"].get(date_key, {}).keys())
    required = [
        u for u in SLICE_USERS_1600
        if must_do_full(u, day)
    ]
    return [u for u in required if u not in done_users]


def timur_missing_slice_for(day: datetime.date) -> bool:
    """Нужно ли требовать срез от Тимура в этот день и не выложил ли он его."""
    if not must_do_full(TIMUR_USERNAME, day):
        return False
    date_key = day.isoformat()
    done_users = set(data["slices"].get(date_key, {}).keys())
    return TIMUR_USERNAME not in done_users


def missing_reports_for(day: datetime.date) -> list[str]:
    """Кто должен был и не сдал отчёт в этот день."""
    date_key = day.isoformat()
    done_users = set(data["reports"].get(date_key, []))

    # Берём всех сотрудников из employees.json
    all_users = list(employees.keys())
    required = [u for u in all_users if must_do_report(u, day)]
    return [u for u in required if u not in done_users]


# ------------------ ЗАДАЧИ ПО ВРЕМЕНИ ------------------
# Все времена — по Москве (TZ)


# --- ВЫВОДЫ ---


async def conclusions_reminder_1230(context: ContextTypes.DEFAULT_TYPE):
    """12:30 – напоминание в КУ: кто не выложил выводы."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_conclusions_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = f"⏰ Ещё не выложили выводы:\n{mentions}"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def conclusions_reminder_1300(context: ContextTypes.DEFAULT_TYPE):
    """13:00 – второе напоминание в КУ."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_conclusions_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = (
        f"⚠️ Не выложили выводы:\n{mentions}\n"
        f"Напишите выводы и скрин 4%"
    )
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def conclusions_admin_1310(context: ContextTypes.DEFAULT_TYPE):
    """13:10 – в админский чат: кто не выложил выводы."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_conclusions_for(today)
    if not missing:
        return

    lines = ["⚠️ Выводы не выложили:"]
    for u in missing:
        lines.append(f"@{u}")
    lines.append(f"@{ADMIN_USERNAME}")
    text = "\n".join(lines)
    await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=text)


# --- СРЕЗЫ 16:00 ---


async def slices_reminder_1600(context: ContextTypes.DEFAULT_TYPE):
    """16:00 – напоминание в КУ по срезам (16:00 группа)."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_slices_1600_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = f"⏰ {mentions}, нужно выложить срез."
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def slices_reminder_1630(context: ContextTypes.DEFAULT_TYPE):
    """16:30 – ещё не выложили срез."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_slices_1600_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = f"⚠️ {mentions}, не выложил срез. Напишите срез!"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def slices_admin_1640(context: ContextTypes.DEFAULT_TYPE):
    """16:40 – в админский: кто не выложил срез 16:00."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_slices_1600_for(today)
    if not missing:
        return

    lines = ["⚠️ Срезы не выложили (16:00):"]
    for u in missing:
        lines.append(f"@{u}")
    lines.append(f"@{ADMIN_USERNAME}")
    text = "\n".join(lines)
    await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=text)


# --- СРЕЗЫ ТИМУР (17:30 / 17:50 / 18:00 админский) ---


async def timur_reminder_1730(context: ContextTypes.DEFAULT_TYPE):
    """17:30 – напоминание Тимуру в КУ."""
    today = datetime.datetime.now(TZ).date()
    if not timur_missing_slice_for(today):
        return

    text = "⏰ @Aikyrie_STech, нужно выложить срез."
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def timur_reminder_1750(context: ContextTypes.DEFAULT_TYPE):
    """17:50 – последнее напоминание Тимуру в КУ."""
    today = datetime.datetime.now(TZ).date()
    if not timur_missing_slice_for(today):
        return

    text = "⚠️ @Aikyrie_STech, не выложил срез. Напиши срез!"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def timur_admin_1800(context: ContextTypes.DEFAULT_TYPE):
    """18:00 – в админский: Тимур не выложил срез."""
    today = datetime.datetime.now(TZ).date()
    if not timur_missing_slice_for(today):
        return

    text = f"⚠️ Тимур не выложил срез.\n@{ADMIN_USERNAME}"
    await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=text)


# --- ОТЧЁТЫ (19:00, 21:00, 22:40, 23:00 в КУ) ---


async def reports_reminder_1900(context: ContextTypes.DEFAULT_TYPE):
    """19:00 – напоминание по отчётам в КУ."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_reports_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = f"⏰ Ещё не сдали отчёт:\n{mentions}"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def reports_reminder_2100(context: ContextTypes.DEFAULT_TYPE):
    """21:00 – второе напоминание по отчётам."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_reports_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = f"⏰ Ещё не сдали отчёт:\n{mentions}"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def reports_warning_2240(context: ContextTypes.DEFAULT_TYPE):
    """22:40 – осталось 20 минут до дедлайна по отчёту."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_reports_for(today)
    if not missing:
        return

    mentions = " ".join(f"@{u}" for u in missing)
    text = f"⚠️ Осталось 20 минут до дедлайна по отчету!\n{mentions}"
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


async def reports_summary_2300(context: ContextTypes.DEFAULT_TYPE):
    """23:00 – итог по отчётам в КУ."""
    today = datetime.datetime.now(TZ).date()
    missing = missing_reports_for(today)
    if not missing:
        return

    lines = ["❌ Итог 23:00. Не сдали отчет:"]
    for u in missing:
        lines.append(f"@{u}")
    text = "\n".join(lines)
    await context.bot.send_message(chat_id=CHAT_ID, text=text)


# --- ОТЧЁТЫ ДИРЕКТОРУ (05:00 за вчера) ---


async def director_reports_0500(context: ContextTypes.DEFAULT_TYPE):
    """05:00 – директору: кто не сдал отчёт за вчера."""
    now = datetime.datetime.now(TZ).date()
    yesterday = now - datetime.timedelta(days=1)
    missing = missing_reports_for(yesterday)
    if not missing:
        return

    lines = ["❌ Не сдали отчёт:"]
    for u in missing:
        lines.append(f"@{u}")
    text = "\n".join(lines)
    await context.bot.send_message(chat_id=DIRECTOR_ID, text=text)


# --- СРЕЗЫ ДИРЕКТОРУ (18:00 за сегодня) ---


async def director_slices_1800(context: ContextTypes.DEFAULT_TYPE):
    """18:00 – директору: итог по срезам за сегодня."""
    today = datetime.datetime.now(TZ).date()
    date_key = today.isoformat()
    slices_today = data.get("slices", {}).get(date_key, {})

    # Все, кто по логике должен сдавать срез (full-день):
    required = [
        u for u in (SLICE_USERS_1600 + [TIMUR_USERNAME])
        if must_do_full(u, today)
    ]
    if not required:
        return

    text_lines = ["📊 Итог по срезам за сегодня:\n"]

    # кто выложил
    for u in required:
        if u in slices_today:
            name = employees.get(u, u)
            text_lines.append(f"✔ {name}:\n{slices_today[u]}\n")

    # кто не выложил
    missing = [u for u in required if u not in slices_today]
    if missing:
        mentions = " ".join(f"@{u}" for u in missing)
        text_lines.append(f"❌ Не выложили срез: {mentions}")

    text = "\n".join(text_lines).strip()
    await context.bot.send_message(chat_id=DIRECTOR_ID, text=text)


# ------------------ ЗАПУСК ПРИЛОЖЕНИЯ ------------------


def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # обработчик текстовых сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # панель управления графиком (/schedule)
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CallbackQueryHandler(schedule_callback))

    jq = application.job_queue

    # Выводы
    jq.run_daily(conclusions_reminder_1230, time(12, 30, tzinfo=TZ))
    jq.run_daily(conclusions_reminder_1300, time(13, 0, tzinfo=TZ))
    jq.run_daily(conclusions_admin_1310, time(13, 10, tzinfo=TZ))

    # Срезы 16:00
    jq.run_daily(slices_reminder_1600, time(16, 0, tzinfo=TZ))
    jq.run_daily(slices_reminder_1630, time(16, 30, tzinfo=TZ))
    jq.run_daily(slices_admin_1640, time(16, 40, tzinfo=TZ))

    # Тимур
    jq.run_daily(timur_reminder_1730, time(17, 30, tzinfo=TZ))
    jq.run_daily(timur_reminder_1750, time(17, 50, tzinfo=TZ))
    jq.run_daily(timur_admin_1800, time(18, 0, tzinfo=TZ))

    # Отчёты в КУ
    jq.run_daily(reports_reminder_1900, time(19, 0, tzinfo=TZ))
    jq.run_daily(reports_reminder_2100, time(21, 0, tzinfo=TZ))
    jq.run_daily(reports_warning_2240, time(22, 40, tzinfo=TZ))
    jq.run_daily(reports_summary_2300, time(23, 0, tzinfo=TZ))

    # Отчёты директору (за вчера)
    jq.run_daily(director_reports_0500, time(5, 0, tzinfo=TZ))

    # Срезы директору
    jq.run_daily(director_slices_1800, time(18, 0, tzinfo=TZ))

    logger.info("Bot started")
    application.run_polling()


if __name__ == "__main__":
    clear_old(days=2)
    save_data()
    main()
