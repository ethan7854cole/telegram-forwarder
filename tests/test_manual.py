"""Ethan and Larry can finish a cashout by hand when nothing is open.

The standing rule is that a /out with no request pending is ordinary traffic
and is left completely alone. That is right for the crew and wrong for Ethan
and Larry, because open requests live in MEMORY: a redeploy wipes them, and a
redeploy is exactly the moment somebody needs to finish a cashout the bot has
forgotten.

Before this, their /out did nothing at all - it sat in the handling group
looking actioned to everyone reading it, while the group that asked was told
nothing and its books never moved. The failure was completely silent, which is
the shape of failure this bot exists to remove.

The crew's /out with nothing open is still ignored, and that is what keeps this
from firing on ordinary chatter.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
ETHAN, LARRY, CREW = 7578145913, 7418675217, 77

sent, dms, copies, hearts = [], [], [], []
_ids = [1000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    fail_send = False

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        if self.fail_send and chat_id < 0:
            raise RuntimeError('CHAT_WRITE_FORBIDDEN')
        _ids[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_ids[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        copies.append((chat_id, from_chat_id, message_id, caption))
        return FakeMsg(9500)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        hearts.append((chat_id, message_id))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = False
f._active_client = None
f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY, 'maynuddin23': CREW})

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); copies.clear(); hearts.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._cashout_stopped = False
    f.bot.fail_send = False


def relayed_to(chat):
    return [t for c, t in sent if c == chat]


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. both routes, both admins, nothing open --------------------------
    for who, uid, uname, handling, target in (
            ('Larry', LARRY, 'Larryyxx', CHIMEREV, GAFFER),
            ('Ethan', ETHAN, 'ethannxxxx', MHLARRY, PICCASO)):
        reset()
        await f.observe_cashout(handling, '/out 25', 900, now,
                                user_id=uid, username=uname)
        check(f'{who}: the /out reaches the group that asked',
              relayed_to(target), str(sent))
        check(f'{who}: Total Out is booked there',
              f.ledger_snapshot(target)[1] == 25.0, str(f.ledger_snapshot(target)))
        check(f'{who}: and both admins have a record of it',
              sorted({c for c, _ in dms}) == sorted([ETHAN, LARRY]), str(dms))

    # -- 2. the crew cannot do this ----------------------------------------
    # Their /out with nothing pending is ordinary traffic, exactly as before.
    # This is what stops the whole thing firing on chatter.
    reset()
    await f.observe_cashout(MHLARRY, '/out 25', 901, now,
                            user_id=CREW, username='Maynuddin23')
    check('the crew /out with nothing open is still ignored', sent == [], str(sent))
    check('no ledger movement', f.ledger_snapshot(PICCASO) == (0.0, 0.0),
          str(f.ledger_snapshot(PICCASO)))
    check('and nobody is DMed', dms == [], str(dms))

    # -- 3. it routes to the right chime group ------------------------------
    # The handling group decides. Sending Chime Rev's cashout to PICCASO would
    # move one group's books while another group displays the figures.
    reset()
    await f.observe_cashout(CHIMEREV, '/out 40', 902, now,
                            user_id=LARRY, username='Larryyxx')
    check('Chime Rev goes to CHIME GAFFER only',
          relayed_to(GAFFER) and not relayed_to(PICCASO), str(sent))
    check('and books GAFFER, not PICCASO',
          f.ledger_snapshot(GAFFER)[1] == 40.0
          and f.ledger_snapshot(PICCASO) == (0.0, 0.0), str(f._ledger))

    # -- 4. an open request still takes precedence --------------------------
    # With something open this is the ORDINARY completion: hearted and closed.
    # The manual path must not shadow it.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 910, now,
                            user_id=42)
    sent.clear(); dms.clear()
    await f.observe_cashout(MHLARRY, '/out 25', 911, now,
                            user_id=ETHAN, username='ethannxxxx')
    check('an open request is settled the ordinary way',
          any(c == PICCASO and m == 910 for c, m in hearts), str(hearts))
    check('the request is closed', MHLARRY not in f._pending_cashouts)
    check('and no "completed by hand" note is sent',
          not any('by hand' in t for _, t in dms), str(dms))

    # -- 5. the screenshot still travels ------------------------------------
    reset()
    await f.observe_cashout(CHIMEREV, '/out 25', 903, now,
                            user_id=LARRY, username='Larryyxx', has_media=True)
    check('a screenshot is copied on the manual route too',
          len(copies) == 1 and copies[0][0] == GAFFER, str(copies))
    check('with the /out as its caption', copies and copies[0][3] == '/out 25',
          str(copies))

    # -- 6. crew names are redacted here as well ----------------------------
    reset()
    await f.observe_cashout(CHIMEREV, '/out 25 $jenny-buhr sent by @Maynuddin23',
                            904, now, user_id=LARRY, username='Larryyxx')
    body = relayed_to(GAFFER)
    check('the manual route redacts too',
          body and 'maynuddin' not in body[0].lower(), str(body))
    check('and rebuilds it the same way',
          body and body[0] == '/out 25\n$jenny-buhr', str(body))

    # -- 7. a /out with no figure moves nothing -----------------------------
    # Same rule as the ordinary path: forward the instruction, invent no amount.
    reset()
    await f.observe_cashout(CHIMEREV, '/out', 905, now,
                            user_id=LARRY, username='Larryyxx')
    check('a bare /out is still relayed', relayed_to(GAFFER), str(sent))
    check('but books nothing', f.ledger_snapshot(GAFFER) == (0.0, 0.0),
          str(f.ledger_snapshot(GAFFER)))
    check('and the note says so',
          any('no figure' in t for _, t in dms), str(dms))

    # -- 8. nothing is booked if the message never landed -------------------
    # The books must never run ahead of what the group can see.
    reset()
    f.bot.fail_send = True
    await f.observe_cashout(CHIMEREV, '/out 40', 906, now,
                            user_id=LARRY, username='Larryyxx')
    check('a failed send books nothing',
          f.ledger_snapshot(GAFFER) == (0.0, 0.0), str(f.ledger_snapshot(GAFFER)))

    # -- 9. ordinary talk from an admin does nothing ------------------------
    reset()
    await f.observe_cashout(MHLARRY, 'morning all', 907, now,
                            user_id=ETHAN, username='ethannxxxx')
    check('an admin chatting settles nothing', sent == [] and dms == [], str(sent + dms))

    # -- 10. and none of it works while the flow is stopped -----------------
    reset()
    f._cashout_stopped = True
    await f.observe_cashout(CHIMEREV, '/out 40', 908, now,
                            user_id=LARRY, username='Larryyxx')
    check('the emergency stop outranks the manual completion',
          not relayed_to(GAFFER) and f.ledger_snapshot(GAFFER) == (0.0, 0.0),
          str(sent))
    f._cashout_stopped = False

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
