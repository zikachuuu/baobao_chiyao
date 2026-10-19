import datetime
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).with_name("medicines.db")


def initialize_database() -> None:
    """Create the local SQLite database and its tables if they do not exist."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                timezone TEXT
            );

            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
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
                ),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                med_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                log_date TEXT,
                status TEXT NOT NULL CHECK (status IN ('eaten', 'forgot')),
                FOREIGN KEY (med_id) REFERENCES medicines (id)
            );

            CREATE TABLE IF NOT EXISTS reminder_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                med_id INTEGER NOT NULL,
                reminder_date TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                FOREIGN KEY (med_id) REFERENCES medicines (id)
            );
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if "timezone" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN timezone TEXT")
        log_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(logs)")
        }
        if "log_date" not in log_columns:
            connection.execute("ALTER TABLE logs ADD COLUMN log_date TEXT")
            connection.execute(
                "UPDATE logs SET log_date = date(timestamp) WHERE log_date IS NULL"
            )
        connection.execute(
            """
            DELETE FROM logs
            WHERE id NOT IN (
                SELECT MIN(id) FROM logs
                WHERE log_date IS NOT NULL
                GROUP BY med_id, log_date
            )
            AND log_date IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_logs_med_date
            ON logs (med_id, log_date)
            """
        )
        reminder_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(reminder_messages)")
        }
        if "chat_id" in reminder_columns:
            connection.executescript(
                """
                ALTER TABLE reminder_messages RENAME TO reminder_messages_old;
                CREATE TABLE reminder_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    med_id INTEGER NOT NULL,
                    reminder_date TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    FOREIGN KEY (med_id) REFERENCES medicines (id)
                );
                INSERT INTO reminder_messages (
                    id, med_id, reminder_date, message_id
                )
                SELECT id, med_id, reminder_date, message_id
                FROM reminder_messages_old;
                DROP TABLE reminder_messages_old;
                """
            )


def get_cycle_day(
    days_elapsed: int,
    days_on: int,
    days_off: int,
    initial_cycle_day: int,
) -> int:
    """Return the zero-based cycle position for a medicine date."""
    cycle_length = days_on + days_off

    if initial_cycle_day < 0:
        # e.g., -3 (3rd day ON) maps to index 2
        start_index = abs(initial_cycle_day) - 1
    elif initial_cycle_day > 0:
        # e.g., 2 (2nd day OFF) maps to index (days_on + 2 - 1)
        start_index = days_on + initial_cycle_day - 1
    else:
        raise ValueError("initial_cycle_day cannot be zero")

    # Simply advance the cycle by the number of days elapsed
    return (start_index + days_elapsed) % cycle_length


def get_first_on_date(
    start_date: datetime.date,
    days_on: int,
    days_off: int,
    initial_cycle_day: int,
) -> datetime.date:
    """Return the first day of the on-medicine period containing start_date."""
    if initial_cycle_day < 0:
        return start_date - datetime.timedelta(days=abs(initial_cycle_day) - 1)
    if initial_cycle_day > 0:
        return start_date + datetime.timedelta(
            days=days_off - initial_cycle_day + 1
        )
    return start_date
