"""A cashout that cannot be marked done must not fail silently.

The ❤ on the original request is the only durable record that a cashout was
actioned - the open requests themselves live in memory and a redeploy wipes
them. So a request that was paid but never marked reads as still outstanding to
anyone scrolling the group, and nobody finds out until someone chases a cashout
that already went.

Placing it can fail for reasons that have nothing to do with this bot's logic:
the bot not being an administrator in the group, or the group restricting which
reactions may be used. This suite pins what happens then - Ethan is told, with
the error, and the money side is reported as already done so nobody pays twice.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, MHLARRY = -5350880041, -1003894781195
ETHAN = f.ADMIN_ID

sent, dms, reactions, user_reactions = [], [], [], []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    react_error = None              # what set_message_reaction raises, if anything

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(7000 + len(sent) + len(dms))

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None):
        sent.append((chat_id, caption))
        return FakeMsg(7900)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        if self.react_error:
            raise RuntimeError(self.react_error)
        reactions.append((chat_id, message_id))
        return True


class FakeEntity:
    pass


class FakeUserClient:
    """The user account. Called directly with a Telethon request object."""
    fail = False

    async def __call__(self, request):
        if self.fail:
            raise RuntimeError('USER_BANNED_IN_CHANNEL')
        user_reactions.append(request)
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset(react_error=None, userbot=False, userbot_fails=False):
    sent.clear(); dms.clear(); reactions.clear(); user_reactions.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f.bot.react_error = react_error
    if userbot:
        client = FakeUserClient()
        client.fail = userbot_fails
        f.USERBOT_SEND = True
        f._active_client = client
    else:
        f.USERBOT_SEND = False
        f._active_client = None


async def _resolve_ok(client, chat_id):
    return FakeEntity()


f._resolve_one = _resolve_ok


def admin_alerts():
    return [t for c, t in dms if c == ETHAN and 'could NOT be marked' in t]


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. the ordinary case: it lands, nobody is bothered -----------------
    reset()
    ok = await f.heart_request(PICCASO, 901)
    check('the heart is placed', ok is True and reactions == [(PICCASO, 901)], str(reactions))
    check('and Ethan is not told about a success', admin_alerts() == [], str(dms))

    # -- 2. the request was deleted - benign, and still no alert ------------
    # Nothing left to mark is not a failure. Alerting here would page Ethan
    # every time somebody tidied a group.
    reset(react_error='Bad Request: message to react not found')
    ok = await f.heart_request(PICCASO, 902)
    check('a deleted request is not an error', ok is False)
    check('and raises no alarm', admin_alerts() == [], str(dms))

    # -- 3. a rights failure, with no user account to fall back on ----------
    reset(react_error='Bad Request: not enough rights to manage reactions')
    ok = await f.heart_request(PICCASO, 903)
    check('a rights failure reports failure', ok is False)
    alerts = admin_alerts()
    check('Ethan is told exactly once', len(alerts) == 1, str(dms))
    if alerts:
        body = alerts[0]
        check('the alert names the group', f.chat_name(PICCASO) in body, body)
        check('the alert carries the message id', '903' in body, body)
        check('the alert carries the real error',
              'not enough rights' in body, body)
        check('it says the money side is already done',
              'booked' in body.lower() and 'done' in body.lower(), body)
        check('it points at the likely cause',
              'administrator' in body.lower(), body)

    # -- 4. the user account saves it - no alert -----------------------------
    # The bot often cannot react on somebody else's message; the account can.
    # That is the normal path, not a problem worth telling anyone about.
    reset(react_error='Bad Request: not enough rights to manage reactions',
          userbot=True)
    ok = await f.heart_request(PICCASO, 904)
    check('the user account places it instead', ok is True)
    check('and it really went through the account', len(user_reactions) == 1)
    check('so Ethan is not told', admin_alerts() == [], str(dms))

    # -- 5. both routes fail - Ethan is told, naming both -------------------
    reset(react_error='Bad Request: not enough rights to manage reactions',
          userbot=True, userbot_fails=True)
    ok = await f.heart_request(PICCASO, 905)
    check('both failing reports failure', ok is False)
    alerts = admin_alerts()
    check('Ethan is told', len(alerts) == 1, str(dms))
    if alerts:
        check('the alert reports the bot error',
              'not enough rights' in alerts[0], alerts[0])
        check('and the user-account error too',
              'USER_BANNED_IN_CHANNEL' in alerts[0], alerts[0])

    # -- 6. a missing heart never blocks the money -------------------------
    # The most important check here. The /out has to be relayed and the totals
    # booked whatever the reaction does; the mark is the last step and the least
    # important one. Failing it must not strand a real cashout.
    reset(react_error='Bad Request: not enough rights to manage reactions')
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 910, now,
                            user_id=42)
    sent.clear()
    await f.observe_cashout(MHLARRY, '/out 25', 911, now,
                            user_id=77, username='Maynuddin23')
    check('the /out still reaches the group that asked',
          any(c == PICCASO for c, _ in sent), str(sent))
    check('the request is still closed', MHLARRY not in f._pending_cashouts)
    check('Total Out is still booked', f.ledger_snapshot(PICCASO)[1] == 25.0,
          str(f.ledger_snapshot(PICCASO)))
    check('and Ethan is told the mark is missing', len(admin_alerts()) == 1, str(dms))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
