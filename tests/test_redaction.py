"""A crew handle must never reach a target group.

CHIME PICCASO, CHIME GAFFER and the two VENMO groups are told figures, never
who moved them. That has to hold for EVERY message the bot sends there - the
/out relay, a forwarded payment, a milestone, a correction, anything added
later - which is why it is guarded at the door in send_group() rather than at
each caller.

The mirror of that matters just as much, and is the easier thing to break: the
handling groups are tagged with those exact handles on every single request,
and the DMs to Ethan and Larry deliberately name the crew member who is stuck.
Redacting either would be a worse bug than the one this fixes.

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

PICCASO, GAFFER = -5350880041, -5580596463
PICCASO_VENMO, GAFFER_VENMO = -5306739731, -5100231154
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
LARRY_VENMO_SRC = -5339749243
ETHAN, LARRY, CREW = 7578145913, 7418675217, 77

sent, dms = [], []
_next = [9000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_next[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        sent.append((chat_id, caption))
        return FakeMsg(9500)

    react_error = None

    async def set_message_reaction(self, *a, **k):
        if self.react_error:
            raise RuntimeError(self.react_error)
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY, 'maynuddin23': CREW})

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._cashout_stopped = False
    f.bot.react_error = None


CREW_WORDS = ('maynuddin23', 'maynuddin233', 'mhsupportzone')
DIRTY = ('You received $15.00 from Gabriel W.\n'
         'handled by @Maynuddin23 and @MHSUPPORTZONE, ask maynuddin233\n'
         'Total In : 100.00$\nTotal Out: 20.00$')


def clean(text):
    low = (text or '').lower()
    return not any(w in low for w in CREW_WORDS)


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. every target group is scrubbed, whatever is sent ----------------
    for chat, name in ((PICCASO, 'CHIME PICCASO'), (GAFFER, 'CHIME GAFFER'),
                       (PICCASO_VENMO, 'PICCASO VENMO'), (GAFFER_VENMO, 'GAFFER VENMO')):
        reset()
        await f.send_group(chat, DIRTY)
        body = sent[0][1] if sent else ''
        check(f'{name} never sees a crew handle', clean(body), body)
        check(f'{name} still gets the message itself',
              'You received $15.00' in body, body)

    # -- 2. the handling groups MUST keep them -----------------------------
    # They are tagged on every request. Stripping here would mean nobody is
    # ever told a cashout is waiting - a far worse bug than the one above.
    for chat, name in ((MHLARRY, 'MH X LARRY GROUP 2'), (CHIMEREV, 'Chime Rev & out no-7')):
        reset()
        await f.send_group(chat, DIRTY)
        body = sent[0][1] if sent else ''
        check(f'{name} keeps the handles', not clean(body), body)

    # -- 3. and so do the private messages ---------------------------------
    # "Somebody is stuck" is useless without saying who.
    reset()
    await f.send_group(ETHAN, DIRTY)
    check('a DM to Ethan keeps the handles', dms and not clean(dms[0][1]), str(dms))

    # -- 4. through the REAL request path ----------------------------------
    # The forward into the handling group must still carry CASHOUT_MENTIONS.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 901, now,
                            user_id=42)
    posted = [t for c, t in sent if c == MHLARRY]
    check('the request forward still tags the crew',
          posted and '@Maynuddin23' in posted[0], str(posted))

    # -- 5. through the REAL payment path ----------------------------------
    # A payment notification is rewritten and forwarded to a target group. If a
    # handle is anywhere in it, it must not survive the trip.
    reset()
    await f.process_incoming(MHLARRY, DIRTY, 'test', from_bot=True, sent_at=now)
    to_target = [t for c, t in sent if c == PICCASO]
    check('a forwarded payment reaches CHIME PICCASO', len(to_target) == 1, str(sent))
    if to_target:
        check('with no crew handle on it', clean(to_target[0]), to_target[0])
        check('and the money still intact',
              '15.00' in to_target[0], to_target[0])

    # -- 6. through the REAL /out relay ------------------------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 910, now,
                            user_id=42)
    sent.clear()
    await f.observe_cashout(MHLARRY, '/out 25 sent by @Maynuddin23', 911, now,
                            user_id=CREW, username='Maynuddin23',
                            full_name='Maynuddin Ahmed')
    relayed = [t for c, t in sent if c == PICCASO]
    check('the /out reaches the chime group', relayed, str(sent))
    if relayed:
        check('with the handle gone', clean(relayed[0]), relayed[0])
        check('and the instruction intact', '/out 25' in relayed[0], relayed[0])
    check('the ledger still moved by the full amount',
          f.ledger_snapshot(PICCASO)[1] == 25.0, str(f.ledger_snapshot(PICCASO)))

    # -- 7. the escalation DM still names who is stuck ---------------------
    # flag_cashout_issue exists to tell Ethan and Larry WHICH crew member has
    # gone quiet. A redacted version of that would be worthless.
    reset()
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $40 for Dana', 920, now,
                            user_id=42)
    await f.observe_cashout(CHIMEREV, 'looking at it', 921, now,
                            user_id=CREW, username='Maynuddin23',
                            full_name='Maynuddin Ahmed')
    dms.clear()
    await f.observe_cashout(CHIMEREV, 'still stuck here', 922, now,
                            user_id=CREW, username='Maynuddin23',
                            full_name='Maynuddin Ahmed')
    admin = [t for c, t in dms if c in (ETHAN, LARRY)]
    check('Ethan and Larry are told who is stuck',
          admin and not clean(admin[0]), str(admin))

    # -- 8. no bot ERROR ever reaches the crew -----------------------------
    # The crew are told one thing and one thing only: that a request is still
    # waiting on a /out. Everything that has gone wrong with the bot is Ethan's
    # and Larry's - the crew cannot act on it, and telling them turns a working
    # chase into noise they learn to ignore.
    def crew_got():
        return [t for c, t in dms if c == CREW]

    # a) the heart cannot be placed
    reset()
    f.bot.react_error = 'Bad Request: not enough rights to manage reactions'
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 930, now,
                            user_id=42)
    await f.observe_cashout(MHLARRY, '/out 25', 931, now,
                            user_id=CREW, username='Maynuddin23')
    check('a failed heart tells Ethan', any(c == ETHAN for c, _ in dms), str(dms))
    check('and tells the crew nothing', crew_got() == [], str(crew_got()))

    # b) something arrives while the flow is stopped
    reset()
    await f.set_cashout_stopped(True, '@ethannxxxx')
    dms.clear()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 932, now,
                            user_id=42)
    check('an ignored request tells Ethan and Larry',
          sorted({c for c, _ in dms}) == sorted([ETHAN, LARRY]), str(dms))
    check('and tells the crew nothing', crew_got() == [], str(crew_got()))
    f._cashout_stopped = False

    # c) a crew member is engaged but stuck
    reset()
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $40 for Dana', 940, now,
                            user_id=42)
    await f.observe_cashout(CHIMEREV, 'on it', 941, now,
                            user_id=CREW, username='Maynuddin23')
    dms.clear()
    await f.observe_cashout(CHIMEREV, 'stuck, cash app is down', 942, now,
                            user_id=CREW, username='Maynuddin23')
    check('a stuck crew member is reported to Ethan and Larry',
          any(c in (ETHAN, LARRY) for c, _ in dms), str(dms))
    check('and never to the crew themselves', crew_got() == [], str(crew_got()))

    # d) the switch being thrown is not their business either
    reset()
    await f.set_cashout_stopped(True, '@larryyxx')
    check('stopping the flow tells only Ethan and Larry',
          sorted({c for c, _ in dms}) == sorted([ETHAN, LARRY]), str(dms))
    check('the crew are not told the bot was stopped', crew_got() == [], str(crew_got()))
    f._cashout_stopped = False

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
