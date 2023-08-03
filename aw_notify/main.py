"""
Get time spent for different categories in a day,
and send notifications to the user on predefined conditions.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from time import sleep

import aw_client
import aw_client.queries
import click
from desktop_notifier import DesktopNotifier

logger = logging.getLogger(__name__)

# TODO: Get categories from aw-webui export (in the future from server key-val store)
# TODO: Add thresholds for total time today (incl percentage of productive time)

# regex for productive time
RE_PRODUCTIVE = r"Programming|nvim|taxes|Roam|Code"


CATEGORIES: list[tuple[list[str], dict]] = [
    (
        ["Work"],
        {
            "type": "regex",
            "regex": RE_PRODUCTIVE,
            "ignore_case": True,
        },
    ),
    (
        ["Twitter"],
        {
            "type": "regex",
            "regex": r"Twitter|twitter.com|Home / X",
            "ignore_case": True,
        },
    ),
]

time_offset = timedelta(hours=4)

aw = aw_client.ActivityWatchClient("aw-notify", testing=False)


def get_time(category: str) -> timedelta:
    now = datetime.now(timezone.utc)
    timeperiods = [
        (
            now.replace(hour=0, minute=0, second=0, microsecond=0) + time_offset,
            now,
        )
    ]

    hostname = aw.get_info().get("hostname", "unknown")
    canonicalQuery = aw_client.queries.canonicalEvents(
        aw_client.queries.DesktopQueryParams(
            bid_window=f"aw-watcher-window_{hostname}",
            bid_afk=f"aw-watcher-afk_{hostname}",
            classes=CATEGORIES,
            filter_classes=[[category]] if category else [],
        )
    )
    query = f"""
    {canonicalQuery}
    duration = sum_durations(events);
    RETURN = {{"events": events, "duration": duration}};
    """

    res = aw.query(query, timeperiods)[0]
    time = timedelta(seconds=res["duration"])
    return time


def to_hms(duration: timedelta) -> str:
    days = duration.days
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    s = ""
    if days > 0:
        s += f"{days}d "
    if hours > 0:
        s += f"{hours}h "
    if minutes > 0:
        s += f"{minutes}m "
    if len(s) == 0:
        s += f"{seconds}s "
    return s.strip()


notifier: DesktopNotifier = None


def notify(title: str, msg: str):
    # send a notification to the user

    global notifier
    if notifier is None:
        notifier = DesktopNotifier(
            app_name="ActivityWatch",
            # icon="file:///path/to/icon.png",
            notification_limit=10,
        )

    print(msg)
    notifier.send_sync(title=title, message=msg)


td15min = timedelta(minutes=15)
td30min = timedelta(minutes=30)
td1h = timedelta(hours=1)
td2h = timedelta(hours=2)
td6h = timedelta(hours=6)
td4h = timedelta(hours=4)
td8h = timedelta(hours=8)


class CategoryAlert:
    """
    Alerts for a category.
    Keeps track of the time spent so far, which alerts to trigger, and which have been triggered.
    """

    def __init__(self, category: str, thresholds: list[timedelta]):
        self.category = category
        self.thresholds = thresholds
        self.max_triggered: timedelta = timedelta()
        self.time_spent = timedelta()
        self.last_check = datetime(1970, 1, 1, tzinfo=timezone.utc)

    @property
    def thresholds_untriggered(self):
        return [t for t in self.thresholds if t > self.max_triggered]

    @property
    def time_to_next_threshold(self) -> timedelta:
        """Returns the earliest time at which the next threshold can be reached."""
        if not self.thresholds_untriggered:
            # if no thresholds to trigger, wait until tomorrow
            day_end = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if day_end < datetime.now(timezone.utc):
                day_end += timedelta(days=1)
            time_to_next_day = day_end - datetime.now(timezone.utc) + time_offset
            return time_to_next_day + min(self.thresholds)

        return min(self.thresholds_untriggered) - self.time_spent

    def update(self):
        """
        Update the time spent and check if a threshold has been reached.
        """
        now = datetime.now(timezone.utc)
        time_to_threshold = self.time_to_next_threshold
        # print("Update?")
        if now > (self.last_check + time_to_threshold):
            logger.debug(f"Updating {self.category}")
            # print(f"Time to threshold: {time_to_threshold}")
            self.last_check = now
            self.time_spent = get_time(self.category)
        else:
            pass
            # logger.debug("Not updating, too soon")

    def check(self):
        """Check if thresholds have been reached"""
        for thres in sorted(self.thresholds_untriggered, reverse=True):
            if thres <= self.time_spent:
                # threshold reached
                self.max_triggered = thres
                notify(
                    "Time spent",
                    f"{self.category or 'All'}: {to_hms(self.time_spent)}",
                )
                break

    def status(self) -> str:
        return f"""{self.category or 'All'}: {to_hms(self.time_spent)}"""
        # (time to thres: {to_hms(self.time_to_next_threshold)})
        # triggered: {self.max_triggered}"""


def test_category_alert():
    catalert = CategoryAlert("Work", [td15min, td30min, td1h, td2h, td4h])
    catalert.update()
    catalert.check()


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enables verbose mode.")
def main(verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@main.command()
def start():
    """Start the notification service."""
    checkin()
    hourly()
    threshold_alerts()


def threshold_alerts():
    """
    Checks elapsed time for each category and triggers alerts when thresholds are reached.
    """
    alerts = [
        CategoryAlert("", [td15min, td30min, td1h, td2h, td4h, td6h, td8h]),
        CategoryAlert("Twitter", [td15min, td30min, td1h]),
        CategoryAlert("Work", [td15min, td30min, td1h, td2h, td4h]),
    ]

    while True:
        for alert in alerts:
            alert.update()
            alert.check()
            status = alert.status()
            if status != getattr(alert, "last_status", None):
                print(f"New status: {status}")
                alert.last_status = status

        sleep(10)


@main.command()
def _checkin():
    """Send a summary notification."""
    checkin()


def checkin():
    """
    Sends a summary notification of the day.
    Meant to be sent at a particular time, like at the end of a working day (e.g. 5pm).
    """
    # TODO: load categories from data
    top_categories = [""] + [k[0] for k, _ in CATEGORIES]
    time_spent = [get_time(c) for c in top_categories]
    msg = f"Time spent today: {sum(time_spent, timedelta())}\n"
    msg += "Categories:\n"
    msg += "\n".join(
        f" - {c if c else 'All'}: {t}"
        for c, t in sorted(
            zip(top_categories, time_spent), key=lambda x: x[1], reverse=True
        )
    )
    notify("Checkin", msg)


def get_active_status() -> bool:
    """
    Get active status by polling latest event in aw-watcher-afk bucket.
    Returns True if user is active/not-afk, False if not.
    On error, like out-of-date event, returns None.
    """

    hostname = aw.get_info().get("hostname", "unknown")
    events = aw.get_events(f"aw-watcher-afk_{hostname}", limit=1)
    print(events)
    if not events:
        return None
    event = events[0]
    if event.timestamp < datetime.now(timezone.utc) - timedelta(minutes=5):
        # event is too old
        logger.warning(
            "AFK event is too old, can't use to reliably determine AFK state"
        )
        return None
    return events[0]["data"]["status"] == "not-afk"


def hourly():
    """Start a thread that does hourly checkins, on every whole hour that the user is active (not if afk)."""

    def checkin_thread():
        while True:
            # wait until next whole hour
            now = datetime.now(timezone.utc)
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(
                hours=1
            )
            sleep_time = (next_hour - now).total_seconds()
            logger.debug(f"Sleeping for {sleep_time} seconds")
            sleep(sleep_time)

            # check if user is afk
            active = get_active_status()
            if active is None:
                logger.warning("Can't determine AFK status, skipping hourly checkin")
                continue
            if not active:
                logger.info("User is AFK, skipping hourly checkin")
                continue

            checkin()

    threading.Thread(target=checkin_thread, daemon=True).start()


if __name__ == "__main__":
    main()
