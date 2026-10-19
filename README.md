# baobao_chiyao

`baobao_chiyao` is a Telegram bot that reminds users to take their medicines
according to configurable schedules. Each medicine belongs to a Telegram user
and is delivered only in the chat where it was created. Reminder times and the
daily scheduling cycle follow the user's configured timezone, including when
the user travels.

## Running locally

Set the bot token without committing it:

```sh
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
python main.py
```

Alternatively, place the token in a local `.env` file:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
```

Install dependencies before starting the bot:

```sh
source bot-env/bin/activate
pip install -r requirements.txt
python main.py
```

## Bot commands

- `/start` — Introduces the bot. On first use, asks the user to share their
  current location so the bot can determine and save their timezone.
- `/timezone` — Updates the user's timezone after traveling. The user shares
  their new location, then existing timezone-dependent reminder jobs are
  canceled and recreated.
- `/add_medicine` — Starts the medicine setup flow. It collects the medicine
  name, reminder time, snooze interval, medication days, rest days, today's
  medication/rest status and day number, and optional end date.
- `/info` — Shows medicine information for the current user's medicine list.
  The user can choose a summary or daily logs for the current cycle or the
  last 3, 5, or 10 cycles.
- `/cancel` — Cancels an active medicine setup, timezone update, or information
  lookup without saving the unfinished flow.

## Reminder behavior

- Reminders are sent only to the chat where the medicine was created.
- The user's timezone controls the reminder time and the daily `00:01`
  scheduling check.
- A medicine can use an on/off cycle, such as 5 medication days followed by
  2 rest days.
- The first reminder is scheduled immediately after a medicine is added when
  its reminder time has not yet passed for that local day.
- Snooze reminders continue until the owner selects `Eaten` or `Forgot to
  bring`.
- Only the owner who added the medicine can use the inline keyboard buttons.
- Once one response is recorded for a medicine on a local day, all reminder
  buttons for that medicine and day are disabled and duplicate logs are
  rejected.

## Sample flow

1. The user sends `/start`.
2. The bot asks the user to share their current location.
3. The user shares the location. The bot detects and saves the user's timezone.
4. The user sends `/add_medicine`.
5. The bot asks for the medicine name, reminder time, snooze interval, on/off
   cycle, current cycle status and day, and optional end date.
6. The user completes the setup. The bot saves the medicine owner, originating
   chat, and schedule, then schedules today's reminder if applicable.
7. At the configured local time, the bot sends the reminder in the originating
   chat.
8. The user selects `Eaten` or `Forgot to bring`. The bot records one daily
   result, cancels snooze reminders, and disables all other buttons for that
   medicine's reminders that day.
9. The user sends `/info`, selects the medicine, and chooses either summary
   statistics or daily logs for the desired cycle range.
10. If the user travels, they send `/timezone` and share their new location.
    The bot updates the timezone and recreates the user's reminder schedule.
