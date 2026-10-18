import datetime
import sqlite3

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import DATABASE_PATH, get_first_on_date


MEDICINE, VIEW_TYPE, PERIOD = range(3)
PERIODS = {"current": 1, "3": 3, "5": 5, "10": 10}


def _load_medicines(chat_id: int) -> list[sqlite3.Row]:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT id, medicine_name, days_on, days_off, start_date,
                   initial_cycle_day, end_date
            FROM medicines
            WHERE chat_id = ?
            ORDER BY id
            """,
            (chat_id,),
        ).fetchall()


async def start_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    medicines = _load_medicines(update.message.chat_id)
    if not medicines:
        await update.message.reply_text("No medicines have been added yet. Use /addmed first.")
        return ConversationHandler.END

    context.user_data["info_medicines"] = {
        str(row["id"]): row["medicine_name"] for row in medicines
    }
    choices = "\n".join(
        f"{row['id']}: {row['medicine_name']}" for row in medicines
    )
    await update.message.reply_text(
        f"Which medicine should I show?\n{choices}\nReply with its number."
    )
    return MEDICINE


async def choose_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    medicine_id = update.message.text.strip()
    if medicine_id not in context.user_data.get("info_medicines", {}):
        await update.message.reply_text("Please reply with one of the listed medicine numbers.")
        return MEDICINE
    context.user_data["info_med_id"] = int(medicine_id)
    await update.message.reply_text(
        "Choose a view: 'summary' for taken/missed totals or 'logs' for each day."
    )
    return VIEW_TYPE


async def choose_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    view_type = update.message.text.strip().lower()
    if view_type not in {"summary", "logs"}:
        await update.message.reply_text("Reply with 'summary' or 'logs'.")
        return VIEW_TYPE
    context.user_data["info_view"] = view_type
    await update.message.reply_text(
        "How many cycles? Reply 'current', '3', '5', or '10'."
    )
    return PERIOD


def _cycle_dates(
    medicine: sqlite3.Row,
    today: datetime.date,
    cycle_count: int,
) -> list[tuple[int, datetime.date, datetime.date]]:
    start_date = datetime.date.fromisoformat(medicine["start_date"])
    first_on_date = get_first_on_date(
        start_date,
        medicine["days_on"],
        medicine["days_off"],
        medicine["initial_cycle_day"],
    )
    cycle_length = medicine["days_on"] + medicine["days_off"]
    current_cycle = (today - first_on_date).days // cycle_length
    if (today - first_on_date).days % cycle_length >= medicine["days_on"]:
        current_cycle -= 1

    return [
        (
            cycle_number,
            first_on_date + datetime.timedelta(days=cycle_number * cycle_length),
            first_on_date
            + datetime.timedelta(
                days=cycle_number * cycle_length + medicine["days_on"] - 1
            ),
        )
        for cycle_number in range(current_cycle - cycle_count + 1, current_cycle + 1)
    ]


def _get_report(
    medicine: sqlite3.Row,
    cycle_count: int,
    today: datetime.date,
) -> list[tuple[int, datetime.date, str]]:
    cycles = _cycle_dates(medicine, today, cycle_count)
    first_date = max(cycles[0][1], datetime.date.fromisoformat(medicine["start_date"]))
    last_date = cycles[-1][2]
    if medicine["end_date"]:
        last_date = min(last_date, datetime.date.fromisoformat(medicine["end_date"]))

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        logs = connection.execute(
            """
            SELECT date(timestamp) AS log_date, status
            FROM logs
            WHERE med_id = ? AND date(timestamp) BETWEEN ? AND ?
            ORDER BY timestamp
            """,
            (medicine["id"], first_date.isoformat(), last_date.isoformat()),
        ).fetchall()

    statuses: dict[str, set[str]] = {}
    for log in logs:
        statuses.setdefault(log["log_date"], set()).add(log["status"])

    report = []
    for _, cycle_start, cycle_end in cycles:
        day = max(cycle_start, first_date)
        while day <= min(cycle_end, last_date, today):
            day_statuses = statuses.get(day.isoformat(), set())
            status = (
                "eaten"
                if "eaten" in day_statuses
                else "forgot"
                if day_statuses
                else "pending"
                if day == today
                else "missed"
            )
            report.append((_, day, status))
            day += datetime.timedelta(days=1)
    return report


async def show_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    period = update.message.text.strip().lower()
    if period not in PERIODS:
        await update.message.reply_text("Reply with 'current', '3', '5', or '10'.")
        return PERIOD

    med_id = context.user_data["info_med_id"]
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        medicine = connection.execute(
            "SELECT * FROM medicines WHERE id = ? AND chat_id = ?",
            (med_id, update.message.chat_id),
        ).fetchone()

    report = _get_report(medicine, PERIODS[period], datetime.date.today())
    if not report:
        await update.message.reply_text("There is no recorded cycle history yet.")
    elif context.user_data["info_view"] == "summary":
        eaten = sum(status == "eaten" for _, _, status in report)
        missed = sum(status in {"forgot", "missed"} for _, _, status in report)
        pending = sum(status == "pending" for _, _, status in report)
        await update.message.reply_text(
            f"📊 {medicine['medicine_name']} ({period} cycle{'s' if period != 'current' else ''})\n"
            f"Taken: {eaten}\nMissed: {missed}\nPending: {pending}"
        )
    else:
        lines = [
            f"{day.isoformat()}: "
            f"{'✅ taken' if status == 'eaten' else '⏳ pending' if status == 'pending' else '❌ missed'}"
            for _, day, status in report
        ]
        await update.message.reply_text(
            f"📅 {medicine['medicine_name']} daily logs\n" + "\n".join(lines)
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Info view canceled.")
    context.user_data.clear()
    return ConversationHandler.END


def get_info_conv_handler() -> ConversationHandler:
    text = MessageHandler(filters.TEXT & ~filters.COMMAND, choose_medicine)
    return ConversationHandler(
        entry_points=[CommandHandler("info", start_info)],
        states={
            MEDICINE: [text],
            VIEW_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_view)],
            PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_info)],
        },
        fallbacks=[CommandHandler("cancel", cancel_info)],
    )
