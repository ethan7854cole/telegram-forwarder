"""The forwarded /out must move Total Out, survive a redeploy, and fire milestones."""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
LARRY = 7418675217
sent, reactions, failures = [], [], []
fail_next = [False]


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        if fail_next[0] and 'Group Total' in text:
            raise RuntimeError('simulated send failure')
        sent.append((chat_id, text)); return FakeMsg(7000 + len(sent))
    async def reply_to(self, message, text):
        sent.append((message.chat.id, text)); return FakeMsg(1)
    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id, reaction[0].emoji)); return True


f.bot = FakeBot(); f.USERBOT_SEND = False; f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def reset():
    sent.clear(); reactions.clear(); f._ledger.clear()
    f._seen_messages.clear(); f._pending_cashouts.clear(); fail_next[0] = False


async def open_and_answer(origin, reply_text, mid=1):
    handling = f.CASHOUT_ROUTES[origin]['handling']
    now = datetime.now(timezone.utc)
    await f.observe_cashout(origin, 'CASHOUT REQUEST', 100 + mid, now, user_id=42)
    await f.observe_cashout(handling, reply_text, 200 + mid, now,
                            user_id=77, username='Maynuddin23')
    return handling


async def main():
    # -- the amount lands on Total Out ---------------------------------------
    reset()
    f._ledger[PICCASO] = {'in': 1000.0, 'out': 200.0}
    await open_and_answer(PICCASO, '/out 500')
    check('Total Out moved by the /out amount',
          f.ledger_snapshot(PICCASO) == (1000.0, 700.0), str(f.ledger_snapshot(PICCASO)))
    check('Total In untouched', f.ledger_snapshot(PICCASO)[0] == 1000.0)
    check('the /out instruction still reached the group',
          any(c == PICCASO and t == '/out 500' for c, t in sent), str(sent))
    check('the request was still hearted', len(reactions) == 1)

    # -- the confirmation is in the shape recover_ledgers can read back ------
    confirm = [t for c, t in sent if c == PICCASO and 'Group Total' in t]
    check('a totals block was posted', len(confirm) == 1, str(sent))
    check('it matches the existing /out wording',
          confirm and confirm[0].startswith('📤 Out = -500.00$'), confirm[0] if confirm else '')
    check('a redeploy could recover these exact books',
          f.parse_totals(confirm[0]) == (1000.0, 700.0), str(f.parse_totals(confirm[0])))

    # -- GAFFER books to its own ledger, not PICCASO's -----------------------
    reset()
    f._ledger[GAFFER] = {'in': 50.0, 'out': 10.0}
    await open_and_answer(GAFFER, '/out 40')
    check('GAFFER books to its own ledger', f.ledger_snapshot(GAFFER) == (50.0, 50.0))
    check("PICCASO's ledger untouched", PICCASO not in f._ledger)

    # -- amount formats ------------------------------------------------------
    for i, (text, expect) in enumerate([('/out 1,200.50', 1200.5),
                                        ('/out $75', 75.0),
                                        ('ok /out 30 done', 30.0),
                                        ('/out@mybot 60', 60.0),
                                        ('/out   12.25', 12.25)]):
        reset()
        await open_and_answer(PICCASO, text, mid=i + 10)
        check(f'parses {text!r}', f.ledger_snapshot(PICCASO) == (0.0, expect),
              str(f.ledger_snapshot(PICCASO)))

    # -- a bare /out still forwards and hearts, books nothing ---------------
    reset()
    f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
    await open_and_answer(PICCASO, '/out')
    check('bare /out books nothing', f.ledger_snapshot(PICCASO) == (100.0, 20.0))
    check('bare /out is still forwarded', any(t == '/out' for _, t in sent))
    check('bare /out still hearts the request', len(reactions) == 1)
    check('bare /out posts no totals block',
          not any('Group Total' in t for _, t in sent))

    # -- a failed confirmation must not move the books -----------------------
    reset()
    f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
    fail_next[0] = True
    await open_and_answer(PICCASO, '/out 999')
    check('books do not move when the confirmation fails',
          f.ledger_snapshot(PICCASO) == (100.0, 20.0), str(f.ledger_snapshot(PICCASO)))

    # -- milestones still fire off a cashout --------------------------------
    reset()
    f._ledger[GAFFER] = {'in': 0.0, 'out': 900.0}
    await open_and_answer(GAFFER, '/out 200')
    check('OUT milestone fires off a cashout',
          any('OUT ALERT' in t and '$1,000' in t for _, t in sent), str(sent))

    # -- the manual /out command is untouched --------------------------------
    reset()
    class C:
        def __init__(s, cid): s.id = cid
    class U:
        def __init__(s, uid): s.id = uid
    class M:
        def __init__(s, cid, text, uid):
            s.chat, s.text, s.from_user = C(cid), text, U(uid)
            s.message_id, s.date, s.reply_to_message = 1, None, None
    await f.ledger_command(M(GAFFER, '/out 100', LARRY))
    check('Ethan/Larry manual /out still works', f.ledger_snapshot(GAFFER) == (0.0, 100.0))
    reset()
    await f.ledger_command(M(GAFFER, '/out 100', 999))
    check('a non-admin still cannot move Total Out',
          f.ledger_snapshot(GAFFER) == (0.0, 0.0) and 'Not permitted' in sent[-1][1])

    # -- the booking message must not loop back through the bot -------------
    reset()
    f._ledger[PICCASO] = {'in': 0.0, 'out': 0.0}
    await open_and_answer(PICCASO, '/out 500')
    before = f.ledger_snapshot(PICCASO)
    for chat, text in list(sent):
        await f.observe_cashout(chat, text, 9999, datetime.now(timezone.utc),
                                user_id=111222)          # our own bot id
    check('our own posts cannot re-book or re-open',
          f.ledger_snapshot(PICCASO) == before and not f._pending_cashouts, str(before))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all booking checks passed")


asyncio.run(main())
