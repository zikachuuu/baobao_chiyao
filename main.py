import datetime
import os
import sqlite3
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from database import DATABASE_PATH, initialize_database
from info import get_info_conv_handler
from medicine_setup import get_conv_handler
from scheduling import (
    reset_user_schedule,
    schedule_all_user_jobs,
    schedule_new_medicine,
)
from timezone import get_timezone_conv_handler


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
            """
            SELECT m.user_id, u.timezone
            FROM medicines AS m
            JOIN users AS u ON u.user_id = m.user_id
            WHERE m.id = ?
            """,
            (int(med_id),),
        ).fetchone()

    if medicine is None or medicine[0] != update.effective_user.id:
        await query.answer(
            "Only the person who added this medicine can respond.",
            show_alert=True,
        )
        return

    local_date = datetime.datetime.now(
        ZoneInfo(medicine[1])
    ).date().isoformat()
    local_time = datetime.datetime.now(
        ZoneInfo(medicine[1])
    ).time().isoformat(timespec="seconds")
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute(
                """
                INSERT INTO logs (
                    med_id, log_date, log_time, log_timezone, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (int(med_id), local_date, local_time, medicine[1], action),
            )
        except sqlite3.IntegrityError:
            await query.answer(
                "This medicine has already been recorded for today.",
                show_alert=True,
            )
            return

        reminder_messages = connection.execute(
            """
            SELECT m.chat_id, r.message_id
            FROM reminder_messages AS r
            JOIN medicines AS m ON m.id = r.med_id
            WHERE r.med_id = ? AND r.reminder_date = ?
            """,
            (int(med_id), local_date),
        ).fetchall()

    await query.answer()
    for job in context.job_queue.get_jobs_by_name(f"med_{med_id}_snooze"):
        job.schedule_removal()

    for chat_id, message_id in reminder_messages:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except TelegramError:
            continue

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
    app.job_queue.run_once(schedule_all_user_jobs, when=datetime.timedelta(seconds=1))
    app.add_handler(get_timezone_conv_handler(reset_user_schedule))
    app.add_handler(get_conv_handler(schedule_new_medicine))
    app.add_handler(get_info_conv_handler())
    app.add_handler(CallbackQueryHandler(handle_button_click, pattern=r"^(eaten|forgot)_\d+$"))
    app.run_polling()


if __name__ == "__main__":
    main()
