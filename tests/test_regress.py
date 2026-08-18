"""Existing payment + ledger behaviour must be untouched by the cashout work."""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
sent = []
failures = []


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        sent.append((chat_id, text)); return FakeMsg(1)
    async def reply_to(self, message, text):
        sent.append((message.chat.id, text)); return FakeMsg(1)
    async def set_message_reaction(self, *a, **k): return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def reset():
    sent.clear(); f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()


class U:
    def __init__(self, uid, username=None, is_bot=False):
        self.id, self.username, self.is_bot = uid, username, is_bot


class C:
    def __init__(self, cid): self.id = cid


class M:
    def __init__(self, cid, text, uid, mid=1):
        self.chat, self.text, self.from_user = C(cid), text, U(uid)
        self.message_id, self.date, self.reply_to_message = mid, None, None


async def main():
    now = datetime.now(timezone.utc)

    # -- payment forwarding still works, ledger opens from the source totals --
    reset()
    body = 'You received $15.00 from Gabriel W.\n03:35 AM - 30 Jul 2026\nTotal In: 100.00\nTotal Out: 20.00'
    await f.process_incoming(MHLARRY, body, 'test', from_bot=True, sent_at=now)
    check('payment forwarded to its target', len(sent) == 1 and sent[0][0] == PICCASO, str(sent))
    check('ledger opened from source totals', f.ledger_snapshot(PICCASO) == (100.0, 20.0),
          str(f.ledger_snapshot(PICCASO)))

    # second payment adds to Total In
    await f.process_incoming(MHLARRY, 'You received $25.00 from X\nTotal In: 999\nTotal Out: 999',
                             'test', from_bot=True, sent_at=now)
    check('second payment adds to Total In', f.ledger_snapshot(PICCASO) == (125.0, 20.0),
          str(f.ledger_snapshot(PICCASO)))
    check('target sees the ledger, not the source figures',
          'Total In: 125.00' in sent[-1][1], sent[-1][1])

    # -- non-keyword traffic still ignored -----------------------------------
    reset()
    await f.process_incoming(MHLARRY, 'hello team', 'test', from_bot=True, sent_at=now)
    check('non-keyword message not forwarded', sent == [])

    # -- BOT_ONLY_SOURCES still blocks humans --------------------------------
    reset()
    await f.process_incoming(CHIMEREV, 'You received $5.00', 'test', from_bot=False, sent_at=now)
    check('human blocked in a bot-only source', sent == [])

    # -- /out ledger command in a target group is unaffected -----------------
    reset()
    await f.ledger_command(M(GAFFER, '/out 100', 7418675217))
    check('/out still books to Total Out in a chime group',
          f.ledger_snapshot(GAFFER) == (0.0, 100.0), str(f.ledger_snapshot(GAFFER)))
    check('/out opened no cashout request', not f._pending_cashouts)

    # -- /add still works ----------------------------------------------------
    reset()
    await f.ledger_command(M(GAFFER, '/add 250', 7418675217))
    check('/add still books to Total In', f.ledger_snapshot(GAFFER) == (250.0, 0.0))

    # -- a non-admin is still refused ----------------------------------------
    reset()
    await f.ledger_command(M(GAFFER, '/add 999', 12345))
    check('non-admin still refused', f.ledger_snapshot(GAFFER) == (0.0, 0.0)
          and 'Not permitted' in sent[-1][1])

    # -- /set still corrects -------------------------------------------------
    reset()
    await f.ledger_set_command(M(GAFFER, '/set in 800', 7418675217))
    check('/set still overwrites a column', f.ledger_snapshot(GAFFER) == (800.0, 0.0))

    # -- watched chat list now covers both ends of a cashout route -----------
    chats = f._configured_source_chats()
    check('all four payment sources still watched',
          all(c in chats for c in f.FORWARD_RULES), str(chats))
    check('chime groups now watched too', PICCASO in chats and GAFFER in chats, str(chats))
    check('no duplicate chats', len(chats) == len(set(chats)), str(chats))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all regression checks passed")


asyncio.run(main())
