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

from database import DATABASE_PATH


MED_NAME, TIME, SNOOZE, DAYS_ON, DAYS_OFF, CURRENT_STATUS, CURRENT_DAY, END_DATE = range(8)


async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Let's set up a new medicine. What is the name?")
    return MED_NAME


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["med_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"Got it. What time to take {context.user_data['med_name']}? (HH:MM)"
    )
    return TIME


async def ask_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        datetime.datetime.strptime(update.message.text.strip(), "%H:%M")
    except ValueError:
        await update.message.reply_text("Please use 24-hour HH:MM format, for example 08:30.")
        return TIME
    context.user_data["time"] = update.message.text.strip()
    await update.message.reply_text("How many minutes between snooze reminders?")
    return SNOOZE


async def ask_days_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int(update.message.text)
        if value < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a positive whole number.")
        return SNOOZE
    context.user_data["snooze"] = value
    await update.message.reply_text("How many consecutive days do you take this?")
    return DAYS_ON


async def ask_days_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int(update.message.text)
        if value < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a positive whole number.")
        return DAYS_ON
    context.user_data["days_on"] = value
    await update.message.reply_text("How many days do you pause afterward?")
    return DAYS_OFF


async def ask_current_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int(update.message.text)
        if value < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a positive whole number.")
        return DAYS_OFF
    context.user_data["days_off"] = value
    await update.message.reply_text(
        "Is today a medicine day or a no-medication day? Reply 'on' or 'off'."
    )
    return CURRENT_STATUS


async def ask_current_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    status = update.message.text.strip().lower()
    if status not in {"on", "off"}:
        await update.message.reply_text("Reply with 'on' or 'off'.")
        return CURRENT_STATUS
    context.user_data["current_status"] = status
    await update.message.reply_text(
        "Which day of that period is today? For example, 1 means its first day."
    )
    return CURRENT_DAY


async def ask_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        day = int(update.message.text)
        if day < 1:
            raise ValueError
        limit = (
            context.user_data["days_on"]
            if context.user_data["current_status"] == "on"
            else context.user_data["days_off"]
        )
        if day > limit:
            raise ValueError
    except ValueError:
        await update.message.reply_text("That day is outside the selected period. Please try again.")
        return CURRENT_DAY
    context.user_data["current_day"] = day
    await update.message.reply_text(
        "What is the end date? (DDMMYYYY). Type 'none' if it is indefinite."
    )
    return END_DATE


async def save_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end_date_text = update.message.text.strip().lower()
    if end_date_text == "none":
        end_date = None
    else:
        try:
            end_date = datetime.datetime.strptime(end_date_text, "%d%m%Y").date().isoformat()
        except ValueError:
            await update.message.reply_text("Please use DDMMYYYY or type 'none'.")
            return END_DATE

    data = context.user_data
    initial_cycle_day = data["current_day"]
    if data["current_status"] == "on":
        initial_cycle_day = -initial_cycle_day

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            INSERT INTO medicines (
                chat_id, medicine_name, reminder_time, snooze_interval,
                days_on, days_off, start_date, initial_cycle_day, end_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                update.message.chat_id,
                data["med_name"],
                data["time"],
                data["snooze"],
                data["days_on"],
                data["days_off"],
                datetime.date.today().isoformat(),
                initial_cycle_day,
                end_date,
            ),
        )

    await update.message.reply_text(f"✅ Setup complete for {data['med_name']}!")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Setup canceled.")
    context.user_data.clear()
    return ConversationHandler.END


def get_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("addmed", start_setup)],
        states={
            MED_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_snooze)],
            SNOOZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_days_on)],
            DAYS_ON: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_days_off)],
            DAYS_OFF: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_current_status)],
            CURRENT_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_current_day)],
            CURRENT_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_end_date)],
            END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_medicine)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
