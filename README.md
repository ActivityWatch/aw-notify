aw-notify
=========

A notification service for ActivityWatch.

Still work-in-progress, but it is pretty simple and should work fine.

Sends you notifications:
 - when you've done a certain activity for certain amounts of time
     - "You've been working for 1h today"
     - "You've been on Twitter for 30min today"
 - when the work day is over (e.g. 5pm)
    - "You've spent a total of 3h 21min today. You did Work for 2h 20min (66%)"


## Installation

Install it using `poetry` with `poetry install`.

## Usage

```
$ aw-notify --help
Usage: aw-notify [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  checkin  Sends a summary notification of the day.
  start    Start the notification service.
```

## Limitations

On macOS, you need to run it from a signed bundle to allow access to Notification Center.
