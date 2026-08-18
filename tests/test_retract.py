"""Reacting to a payment in the source group undoes it in the target.

A payment is forwarded and booked within seconds of landing, so by the time
anyone can see it should not count, the money is on the books and the copy is
in the group. A reaction on the ORIGINAL undoes both.

The ledger rule still applies and is the fiddly part: the correction has to
POST both totals before anything is committed, because the message being
deleted was itself one of the messages recover_ledgers() reads back.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

CHIMEREV, GAFFER = -1002335630148, -5580596463      # the retractable route
MHLARRY, PICCASO = -1003894781195, -5350880041      # the one that is not
ETHAN, LARRY = f.ADMIN_ID, 7418675217
STRANGER = 999

sent, deleted, user_deleted, dms, failures = [], [], [], [], []
_next_id = [4000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    fail_send = False
    fail_delete = False

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        if self.fail_send:
            raise RuntimeError('send refused')
        _next_id[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text, _next_id[0]))
        return FakeMsg(_next_id[0])

    async def delete_message(self, chat_id, message_id):
        if self.fail_delete:
            raise RuntimeError("message can't be deleted for everyone")
        deleted.append((chat_id, message_id))
        return True

    async def set_message_reaction(self, *a, **k):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None

NOW = datetime(2026, 8, 3, 3, 47, tzinfo=timezone.utc)
PAYMENT = 'You received $15.00 from Gabriel W.\n03:35 AM - 03 Aug 2026'


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset(opening=(100.0, 20.0)):
    sent.clear(); deleted.clear(); user_deleted.clear(); dms.clear()
    f._ledger.clear(); f._delivered.clear(); f._seen_messages.clear()
    f.bot.fail_send = f.bot.fail_delete = False
    if opening:
        f.ledger_commit(GAFFER, opening)
        f.ledger_commit(PICCASO, opening)


async def forward(source=CHIMEREV, mid=500, text=PAYMENT):
    await f.process_incoming(source, text, 'test', from_bot=True, sent_at=NOW,
                             source_msg_id=mid)


def totals_posts(chat):
    return [t for c, t, _ in sent
            if c == chat and 'Total In' in t and 'Total Out' in t]


class FakeEntity:
    def __init__(self, cid):
        self.id, self.title, self.username = cid, str(cid), None


class Sender:
    def __init__(self, uid):
        self.id = uid


class TeleMsg:
    """Defaults to being FROM the bot, since that is what recover_one_ledger
    accepts - only the bot's own posts carry trustworthy totals."""

    def __init__(self, mid, text, sender_id=111222):
        self.id, self.raw_text = mid, text
        self.date = NOW
        self._sender = Sender(sender_id)

    async def get_sender(self):
        return self._sender


class FakeClient:
    """Stands in for the userbot when the in-memory record is gone."""

    def __init__(self, source=None, history=None, resolvable=True,
                 can_delete=True):
        self.source = source or {}
        self.history = history or {}
        self.resolvable = resolvable
        self.can_delete = can_delete

    async def get_entity(self, cid):
        if not self.resolvable:
            raise ValueError('no entity')
        return FakeEntity(cid)

    async def get_messages(self, entity, ids=None):
        return [self.source.get(ids[0])]

    def iter_messages(self, entity, limit=None):
        async def gen():
            for m in self.history.get(entity.id, [])[:limit]:
                yield m
        return gen()

    async def delete_messages(self, entity, ids):
        if not self.can_delete:
            raise RuntimeError('not an admin here')
        user_deleted.append((entity.id, ids[0]))
        return True


async def main():
    # -- 1. the ordinary retraction ------------------------------------------
    reset()
    await forward()
    check('the payment is forwarded', any(c == GAFFER for c, _, _ in sent), str(sent))
    check('and booked', f.ledger_snapshot(GAFFER)[0] == 115.0,
          str(f.ledger_snapshot(GAFFER)))
    copy_id = [i for c, _, i in sent if c == GAFFER][0]

    sent.clear()
    did = await f.retract_payment(CHIMEREV, 500, ETHAN)
    check('the reaction retracts it', did is True)
    check('Total In is back where it started', f.ledger_snapshot(GAFFER)[0] == 100.0,
          str(f.ledger_snapshot(GAFFER)))
    check('Total Out is untouched', f.ledger_snapshot(GAFFER)[1] == 20.0,
          str(f.ledger_snapshot(GAFFER)))
    check('the forwarded copy is deleted', deleted == [(GAFFER, copy_id)], str(deleted))
    check('a correction carrying BOTH totals is posted',
          len(totals_posts(GAFFER)) == 1, str(sent))
    check('the correction names the amount',
          any('15.00' in t for t in totals_posts(GAFFER)), str(totals_posts(GAFFER)))
    check('and reads exactly like /add -15',
          any(t.startswith('✏️ Total In adjusted by -15.00$')
              for t in totals_posts(GAFFER)), str(totals_posts(GAFFER)))

    # -- 2. reacting twice must not deduct twice -----------------------------
    again = await f.retract_payment(CHIMEREV, 500, ETHAN)
    check('a second reaction does nothing', again is False)
    check('and the books do not move again', f.ledger_snapshot(GAFFER)[0] == 100.0,
          str(f.ledger_snapshot(GAFFER)))

    # -- 3. only Ethan and Larry ---------------------------------------------
    reset()
    await forward(mid=501)
    sent.clear()
    did = await f.retract_payment(CHIMEREV, 501, STRANGER)
    check('a stranger cannot retract', did is False)
    check('nothing was deducted', f.ledger_snapshot(GAFFER)[0] == 115.0,
          str(f.ledger_snapshot(GAFFER)))
    check('and nothing was deleted', deleted == [], str(deleted))
    check('Larry can retract', await f.retract_payment(CHIMEREV, 501, LARRY) is True)

    # -- 4. the OTHER route is out of scope ----------------------------------
    reset()
    await forward(source=MHLARRY, mid=502)
    check('it still forwards normally', any(c == PICCASO for c, _, _ in sent), str(sent))
    sent.clear()
    did = await f.retract_payment(MHLARRY, 502, ETHAN)
    check('reacting in MH X LARRY retracts nothing', did is False)
    check('PICCASO keeps the payment', f.ledger_snapshot(PICCASO)[0] == 115.0,
          str(f.ledger_snapshot(PICCASO)))
    check('and nothing is deleted there', deleted == [], str(deleted))

    # -- 5. a message we never forwarded -------------------------------------
    reset()
    did = await f.retract_payment(CHIMEREV, 777, ETHAN)
    check('an unknown message retracts nothing', did is False)
    check('and moves no books', f.ledger_snapshot(GAFFER) == (100.0, 20.0),
          str(f.ledger_snapshot(GAFFER)))

    # -- 6. a failed correction must not move the books ----------------------
    reset()
    await forward(mid=503)
    booked = f.ledger_snapshot(GAFFER)
    f.bot.fail_send = True
    await f.retract_payment(CHIMEREV, 503, ETHAN)
    f.bot.fail_send = False
    check('a correction that cannot be posted commits nothing',
          f.ledger_snapshot(GAFFER) == booked, str(f.ledger_snapshot(GAFFER)))
    check('and leaves the copy in place', deleted == [], str(deleted))

    # -- 7. a failed delete still leaves the books right ---------------------
    reset()
    await forward(mid=504)
    sent.clear(); dms.clear()
    f.bot.fail_delete = True
    did = await f.retract_payment(CHIMEREV, 504, ETHAN)
    f.bot.fail_delete = False
    check('a delete that fails still retracts the money', did is True)
    check('the books are corrected anyway', f.ledger_snapshot(GAFFER)[0] == 100.0,
          str(f.ledger_snapshot(GAFFER)))
    check('the corrected totals are still published',
          len(totals_posts(GAFFER)) == 1, str(sent))
    check('and Ethan is told to delete it by hand',
          any('could not be deleted' in t for _, t, _ in dms), str(dms))

    # -- 8. an overshoot is REFUSED, exactly as /add -N refuses one ----------
    # Clamping would invent a figure and then delete the evidence for it.
    reset(opening=(5.0, 0.0))
    await forward(mid=505)                       # +15 on a Total In of 5
    check('booked on top', f.ledger_snapshot(GAFFER)[0] == 20.0,
          str(f.ledger_snapshot(GAFFER)))
    f.ledger_commit(GAFFER, (2.0, 0.0))          # something else took it down
    sent.clear(); deleted.clear()
    await f.retract_payment(CHIMEREV, 505, ETHAN)
    check('a deduction bigger than the balance is refused',
          f.ledger_snapshot(GAFFER) == (2.0, 0.0), str(f.ledger_snapshot(GAFFER)))
    check('it says so in the group',
          any('below zero' in t for c, t, _ in sent if c == GAFFER), str(sent))
    check('it points at /set',
          any('/set in' in t for c, t, _ in sent if c == GAFFER), str(sent))
    check('the copy is left in place', deleted == [], str(deleted))
    check('and no negative is ever published',
          not any('-' in t.split('Total In')[1][:14] for t in totals_posts(GAFFER)),
          str(totals_posts(GAFFER)))

    # -- 9. both id spellings of the source reach it -------------------------
    reset()
    await forward(mid=506)
    check('the -100 spelling is recognised',
          await f.retract_payment(-2335630148, 506, ETHAN) is True)

    # -- 10. after a redeploy: recovered from the group history -------------
    # The in-memory record is gone, which is what a deploy does. The messages
    # in the groups are the durable record, so read them instead.
    reset()
    forwarded_body = ('You received $10.00 from Gabriel W.\n'
                      '02:54 PM - 03 Aug 2026\n'
                      'Total In : 110.00$\nTotal Out: 20.00$')
    source_body = ('You received $10.00 from Gabriel W.\n'
                   '03:08 PM - 03 Aug 2026\n'
                   'Total In : 999.00$\nTotal Out: 999.00$')
    f._delivered.clear()                          # exactly what a restart leaves
    f._active_client = FakeClient(
        source={600: TeleMsg(600, source_body)},
        history={GAFFER: [TeleMsg(7788, forwarded_body),
                          TeleMsg(7700, 'something else entirely')]})
    did = await f.retract_payment(CHIMEREV, 600, ETHAN)
    check('a payment forwarded before the restart is still retractable', did is True)
    check('the copy is found by content, not by id',
          deleted == [(GAFFER, 7788)], str(deleted))
    check('the amount comes off Total In', f.ledger_snapshot(GAFFER)[0] == 90.0,
          str(f.ledger_snapshot(GAFFER)))
    check('and both totals are republished', len(totals_posts(GAFFER)) == 1, str(sent))

    # -- 11. history fallback: the cases that must NOT act -------------------
    reset()
    f._delivered.clear()
    f._active_client = FakeClient(
        source={601: TeleMsg(601, 'just chatting, no payment here')},
        history={GAFFER: [TeleMsg(7789, forwarded_body)]})
    check('a message with no amount retracts nothing',
          await f.retract_payment(CHIMEREV, 601, ETHAN) is False)
    check('and moves no books', f.ledger_snapshot(GAFFER) == (100.0, 20.0),
          str(f.ledger_snapshot(GAFFER)))

    reset()
    f._delivered.clear()
    f._active_client = FakeClient(
        source={602: TeleMsg(602, source_body)},
        history={GAFFER: [TeleMsg(7790, 'You received $99.00 from Someone Else')]})
    check('no matching copy in the target retracts nothing',
          await f.retract_payment(CHIMEREV, 602, ETHAN) is False)
    check('and deletes nothing', deleted == [], str(deleted))

    reset()
    f._delivered.clear()
    f._active_client = None
    check('with no userbot it fails quietly',
          await f.retract_payment(CHIMEREV, 603, ETHAN) is False)

    reset()
    f._delivered.clear()
    f._active_client = FakeClient(source={604: TeleMsg(604, source_body)},
                                  history={}, resolvable=False)
    check('an unreadable group retracts nothing',
          await f.retract_payment(CHIMEREV, 604, ETHAN) is False)
    f._active_client = None

    # -- 12. the books must never be subtracted from a guess ----------------
    # An empty ledger means "not loaded yet", not "zero". Getting this wrong
    # wrote 0.00/0.00 into a live group and made that the newest totals message.
    reset(opening=None)                     # exactly what a fresh boot looks like
    f._delivered.clear()
    f._active_client = FakeClient(
        source={700: TeleMsg(700, source_body)},
        history={GAFFER: [TeleMsg(7799, forwarded_body)]})
    did = await f.retract_payment(CHIMEREV, 700, ETHAN)
    check('an unloaded ledger is recovered before subtracting',
          f.ledger_snapshot(GAFFER) == (100.0, 20.0), str(f.ledger_snapshot(GAFFER)))
    check('and the retraction then goes through', did is True)

    reset(opening=None)
    f._delivered.clear()
    # The copy is there and matches by content, but it is not FROM the bot, so
    # recover_one_ledger will not trust its totals - leaving the books unknown.
    f._active_client = FakeClient(
        source={701: TeleMsg(701, source_body)},
        history={GAFFER: [TeleMsg(7801, forwarded_body, sender_id=999)]})
    sent.clear()
    did = await f.retract_payment(CHIMEREV, 701, ETHAN)
    check('with no recoverable totals it refuses outright', did is True)
    check('and never publishes a zeroed ledger',
          not any('Total In : 0.00' in t for t in totals_posts(GAFFER)), str(sent))
    check('nothing is deleted when it refuses', deleted == [], str(deleted))
    check('and Ethan is told why',
          any('not loaded yet' in t for _, t, _ in dms), str(dms))

    # -- 13. deleting a copy the userbot found -------------------------------
    # Its id is only meaningful alongside the entity it was read from, so when
    # the bot token cannot address it the user account must.
    reset()
    f._delivered.clear()
    f.bot.fail_delete = True                # "message to delete not found"
    f._active_client = FakeClient(
        source={702: TeleMsg(702, source_body)},
        history={GAFFER: [TeleMsg(7802, forwarded_body)]})
    did = await f.retract_payment(CHIMEREV, 702, ETHAN)
    f.bot.fail_delete = False
    check('the user account deletes what the bot could not', did is True)
    check('and it used the entity the message came from',
          user_deleted == [(GAFFER, 7802)], str(user_deleted))
    check('so no by-hand warning is sent',
          not any('could not be deleted' in t for _, t, _ in dms), str(dms))

    reset()
    f._delivered.clear()
    f.bot.fail_delete = True
    f._active_client = FakeClient(
        source={703: TeleMsg(703, source_body)},
        history={GAFFER: [TeleMsg(7803, forwarded_body)]}, can_delete=False)
    await f.retract_payment(CHIMEREV, 703, ETHAN)
    f.bot.fail_delete = False
    check('when neither can delete, the books are still right',
          f.ledger_snapshot(GAFFER)[0] == 90.0, str(f.ledger_snapshot(GAFFER)))
    check('and Ethan is asked to remove it by hand',
          any('could not be deleted' in t for _, t, _ in dms), str(dms))
    f._active_client = None

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
