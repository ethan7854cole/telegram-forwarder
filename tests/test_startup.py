"""Polling must not start while the outgoing container still holds the token.

Two pollers on one token do NOT duplicate - Telegram gives each update to
exactly one of them, so they SPLIT. The open cashout requests live in the
memory of one container, so a /out delivered to the other finds nothing pending
and is dropped as ordinary traffic: a real cashout goes unanswered and nothing
reports it.

Holding the first poll costs nothing, which is the whole point. Telegram queues
updates server-side and delivers the backlog when polling starts, so a deferred
poll loses no messages - unlike the userbot, which is genuinely deaf while it
waits.
"""
import asyncio
import os
import sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


class Break(BaseException):
    """Escapes run_bot's `except Exception` so the retry loop can be stopped."""


class PollingBot:
    """Records the order of what run_bot does, then lets the loop be broken."""

    def __init__(self):
        self.polls = []

    async def polling(self, **kwargs):
        self.polls.append(kwargs)
        raise RuntimeError('polling stopped')   # caught by run_bot, then it sleeps


async def drive_run_bot(delay):
    """Run run_bot() with a stubbed clock until it has polled once and retried.

    Returns (sleeps, bot) where sleeps is every duration it waited, in order.
    """
    sleeps = []
    stub = PollingBot()
    real_bot, real_sleep, real_delay = f.bot, f.asyncio.sleep, f.BOT_START_DELAY

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        # Break on the first sleep that follows a poll - that is the retry
        # backoff, and by then run_bot has shown everything under test. Keying
        # off the poll rather than a sleep count keeps this correct whether or
        # not there was a start-up hold to record first.
        if stub.polls:
            raise Break()
        await real_sleep(0)

    f.bot, f.BOT_START_DELAY = stub, delay
    f.asyncio.sleep = fake_sleep
    try:
        await f.run_bot()
    except Break:
        pass
    finally:
        f.bot, f.asyncio.sleep, f.BOT_START_DELAY = real_bot, real_sleep, real_delay
    return sleeps, stub


class AdminSpy:
    def __init__(self):
        self.sent = []

    async def __call__(self, text):
        self.sent.append(text)


async def main():
    # -- 1. the hold happens BEFORE the first poll ---------------------------
    sleeps, stub = await drive_run_bot(45)
    check('it waits before polling at all', sleeps and sleeps[0] == 45, str(sleeps))
    check('it does poll once the hold is over', len(stub.polls) == 1, str(stub.polls))
    check('the retry backoff is unchanged', sleeps[1:] == [5], str(sleeps))

    # -- 2. no hold configured, no wait --------------------------------------
    sleeps, stub = await drive_run_bot(0)
    check('with the hold off it polls immediately', sleeps == [5], str(sleeps))
    check('and still polls', len(stub.polls) == 1, str(stub.polls))

    # -- 3. reactions are still asked for by name ----------------------------
    # Not part of this change, but the poll arguments are being touched and a
    # missing message_reaction silently breaks every crew acknowledgement.
    check('message_reaction is still requested',
          stub.polls and 'message_reaction' in stub.polls[0].get('allowed_updates', []),
          str(stub.polls))
    check('message is still requested',
          stub.polls and 'message' in stub.polls[0].get('allowed_updates', []),
          str(stub.polls))

    # -- 4. the hold defaults to the userbot's, one dial for both ------------
    check('the two holds default together',
          f.BOT_START_DELAY == f.TELETHON_START_DELAY,
          str((f.BOT_START_DELAY, f.TELETHON_START_DELAY)))

    # -- 5. the conflict watcher ---------------------------------------------
    spy = AdminSpy()
    real_notify = f.notify_admin
    f.notify_admin = spy
    try:
        watcher = f._ConflictWatcher()

        handled = await watcher.handle(Exception('Bad Request: something else'))
        check('an unrelated error is left to telebot', handled is False)
        check('and is not counted', watcher.conflicts == 0, str(watcher.conflicts))

        handled = await watcher.handle(Exception('Error code: 409'))
        check('a 409 is claimed', handled is True)
        handled = await watcher.handle(
            Exception('terminated by other getUpdates request'))
        check('so is the long-form wording', handled is True)
        check('both were counted', watcher.conflicts == 2, str(watcher.conflicts))
        check('but nobody is woken up yet', spy.sent == [], str(spy.sent))

        while watcher.conflicts < watcher.ALERT_AFTER:
            await watcher.handle(Exception('Error code: 409'))
        check('sustained conflict raises the alarm', len(spy.sent) == 1, str(spy.sent))
        check('it names the dial to turn',
              spy.sent and 'BOT_START_DELAY' in spy.sent[0], str(spy.sent))
        check('it explains the split, not a duplicate',
              spy.sent and 'splits incoming messages' in spy.sent[0], str(spy.sent))

        for _ in range(20):
            await watcher.handle(Exception('Error code: 409'))
        check('the alarm is raised once, not per conflict',
              len(spy.sent) == 1, str(len(spy.sent)))
    finally:
        f.notify_admin = real_notify

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
