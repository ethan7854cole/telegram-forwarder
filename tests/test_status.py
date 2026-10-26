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

sent, dms, clicks, hearts = [], [], [], []


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
        hearts.append((chat_id, message_id))
        return True


class User:
    def __init__(self, username):
        self.username = username


class Button:
    def __init__(self, text, msg, error=None):
        self.text, self.msg, self.error = text, msg, error

    async def click(self):
        """@staffhelper as seen live: Status offers the choices, Completed
        rewrites the request and takes the buttons away."""
        if self.error:
            raise self.error
        clicks.append((self.msg.id, self.text))
        label = self.text.lower()
        if 'status' in label and self.msg.offers:
            self.msg.set_buttons(self.msg.offers)
        elif 'complete' in label and self.msg.obeys:
            self.msg.raw_text = self.msg.raw_text.replace('PENDING', 'COMPLETED')
            self.msg.buttons = None


class UserMsg:
    def __init__(self, mid, text, sender='staffhelper', buttons=('Status',),
                 offers=('✅ Completed', 'Pending', 'Rejected'), error=None,
                 obeys=True):
        self.id = mid
        self.raw_text = text
        self.sender = User(sender)
        self.via_bot = None
        self.offers, self.error, self.obeys = offers, error, obeys
        self.set_buttons(buttons)

    def set_buttons(self, labels):
        self.buttons = ([[Button(b, self, self.error) for b in labels]]
                        if labels else None)


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
f.STATUS_STEP_SECONDS = 0

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def request(tag, amount, status='PENDING'):
    # @staffhelper's shape, as in the screenshot.
    return (f'!! Cashout Request !!\nTag name : {tag}\nAmount : ${amount}.00\n'
            f'Status : {status}')


def reset(history=None):
    sent.clear(); dms.clear(); clicks.clear(); hearts.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._active_client = FakeUserClient(history) if history is not None else None


def status_alerts():
    return [t for c, t in dms if c == ADMIN and 'Status : COMPLETED' in t
            and 'could NOT be' in t]


def completed_dms():
    return [t for _, t in dms if 'COMPLETED SUCCESSFULLY' in t]


async def run_cashout(source, handling, text, mid, out='/out 25', reply=None):
    now = datetime.now(timezone.utc)
    await f.observe_cashout(source, text, mid, now, user_id=42)
    await f.observe_cashout(handling, out, mid + 1, now, user_id=77,
                            username='Maynuddin23', reply_to=reply)


def shown(history, mid):
    return next(m for m in history if m.id == mid).raw_text


async def main():
    PRESSED = [(910, 'Status'), (910, '✅ Completed')]

    # -- 1. the crew /out completes it: Status, then Completed ---------------
    text = request('$Cayce-Parker-2', 25)
    history = [UserMsg(910, text)]
    reset(history)
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('Status is pressed, then Completed', clicks == PRESSED, str(clicks))
    check('the request now reads Status : COMPLETED',
          'Status : COMPLETED' in shown(history, 910), shown(history, 910))
    check('Larry still gets the completed DM', len(completed_dms()) == 1, str(dms))
    check('nobody is alerted', status_alerts() == [], str(dms))
    # 2026-10-26, the user: "instead of reacting click the button".
    check('the button replaces the ❤ - no reaction', hearts == [], str(hearts))
    check('the /out still reaches CHIME PICCASO',
          any(c == PICCASO for c, _ in sent), str(sent))
    check('Total Out is booked', f.ledger_snapshot(PICCASO)[1] == 25.0)

    # -- 2. the stored id is the bot's numbering: found by tag and figure ----
    # In a basic group the id the bot saw may point at a different message for
    # the user account. That message is never pressed.
    other = request('$someone-else', 25)
    history = [UserMsg(910, other), UserMsg(925, text)]
    reset(history)
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('the matching request is marked, not the one at the id',
          [m for m, _ in clicks] == [925, 925], str(clicks))
    check('the one at the id is untouched', 'PENDING' in shown(history, 910))
    check('no alert', status_alerts() == [], str(dms))

    # -- 3. the same customer and figure again: the COMPLETED one is skipped --
    history = [UserMsg(905, request('$Cayce-Parker-2', 25, 'COMPLETED'), buttons=()),
               UserMsg(925, text)]
    reset(history)
    await run_cashout(PICCASO, MHLARRY, text, 999)
    check('a repeat request: the open one is marked',
          [m for m, _ in clicks] == [925, 925], str(clicks))
    check('no alert', status_alerts() == [], str(dms))

    # ...even when the stored id points straight at the old, completed one.
    history = [UserMsg(905, request('$Cayce-Parker-2', 25, 'COMPLETED'), buttons=()),
               UserMsg(925, text)]
    reset(history)
    await run_cashout(PICCASO, MHLARRY, text, 905)
    check('an id pointing at the old completed one still finds the open one',
          [m for m, _ in clicks] == [925, 925], str(clicks))

    # -- 4. two identical OPEN requests: never guessed ------------------------
    reset([UserMsg(950, other), UserMsg(925, text), UserMsg(926, text)])
    await run_cashout(PICCASO, MHLARRY, text, 950)
    check('nothing pressed when two open requests match', clicks == [], str(clicks))
    check('the admin account is told instead', len(status_alerts()) == 1, str(dms))
    check('the completed DM still goes', len(completed_dms()) == 1)

    # -- 5. already COMPLETED by hand: nothing pressed, nobody bothered -------
    reset([UserMsg(910, request('$Cayce-Parker-2', 25, 'COMPLETED'), buttons=())])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('already completed: nothing pressed', clicks == [], str(clicks))
    check('already completed: no alert', status_alerts() == [], str(dms))
    check('already completed: no ❤ either', hearts == [], str(hearts))

    # -- 6. a request a person typed: no button to press, nobody bothered -----
    plain = '!! Cashout Request !!\nTag name : $Cayce-Parker-2\nAmount : 25'
    reset([UserMsg(910, plain, sender='someperson', buttons=())])
    await run_cashout(PICCASO, MHLARRY, plain, 910)
    check('a human request is left alone', clicks == [], str(clicks))
    check('and raises no alert', status_alerts() == [], str(dms))
    check('no button to press, so it is ❤\'d as before',
          hearts == [(PICCASO, 910)], str(hearts))

    # -- 7. no Status button --------------------------------------------------
    reset([UserMsg(910, text, buttons=('Open',))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('no button: nothing pressed', clicks == [])
    alerts = status_alerts()
    check('no button: the admin account is told', len(alerts) == 1, str(dms))
    check('a press that failed falls back to the ❤, so it never looks unpaid',
          hearts == [(PICCASO, 910)], str(hearts))
    if alerts:
        check('the alert says the money side is done', 'booked' in alerts[0], alerts[0])
        check('the alert shows which request', '$Cayce-Parker-2' in alerts[0], alerts[0])
        check('the alert says what to press', 'Status -> Completed' in alerts[0], alerts[0])

    # -- 8. Status offers no Completed ----------------------------------------
    reset([UserMsg(910, text, offers=('Pending',))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('no Completed choice: only Status pressed',
          clicks == [(910, 'Status')], str(clicks))
    alerts = status_alerts()
    check('and the admin account is told', len(alerts) == 1, str(dms))
    if alerts:
        check('saying no Completed choice appeared', 'no "Completed"' in alerts[0], alerts[0])

    # -- 9. Completed pressed but the request never changes -------------------
    reset([UserMsg(910, text, obeys=False)])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('both pressed', clicks == PRESSED, str(clicks))
    alerts = status_alerts()
    check('an unconfirmed press is reported', len(alerts) == 1, str(dms))

    # -- 10. a Completed button already showing is pressed directly -----------
    reset([UserMsg(910, text, buttons=('Completed', 'Pending'))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('Completed already on show: pressed straight away',
          clicks == [(910, 'Completed')], str(clicks))
    check('no alert', status_alerts() == [], str(dms))

    # -- 11. the press fails: told, and the money is unaffected ---------------
    reset([UserMsg(910, text, error=RuntimeError('MESSAGE_ID_INVALID'))])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    alerts = status_alerts()
    check('a failed press is reported', len(alerts) == 1, str(dms))
    if alerts:
        check('with the real error', 'MESSAGE_ID_INVALID' in alerts[0], alerts[0])
    check('the booking stands', f.ledger_snapshot(PICCASO)[1] == 25.0)
    check('the completed DM still goes', len(completed_dms()) == 1)

    # -- 12. @staffhelper not answering the press is still a press ------------
    msg = UserMsg(910, text)
    for row in msg.buttons:
        for button in row:
            real = button.click
            async def slow(real=real):
                await real()
                raise f.BotResponseTimeoutError(None)
            button.click = slow
    reset([msg])
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('a slow @staffhelper raises no alert', status_alerts() == [], str(dms))
    check('and it still gets to COMPLETED', 'COMPLETED' in msg.raw_text, msg.raw_text)

    # -- 13. the user account is down: told -----------------------------------
    reset(None)
    await run_cashout(PICCASO, MHLARRY, text, 910)
    check('no user account: the admin account is told', len(status_alerts()) == 1, str(dms))
    check('and the cashout still completes', len(completed_dms()) == 1)

    # -- 14. CHIME PICCASO only -----------------------------------------------
    reset([UserMsg(910, text)])
    await run_cashout(GAFFER, CHIMEREV, text, 910)
    check('CHIME GAFFER: nothing pressed', clicks == [], str(clicks))
    check('CHIME GAFFER: no alert', status_alerts() == [], str(dms))
    check('CHIME GAFFER: completed as before', len(completed_dms()) == 1)
    check('CHIME GAFFER: still ❤\'d', hearts == [(GAFFER, 910)], str(hearts))

    reset(None)
    await run_cashout(GAFFER, CHIMEREV, text, 910)
    check('CHIME GAFFER with the user account down: still no alert',
          status_alerts() == [], str(dms))

    # -- 15. a request still open is never pressed ----------------------------
    reset([UserMsg(910, text)])
    await f.observe_cashout(PICCASO, text, 910, datetime.now(timezone.utc), user_id=42)
    check('an open request is not pressed', clicks == [], str(clicks))

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("all passed")


asyncio.run(main())
