from datetime import datetime, timedelta, timezone

import aw_client
import aw_client.queries
from desktop_notifier import DesktopNotifier

from aw_notify.observable import DesktopObservable
from aw_notify import utils 

notifier: DesktopNotifier = None

class ThresholdObserver:
    # class for thresholds
    # stores the time and message for a threshold
    # and whether the threshold has been triggered before

    triggered: datetime = None

    def __init__(self, observable: DesktopObservable, duration: timedelta, category: str = "Work"):
        observable.subscribe(self)

        self.duration = duration
        self.category = category

    def trigger(self):
        if self.triggered is None:
            self.triggered = datetime.now(timezone.utc)
            return True
        return False

    def message(self):
        # translate timedelta into "Xh Ym Zs" format
        hms = utils.to_hms(self.duration)
        return f"You have been doing {self.category} for {hms}."


    def notify(self, observable: DesktopObservable):
        # send a notification to the user

        global notifier
        if notifier is None:
            notifier = DesktopNotifier(
                app_name="ActivityWatch notify",
                # icon="file:///path/to/icon.png",
                notification_limit=10,
            )

        msg = self.message()
        print(msg)
        notifier.send_sync(title="AW", message=msg)
