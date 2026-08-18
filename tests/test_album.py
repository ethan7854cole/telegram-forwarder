"""Several screenshots answering one cashout.

Seen live on 2026-08-09: @MHSUPPORTZONE answered a $200 request in
Chime Rev & out no-7 with TWO screenshots and `/out 200` as the caption, and
only the first picture reached CHIME GAFFER. Telegram sends an album as
separate messages sharing a media_group_id, and only one of them carries the
caption, so copying "the message the /out was on" relayed one and dropped the
rest.

Both orderings matter: the caption normally sits on the FIRST of the album, so
the siblings arrive afterwards - but the parts can also be seen first.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
CREW, LARRY, ETHAN = 77, 7418675217, 7578145913

sent, copies, dms, reactions = [], [], [], []
_next_id = [8000]
failures = []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_next_id[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None):
        _next_id[0] += 1
        copies.append((chat_id, from_chat_id, message_id, caption))
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
    sent.clear(); copies.clear(); dms.clear(); reactions.clear()
    f._pending_cashouts.clear(); f._seen_messages.clear(); f._ledger.clear()
    f._album_parts.clear()
    f._user_ids['larryyxx'] = LARRY


async def open_request(chat=GAFFER, mid=901):
    await f.observe_cashout(chat, '!! Cashout Request !!\nTag name: $Genetta-Dill'
                            '\nAmount: 200', mid, datetime.now(timezone.utc),
                            user_id=42)
    return f._pending_cashouts[CHIMEREV][0]


async def part(message_id, group_id, text=None):
    """One member of an album, posted in the handling group."""
    await f.observe_cashout(CHIMEREV, text, message_id, datetime.now(timezone.utc),
                            user_id=CREW, username='MHSUPPORTZONE',
                            has_media=True, media_group_id=group_id)


def relayed_to_gaffer():
    return [c for c in copies if c[0] == GAFFER]


async def main():
    # -- the live case: caption first, second screenshot after ---------------
    reset()
    await open_request()
    await part(910, 'alb1', '/out 200\nGenetta-Dill')      # the captioned one
    await part(911, 'alb1')                                # the extra one

    got = relayed_to_gaffer()
    check('both screenshots reach the group that asked', len(got) == 2, str(copies))
    check('the first carries the /out as its caption',
          got and got[0][2] == 910 and '/out 200' in (got[0][3] or ''), str(got))
    check('the extra one carries NO caption',
          len(got) > 1 and got[1][2] == 911 and got[1][3] == '', str(got))
    check('the cashout is settled', CHIMEREV not in f._pending_cashouts)
    check('booked once, from the /out figure',
          f.ledger_snapshot(GAFFER)[1] == 200.0, str(f.ledger_snapshot(GAFFER)))
    check('the original request is hearted', (GAFFER, 901) in reactions,
          str(reactions))

    # -- a third and fourth screenshot, still arriving late ------------------
    await part(912, 'alb1')
    await part(913, 'alb1')
    check('later screenshots keep going across', len(relayed_to_gaffer()) == 4,
          str(copies))

    # -- the other ordering: parts first, caption last -----------------------
    reset()
    await open_request(mid=902)
    await part(920, 'alb2')                                # no caption yet
    await part(921, 'alb2')
    check('nothing is relayed before the /out arrives',
          relayed_to_gaffer() == [], str(copies))

    await part(922, 'alb2', '/out 200\nGenetta-Dill')      # the caption, last
    got = relayed_to_gaffer()
    check('the buffered screenshots are flushed after the /out',
          len(got) == 3, str(copies))
    check('the captioned one goes first',
          got and got[0][2] == 922, str(got))
    check('and the earlier parts follow, in order',
          [c[2] for c in got[1:]] == [920, 921], str(got))

    # -- one screenshot on its own is unchanged ------------------------------
    reset()
    await open_request(mid=903)
    await part(930, None, '/out 200\nGenetta-Dill')
    got = relayed_to_gaffer()
    check('a lone screenshot still relays exactly once', len(got) == 1, str(copies))
    check('with the /out as its caption',
          got and '/out 200' in (got[0][3] or ''), str(got))

    # -- album parts belonging to no cashout are not relayed -----------------
    reset()
    await part(940, 'alb3')
    await part(941, 'alb3')
    check('screenshots with nothing open go nowhere', copies == [], str(copies))
    check('and no request is invented', CHIMEREV not in f._pending_cashouts)

    # -- a crew name on a sibling caption never reaches the chime group ------
    # Telegram allows one caption per album, but copy_message keeps whatever is
    # there, so the sibling is copied with an explicitly empty caption.
    reset()
    await open_request(mid=904)
    await part(950, 'alb4', '/out 200\nGenetta-Dill')
    await part(951, 'alb4')
    extra = [c for c in relayed_to_gaffer() if c[2] == 951]
    check('the extra screenshot is copied with an empty caption',
          extra and extra[0][3] == '', str(extra))

    # -- the same part arriving down both input paths is copied once ---------
    reset()
    await open_request(mid=905)
    await part(960, 'alb5', '/out 200\nGenetta-Dill')
    before = len(relayed_to_gaffer())
    await part(961, 'alb5')
    await part(961, 'alb5')                                # the other listener
    check('a duplicated album part is relayed once',
          len(relayed_to_gaffer()) == before + 1, str(copies))

    # -- the parity route behaves the same ------------------------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $75', 906,
                            datetime.now(timezone.utc), user_id=42)
    await f.observe_cashout(MHLARRY, '/out 75', 970, datetime.now(timezone.utc),
                            user_id=CREW, username='Maynuddin23',
                            has_media=True, media_group_id='alb6')
    await f.observe_cashout(MHLARRY, None, 971, datetime.now(timezone.utc),
                            user_id=CREW, username='Maynuddin23',
                            has_media=True, media_group_id='alb6')
    check('the PICCASO route relays the whole album too',
          len([c for c in copies if c[0] == PICCASO]) == 2, str(copies))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all album checks passed")


asyncio.run(main())
