import sqlite3
import inspect
from collections.abc import Awaitable, Callable

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from timezonefinder import TimezoneFinder

from database import DATABASE_PATH


LOCATION = 0
TimezoneCallback = Callable[
    [ContextTypes.DEFAULT_TYPE, int], Awaitable[None] | None
]
_timezone_finder = TimezoneFinder()


def get_user_timezone(user_id: int) -> str | None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT timezone FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Share current location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def start_timezone_setup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str = "Please share your current location so I can set your timezone.",
) -> int:
    await update.message.reply_text(prompt, reply_markup=location_keyboard())
    return LOCATION


async def save_timezone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reschedule: TimezoneCallback | None = None,
) -> int:
    location = update.message.location
    user = update.effective_user
    if location is None or user is None:
        await update.message.reply_text(
            "Please use the 'Share current location' button.",
            reply_markup=location_keyboard(),
        )
        return LOCATION

    timezone_name = _timezone_finder.timezone_at(
        lat=location.latitude,
        lng=location.longitude,
    )
    if not timezone_name:
        await update.message.reply_text(
            "I could not determine a timezone from that location. Please share it again."
        )
        return LOCATION

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, name, timezone)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                timezone = excluded.timezone
            """,
            (user.id, user.full_name, timezone_name),
        )

    await update.message.reply_text(
        f"Timezone set to {timezone_name}. Your reminders will follow local time.",
        reply_markup=ReplyKeyboardRemove(),
    )
    if reschedule is not None:
        result = reschedule(context, user.id)
        if inspect.isawaitable(result):
            await result
    context.user_data.clear()
    return ConversationHandler.END


async def _start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if user is not None and get_user_timezone(user.id):
        await update.message.reply_text(
            "Welcome back. Use /add_medicine to add a medicine, "
            "/info to view your logs, or /timezone to update your timezone."
        )
        return ConversationHandler.END
    return await start_timezone_setup(
        update,
        context,
        "Welcome! Please share your current location to enable reminders.",
    )


def get_timezone_conv_handler(
    reschedule: TimezoneCallback | None = None,
) -> ConversationHandler:
    async def save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await save_timezone(update, context, reschedule)

    return ConversationHandler(
        entry_points=[
            CommandHandler("start", _start_command),
            CommandHandler(
                "timezone",
                lambda update, context: start_timezone_setup(
                    update,
                    context,
                    "Share your new current location to update your timezone.",
                ),
            ),
            MessageHandler(filters.LOCATION, save),
        ],
        states={
            LOCATION: [MessageHandler(filters.LOCATION, save)],
        },
        fallbacks=[CommandHandler("cancel", _cancel_timezone)],
    )


async def _cancel_timezone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(
        "Timezone setup canceled.", reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END
