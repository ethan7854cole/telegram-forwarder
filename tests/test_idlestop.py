"""The "no payments" prompt stops once a group has been quiet 4 hours.

Asked for on 2026-10-14. At the 90-minute spacing that is two prompts, at 1h30
and 3h; the one that would fall at 4h30 is never sent, however long the
silence goes on. A payment restarts the clock and the prompts with it.
"""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

GAFFER = -5580596463
sent, failures = [], []
real_sleep = asyncio.sleep


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        sent.append((chat_id, text)); return FakeMsg(1)


f.bot = FakeBot(); f.USERBOT_SEND = False; f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


async def run_watchdog(seconds=0.25):
    async def fast(_):
        await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.idle_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


def quiet_for(minutes, sent_so_far=0):
    sent.clear(); f._idle_state.clear()
    f._idle_slot(GAFFER)
    f._idle_state[GAFFER].update(
        since=datetime.now(timezone.utc) - timedelta(minutes=minutes),
        sent=sent_so_far)


def prompts():
    return [t for c, t in sent if c == GAFFER]


async def main():
    check('the shipped limit is 4 hours', f.IDLE_STOP_MINUTES == 240,
          str(f.IDLE_STOP_MINUTES))
    check('at 90-minute spacing', f.IDLE_ALERT_MINUTES == 90, str(f.IDLE_ALERT_MINUTES))

    quiet_for(95)
    await run_watchdog()
    check('first prompt at 1h30', len(prompts()) == 1, str(prompts()))
    check('saying 1 hour 30 minutes',
          prompts() and '1 hour 30 minutes' in prompts()[0], str(prompts()))

    quiet_for(185, sent_so_far=1)
    await run_watchdog()
    check('second prompt at 3h', len(prompts()) == 1 and '3 hours' in prompts()[0],
          str(prompts()))

    quiet_for(275, sent_so_far=2)
    await run_watchdog()
    check('nothing at 4h30', prompts() == [], str(prompts()))

    quiet_for(24 * 60, sent_so_far=2)
    await run_watchdog()
    check('nor a whole day later', prompts() == [], str(prompts()))

    # Silent since boot with no prompt sent yet: the backlog never floods past
    # the limit - one prompt per pass, and none beyond 3h.
    quiet_for(24 * 60, sent_so_far=0)
    await run_watchdog(0.5)
    check('a long silence from scratch sends at most the two',
          len(prompts()) == 2, str(prompts()))

    # A payment starts it all again.
    quiet_for(275, sent_so_far=2)
    await f.note_payment(GAFFER)
    f._idle_state[GAFFER]['since'] -= timedelta(minutes=95)
    await run_watchdog()
    check('after a payment the prompts come back', len(prompts()) == 1, str(prompts()))

    # 0 switches the limit off.
    saved, f.IDLE_STOP_MINUTES = f.IDLE_STOP_MINUTES, 0
    try:
        quiet_for(275, sent_so_far=2)
        await run_watchdog()
        check('IDLE_STOP_MINUTES=0 keeps asking', len(prompts()) == 1, str(prompts()))
    finally:
        f.IDLE_STOP_MINUTES = saved

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print('all passed')


asyncio.run(main())
