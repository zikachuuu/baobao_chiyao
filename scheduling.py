import datetime
import sqlite3
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import DATABASE_PATH, get_cycle_day
from timezone import get_user_timezone


def get_medicine_for_today(medicine: sqlite3.Row) -> dict | None:
    '''
    Determine if a medicine is due today and return its details if so.
    If the medicine is not due today, return None.
    '''

    local_now = datetime.datetime.now(ZoneInfo(medicine["timezone"]))
    today = local_now.date()
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
    reminder_at = datetime.datetime.combine(
        today, reminder_time, tzinfo=ZoneInfo(medicine["timezone"])
    )
    if reminder_at <= local_now:
        return None

    return {
        "id": medicine["id"],
        "chat_id": medicine["chat_id"],
        "name": medicine["medicine_name"],
        "time": reminder_at,
        "snooze_mins": medicine["snooze_interval"],
        "timezone": medicine["timezone"],
    }


def load_medicines() -> list[sqlite3.Row]:
    '''
    Load all medicines from the database and return them as a list of sqlite3.Row objects.
    '''

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT m.id, m.chat_id, m.medicine_name,
                   m.reminder_time, m.snooze_interval,
                   m.user_id, m.days_on, m.days_off,
                   m.start_date, m.initial_cycle_day,
                   m.end_date,
                   u.timezone
            FROM medicines AS m
            JOIN users AS u ON u.user_id = m.user_id
            WHERE u.timezone IS NOT NULL
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
            SELECT m.id, m.chat_id, m.medicine_name,
                   m.reminder_time, m.snooze_interval,
                   m.user_id, m.days_on, m.days_off,
                   m.start_date, m.initial_cycle_day,
                   m.end_date,
                   u.timezone
            FROM medicines AS m
            JOIN users AS u ON u.user_id = m.user_id
            WHERE m.id = ?
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
        when=med["time"] - datetime.datetime.now(
            ZoneInfo(med["timezone"])
        ),
        data=med,
        name=f"med_{med['id']}_first",
    )


async def check_daily_medicines(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Schedule all medicines due today during the daily 00:01 check.
    """

    for medicine in load_medicines():
        schedule_medicine_for_today(context, medicine)


async def check_user_medicines(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = context.job.data["user_id"]
    for medicine in load_medicines():
        if medicine["user_id"] == user_id:
            schedule_medicine_for_today(context, medicine)


def ensure_user_daily_schedule(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> None:
    for job in context.job_queue.get_jobs_by_name(f"med_user_{user_id}_daily"):
        job.schedule_removal()

    timezone_name = get_user_timezone(user_id)
    if timezone_name:
        context.job_queue.run_daily(
            check_user_medicines,
            time=datetime.time(0, 1, tzinfo=ZoneInfo(timezone_name)),
            data={"user_id": user_id},
            name=f"med_user_{user_id}_daily",
        )


def reset_user_schedule(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> None:
    for medicine in load_medicines():
        if medicine["user_id"] == user_id:
            for job in context.job_queue.get_jobs_by_name(
                f"med_{medicine['id']}_first"
            ):
                job.schedule_removal()
            for job in context.job_queue.get_jobs_by_name(
                f"med_{medicine['id']}_snooze"
            ):
                job.schedule_removal()
    ensure_user_daily_schedule(context, user_id)


async def schedule_all_user_jobs(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_ids = {medicine["user_id"] for medicine in load_medicines()}
    for user_id in user_ids:
        reset_user_schedule(context, user_id)
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
        ensure_user_daily_schedule(context, medicine["user_id"])
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
    message = await context.bot.send_message(
        chat_id=med["chat_id"],
        text=f"💊 Time to take your {med['name']}!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    reminder_date = datetime.datetime.now(
        ZoneInfo(med["timezone"])
    ).date().isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            INSERT INTO reminder_messages (
                med_id, reminder_date, message_id
            ) VALUES (?, ?, ?)
            """,
            (med["id"], reminder_date, message.message_id),
        )
    context.job_queue.run_once(
        send_reminder,
        when=med["snooze_mins"] * 60,
        data=med,
        name=f"med_{med['id']}_snooze",
    )
