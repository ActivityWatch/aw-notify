"""
Get time spent for different categories in a day,
and send notifications to the user on predefined conditions.
"""
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from time import sleep
from typing import (
    Callable,
    Optional,
    TypeVar,
    Union,
)

import aw_client.queries
import click
import tomlkit
from desktop_notifier import DesktopNotifier
from typing_extensions import TypeAlias

# TODO: Add thresholds for total time today (incl percentage of productive time)

logger = logging.getLogger(__name__)
TIME_OFFSET = timedelta(hours=4)
FALLBACK_CATEGORIES: list[tuple[list[str], dict]] = [
    (
        ["Work"],
        {
            "type": "regex",
            "regex": "Programming|nvim|taxes|Roam|Code",
        },
    ),
    (
        ["Twitter"],
        {
            "type": "regex",
            "regex": r"Twitter|twitter.com|Home / X",
        },
    ),
    (
        ["Youtube"],
        {
            "type": "regex",
            "regex": r"Youtube|youtube.com",
        },
    ),
]


# TODO: move to aw-client utils
# TODO: Get categories from aw-webui export (in the future from server key-val store)
def load_category_toml(path: Path) -> list[tuple[list[str], dict]]:
    with open(path, "r") as f:
        toml = tomlkit.load(f)
    return parse_category_toml(toml, parent=[])


def parse_category_toml(toml: dict, parent: list[str]) -> list[tuple[list[str], dict]]:
    """
    Parse category config file and return a list of categories.
    """
    categories = []
    if "categories" in toml:
        toml = toml["categories"]
    for cat_name, cat in toml.items():
        if isinstance(cat, dict):
            categories += parse_category_toml(cat, parent=parent + [cat_name])
        else:
            if cat_name == "$re":
                categories.append((parent, {"type": "regex", "regex": cat}))
            else:
                categories.append(
                    (parent + [cat_name], {"type": "regex", "regex": cat})
                )
    # create parent category with no rule if $re not given
    if parent and parent not in (c for c, _ in categories):
        categories.append((parent, {"type": "none"}))
    return sorted(categories)


def test_parse_category_toml():
    """
    Test parsing of category config file.
    """
    # Example category config file:
    config = """
    [categories]
        [categories.Media]
        Music = '[Ss]potify|[Ss]ound[Cc]loud|Mixxx|Shazam'
            [categories.Media.Games]
            '$re' = 'Video Games'
            Steam = 'Steam'
    """
    categories = parse_category_toml(tomlkit.loads(config), parent=[])

    # Check that "Media" category exists
    assert categories[0][0] == ["Media"]

    # Check that "Games" category exists, and has the correct regex
    assert categories[1][0] == ["Media", "Games"]
    assert categories[1][1]["regex"] == "Video Games"
    assert categories[2][0] == ["Media", "Games", "Steam"]
    assert categories[2][1]["regex"] == "Steam"


CATEGORIES = FALLBACK_CATEGORIES


time_offset = timedelta(hours=4)

aw = aw_client.ActivityWatchClient("aw-notify", testing=False)


def cache_ttl(ttl: Union[timedelta, int]):
    """Decorator that caches the result of a function in-memory, with a given time-to-live."""
    T = TypeVar("T")
    CacheKey: TypeAlias = tuple

    _ttl: timedelta = ttl if isinstance(ttl, timedelta) else timedelta(seconds=ttl)

    def wrapper(func: Callable[..., T]) -> Callable[..., T]:
        last_update: dict[CacheKey, datetime] = defaultdict(
            lambda: datetime(1970, 1, 1, tzinfo=timezone.utc)
        )
        cache: dict[CacheKey, T] = {}

        @wraps(func)
        def _cache_ttl(*args, **kwargs) -> T:
            now = datetime.now(timezone.utc)
            cache_key: CacheKey = (*args, *kwargs.items())
            if now - last_update[cache_key] > _ttl:
                logger.debug(f"Cache expired for {func.__name__}, updating")
                last_update[cache_key] = now
                cache[cache_key] = func(*args, **kwargs)
            return cache[cache_key]

        return _cache_ttl

    return wrapper


@cache_ttl(60)
def get_time(date=None) -> dict[str, timedelta]:
    """
    Returns a dict with the time spent today (or for `date`) for each category.
    """

    if date is None:
        date = datetime.now(timezone.utc)
    date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    timeperiods = [
        (
            date + time_offset,
            date + time_offset + timedelta(days=1),
        )
    ]

    hostname = aw.get_info().get("hostname", "unknown")
    canonicalQuery = aw_client.queries.canonicalEvents(
        aw_client.queries.DesktopQueryParams(
            bid_window=f"aw-watcher-window_{hostname}",
            bid_afk=f"aw-watcher-afk_{hostname}",
            classes=CATEGORIES,
        )
    )
    query = f"""
    {canonicalQuery}
    duration = sum_durations(events);
    cat_events = sort_by_duration(merge_events_by_keys(events, ["$category"]));
    RETURN = {{"events": events, "duration": duration, "cat_events": cat_events}};
    """

    res = aw.query(query, timeperiods)[0]
    res["cat_events"] += [{"data": {"$category": ["All"]}, "duration": res["duration"]}]

    top_level_only = True

    cat_time: dict[str, timedelta] = defaultdict(timedelta)
    for e in res["cat_events"]:
        if top_level_only:
            cat = e["data"]["$category"][0]
        else:
            cat = ">".join(e["data"]["$category"])
        cat_time[cat] += timedelta(seconds=e["duration"])
    return cat_time


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

# executable path

script_dir = Path(__file__).parent.absolute()
icon_path = script_dir / ".." / "media" / "logo" / "logo.png"


def notify(title: str, msg: str):
    # send a notification to the user

    global notifier
    if notifier is None:
        notifier = DesktopNotifier(
            app_name="AW",
            app_icon=f"file://{icon_path}",
            notification_limit=10,
        )

    logger.info(f'Showing: "{title} - {msg}"')
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

    def __init__(
        self,
        category: str,
        thresholds: list[timedelta],
        label: Optional[str] = None,
        positive=False,
    ):
        self.category = category
        self.label = label or category or "All"
        self.thresholds = thresholds
        self.max_triggered: timedelta = timedelta()
        self.time_spent = timedelta()
        self.last_check = datetime(1970, 1, 1, tzinfo=timezone.utc)

        # wether the alert is "positive"
        # i.e. if the activity should be encouraged ("goal reached!")
        # if not, assume neutral ("time spent")
        self.positive = positive

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
            self.time_spent = get_time().get(self.category, timedelta())
            self.last_check = now
        else:
            pass
            # logger.debug("Not updating, too soon")

    def check(self, silent=False):
        """Check if thresholds have been reached"""
        for thres in sorted(self.thresholds_untriggered, reverse=True):
            if thres <= self.time_spent:
                # threshold reached
                self.max_triggered = thres
                # TODO: use more general, or configurable, language for the notification
                #       as each thres isn't necessarily a "goal" nor a "limit" being hit
                if not silent:
                    thres_str = to_hms(thres)
                    spent_str = to_hms(self.time_spent)
                    notify(
                        "Goal reached!" if self.positive else "Time spent",
                        f"{self.label}: {thres_str}"
                        + (f"  ({spent_str})" if thres_str != spent_str else ""),
                    )
                break

    def status(self) -> str:
        return f"""{self.label}: {to_hms(self.time_spent)}"""
        # (time to thres: {to_hms(self.time_to_next_threshold)})
        # triggered: {self.max_triggered}"""


def test_category_alert():
    catalert = CategoryAlert("Work", [td15min, td30min, td1h, td2h, td4h])
    catalert.update()
    catalert.check()


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enables verbose mode.")
def main(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)5s] %(message)s"
        + ("  (%(name)s.%(funcName)s:%(lineno)d)" if verbose else ""),
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    AW_CATEGORY_PATH = os.environ.get("AW_CATEGORY_PATH", None)
    if AW_CATEGORY_PATH:
        global CATEGORIES
        CATEGORIES = load_category_toml(Path(AW_CATEGORY_PATH))
        logger.info("Loaded categories from $AW_CATEGORY_PATH")


@main.command()
def start():
    """Start the notification service."""
    send_checkin()
    send_checkin_yesterday()
    start_hourly()
    start_new_day()
    threshold_alerts()


def threshold_alerts():
    """
    Checks elapsed time for each category and triggers alerts when thresholds are reached.
    """
    # TODO: make configurable
    alerts = [
        CategoryAlert("All", [td1h, td2h, td4h, td6h, td8h], label="All"),
        CategoryAlert("Twitter", [td15min, td30min, td1h], label="🐦 Twitter"),
        CategoryAlert("Youtube", [td15min, td30min, td1h], label="📺 Youtube"),
        CategoryAlert(
            "Work", [td15min, td30min, td1h, td2h, td4h], label="💼 Work", positive=True
        ),
    ]

    # run through them once to check if any thresholds have been reached
    for alert in alerts:
        alert.update()
        alert.check(silent=True)

    while True:
        for alert in alerts:
            alert.update()
            alert.check()
            status = alert.status()
            if status != getattr(alert, "last_status", None):
                logger.debug(f"New status: {status}")
                alert.last_status = status

        sleep(10)


@main.command()
def checkin():
    """Send a summary notification."""
    send_checkin()


def send_checkin(title="Time today", date=None):
    """
    Sends a summary notification of the day.
    Meant to be sent at a particular time, like at the end of a working day (e.g. 5pm).
    """
    categories = list(
        set(["All", "Uncategorized"] + [">".join(k) for k, _ in CATEGORIES])
    )
    cat_time = get_time(date=date)
    time_spent = [cat_time.get(c, timedelta()) for c in categories]
    top_categories = [
        (c, to_hms(t))
        for c, t in sorted(
            zip(categories, time_spent), key=lambda x: x[1], reverse=True
        )
        if t > 0.02 * cat_time["All"]
    ]
    msg = ""
    msg += "\n".join(f"- {c}: {t}" for c, t in top_categories)
    if msg:
        notify(title, msg)
    else:
        logger.debug("No time spent")


def send_checkin_yesterday():
    """Send a summary notification of yesterday, using `send_checkin`."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    send_checkin(title="Time yesterday", date=yesterday)


@cache_ttl(60)
def get_active_status() -> Union[bool, None]:
    """
    Get active status by polling latest event in aw-watcher-afk bucket.
    Returns True if user is active/not-afk, False if not.
    On error, like out-of-date event, returns None.
    """

    hostname = aw.get_info().get("hostname", "unknown")
    events = aw.get_events(f"aw-watcher-afk_{hostname}", limit=1)
    logger.debug(events)
    if not events:
        return None
    event = events[0]
    event_end = event.timestamp + event.duration
    if event_end < datetime.now(timezone.utc) - timedelta(minutes=5):
        # event is too old
        logger.warning(
            "AFK event is too old, can't use to reliably determine AFK state"
        )
        return None
    return events[0]["data"]["status"] == "not-afk"


def start_hourly():
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
            try:
                active = get_active_status()
            except Exception as e:
                logger.warning(f"Error getting AFK status: {e}")
                continue
            if active is None:
                logger.warning("Can't determine AFK status, skipping hourly checkin")
                continue
            if not active:
                logger.info("User is AFK, skipping hourly checkin")
                continue

            send_checkin()

    threading.Thread(target=checkin_thread, daemon=True).start()


def start_new_day():
    """
    Start a thread that sends a notification when the user first becomes active (not afk) on a new days (at TIME_OFFSET).
    """

    def new_day_thread():
        last_day = (datetime.now(timezone.utc) - TIME_OFFSET).date()
        while True:
            now = datetime.now(timezone.utc)
            day = (now - TIME_OFFSET).date()
            if day != last_day:
                active = get_active_status()
                if active:
                    logger.info("New day, sending notification")
                    day_of_week = day.strftime("%A")
                    # TODO: Better message
                    #       - summary of yesterday?
                    #       - average time spent per day?
                    notify("New day", f"It is {day_of_week}, {day}")
                    last_day = day
                elif active is None:
                    logger.warning("Can't determine AFK status, skipping new day check")
            else:
                start_of_tomorrow = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                sleep((start_of_tomorrow - now).total_seconds())
            sleep(60)

    threading.Thread(target=new_day_thread, daemon=True).start()


def start_welcome_back():
    """
    Start a thread that sends a notification when the user becomes active after a period of non-activity.
    """
    # TODO


if __name__ == "__main__":
    main()
