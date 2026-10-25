"""CHIME PICCASO: a completed cashout presses @staffhelper's "Status" button.

CHIME PICCASO's requests are posted by @staffhelper with a "Status" button under
them, and pressing it is what marks the request completed on their side. The
bot presses it - through the user account, since the Bot API cannot press a
button on another bot's message - when a crew /out completes the request, the
same moment Larry is DMed "completed".

CHIME PICCASO is a basic group, so the stored id may be the bot's numbering
rather than the user account's. The button is only pressed on a @staffhelper
message carrying the request's own tag and figure, and two candidates are
never guessed between.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, MHLARRY = -5350880041, -1003894781195
GAFFER, CHIMEREV = -5580596463, -1002335630148
ADMIN = f.ADMIN_ID

sent, dms, clicks = [], [], []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(7000 + len(sent) + len(dms))

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None):
        sent.append((chat_id, caption))
        return FakeMsg(7900)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        return True


class User:
    def __init__(self, username):
        self.username = username


class Button:
    def __init__(self, text, mid, error=None):
        self.text, self.mid, self.error = text, mid, error

    async def click(self):
        if self.error:
            raise self.error
        clicks.append((self.mid, self.text))


class UserMsg:
    def __init__(self, mid, text, sender='staffhelper', buttons=('📊 Status',),
                 error=None):
        self.id = mid
        self.raw_text = text
        self.sender = User(sender)
        self.via_bot = None
        self.buttons = [[Button(b, mid, error) for b in buttons]] if buttons else None


class FakeUserClient:
    """The user account: CHIME PICCASO's history, as that account numbers it."""
    def __init__(self, history):
        self.history = {m.id: m for m in history}

    async def get_messages(self, entity, ids=None):
        return self.history.get(ids)

    async def iter_messages(self, entity, limit=None):
        for mid in sorted(self.history, reverse=True)[:limit]:
            yield self.history[mid]


async def _resolve_ok(client, chat_id):
    return object()


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = False
f._resolve_one = _resolve_ok

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def request(tag, amount):
    return f'!! Cashout Request !!\nTag name : {tag}\nAmount : {amount}'


def reset(history=None):
    sent.clear(); dms.clear(); clicks.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._active_client = FakeUserClient(history) if history is not None else None


def status_alerts():
    return [t for c, t in dms if c == ADMIN and 'Status' in t and 'NOT be pressed' in t]


def completed_dms():
    return [t for _, t in dms if 'COMPLETED SUCCESSFULLY' in t]


async def run_cashout(source, handling, text, mid, out='/out 25', reply=None):
    now = datetime.now(timezone.utc)
    await f.observe_cashout(source, text, mid, now, user_id=42)
    await f.observe_cashout(handling, out, mid + 1, now, user_id=77,
                            username='Maynuddin23', reply_to=reply)


async def main():
    # -- 1. the crew /out completes it: Status is pressed --------------------
    text = request('$jenny-buhr', 25)
    reset([UserMsg(910, text)])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('Status is pressed on the request', clicks == [(910, '📊 Status')], str(clicks))
    check('Larry still gets the completed DM', len(completed_dms()) == 1, str(dms))
    check('nobody is alerted', status_alerts() == [], str(dms))
    check('the /out still reaches CHIME PICCASO',
          any(c == PICCASO for c, _ in sent), str(sent))
    check('Total Out is booked', f.ledger_snapshot(PICCASO)[1] == 25.0)

    # -- 2. the stored id is the bot's numbering: found by tag and figure ----
    # In a basic group the id the bot saw may point at a different message for
    # the user account. That message is never pressed.
    other = request('$someone-else', 25)
    reset([UserMsg(910, other), UserMsg(925, text)])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('the matching request is pressed, not the one at the id',
          clicks == [(925, '📊 Status')], str(clicks))
    check('no alert', status_alerts() == [], str(dms))

    # -- 3. two identical requests: never guessed -----------------------------
    reset([UserMsg(950, other), UserMsg(925, text), UserMsg(926, text)])
    await run_cashout(PICCASO, MHLARRY, text, 950)
    check('nothing pressed when two requests match', clicks == [], str(clicks))
    check('the admin account is told instead', len(status_alerts()) == 1, str(dms))
    check('the completed DM still goes', len(completed_dms()) == 1)

    # -- 4. a request a person typed: no button to press, nobody bothered -----
    reset([UserMsg(910, text, sender='someperson', buttons=())])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('a human request is left alone', clicks == [], str(clicks))
    check('and raises no alert', status_alerts() == [], str(dms))

    # -- 5. @staffhelper's request with no Status button ----------------------
    reset([UserMsg(910, text, buttons=('Open',))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('no button: nothing pressed', clicks == [])
    alerts = status_alerts()
    check('no button: the admin account is told', len(alerts) == 1, str(dms))
    if alerts:
        check('the alert says the money side is done', 'booked' in alerts[0], alerts[0])
        check('the alert shows which request', '$jenny-buhr' in alerts[0], alerts[0])

    # -- 6. the press fails: told, and the money is unaffected ----------------
    reset([UserMsg(910, text, error=RuntimeError('MESSAGE_ID_INVALID'))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    alerts = status_alerts()
    check('a failed press is reported', len(alerts) == 1, str(dms))
    if alerts:
        check('with the real error', 'MESSAGE_ID_INVALID' in alerts[0], alerts[0])
    check('the booking stands', f.ledger_snapshot(PICCASO)[1] == 25.0)
    check('the completed DM still goes', len(completed_dms()) == 1)

    # -- 7. @staffhelper not answering the press is still a press -------------
    reset([UserMsg(910, text, error=f.BotResponseTimeoutError(None))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('a slow @staffhelper raises no alert', status_alerts() == [], str(dms))

    # -- 8. the user account is down: told -----------------------------------
    reset(None)
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('no user account: the admin account is told', len(status_alerts()) == 1, str(dms))
    check('and the cashout still completes', len(completed_dms()) == 1)

    # -- 9. CHIME PICCASO only ------------------------------------------------
    reset([UserMsg(910, text)])
    await run_cashout(GAFFER, CHIMEREV, text, 910)
    check('CHIME GAFFER: nothing pressed', clicks == [], str(clicks))
    check('CHIME GAFFER: no alert', status_alerts() == [], str(dms))
    check('CHIME GAFFER: completed as before', len(completed_dms()) == 1)

    reset(None)
    await run_cashout(GAFFER, CHIMEREV, text, 910)
    check('CHIME GAFFER with the user account down: still no alert',
          status_alerts() == [], str(dms))

    # -- 10. a request still open is never pressed -----------------------------
    reset([UserMsg(910, text)])
    await f.observe_cashout(PICCASO, text, 910, datetime.now(timezone.utc), user_id=42)
    check('an open request is not pressed', clicks == [], str(clicks))

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("all passed")


asyncio.run(main())
