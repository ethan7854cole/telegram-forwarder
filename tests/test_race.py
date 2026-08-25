"""Two copies of one cashout request arriving at the same moment.

The duplicate guard in open_cashout_request() compares against
`_pending_cashouts`, but that entry is not written until AFTER the request has
been posted - and posting is an await on a network call. asyncio runs the next
ready task inside that await, so a second copy arriving in the window checks a
list that is still empty, passes, and posts again.

test_cashout.py 7b covers the same two-different-ids case but awaits the copies
one after the other, so the first is fully recorded before the second is even
started. That is the sequential path, and it always worked. This suite is the
concurrent one, which is what the handling groups actually see: a double send
upstream, or one request reaching both input paths under different ids.

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

sent, dms = [], []
_next_id = [7000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class SlowBot:
    """send_message yields, exactly as a real network round-trip does.

    This is the whole point of the suite. A stub that returns without awaiting
    never lets another task run, so the window the bug lives in does not exist
    and a racing duplicate cannot be reproduced at all.
    """
    fail_sends = False

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        await asyncio.sleep(0.01)            # the round-trip to Telegram
        if self.fail_sends:
            raise RuntimeError('Bad Gateway')
        _next_id[0] += 1
        if chat_id > 0:
            dms.append((chat_id, text))
        else:
            sent.append((chat_id, text, reply_to_message_id))
        return FakeMsg(_next_id[0])

    async def set_message_reaction(self, chat_id, message_id, reaction):
        return True


f.bot = SlowBot()
f.USERBOT_SEND = False
f._active_client = None

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
    f.bot.fail_sends = False


REQUEST = '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 25'


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. the live bug: two copies, different ids, at the same moment ------
    reset()
    await asyncio.gather(
        f.observe_cashout(PICCASO, REQUEST, 801, now, user_id=42),
        f.observe_cashout(PICCASO, REQUEST, 802, now, user_id=42),
    )
    check('two simultaneous copies post ONCE', len(sent) == 1, f"{len(sent)} posts: {sent}")
    check('and leave ONE request open',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1,
          str(f._pending_cashouts.get(MHLARRY, [])))

    # A second ladder is the damage the duplicate post does downstream: two
    # sets of reminders and two things to answer for one cashout.
    open_requests = f._pending_cashouts.get(MHLARRY, [])
    check('so only one escalation ladder is running', len(open_requests) == 1)

    # -- 2. whitespace and case still do not slip past it concurrently -------
    reset()
    await asyncio.gather(
        f.observe_cashout(PICCASO, REQUEST, 803, now, user_id=42),
        f.observe_cashout(PICCASO, REQUEST.upper().replace('\n', '\n  '), 804, now, user_id=42),
    )
    check('a reformatted copy racing the original posts once',
          len(sent) == 1, f"{len(sent)} posts: {sent}")

    # -- 3. three at once, which is what a retrying upstream bot looks like --
    reset()
    await asyncio.gather(*[
        f.observe_cashout(PICCASO, REQUEST, 810 + i, now, user_id=42)
        for i in range(3)
    ])
    check('three simultaneous copies still post once',
          len(sent) == 1, f"{len(sent)} posts: {sent}")

    # -- 4. genuinely different requests must ALL get through ---------------
    # The fix must not turn a burst of real, distinct cashouts into one post.
    reset()
    await asyncio.gather(
        f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 25', 820, now, user_id=42),
        f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $someone-else\nAmount : 40', 821, now, user_id=42),
        f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $third-person\nAmount : 25', 822, now, user_id=42),
    )
    check('three distinct requests all post', len(sent) == 3, f"{len(sent)} posts: {sent}")
    check('and all three are left open',
          len(f._pending_cashouts.get(MHLARRY, [])) == 3)

    # -- 5. the two routes stay independent ---------------------------------
    # Same text, different chime group. These are two real cashouts that happen
    # to read alike, and they go to different handling groups.
    reset()
    await asyncio.gather(
        f.observe_cashout(PICCASO, REQUEST, 830, now, user_id=42),
        f.observe_cashout(GAFFER, REQUEST, 831, now, user_id=42),
    )
    check('the same text on both routes posts to both', len(sent) == 2, str(sent))
    check('one open in each handling group',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1
          and len(f._pending_cashouts.get(CHIMEREV, [])) == 1)

    # -- 5b. the Chime Rev route, on its own ---------------------------------
    # The group the duplicate was actually seen in on 2026-08-04. Section 5
    # proves the two routes do not interfere; this proves the guard holds on
    # THIS one when nothing else is in play, rather than leaving it inferred
    # from the Piccaso case.
    reset()
    await asyncio.gather(*[
        f.observe_cashout(GAFFER, REQUEST, 860 + i, now, user_id=42)
        for i in range(3)
    ])
    check('one request posts ONCE into Chime Rev & out no-7',
          len(sent) == 1 and sent[0][0] == CHIMEREV, f"{len(sent)} posts: {sent}")
    check('and leaves one ladder running there',
          len(f._pending_cashouts.get(CHIMEREV, [])) == 1,
          str(f._pending_cashouts.get(CHIMEREV, [])))
    check('nothing leaked into the other handling group',
          MHLARRY not in f._pending_cashouts, str(f._pending_cashouts))

    # -- 6. a failed send must not block the retry --------------------------
    # Claiming before the post means a post that never happened would otherwise
    # hold the fingerprint and silently swallow the next genuine attempt. The
    # group would be told nothing at all, which is worse than the duplicate.
    reset()
    f.bot.fail_sends = True
    await f.observe_cashout(PICCASO, REQUEST, 840, now, user_id=42)
    check('nothing posted when the send fails', len(sent) == 0, str(sent))
    f.bot.fail_sends = False
    await f.observe_cashout(PICCASO, REQUEST, 841, now, user_id=42)
    check('the retry after a failed send DOES post',
          len(sent) == 1, f"{len(sent)} posts: {sent}")

    # -- 7. the sequential guard still works --------------------------------
    # test_cashout.py 7b in miniature: the fix must not have replaced the
    # existing check, only closed the window in front of it.
    reset()
    await f.observe_cashout(PICCASO, REQUEST, 850, now, user_id=42)
    await f.observe_cashout(PICCASO, REQUEST, 851, now, user_id=42)
    check('sequential duplicates still post once', len(sent) == 1, str(sent))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
