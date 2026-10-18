import datetime
import sqlite3

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from database import DATABASE_PATH, get_cycle_day, initialize_database
from info import get_info_conv_handler
from medicine_setup import get_conv_handler

TOKEN = "8650011922:AAHjDWBzZ7ajpGHsm1piDgOIJUzCHXuvV-4"


async def check_daily_medicines(context: ContextTypes.DEFAULT_TYPE):
    """Schedule the first reminder for each medicine due today."""
    today = datetime.date.today()
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        medicines = connection.execute(
            """
            SELECT id, chat_id, medicine_name, reminder_time, snooze_interval,
                   days_on, days_off, start_date, initial_cycle_day, end_date
            FROM medicines
            """
        ).fetchall()

    for medicine in medicines:
        start_date = datetime.date.fromisoformat(medicine["start_date"])
        end_date = (
            datetime.date.fromisoformat(medicine["end_date"])
            if medicine["end_date"]
            else None
        )
        if today < start_date or (end_date and today > end_date):
            continue

        current_cycle_day = get_cycle_day(
            (today - start_date).days,
            medicine["days_on"],
            medicine["days_off"],
            medicine["initial_cycle_day"],
        )
        if current_cycle_day >= medicine["days_on"]:
            continue

        med = {
            "id": medicine["id"],
            "chat_id": medicine["chat_id"],
            "name": medicine["medicine_name"],
            "time": datetime.datetime.strptime(
                medicine["reminder_time"], "%H:%M"
            ).time(),
            "snooze_mins": medicine["snooze_interval"],
        }
        context.job_queue.run_once(
            send_reminder,
            when=med["time"],
            data=med,
            name=f"med_{med['id']}_first",
        )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send a reminder and queue its next snooze."""
    med = context.job.data
    keyboard = [[
        InlineKeyboardButton("✅ Eaten", callback_data=f"eaten_{med['id']}"),
        InlineKeyboardButton("❌ Forgot to bring", callback_data=f"forgot_{med['id']}"),
    ]]
    await context.bot.send_message(
        chat_id=med["chat_id"],
        text=f"💊 Time to take your {med['name']}!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.job_queue.run_once(
        send_reminder,
        when=med["snooze_mins"] * 60,
        data=med,
        name=f"med_{med['id']}_snooze",
    )


async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, med_id = query.data.split("_", 1)

    for job in context.job_queue.get_jobs_by_name(f"med_{med_id}_snooze"):
        job.schedule_removal()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "INSERT INTO logs (med_id, status) VALUES (?, ?)",
            (int(med_id), action),
        )

    status_emoji = "✅" if action == "eaten" else "❌"
    await query.edit_message_text(
        text=f"{status_emoji} Logged as '{action}' for today. Reminders paused."
    )


def main():
    initialize_database()
    app = Application.builder().token(TOKEN).build()
    app.job_queue.run_daily(
        check_daily_medicines,
        time=datetime.time(hour=0, minute=1),
    )
    app.add_handler(get_conv_handler())
    app.add_handler(get_info_conv_handler())
    app.add_handler(CallbackQueryHandler(handle_button_click, pattern=r"^(eaten|forgot)_\d+$"))
    app.run_polling()


if __name__ == "__main__":
    main()
