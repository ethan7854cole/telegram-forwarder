"""catch_up() must not re-send what it already delivered, at any ledger state."""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

MHLARRY, PICCASO = -1003894781195, -5350880041
BOTID = 111222
sent, failures = [], []
NOW = datetime.now(timezone.utc)


class FakeEntity:
    def __init__(self, cid): self.id, self.title = cid, str(cid)


class Sender:
    def __init__(self, uid, is_bot=True): self.id, self.bot = uid, is_bot


class Msg:
    def __init__(self, mid, text, minutes_ago, sender):
        self.id, self.raw_text = mid, text
        self.date = NOW - timedelta(minutes=minutes_ago)
        self.media, self._sender = None, sender
    async def get_sender(self): return self._sender


class FakeClient:
    def __init__(self, history): self.history = history
    async def get_entity(self, cid):
        if cid in self.history: return FakeEntity(cid)
        raise ValueError('no entity %s' % cid)
    def iter_messages(self, entity, limit=None):
        async def gen():
            msgs = self.history.get(entity.id, [])      # newest first, like Telethon
            for m in (msgs[:limit] if limit else msgs):
                yield m
        return gen()


class FakeMsgOut:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        sent.append((chat_id, text)); return FakeMsgOut(1)
    async def set_message_reaction(self, *a, **k): return True


f.bot = FakeBot()
f.utils.get_peer_id = lambda e: e.id          # our fakes are not real peers
f.USERBOT_SEND = False
f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def payment(n, total_in, total_out):
    return (f"You received ${n}.00 from Person{n}\n"
            f"0{n}:35 AM - 30 Jul 2026\n"
            f"Total In : {total_in:,.2f}$\n"
            f"Total Out: {total_out:,.2f}$")


def delivered_copy(src_text, ledger_in, ledger_out):
    """Exactly what deliver_to_target() would have posted."""
    return f.rewrite_totals(src_text, ledger_in, ledger_out)


async def run(source_msgs, target_msgs, ledger=None):
    sent.clear(); f._ledger.clear(); f._seen_messages.clear()
    if ledger:
        f._ledger[PICCASO] = ledger
    client = FakeClient({MHLARRY: source_msgs, PICCASO: target_msgs})
    # only the one rule under test, so other routes cannot add noise
    original = dict(f.FORWARD_RULES)
    f.FORWARD_RULES.clear(); f.FORWARD_RULES[MHLARRY] = [PICCASO]
    try:
        await f.catch_up(client)
    finally:
        f.FORWARD_RULES.clear(); f.FORWARD_RULES.update(original)
    return [t for c, t in sent if c == PICCASO]


async def main():
    bot_sender, src_bot = Sender(BOTID), Sender(777)

    # -- the reported bug: everything delivered, ledger has moved on ---------
    srcs = [payment(i, 100.0, 20.0) for i in (3, 2, 1)]          # newest first
    source_msgs = [Msg(300 + i, t, i * 5, src_bot) for i, t in enumerate(srcs)]
    target_msgs = [Msg(900 + i, delivered_copy(t, 1250.0, 340.0), i * 5, bot_sender)
                   for i, t in enumerate(srcs)]
    out = await run(source_msgs, target_msgs, ledger={'in': 1250.0, 'out': 340.0})
    check('nothing re-sent when the ledger has diverged', out == [], f"{len(out)} re-sent")

    # -- and while the ledger still matches (the case that used to work) ----
    target_msgs = [Msg(900 + i, delivered_copy(t, 100.0, 20.0), i * 5, bot_sender)
                   for i, t in enumerate(srcs)]
    out = await run(source_msgs, target_msgs, ledger={'in': 100.0, 'out': 20.0})
    check('nothing re-sent when the ledger matches', out == [], f"{len(out)} re-sent")

    # -- a genuinely missed payment is still delivered ----------------------
    target_msgs = [Msg(900 + i, delivered_copy(t, 1250.0, 340.0), i * 5, bot_sender)
                   for i, t in enumerate(srcs[1:])]              # newest one missing
    out = await run(source_msgs, target_msgs, ledger={'in': 1250.0, 'out': 340.0})
    check('a genuinely missing payment is still forwarded', len(out) == 1, f"{len(out)} sent")
    check('and it is the right one', out and 'Person3' in out[0], str(out))

    # -- two identical payments, only one delivered -------------------------
    twin = payment(5, 100.0, 20.0)
    source_msgs = [Msg(401, twin, 5, src_bot), Msg(400, twin, 10, src_bot)]
    target_msgs = [Msg(901, delivered_copy(twin, 1250.0, 340.0), 5, bot_sender)]
    out = await run(source_msgs, target_msgs, ledger={'in': 1250.0, 'out': 340.0})
    check('duplicates are counted, not deduped', len(out) == 1, f"{len(out)} sent")

    # -- both delivered ------------------------------------------------------
    target_msgs = [Msg(901, delivered_copy(twin, 1250.0, 340.0), 5, bot_sender),
                   Msg(900, delivered_copy(twin, 1250.0, 340.0), 10, bot_sender)]
    out = await run(source_msgs, target_msgs, ledger={'in': 1250.0, 'out': 340.0})
    check('two delivered twins re-send nothing', out == [], f"{len(out)} re-sent")

    # -- anything older than the window is ignored --------------------------
    old = payment(9, 100.0, 20.0)
    source_msgs = [Msg(500, old, f.CATCHUP_LOOKBACK_MINUTES + 60, src_bot)]
    out = await run(source_msgs, [], ledger={'in': 1250.0, 'out': 340.0})
    check('messages outside the lookback are ignored', out == [], f"{len(out)} sent")

    # -- a human post in the source is never swept up -----------------------
    source_msgs = [Msg(600, payment(7, 100.0, 20.0), 5, Sender(555, is_bot=False))]
    out = await run(source_msgs, [], ledger={'in': 1250.0, 'out': 340.0})
    check('human posts are not swept up', out == [], f"{len(out)} sent")

    # -- an unreadable target is skipped, never guessed ---------------------
    sent.clear(); f._ledger.clear(); f._seen_messages.clear()
    client = FakeClient({MHLARRY: [Msg(700, payment(8, 100.0, 20.0), 5, src_bot)]})
    original = dict(f.FORWARD_RULES)
    f.FORWARD_RULES.clear(); f.FORWARD_RULES[MHLARRY] = [PICCASO]
    try:
        await f.catch_up(client)
    finally:
        f.FORWARD_RULES.clear(); f.FORWARD_RULES.update(original)
    check('an unreadable target is skipped, not guessed',
          not [t for c, t in sent if c == PICCASO], str(sent))

    # -- delivered copies credited to the channel, not the bot ---------------
    # Telegram attributes a channel post to the channel itself, and an
    # anonymous admin's post to the group. Attribution must not decide this.
    srcs = [payment(i, 100.0, 20.0) for i in (3, 2, 1)]
    source_msgs = [Msg(300 + i, t, i * 5, src_bot) for i, t in enumerate(srcs)]
    for label, sender in [('the channel itself', Sender(PICCASO, is_bot=False)),
                          ('an anonymous admin', None)]:
        target_msgs = [Msg(900 + i, delivered_copy(t, 1250.0, 340.0), i * 5, sender)
                       for i, t in enumerate(srcs)]
        out = await run(source_msgs, target_msgs, ledger={'in': 1250.0, 'out': 340.0})
        check(f'delivery credited to {label} still counts', out == [], f"{len(out)} re-sent")

    # -- target history deeper than the scan limit --------------------------
    # The three payments sit beyond the readable window. Unknown is not absent.
    filler = [Msg(800 + i, f"chatter {i}", 1, bot_sender)
              for i in range(f.CATCHUP_TARGET_SCAN_LIMIT)]
    buried = [Msg(700 + i, delivered_copy(t, 1250.0, 340.0), 20 + i, bot_sender)
              for i, t in enumerate(srcs)]
    old_srcs = [Msg(300 + i, t, 20 + i, src_bot) for i, t in enumerate(srcs)]
    out = await run(old_srcs, filler + buried, ledger={'in': 1250.0, 'out': 340.0})
    check('nothing re-sent past the readable history', out == [], f"{len(out)} re-sent")

    # -- but a recent one, inside the readable part, still goes -------------
    fresh = payment(6, 100.0, 20.0)
    out = await run([Msg(350, fresh, 0, src_bot)] + old_srcs,
                    filler + buried, ledger={'in': 1250.0, 'out': 340.0})
    check('a recent missing payment is still delivered',
          len(out) == 1 and 'Person6' in out[0], str(len(out)))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all catch-up checks passed")


asyncio.run(main())
