import datetime
import sqlite3
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = "8650011922:AAHjDWBzZ7ajpGHsm1piDgOIJUzCHXuvV-4"
DATABASE_PATH = Path(__file__).with_name("medicines.db")


def initialize_database() -> None:
    """Create the local SQLite database and its tables if they do not exist."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                medicine_name TEXT NOT NULL,
                reminder_time TEXT NOT NULL CHECK (
                    reminder_time GLOB '[0-1][0-9]:[0-5][0-9]'
                    OR reminder_time GLOB '2[0-3]:[0-5][0-9]'
                ),
                snooze_interval INTEGER NOT NULL CHECK (snooze_interval >= 0),
                days_on INTEGER NOT NULL CHECK (days_on >= 0),
                days_off INTEGER NOT NULL CHECK (days_off >= 0),
                start_date TEXT NOT NULL,
                initial_cycle_day INTEGER NOT NULL,
                end_date TEXT,
                CHECK (days_on + days_off > 0),
                CHECK (
                    initial_cycle_day = 0
                    OR (
                        initial_cycle_day < 0
                        AND -initial_cycle_day <= days_on
                    )
                    OR (
                        initial_cycle_day > 0
                        AND initial_cycle_day <= days_off
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                med_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL CHECK (status IN ('eaten', 'forgot')),
                FOREIGN KEY (med_id) REFERENCES medicines (id)
            );
            """
        )


# ---------------------------------------------------------
# 1. SCHEDULING LOGIC
# ---------------------------------------------------------
def get_cycle_day(
    days_elapsed: int,
    days_on: int,
    days_off: int,
    initial_cycle_day: int,
) -> int:
    """Return the zero-based cycle position for a medicine date.

    A negative initial day means the medicine was selected on that numbered
    on-medicine day. A positive initial day means it was selected on that
    numbered rest day. Zero starts a new cycle on its first on-medicine day.
    """
    cycle_length = days_on + days_off
    if initial_cycle_day < 0:
        initial_position = abs(initial_cycle_day) - 1
    elif initial_cycle_day > 0:
        initial_position = days_on + initial_cycle_day - 1
    else:
        initial_position = 0

    return (initial_position + days_elapsed) % cycle_length


async def check_daily_medicines(context: ContextTypes.DEFAULT_TYPE):
    """
    Schedule the first reminder for each medicine due today.
    """
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

        # Handles empty end date
        end_date = (
            datetime.date.fromisoformat(medicine["end_date"])
            if medicine["end_date"]
            else None
        )

        # Skip if today is before the start date or after the end date (if provided)
        if today < start_date or (end_date and today > end_date):
            continue

        days_elapsed = (today - start_date).days
        current_cycle_day = get_cycle_day(
            days_elapsed,
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
            name=f"med_{med['id']}_first"
        )

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Sends the reminder and queues the next snooze."""
    med = context.job.data
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Eaten", callback_data=f"eaten_{med['id']}"),
            InlineKeyboardButton("❌ Forgot to bring", callback_data=f"forgot_{med['id']}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await context.bot.send_message(
        chat_id=med["chat_id"],
        text=f"💊 Time to take your {med['name']}!",
        reply_markup=reply_markup
    )
    
    # Schedule the snooze reminder
    context.job_queue.run_once(
        send_reminder,
        when=med["snooze_mins"] * 60, # convert to seconds
        data=med,
        name=f"med_{med['id']}_snooze"
    )

# ---------------------------------------------------------
# 2. HANDLING USER ACTIONS
# ---------------------------------------------------------
async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Acknowledge the click
    
    action, med_id = query.data.split("_")
    
    # 1. Cancel any pending snooze jobs for this medicine
    current_jobs = context.job_queue.get_jobs_by_name(f"med_{med_id}_snooze")
    for job in current_jobs:
        job.schedule_removal()
        
    # 2. Save to database (Draft logic)
    # db.execute("INSERT INTO logs (med_id, status, timestamp) VALUES (?, ?, ?)", 
    #            (med_id, action, datetime.datetime.now()))
    
    # 3. Update the message so the buttons disappear
    status_emoji = "✅" if action == "eaten" else "❌"
    await query.edit_message_text(
        text=f"{status_emoji} Logged as '{action}' for today. Reminders paused."
    )

# ---------------------------------------------------------
# 3. BOT INITIALIZATION
# ---------------------------------------------------------
def main():
    initialize_database()
    app = Application.builder().token(TOKEN).build()
    
    # Setup the daily midnight check
    app.job_queue.run_daily(
        check_daily_medicines, 
        time=datetime.time(hour=0, minute=1) 
    )
    
    # Handle the inline keyboard buttons
    app.add_handler(CallbackQueryHandler(handle_button_click, pattern="^(I have taken my mediciation!|I do not have my medication with me all day)_"))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
