# baobao_chiyao
A telegram bot to remind user to eat their medicine

Before starting the bot, set the token without committing it:

```sh
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
python main.py
```

## Bot commands

- `/addmed` walks through adding a medicine, including its reminder time, snooze interval, on/off cycle, current status and day, and optional end date.
- `/info` lets you select a medicine, then view taken/missed summary counts or daily logs for the current cycle or the last 3, 5, or 10 cycles.
- `/cancel` cancels an active setup or information lookup.
