from datetime import datetime, timedelta, timezone
from time import sleep

import aw_client
import aw_client.queries

time_offset = timedelta(hours=4)

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


class DesktopObservable:
    _SLEEP_TIME = 60

    def __init__(self):
        self._observers = []
        self._freezed = False

    def subscribe(self, observer):
        if not self._freezed:
            self._observers.append(observer)

    def freeze(self):
        self._freezed = True
        self._observers = tuple(self._observers)

    def unsubscribe(self, observer):
        if not self._freezed:
            self._observers.remove(observer)

    def alert(self, time: timedelta):
        # alert a user when a threshold has been reached the first time
        # if several thresholds match, only the last/most constrained one is alerted
        # if the threshold is reached again, no alert is sent


        for obs in sorted(self._observers, reverse=True, key=lambda x: x.duration):
            if obs.triggered:
                break
            if time > obs.duration:
                obs.notify()
                obs.trigger()
                break

    @staticmethod
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

    def start(self):
        while True:
            time = self.get_time("Work")
            self.alert(time)
            sleep(self._SLEEP_TIME)

