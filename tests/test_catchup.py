"""catch_up() must not re-send what it already delivered, at any ledger state."""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
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


class Peer:
    def __init__(self, uid): self.user_id = uid


class Reaction:
    """What Telethon hands back on a message somebody has reacted to."""
    def __init__(self, peers, results=('👍',)):
        self.results = list(results)
        self.recent_reactions = [type('R', (), {'peer_id': Peer(uid)})()
                                 for uid in peers]


class Msg:
    def __init__(self, mid, text, minutes_ago, sender, reactions=None):
        self.id, self.raw_text = mid, text
        self.date = NOW - timedelta(minutes=minutes_ago)
        self.media, self._sender = None, sender
        self.reactions = reactions
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


async def run(source_msgs, target_msgs, ledger=None, source=MHLARRY, target=PICCASO):
    sent.clear(); f._ledger.clear(); f._seen_messages.clear()
    if ledger:
        f._ledger[target] = ledger
    client = FakeClient({source: source_msgs, target: target_msgs})
    # only the one rule under test, so other routes cannot add noise
    original = dict(f.FORWARD_RULES)
    f.FORWARD_RULES.clear(); f.FORWARD_RULES[source] = [target]
    try:
        await f.catch_up(client)
    finally:
        f.FORWARD_RULES.clear(); f.FORWARD_RULES.update(original)
    return [t for c, t in sent if c == target]


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

    # -- a retracted payment must NOT come back on the next deploy ----------
    # Live incident, CHIME GAFFER, 2026-08-10. Two $5 payments were retracted
    # by reacting on the originals; retract_payment() deleted both copies out
    # of the target. Ten minutes later a deploy ran the sweep, found no copies,
    # and re-sent AND re-booked both - +10.00$ onto a ledger that was correct.
    # The reaction still on the original is what says it was taken back.
    CHIMEREV, GAFFER = -1002335630148, -5580596463
    check('the live route is a retract source', CHIMEREV in f.RETRACT_SOURCES)
    ETHAN = 7578145913

    twin5 = payment(5, 100.0, 20.0)
    retracted = [Msg(451, twin5, 12, src_bot, Reaction([ETHAN])),
                 Msg(450, twin5, 40, src_bot, Reaction([ETHAN]))]
    # All the target has left is the two corrections retract_payment() posted.
    corrections = [Msg(951, "✏️ Total In adjusted by -5.00$\n\n"
                            "📊 Group Total:\n➕ Total In : 12,146.64$\n"
                            "➖ Total Out: 7,026.00$", 10, bot_sender),
                   Msg(950, "✏️ Total In adjusted by -5.00$\n\n"
                            "📊 Group Total:\n➕ Total In : 12,151.64$\n"
                            "➖ Total Out: 7,026.00$", 11, bot_sender)]
    out = await run(retracted, corrections, ledger={'in': 12146.64, 'out': 7026.0},
                    source=CHIMEREV, target=GAFFER)
    check('a retracted payment is not re-sent after a deploy', out == [],
          f"{len(out)} re-sent")

    # -- ...and a live payment beside it still goes, exactly once -----------
    live = payment(6, 100.0, 20.0)
    out = await run([Msg(452, live, 5, src_bot)] + retracted, corrections,
                    ledger={'in': 12146.64, 'out': 7026.0},
                    source=CHIMEREV, target=GAFFER)
    check('a genuinely missed payment beside it is still delivered',
          len(out) == 1 and 'Person6' in out[0], str(out))

    # -- a reaction from somebody who cannot retract is not a retraction ----
    out = await run([Msg(453, twin5, 5, src_bot, Reaction([424242]))], [],
                    ledger={'in': 12146.64, 'out': 7026.0},
                    source=CHIMEREV, target=GAFFER)
    check("a stranger's reaction does not hold a payment back", len(out) == 1,
          f"{len(out)} sent")

    # -- a reaction where reacting does NOT retract changes nothing ---------
    # MH X LARRY GROUP 2 is not a retract source; a reaction there is somebody
    # acknowledging a payment, and it must still be forwarded.
    out = await run([Msg(454, twin5, 5, src_bot, Reaction([ETHAN]))], [],
                    ledger={'in': 1250.0, 'out': 340.0})
    check('a reaction outside RETRACT_SOURCES is ignored', len(out) == 1,
          f"{len(out)} sent")

    # -- Telegram not saying who reacted errs towards holding back ----------
    out = await run([Msg(455, twin5, 5, src_bot, Reaction([]))], [],
                    ledger={'in': 12146.64, 'out': 7026.0},
                    source=CHIMEREV, target=GAFFER)
    check('an unattributed reaction is treated as a retraction', out == [],
          f"{len(out)} sent")
    told = [t for c, t in sent if c == f.ADMIN_ID and 'did not say whose' in t]
    check('and Ethan is told a payment was left alone', len(told) == 1, str(sent))
    check('the alert says how to send it if that was wrong',
          told and 'backfill.py' in told[0], str(told))

    # -- an ordinary retraction is quiet ------------------------------------
    await run(retracted, corrections, ledger={'in': 12146.64, 'out': 7026.0},
              source=CHIMEREV, target=GAFFER)
    check('a confirmed retraction raises no alert',
          [t for c, t in sent if c == f.ADMIN_ID] == [], str(sent))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all catch-up checks passed")


asyncio.run(main())
