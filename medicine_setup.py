import datetime
import re
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
from timezone import get_user_timezone, start_timezone_setup



MED_NAME, TIME, SNOOZE, DAYS_ON, DAYS_OFF, CURRENT_STATUS, CURRENT_STATUS_DAY, END_DATE = range(8)


async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None or get_user_timezone(user.id) is None:
        await start_timezone_setup(
            update,
            context,
            "Set your timezone before adding medicines. Please share your current location.",
        )
        return ConversationHandler.END
    await update.message.reply_text("Let's set up a new medicine. What is the name?")
    return MED_NAME


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    medicine_name = update.message.text.strip()
    if not medicine_name or re.match(r"^[A-Za-z0-9]", medicine_name) is None:
        await update.message.reply_text(
            "Invalid medicine name. It must start with a letter or number. Please try again."
        )
        return MED_NAME

    context.user_data["med_name"] = medicine_name
    await update.message.reply_text(
        f"Got it. What time to take {context.user_data['med_name']} everyday? (HH:MM)"
    )
    return TIME


async def ask_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        datetime.datetime.strptime(update.message.text.strip(), "%H:%M")
    except ValueError:
        await update.message.reply_text("Please use 24-hour HH:MM format, for example 08:30 (NOT 8:30).")
        return TIME
    
    context.user_data["time"] = update.message.text.strip()
    await update.message.reply_text(f"From {context.user_data['time']} each day, how often do you want to be reminded if you haven't taken {context.user_data['med_name']}? (in minutes)")
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
    await update.message.reply_text(f"How many consecutive days do you take {context.user_data['med_name']}?")
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
    await update.message.reply_text(f"After taking {context.user_data['med_name']} for {value} days, how many days do you pause afterward?")
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
        "Is today a 1 - Medication Day or a 2 - no-medication day? Reply 1 or 2 only."
    )
    return CURRENT_STATUS


async def ask_current_status_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    status_num = update.message.text.strip().lower()
    if status_num not in {"1", "2"}:
        await update.message.reply_text("Reply with '1' or '2'.")
        return CURRENT_STATUS
    
    context.user_data["current_status"] = "on" if status_num == "1" else "off"
    await update.message.reply_text(
        f"Which day of {"Medication Day" if status_num == "1" else "No-Medication Day"} is today? For example, 1 means its first day of {"Medication Day" if status_num == "1" else "No-Medication Day"}."
    )
    return CURRENT_STATUS_DAY


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
        return CURRENT_STATUS_DAY

    context.user_data["current_day"] = day
    await update.message.reply_text(
        f"What is the final day to take {context.user_data['med_name']} before stopping it permanently? (in DDMMYYYY format). Type 'none' if there is no end date."
    )
    return END_DATE


async def save_medicine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    schedule_medicine=None,
) -> int:
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
    user = update.effective_user
    if user is None:
        await update.message.reply_text("Unable to identify your Telegram account.")
        return END_DATE

    # Initial cycle day is negative to indicate that the medicine is current in the "on" phase (on medication)
    initial_cycle_day = data["current_day"]
    if data["current_status"] == "on":
        initial_cycle_day = -initial_cycle_day

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO users (user_id, name)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name = excluded.name
            """,
            (user.id, user.full_name),
        )
        connection.execute(
            """
            INSERT INTO medicines (
                user_id, chat_id, medicine_name, reminder_time, snooze_interval,
                days_on, days_off, start_date, initial_cycle_day, end_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                update.effective_chat.id,
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
        medicine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]

    await update.message.reply_text(f"✅ Setup complete for {data['med_name']}!")
    if schedule_medicine is not None:
        await schedule_medicine(context, medicine_id)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Setup canceled. No changes were made.")
    context.user_data.clear()
    return ConversationHandler.END


def get_conv_handler(schedule_medicine=None) -> ConversationHandler:
    # Define the conversation handler for the medicine setup process
    # This function returns a ConversationHandler that manages the flow of the medicine setup conversation.
    # The conversation starts with the /addmedicine command and progresses through various states,
    #   collecting information about the medicine, reminder time, snooze interval, days on/off, current status, current day, and end date.
    #   Each state has a corresponding handler function that processes user input and transitions to the next state.
    #   The conversation can be canceled at any time with the /cancel command.

    return ConversationHandler(
        entry_points    = [CommandHandler("add_medicine", start_setup)],
        states          = {
            MED_NAME            : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            TIME                : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_snooze)],
            SNOOZE              : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_days_on)],
            DAYS_ON             : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_days_off)],
            DAYS_OFF            : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_current_status)],
            CURRENT_STATUS      : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_current_status_day)],
            CURRENT_STATUS_DAY  : [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_end_date)],
            END_DATE            : [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    lambda update, context: save_medicine(
                        update, context, schedule_medicine
                    ),
                )
            ],
        },
        fallbacks       = [CommandHandler("cancel", cancel)],
    )
