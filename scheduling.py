import datetime
import sqlite3

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import DATABASE_PATH, get_cycle_day


def get_medicine_for_today(medicine: sqlite3.Row) -> dict | None:
    '''
    Determine if a medicine is due today and return its details if so.
    If the medicine is not due today, return None.
    '''

    today = datetime.date.today()
    start_date = datetime.date.fromisoformat(medicine["start_date"])
    end_date = (
        datetime.date.fromisoformat(medicine["end_date"])
        if medicine["end_date"]
        else None
    )
    if today < start_date or (end_date and today > end_date):
        return None

    current_cycle_day = get_cycle_day(
        (today - start_date).days,
        medicine["days_on"],
        medicine["days_off"],
        medicine["initial_cycle_day"],
    )
    if current_cycle_day >= medicine["days_on"]:
        return None

    reminder_time = datetime.datetime.strptime(
        medicine["reminder_time"], "%H:%M"
    ).time()
    reminder_at = datetime.datetime.combine(today, reminder_time)
    if reminder_at <= datetime.datetime.now():
        return None

    return {
        "id": medicine["id"],
        "chat_id": medicine["chat_id"],
        "name": medicine["medicine_name"],
        "time": reminder_at,
        "snooze_mins": medicine["snooze_interval"],
    }


def load_medicines() -> list[sqlite3.Row]:
    '''
    Load all medicines from the database and return them as a list of sqlite3.Row objects.
    '''

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT id, chat_id, medicine_name, reminder_time, snooze_interval,
                   days_on, days_off, start_date, initial_cycle_day, end_date
            FROM medicines
            """
        ).fetchall()


def load_medicine(medicine_id: int) -> sqlite3.Row | None:
    '''
    Load a specific medicine by its ID from the database and return it as an sqlite3.Row object.
    If the medicine does not exist, return None.
    '''

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT id, chat_id, medicine_name, reminder_time, snooze_interval,
                   days_on, days_off, start_date, initial_cycle_day, end_date
            FROM medicines
            WHERE id = ?
            """,
            (medicine_id,),
        ).fetchone()


def schedule_medicine_for_today(
    context: ContextTypes.DEFAULT_TYPE,
    medicine: sqlite3.Row,
) -> None:
    '''
    Schedule a medicine for today.
    If the medicine is due today, schedule its reminder. If not, do nothing.
    '''

    med = get_medicine_for_today(medicine)
    if med is None:
        return

    for job in context.job_queue.get_jobs_by_name(f"med_{med['id']}_first"):
        job.schedule_removal()

    context.job_queue.run_once(
        send_reminder,
        when=med["time"] - datetime.datetime.now(),
        data=med,
        name=f"med_{med['id']}_first",
    )


async def check_daily_medicines(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Schedule all medicines due today during the daily 00:01 check.
    """

    for medicine in load_medicines():
        schedule_medicine_for_today(context, medicine)


async def schedule_new_medicine(
    context: ContextTypes.DEFAULT_TYPE,
    medicine_id: int,
) -> None:
    """
    Schedule a medicine immediately after it is added.
    """
    medicine = load_medicine(medicine_id)
    if medicine is not None:
        schedule_medicine_for_today(context, medicine)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Send a reminder and queue its next snooze.
    """
    
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
