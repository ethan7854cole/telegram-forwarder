"""Every remaining pre-existing feature, verified untouched."""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV, VENMO = -1003894781195, -1002335630148, -5339749243
GVENMO, PVENMO = -5100231154, -5306739731
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

    # -- VENMO route still fans out to BOTH targets --------------------------
    reset()
    await f.process_incoming(VENMO, 'You received $10.00\nTotal In: 50\nTotal Out: 5',
                             'test', from_bot=True, sent_at=now)
    check('VENMO fans out to both targets',
          sorted(c for c, _ in sent) == sorted([GVENMO, PVENMO]), str(sent))

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
    body = sent[-1][1]
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
