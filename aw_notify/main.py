"""
Get time spent for different categories in a day, and send notifications to the user on predefined conditions.
"""

from datetime import timedelta

from aw_notify.observer import ThresholdObserver
from aw_notify.observable import DesktopObservable


def main():
    desktop_observable = DesktopObservable()

    threshold_observers = (
        ThresholdObserver(desktop_observable, timedelta(minutes=15)),
        ThresholdObserver(desktop_observable, timedelta(minutes=30)),
        ThresholdObserver(desktop_observable, timedelta(minutes=32)),
        ThresholdObserver(desktop_observable, timedelta(minutes=33)),
        ThresholdObserver(desktop_observable, timedelta(minutes=34)),
        ThresholdObserver(desktop_observable, timedelta(minutes=35)),
        ThresholdObserver(desktop_observable, timedelta(hours=1)),
        ThresholdObserver(desktop_observable, timedelta(hours=2)),
        ThresholdObserver(desktop_observable, timedelta(hours=3)),
        ThresholdObserver(desktop_observable, timedelta(hours=4)),
    )

    desktop_observable.freeze()
    desktop_observable.start()


if __name__ == "__main__":
    main()
