"""Every remaining pre-existing feature, verified untouched."""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV, VENMO = -1003894781195, -1002335630148, -1004298140797
GVENMO, PVENMO = -5100231154, -5306739731
LARRY = f.LARRY_ID
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


def reset():
    sent.clear(); f._ledger.clear(); f._seen_messages.clear()
    f._pending_cashouts.clear(); f._idle_state.clear()


class C:
    def __init__(self, cid): self.id = cid


class U:
    def __init__(self, uid): self.id = uid


class M:
    def __init__(self, cid, text, uid):
        self.chat, self.text, self.from_user = C(cid), text, U(uid)
        self.message_id, self.date, self.reply_to_message = 1, None, None


async def main():
    now = datetime.now(timezone.utc)

    # -- VENMO goes to GAFFER VENMO and PICCASO VENMO -----------------------
    # Fed to GAFFER VENMO only from 2026-08-18; PICCASO VENMO was put back on
    # 2026-10-14 at the user's request, knowing one payment then moves both
    # groups' books. test_shared.py covers the cashout side of that.
    reset()
    f._ledger[GVENMO] = {'in': 50.0, 'out': 5.0}
    f._ledger[PVENMO] = {'in': 300.0, 'out': 40.0}
    await f.process_incoming(VENMO, 'You received $10.00\nTotal In: 50\nTotal Out: 5',
                             'test', from_bot=True, sent_at=now)
    check('VENMO forwards to GAFFER VENMO and PICCASO VENMO',
          sorted(c for c, _ in sent) == sorted([GVENMO, PVENMO]), str(sent))
    check('once each', len(sent) == 2, str(sent))
    check('each group books it on its own figures',
          f.ledger_snapshot(GVENMO) == (60.0, 5.0)
          and f.ledger_snapshot(PVENMO) == (310.0, 40.0),
          f"{f.ledger_snapshot(GVENMO)} {f.ledger_snapshot(PVENMO)}")

    # -- PICCASO VENMO's books -----------------------------------------------
    # Kept through the months it was not fed, and still. Its figures are
    # Ethan's and Larry's to correct - exactly as in GAFFER VENMO and CHIME
    # GAFFER.
    reset()
    f._ledger[PVENMO] = {'in': 1000.0, 'out': 200.0}
    await f.ledger_command(M(PVENMO, '/add 500', LARRY))
    check('/add still works in PICCASO VENMO',
          f.ledger_snapshot(PVENMO) == (1500.0, 200.0), str(f.ledger_snapshot(PVENMO)))
    posted = [t for c, t in sent if c == PVENMO]
    check('and still posts both totals there',
          posted and 'Total In' in posted[-1] and 'Total Out' in posted[-1], str(sent))
    check('in the shape a redeploy can read back',
          posted and f.parse_totals(posted[-1]) == (1500.0, 200.0), str(posted))

    reset()
    f._ledger[PVENMO] = {'in': 1500.0, 'out': 200.0}
    await f.ledger_set_command(M(PVENMO, '/set out 900', LARRY))
    check('/set still works in PICCASO VENMO',
          f.ledger_snapshot(PVENMO) == (1500.0, 900.0), str(f.ledger_snapshot(PVENMO)))

    # The half that is easy to forget: books that are not read back are books
    # the next deploy silently reverts. The commands and the recovery have to
    # cover the same groups or the figures lie until Railway restarts.
    asked = []

    async def note_recovery(client, target):
        asked.append(target)

    real_recover = f.recover_one_ledger
    f.recover_one_ledger = note_recovery
    try:
        await f.recover_ledgers(None)
    finally:
        f.recover_one_ledger = real_recover
    check('a redeploy recovers PICCASO VENMO too', PVENMO in asked, str(asked))
    check('and every group whose books can be moved',
          set(asked) == set(f.LEDGER_CHATS), f"{sorted(asked)} vs {sorted(f.LEDGER_CHATS)}")

    # -- a source group still cannot reach the books --------------------------
    # Chime Rev rather than MH X LARRY GROUP 2 on purpose: the latter ships out
    # of service, so it would pass this for the wrong reason whenever the suite
    # is run on its own rather than through run.py.
    reset()
    await f.ledger_command(M(CHIMEREV, '/add 500', LARRY))
    check('/add in a source group still does nothing',
          CHIMEREV not in f._ledger and sent == [], f"{f._ledger} {sent}")

    # -- IN milestone still fires -------------------------------------------
    reset()
    f._ledger[PICCASO] = {'in': 4900.0, 'out': 0.0}
    await f.check_milestones(PICCASO, (4900.0, 0.0), (5050.0, 0.0))
    check('IN milestone fires on crossing 5000',
          any('MILESTONE HIT' in t and '$5,000 IN' in t for _, t in sent), str(sent))

    # -- OUT milestone still fires ------------------------------------------
    reset()
    await f.check_milestones(GAFFER, (0.0, 900.0), (0.0, 1100.0))
    check('OUT milestone fires on crossing 1000',
          any('OUT ALERT' in t and '$1,000' in t for _, t in sent), str(sent))

    # -- a decrease still replays nothing ------------------------------------
    reset()
    await f.check_milestones(PICCASO, (9000.0, 0.0), (100.0, 0.0))
    check('a reset replays no milestone', sent == [], str(sent))

    # -- milestone still fires through /add ----------------------------------
    reset()
    f._ledger[GAFFER] = {'in': 4900.0, 'out': 0.0}
    await f.ledger_command(M(GAFFER, '/add 200', LARRY))
    check('/add still triggers its milestone',
          any('MILESTONE HIT' in t for _, t in sent), str(sent))
    check('/add still posts the group total',
          any('Group Total' in t for _, t in sent))

    # -- idle watchdog wording + pause/resume --------------------------------
    reset()
    txt = f.idle_alert_text(GAFFER, 90, 0)
    check('idle prompt still asks the group', 'No payments here' in txt and '-ETHAN' in txt, txt)
    check('idle prompt carries no figures', 'Total In' not in txt)

    f.set_idle_paused(GAFFER, True)
    check('pause still sets the flag', f._idle_slot(GAFFER)['paused'])
    f.set_idle_paused(GAFFER, False)
    check('resume still clears it and rearms',
          not f._idle_slot(GAFFER)['paused'] and f._idle_slot(GAFFER)['sent'] == 0)

    f.set_idle_paused(PICCASO, True)
    await f.note_payment(PICCASO)
    check('a payment still lifts a pause', not f._idle_slot(PICCASO)['paused'])

    # -- timestamp correction still applies ----------------------------------
    fixed = f.correct_timestamp('paid at 03:35 AM - 30 Jul 2026 ok',
                                datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc))
    check('timestamp still rewritten', '09:45 AM - 30 Jul 2026' in fixed, fixed)

    # -- totals parse/rewrite unchanged --------------------------------------
    check('totals still parse', f.parse_totals('Total In: 1,200.50\nTotal Out: 30') == (1200.5, 30.0))
    check('amount still parses', f.parse_received_amount('You received $15.0 from X') == 15.0)
    check('totals still rewrite with separators',
          'Total In: 1,234.00' in f.rewrite_totals('Total In: 1\nTotal Out: 2', 1234.0, 5.0))

    # -- /status and /help still render --------------------------------------
    reset()
    await f.status(M(LARRY, '/status', LARRY))
    check('/status still renders', sent and 'Bot Online' in sent[-1][1], str(sent))
    check('/status still reports the userbot', 'Userbot:' in sent[-1][1])
    check('/status still reports payment prompts', 'Payment prompts:' in sent[-1][1])

    reset()
    await f.help_command(M(LARRY, '/help', LARRY))
    body = '\n\n'.join(t for _, t in sent)   # /help now goes in parts
    for token in ['/add 500', '/out 100', '/set in 800', '/pause', '/resume',
                  '/status', '/ping', '/help']:
        check(f'/help still documents {token}', token in body)

    # -- /help and /status stay admin-only -----------------------------------
    reset()
    await f.help_command(M(999, '/help', 999))
    await f.status(M(999, '/status', 999))
    check('/help and /status still admin-only', sent == [], str(sent))

    # -- ping/start still admin-only -----------------------------------------
    reset()
    await f.ping(M(LARRY, '/ping', LARRY))
    check('/ping still answers admins', sent and 'Pong' in sent[-1][1])
    reset()
    await f.ping(M(999, '/ping', 999))
    check('/ping still silent for others', sent == [])

    # -- dedup + id-variant helpers unchanged --------------------------------
    check('id variants unchanged', f._id_variants(-1002335630148) == [-2335630148])
    check('rule key still resolves by variant', f.resolve_rule_key(-2335630148) == -1002335630148)
    f._seen_messages.clear()
    check('dedup still works', f._is_duplicate(('x', 1)) is False and f._is_duplicate(('x', 1)) is True)

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all remaining features verified intact")


asyncio.run(main())
