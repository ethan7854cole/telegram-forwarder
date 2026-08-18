"""/add and /out must accept a negative, in both spellings, without breaking either."""
import asyncio, os, sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY = -1003894781195
LARRY = 7418675217
sent, failures = [], []


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        sent.append((chat_id, text)); return FakeMsg(1)
    async def reply_to(self, message, text):
        sent.append((message.chat.id, text)); return FakeMsg(1)
    async def set_message_reaction(self, *a, **k): return True


f.bot = FakeBot(); f.USERBOT_SEND = False; f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


class C:
    def __init__(s, cid): s.id = cid
class U:
    def __init__(s, uid): s.id = uid
class M:
    def __init__(s, cid, text, uid=LARRY):
        s.chat, s.text, s.from_user = C(cid), text, U(uid)
        s.message_id, s.date, s.reply_to_message = 1, None, None


def setup(chat=PICCASO, tin=1000.0, tout=200.0):
    sent.clear(); f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()
    f._ledger[chat] = {'in': tin, 'out': tout}


async def main():
    # -- both spellings subtract from Total In -------------------------------
    for text in ['/add -100', '/add-100', '/add - 100', '/add -$100', '/add@mybot-100']:
        setup()
        await f.ledger_command(M(PICCASO, text))
        check(f'{text!r} takes 100 off Total In',
              f.ledger_snapshot(PICCASO) == (900.0, 200.0), str(f.ledger_snapshot(PICCASO)))

    # -- negative /out -------------------------------------------------------
    setup()
    await f.ledger_command(M(PICCASO, '/out -50'))
    check('/out -50 takes 50 off Total Out',
          f.ledger_snapshot(PICCASO) == (1000.0, 150.0), str(f.ledger_snapshot(PICCASO)))
    setup()
    await f.ledger_command(M(PICCASO, '/out-50'))
    check('/out-50 does the same', f.ledger_snapshot(PICCASO) == (1000.0, 150.0))

    # -- positives are completely unchanged ----------------------------------
    setup()
    await f.ledger_command(M(PICCASO, '/add 500'))
    check('/add 500 still adds', f.ledger_snapshot(PICCASO) == (1500.0, 200.0))
    check('/add wording unchanged', any('💰 Deposit = +500.00$' in t for _, t in sent), str(sent))
    setup()
    await f.ledger_command(M(PICCASO, '/out 100'))
    check('/out 100 still adds to Out', f.ledger_snapshot(PICCASO) == (1000.0, 300.0))
    check('/out wording unchanged', any('📤 Out = -100.00$' in t for _, t in sent), str(sent))

    # -- the correction is labelled clearly ----------------------------------
    setup()
    await f.ledger_command(M(PICCASO, '/add -100'))
    check('negative /add is labelled a correction',
          any('✏️ Total In adjusted by -100.00$' in t for _, t in sent), str(sent))
    setup()
    await f.ledger_command(M(PICCASO, '/out -50'))
    check('negative /out is labelled a correction',
          any('✏️ Total Out adjusted by -50.00$' in t for _, t in sent), str(sent))

    # -- the totals block still lets a redeploy recover the books ------------
    setup()
    await f.ledger_command(M(PICCASO, '/add-250'))
    block = [t for _, t in sent if 'Group Total' in t]
    check('a totals block is still posted', len(block) == 1, str(sent))
    check('a redeploy recovers the corrected figures',
          f.parse_totals(block[0]) == (750.0, 200.0), str(f.parse_totals(block[0])))

    # -- overshoot is refused ------------------------------------------------
    setup(tin=50.0, tout=10.0)
    await f.ledger_command(M(PICCASO, '/add -100'))
    check('overshooting Total In is refused', f.ledger_snapshot(PICCASO) == (50.0, 10.0))
    check('the refusal explains and points at /set',
          any('below zero' in t and '/set in' in t for _, t in sent), str(sent))
    setup(tin=50.0, tout=10.0)
    await f.ledger_command(M(PICCASO, '/out -100'))
    check('overshooting Total Out is refused', f.ledger_snapshot(PICCASO) == (50.0, 10.0))
    check('the Out refusal points at /set out',
          any('/set out' in t for _, t in sent), str(sent))

    # -- exactly to zero is allowed ------------------------------------------
    setup(tin=100.0, tout=10.0)
    await f.ledger_command(M(PICCASO, '/add -100'))
    check('landing exactly on zero is allowed', f.ledger_snapshot(PICCASO) == (0.0, 10.0))

    # -- zero and junk are refused -------------------------------------------
    for text in ['/add 0', '/add -0', '/add', '/add abc', '/add -']:
        setup()
        await f.ledger_command(M(PICCASO, text))
        check(f'{text!r} refused with usage',
              f.ledger_snapshot(PICCASO) == (1000.0, 200.0)
              and any('Usage:' in t for _, t in sent), str(sent))

    # -- usage text names the command correctly for the joined form ---------
    setup()
    await f.ledger_command(M(PICCASO, '/add-abc'))
    check('usage says /add, not /add-abc',
          any('Usage: /add ' in t for _, t in sent), str(sent))

    # -- permissions unchanged ------------------------------------------------
    setup()
    await f.ledger_command(M(PICCASO, '/add -100', uid=999))
    check('a non-admin still cannot correct', f.ledger_snapshot(PICCASO) == (1000.0, 200.0))
    check('non-admin still told no', any('Not permitted' in t for _, t in sent))

    setup()
    await f.ledger_command(M(MHLARRY, '/add -100'))
    check('still silent outside the target groups',
          sent == [] and f.ledger_snapshot(MHLARRY) == (0.0, 0.0), str(sent))

    # -- a correction fires no milestone -------------------------------------
    setup(tin=5100.0, tout=0.0)
    await f.ledger_command(M(PICCASO, '/add -200'))
    check('a decrease replays no milestone',
          not any('MILESTONE' in t for _, t in sent), str(sent))

    # -- GAFFER works the same -----------------------------------------------
    setup(chat=GAFFER, tin=300.0, tout=100.0)
    await f.ledger_command(M(GAFFER, '/add-50'))
    check('GAFFER corrects its own ledger', f.ledger_snapshot(GAFFER) == (250.0, 100.0))

    # -- the joined-form router matches only what it should -----------------
    yes = ['/add-100', '/out-50', '/add@bot-1', '/OUT-5']
    no = ['/add 100', '/out 100', '/added-100', '/set in 100', 'hello',
          '/pause', 'You received $5.00', '/out']
    check('router matches the joined spellings',
          all(f._JOINED_LEDGER_RE.match(t) for t in yes),
          str([t for t in yes if not f._JOINED_LEDGER_RE.match(t)]))
    check('router ignores everything else',
          not any(f._JOINED_LEDGER_RE.match(t) for t in no),
          str([t for t in no if f._JOINED_LEDGER_RE.match(t)]))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all negative-amount checks passed")


asyncio.run(main())
