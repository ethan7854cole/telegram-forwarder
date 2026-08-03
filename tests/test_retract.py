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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

CHIMEREV, GAFFER = -1002335630148, -5580596463      # the retractable route
MHLARRY, PICCASO = -1003894781195, -5350880041      # the one that is not
ETHAN, LARRY = f.ADMIN_ID, 7418675217
STRANGER = 999

sent, deleted, dms, failures = [], [], [], []
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
    sent.clear(); deleted.clear(); dms.clear()
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


class TeleMsg:
    def __init__(self, mid, text):
        self.id, self.raw_text = mid, text


class FakeClient:
    """Stands in for the userbot when the in-memory record is gone."""

    def __init__(self, source=None, history=None, resolvable=True):
        self.source = source or {}
        self.history = history or {}
        self.resolvable = resolvable

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

    # -- 8. the deduction can never publish a negative -----------------------
    reset(opening=(5.0, 0.0))
    await forward(mid=505)                       # +15 on a Total In of 5
    check('booked on top', f.ledger_snapshot(GAFFER)[0] == 20.0,
          str(f.ledger_snapshot(GAFFER)))
    f.ledger_commit(GAFFER, (2.0, 0.0))          # something else took it down
    sent.clear()
    await f.retract_payment(CHIMEREV, 505, ETHAN)
    check('a deduction bigger than the balance clamps at zero',
          f.ledger_snapshot(GAFFER)[0] == 0.0, str(f.ledger_snapshot(GAFFER)))
    check('and never publishes a negative',
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

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
