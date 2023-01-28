"""
Get time spent for different categories in a day, and send notifications to the user on predefined conditions.
"""

import re
from datetime import datetime, timedelta, timezone
from time import sleep

import aw_client
import aw_client.queries
from desktop_notifier import DesktopNotifier

# TODO: Get categories from aw-webui export (in the future from server key-val store)

# regex for productive time
RE_PRODUCTIVE = r"Programming|nvim"


CATEGORIES: list[tuple[list[str], dict]] = [
    (
        ["Work"],
        {
            "type": "regex",
            "regex": RE_PRODUCTIVE,
            "ignore_case": True,
        },
    )
]

time_offset = timedelta(hours=4)


def get_time(category: str) -> timedelta:
    aw = aw_client.ActivityWatchClient("aw-notify", testing=False)

    now = datetime.now(timezone.utc)
    timeperiods = [
        (
            now.replace(hour=0, minute=0, second=0, microsecond=0) + time_offset,
            now,
        )
    ]

    canonicalQuery = aw_client.queries.canonicalEvents(
        aw_client.queries.DesktopQueryParams(
            bid_window="aw-watcher-window_erb-m2.localdomain",
            bid_afk="aw-watcher-afk_erb-m2.localdomain",
            classes=CATEGORIES,
            filter_classes=[["Work"]],
        )
    )
    query = f"""
    {canonicalQuery}
    duration = sum_durations(events);
    RETURN = {{"events": events, "duration": duration}};
    """

    res = aw.query(query, timeperiods)[0]
    time = timedelta(seconds=res["duration"])
    print(f"{category} time: {time}")

    return time


def to_hms(duration: timedelta) -> str:
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    s = ""
    if hours > 0:
        s += f"{hours}h "
    if minutes > 0:
        s += f"{minutes}m "
    if len(s) == 0:
        s += f"{seconds}s "
    return s.strip()


class Threshold:
    # class for thresholds
    # stores the time and message for a threshold
    # and whether the threshold has been triggered before

    triggered: datetime = None

    def __init__(self, duration: timedelta, category: str):
        self.duration = duration
        self.category = "Work"

    def trigger(self):
        if self.triggered is None:
            self.triggered = datetime.now(timezone.utc)
            return True
        return False

    def message(self):
        # translate timedelta into "Xh Ym Zs" format
        hms = to_hms(self.duration)
        return f"You have been doing {self.category} for {hms}."


thresholds = [
    Threshold(timedelta(minutes=15), "Work"),
    Threshold(timedelta(minutes=30), "Work"),
    Threshold(timedelta(minutes=32), "Work"),
    Threshold(timedelta(minutes=33), "Work"),
    Threshold(timedelta(minutes=34), "Work"),
    Threshold(timedelta(minutes=35), "Work"),
    Threshold(timedelta(hours=1), "Work"),
    Threshold(timedelta(hours=2), "Work"),
    Threshold(timedelta(hours=3), "Work"),
    Threshold(timedelta(hours=4), "Work"),
]


def alert(time: timedelta):
    # alert a user when a threshold has been reached the first time
    # if several thresholds match, only the last/most constrained one is alerted
    # if the threshold is reached again, no alert is sent

    for thres in sorted(thresholds, reverse=True, key=lambda x: x.duration):
        if thres.triggered:
            break
        if time > thres.duration:
            notify(thres.message())
            thres.trigger()
            break


notifier: DesktopNotifier = None


def notify(msg: str):
    # send a notification to the user

    global notifier
    if notifier is None:
        notifier = DesktopNotifier(
            app_name="ActivityWatch notify",
            # icon="file:///path/to/icon.png",
            notification_limit=10,
        )

    print(msg)
    notifier.send_sync(title="AW", message=msg)


if __name__ == "__main__":
    while True:
        time = get_time("Work")
        alert(time)
        sleep(60)
