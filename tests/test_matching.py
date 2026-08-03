"""A /out settles the request it actually paid.

With one request open there is nothing to get wrong. With two, taking the
oldest blindly settled and hearted the WRONG one: the person who asked was left
with an unmarked request still being chased, and somebody else's - for a
different figure entirely - was marked done without a penny being paid.

Seen live in Chime Rev & out no-7 on 2026-08-04: galactus posted a request, the
crew paid it, and the heart landed on an older request from somebody else.

An explicit reply still wins outright. The amount is what decides otherwise,
and the oldest is still the fallback when the amount settles nothing - because
settling the wrong request can be undone, while dropping a real /out strands a
cashout nobody hears about again.

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
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
CREW = 77

sent, hearts = [], []
_ids = [1000]

# The shape the notification bot actually posts, and the hand-typed shape.
BOT_FORM = '!! Cashout Request !!\nTag name : ${tag}\nAmount : {amt}'
TYPED_FORM = 'CASHOUT REQUEST ${amt} for {tag}'


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _ids[0] += 1
        sent.append((chat_id, text))
        return FakeMsg(_ids[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        return FakeMsg(9999)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        hearts.append((chat_id, message_id))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = False
f._active_client = None

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); hearts.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._cashout_stopped = False


def hearted(mid):
    return any(m == mid for _, m in hearts)


def still_open(handling):
    return [r['origin_msg_id'] for r in f._pending_cashouts.get(handling, [])]


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. the live case, in the bot's own request format ------------------
    for name, form in (('bot format', BOT_FORM), ('typed format', TYPED_FORM)):
        reset()
        await f.observe_cashout(GAFFER, form.format(tag='dana-w', amt=50), 801, now,
                                user_id=11)
        await f.observe_cashout(GAFFER, form.format(tag='galactus', amt=25), 802, now,
                                user_id=22, username='galactus')
        await f.observe_cashout(CHIMEREV, '/out 25', 900, now,
                                user_id=CREW, username='Maynuddin23')
        check(f'{name}: the request that was PAID gets the heart', hearted(802),
              str(hearts))
        check(f'{name}: the unpaid one is not marked done', not hearted(801),
              str(hearts))
        check(f'{name}: and it stays open to be chased', still_open(CHIMEREV) == [801],
              str(still_open(CHIMEREV)))

    # -- 2. an explicit reply still wins, even against the amount -----------
    # If they replied to a specific request, that is what they meant, whatever
    # figure they typed.
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='dana-w', amt=50), 810, now,
                            user_id=11)
    first_copy = f._pending_cashouts[CHIMEREV][0]['message_id']
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='galactus', amt=25), 811, now,
                            user_id=22)
    await f.observe_cashout(CHIMEREV, '/out 25', 901, now, user_id=CREW,
                            username='Maynuddin23', reply_to=first_copy)
    check('an explicit reply beats the amount', hearted(810), str(hearts))
    check('and the other is left open', still_open(CHIMEREV) == [811],
          str(still_open(CHIMEREV)))

    # -- 3. decimals and thousands separators --------------------------------
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='a', amt='1,200'), 820, now,
                            user_id=11)
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='b', amt='37.50'), 821, now,
                            user_id=22)
    await f.observe_cashout(CHIMEREV, '/out 37.50', 902, now, user_id=CREW,
                            username='Maynuddin23')
    check('a decimal amount matches its own request', hearted(821), str(hearts))
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='a', amt='1,200'), 830, now,
                            user_id=11)
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='b', amt='25'), 831, now,
                            user_id=22)
    await f.observe_cashout(CHIMEREV, '/out 1,200', 903, now, user_id=CREW,
                            username='Maynuddin23')
    check('a thousands separator matches too', hearted(830), str(hearts))

    # -- 4. no figure to go on -> the old behaviour, unchanged --------------
    # A bare /out still has to settle something. Dropping it would strand a
    # cashout; the oldest is the best guess available.
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='a', amt=50), 840, now,
                            user_id=11)
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='b', amt=25), 841, now,
                            user_id=22)
    await f.observe_cashout(CHIMEREV, '/out', 904, now, user_id=CREW,
                            username='Maynuddin23')
    check('a bare /out still settles the oldest', hearted(840), str(hearts))

    # An amount matching nothing open falls back the same way.
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='a', amt=50), 850, now,
                            user_id=11)
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='b', amt=25), 851, now,
                            user_id=22)
    await f.observe_cashout(CHIMEREV, '/out 999', 905, now, user_id=CREW,
                            username='Maynuddin23')
    check('an amount matching nothing settles the oldest', hearted(850), str(hearts))
    check('and the /out is never dropped',
          any(c == GAFFER for c, _ in sent), str(sent))

    # -- 5. two requests for the SAME amount --------------------------------
    # Genuinely ambiguous, so the oldest wins - the order they are worked in.
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='a', amt=25), 860, now,
                            user_id=11)
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='b', amt=25), 861, now,
                            user_id=22)
    await f.observe_cashout(CHIMEREV, '/out 25', 906, now, user_id=CREW,
                            username='Maynuddin23')
    check('identical amounts settle oldest first', hearted(860), str(hearts))
    check('leaving the other open', still_open(CHIMEREV) == [861],
          str(still_open(CHIMEREV)))

    # -- 6. one request open behaves exactly as it always did ---------------
    reset()
    await f.observe_cashout(GAFFER, BOT_FORM.format(tag='solo', amt=25), 870, now,
                            user_id=11)
    await f.observe_cashout(CHIMEREV, '/out 25', 907, now, user_id=CREW,
                            username='Maynuddin23')
    check('a single request is settled and hearted', hearted(870), str(hearts))
    check('nothing left open', still_open(CHIMEREV) == [], str(still_open(CHIMEREV)))
    check('and the money is booked', f.ledger_snapshot(GAFFER)[1] == 25.0,
          str(f.ledger_snapshot(GAFFER)))

    # -- 7. a cashtag is never read as the amount ---------------------------
    # "$jenny-buhr" must not be mistaken for a figure, or matching would key off
    # nonsense.
    check('a cashtag is not an amount',
          f.request_amount('Tag name : $jenny-buhr') is None,
          str(f.request_amount('Tag name : $jenny-buhr')))
    check('the Amount line is preferred over the cashtag',
          f.request_amount('Tag name : $jenny-buhr\nAmount : 25') == 25.0,
          str(f.request_amount('Tag name : $jenny-buhr\nAmount : 25')))
    check('a typed request still reads', f.request_amount('CASHOUT REQUEST $80 for x') == 80.0)

    # -- 8. the same fix on the Piccaso route -------------------------------
    reset()
    await f.observe_cashout(PICCASO, BOT_FORM.format(tag='a', amt=500), 880, now,
                            user_id=11)
    await f.observe_cashout(PICCASO, BOT_FORM.format(tag='b', amt=120), 881, now,
                            user_id=22)
    await f.observe_cashout(MHLARRY, '/out 120', 908, now, user_id=CREW,
                            username='Maynuddin23')
    check('both routes match by amount', hearted(881), str(hearts))
    check('and the older one is untouched', not hearted(880), str(hearts))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
