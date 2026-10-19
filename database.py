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
