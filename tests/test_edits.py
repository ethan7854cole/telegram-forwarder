"""Editing a /out onto a message the crew already sent.

This is how a great deal of real traffic answers a cashout, and until
2026-08-09 the bot could not see it at all: `edited_message` was not in
allowed_updates and neither listener registered an edit handler. The request
stayed open, the ❤ never landed, the money was never booked, and the chase
carried on against a cashout that had actually been paid.

Also covers the hold on the "answered without a /out" alert, which only means
anything because the edit is now visible.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, MHLARRY = -5350880041, -1003894781195
CREW, LARRY, ETHAN = 77, 7418675217, 7578145913

sent, dms, reactions = [], [], []
_next_id = [7000]
failures = []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_next_id[0])

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id))
        return True

    async def delete_message(self, chat_id, message_id):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); reactions.clear()
    f._pending_cashouts.clear(); f._seen_messages.clear(); f._ledger.clear()
    f._user_ids['larryyxx'] = LARRY
    f._user_ids['ethannxxxx'] = ETHAN


real_sleep = asyncio.sleep


async def run_watchdog(seconds=0.2):
    async def fast(_): await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


async def open_one(amount=200):
    await f.observe_cashout(PICCASO, f'CASHOUT REQUEST ${amount} for Gabriel W.',
                            901, datetime.now(timezone.utc), user_id=42)
    return f._pending_cashouts[MHLARRY][0]


async def main():
    now = datetime.now(timezone.utc)

    # -- the /out edited onto a message that had none ------------------------
    reset()
    req = await open_one()
    await f.observe_cashout(MHLARRY, 'sending now', 902, now,
                            user_id=CREW, username='Maynuddin23')
    check('the first version does not answer the request',
          MHLARRY in f._pending_cashouts, str(f._pending_cashouts))
    sent.clear()

    await f.observe_cashout(MHLARRY, 'sending now /out 200', 902, now,
                            user_id=CREW, username='Maynuddin23', is_edit=True)
    check('the edited /out is acted on',
          any(c == PICCASO for c, _ in sent), str(sent))
    check('the request is settled by the edit', MHLARRY not in f._pending_cashouts)
    check('the original request is hearted', (PICCASO, 901) in reactions,
          str(reactions))
    check('and the money is booked', f.ledger_snapshot(PICCASO)[1] == 200.0,
          str(f.ledger_snapshot(PICCASO)))

    # -- the SAME edit down both input paths is still one event --------------
    reset()
    req = await open_one()
    await f.observe_cashout(MHLARRY, 'sending', 903, now,
                            user_id=CREW, username='Maynuddin23')
    sent.clear()
    for _ in range(2):                       # Telethon, then the Bot API
        await f.observe_cashout(MHLARRY, 'sending /out 200', 903, now,
                                user_id=CREW, username='Maynuddin23', is_edit=True)
    relayed = [t for c, t in sent
               if c == PICCASO and '/out 200' in t and 'Group Total' not in t]
    check('one edit delivered twice relays once', len(relayed) == 1, str(sent))
    check('and books once', f.ledger_snapshot(PICCASO)[1] == 200.0,
          str(f.ledger_snapshot(PICCASO)))

    # -- editing a /out that ALREADY paid does not pay again -----------------
    # With the request settled and gone, Ethan's edit would otherwise reach
    # force_complete_cashout(), which takes a /out at face value.
    reset()
    await open_one()
    await f.observe_cashout(MHLARRY, '/out 200', 904, now,
                            user_id=CREW, username='Maynuddin23')
    check('the /out was booked once', f.ledger_snapshot(PICCASO)[1] == 200.0)
    sent.clear()
    await f.observe_cashout(MHLARRY, '/out 200 $gabriel-w', 904, now,
                            user_id=ETHAN, username='ethannxxxx', is_edit=True)
    check('editing an already-paid /out books nothing more',
          f.ledger_snapshot(PICCASO)[1] == 200.0, str(f.ledger_snapshot(PICCASO)))
    check('and relays nothing more',
          [t for c, t in sent if c == PICCASO] == [], str(sent))

    # -- an edit never reaches the payment path ------------------------------
    # An edited "You received" must not be forwarded and booked a second time.
    reset()
    before = f.ledger_snapshot(PICCASO)
    await f.observe_cashout(MHLARRY, 'You received $500.00', 905, now,
                            user_id=CREW, username='Maynuddin23', is_edit=True)
    check('an edited payment notification books nothing',
          f.ledger_snapshot(PICCASO) == before, str(f.ledger_snapshot(PICCASO)))

    # -- the hold: an edit inside it means no alert at all -------------------
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], CREW, 'Maynuddin23')
    dms.clear()
    await f.observe_cashout(MHLARRY, 'cashapp is being slow', 906, now,
                            user_id=CREW, username='Maynuddin23')
    check('the alert is held, not sent',
          [t for _, t in dms if 'SOMETHING IS WRONG' in t] == [], str(dms))
    check('and it is armed with a deadline', req['issue_due'] is not None)

    await f.observe_cashout(MHLARRY, 'cashapp is being slow /out 200', 906, now,
                            user_id=CREW, username='Maynuddin23', is_edit=True)
    check('the edited /out settles it', MHLARRY not in f._pending_cashouts)
    check('and no alert is ever sent',
          [t for _, t in dms if 'SOMETHING IS WRONG' in t] == [], str(dms))

    # -- a NEW message carrying the /out needs no edit at all ----------------
    # The hold delays the ALERT, never the /out. A fresh message is acted on
    # the instant it lands, exactly as it always was.
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], CREW, 'Maynuddin23')
    dms.clear(); sent.clear()
    await f.observe_cashout(MHLARRY, 'one sec', 920, now,
                            user_id=CREW, username='Maynuddin23')
    check('the alert is armed by the first message', req['issue_due'] is not None)

    await f.observe_cashout(MHLARRY, '/out 200', 921, now,
                            user_id=CREW, username='Maynuddin23')
    check('a new /out message is processed immediately',
          any(c == PICCASO and '/out 200' in t and 'Group Total' not in t
              for c, t in sent), str(sent))
    check('it settles the request there and then',
          MHLARRY not in f._pending_cashouts)
    check('the money is booked without waiting for the hold',
          f.ledger_snapshot(PICCASO)[1] == 200.0, str(f.ledger_snapshot(PICCASO)))
    check('the request is hearted', (PICCASO, 901) in reactions, str(reactions))
    check('and the armed alert never fires',
          [t for _, t in dms if 'SOMETHING IS WRONG' in t] == [], str(dms))

    # Force the deadline into the past and let the REAL watchdog run. The
    # request is off the queue, so there is nothing left for it to walk - which
    # is what makes the alert unsendable rather than merely not yet due.
    req['issue_due'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    await run_watchdog()
    check('the alert stays unsent even once its deadline has passed',
          [t for _, t in dms if 'SOMETHING IS WRONG' in t] == [], str(dms))
    check('because the settled request is off the queue entirely',
          MHLARRY not in f._pending_cashouts)

    # -- the hold: no edit, so the alert goes ---------------------------------
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], CREW, 'Maynuddin23')
    dms.clear()
    await f.observe_cashout(MHLARRY, 'cashapp is down', 907, now,
                            user_id=CREW, username='Maynuddin23')
    req['issue_due'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    await f.flush_pending_issue(MHLARRY, req)
    alerts = [t for uid, t in dms if 'SOMETHING IS WRONG' in t]
    check('the alert goes once the hold is up', len(alerts) == 2, str(dms))
    check('the crew are not told about it',
          [t for uid, t in dms if uid == CREW] == [], str(dms))

    # ...and only once, however many more messages arrive.
    dms.clear()
    await f.observe_cashout(MHLARRY, 'still down', 908, now,
                            user_id=CREW, username='Maynuddin23')
    req['issue_due'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    await f.flush_pending_issue(MHLARRY, req)
    check('it never repeats',
          [t for _, t in dms if 'SOMETHING IS WRONG' in t] == [], str(dms))

    # -- a second message during the hold does not push it out ---------------
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], CREW, 'Maynuddin23')
    await f.observe_cashout(MHLARRY, 'one moment', 909, now,
                            user_id=CREW, username='Maynuddin23')
    first_deadline = req['issue_due']
    await f.observe_cashout(MHLARRY, 'still looking', 910, now,
                            user_id=CREW, username='Maynuddin23')
    check('the deadline is not pushed back by more chatter',
          req['issue_due'] == first_deadline, str((first_deadline, req['issue_due'])))

    # -- an alert armed during the chase still lands after it stops ----------
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], CREW, 'Maynuddin23')
    await f.observe_cashout(MHLARRY, 'stuck', 911, now,
                            user_id=CREW, username='Maynuddin23')
    req['exhausted'] = True                  # chasing already over
    req['issue_due'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    dms.clear()
    await f.flush_pending_issue(MHLARRY, req)
    check('a held alert is not swallowed when the chase has stopped',
          [t for _, t in dms if 'SOMETHING IS WRONG' in t] != [], str(dms))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all edit checks passed")


asyncio.run(main())
