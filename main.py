import datetime
import os
import sqlite3

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from database import DATABASE_PATH, initialize_database
from info import get_info_conv_handler
from medicine_setup import get_conv_handler
from scheduling import check_daily_medicines, schedule_new_medicine


async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''
    Handle the button click for marking a medicine as eaten or forgotten.
    '''
    query = update.callback_query
    action, med_id = query.data.split("_", 1)

    if update.effective_user is None:
        await query.answer("Unable to identify your Telegram account.", show_alert=True)
        return

    with sqlite3.connect(DATABASE_PATH) as connection:
        medicine = connection.execute(
            "SELECT user_id FROM medicines WHERE id = ?",
            (int(med_id),),
        ).fetchone()

    if medicine is None or medicine[0] != update.effective_user.id:
        await query.answer(
            "Only the person who added this medicine can respond.",
            show_alert=True,
        )
        return

    await query.answer()
    for job in context.job_queue.get_jobs_by_name(f"med_{med_id}_snooze"):
        job.schedule_removal()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
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
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Configure it in the environment before starting the bot."
        )

    app = Application.builder().token(token).build()
    app.job_queue.run_daily(
        check_daily_medicines,
        time=datetime.time(hour=0, minute=1),
    )
    app.job_queue.run_once(check_daily_medicines, when=datetime.timedelta(seconds=1))
    app.add_handler(get_conv_handler(schedule_new_medicine))
    app.add_handler(get_info_conv_handler())
    app.add_handler(CallbackQueryHandler(handle_button_click, pattern=r"^(eaten|forgot)_\d+$"))
    app.run_polling()


if __name__ == "__main__":
    main()
