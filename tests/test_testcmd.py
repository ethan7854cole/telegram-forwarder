"""/test reports on the bot without touching any group, and /help fits Telegram.

/help outgrew Telegram's 4096-character limit, and Telegram refuses an
over-long message whole - so Larry typed /help and got nothing at all. It now
goes in parts. /test is a private health report: it reads state and runs the
start-up check's membership lookups, and must never post or book anything.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ.pop('RETRACT_SOURCES', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

MHLARRY, PICCASO = -1003894781195, -5350880041
CHIMEREV, GAFFER = -1002335630148, -5580596463
LVENMO, GVENMO = -1004298140797, -5100231154

sent = []


class Member:
    def __init__(self, status):
        self.status = status


class FakeMsg:
    def __init__(self, mid=1):
        self.message_id = mid


class Chat:
    def __init__(self, cid):
        self.id = cid


class Message:
    def __init__(self, cid, text='/test'):
        self.chat = Chat(cid)
        self.text = text


class FakeBot:
    statuses = {}

    async def get_chat_member(self, chat_id, user_id):
        return Member(self.statuses.get(chat_id, 'administrator'))

    async def send_message(self, chat_id, text, **kw):
        sent.append((chat_id, text))
        return FakeMsg(len(sent))

    async def reply_to(self, message, text, **kw):
        sent.append((message.chat.id, text))
        return FakeMsg(len(sent))


real_bot = f.bot
f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def test_handler():
    """The registered /test handler and its filter, as telebot sees them."""
    for h in real_bot.message_handlers:
        if h['function'] is f.test_command:
            return h
    return None


async def main():
    # -- 1. split_message -----------------------------------------------------
    check('a short text is one part', f.split_message('hi\n\nthere') == ['hi\n\nthere'])
    text = '\n\n'.join(f"SECTION {i}\n" + 'x' * 900 for i in range(10))
    parts = f.split_message(text)
    check('a long text is split', len(parts) > 1, str(len(parts)))
    check('every part fits Telegram', all(len(p) <= 4096 for p in parts))
    check('split at blank lines, nothing lost', '\n\n'.join(parts) == text)
    check('a single huge line is still cut to fit',
          all(len(p) <= 4096 for p in f.split_message('y' * 9000)))
    check('and loses nothing', ''.join(f.split_message('y' * 9000)) == 'y' * 9000)

    # -- 2. /help reaches Larry, in parts ------------------------------------
    for paused in ([], [MHLARRY, PICCASO]):
        f.PAUSED_CHATS = f._with_variants(paused)
        f.PAUSED_CHAT_IDS = sorted(paused)
        sent.clear()
        await f.help_command(Message(f.LARRY_ID, '/help'))
        label = 'with a group out of service' if paused else 'with every group live'
        check(f'/help is answered {label}', len(sent) >= 1, str(sent))
        check(f'every /help part fits Telegram {label}',
              all(len(t) <= 4096 for _, t in sent), str([len(t) for _, t in sent]))
        check(f'all of it goes to Larry only {label}',
              all(c == f.LARRY_ID for c, _ in sent))
        whole = '\n\n'.join(t for _, t in sent)
        check(f'/help lists /test {label}', '/test' in whole)
        check(f'/help ends with GOOD TO KNOW onward {label}',
              'Only Ethan and Larry can use any of these.' in whole)
    f.PAUSED_CHATS = f._with_variants([])
    f.PAUSED_CHAT_IDS = []

    sent.clear()
    await f.help_command(Message(GAFFER, '/help'))
    check('/help in a group says nothing', sent == [], str(sent))

    # -- 3. /test: private, admin only, falls through elsewhere --------------
    h = test_handler()
    check('/test is registered', h is not None)
    flt = h['filters']['func'] if h else (lambda m: False)
    check('/test answers Larry in private', flt(Message(f.LARRY_ID)))
    check('/test answers Ethan in private', flt(Message(f.ETHAN_ID)))
    check('a /test in a group falls through to the old handlers',
          not flt(Message(CHIMEREV)) and not flt(Message(GAFFER)))
    check('a /test from a stranger falls through', not flt(Message(123456)))

    # -- 4. the report --------------------------------------------------------
    f.userbot_status = 'listening (3 chats, from: bots)'
    f._last_payment.clear()
    before = dict(f._ledger)
    sent.clear()
    await f.test_command(Message(f.LARRY_ID))
    check('/test replies once, to Larry only',
          len(sent) == 1 and sent[0][0] == f.LARRY_ID, str(sent))
    report = sent[0][1] if sent else ''
    check('the bot is reported online', '✅ Bot: online' in report, report)
    check('a listening userbot is ✅', '✅ Userbot: listening' in report, report)
    for src, tgt in ((CHIMEREV, GAFFER), (LVENMO, GVENMO), (MHLARRY, PICCASO)):
        check(f'the {f.chat_name(src)} route is listed',
              f"{f.chat_name(src)} → {f.chat_name(tgt)}" in report, report)
    check('no payment yet is said as such', 'no payment since the restart' in report, report)
    check('no problems -> admin line', '✅ Admin in all handling groups' in report, report)
    check('the cashout flow is shown', 'Cashout flow: running' in report, report)
    check('the books are untouched', f._ledger == before)

    # A payment booked through the real delivery path shows up.
    f._ledger[GVENMO] = {'in': 0.0, 'out': 0.0}
    sent.clear()
    await f.deliver_to_target(GVENMO, '🟢 You received $30.0 from Test\n'
                              '➕ Total In : 30.00$\n➖ Total Out: 0.00$',
                              'You received $30.0 from Test', True)
    check('a booked payment is timestamped', GVENMO in f._last_payment)
    sent.clear()
    await f.test_command(Message(f.LARRY_ID))
    report = sent[0][1] if sent else ''
    check('and /test shows it as just now', 'last payment just now' in report, report)
    f._ledger.clear(); f._ledger.update(before)

    # Idle prompts and a pause are visible.
    f._idle_slot(GAFFER)['sent'] = 4
    f.PAUSED_CHATS = f._with_variants([MHLARRY, PICCASO])
    sent.clear()
    await f.test_command(Message(f.LARRY_ID))
    report = sent[0][1]
    check('idle prompts are counted', '(idle prompt #4)' in report, report)
    check('a paused route is marked out of service',
          f"⏸ {f.chat_name(MHLARRY)} → {f.chat_name(PICCASO)}: out of service" in report,
          report)
    f._idle_slot(GAFFER)['sent'] = 0
    f.PAUSED_CHATS = f._with_variants([])

    # A problem the start-up check would find is shown, not DMed on its own.
    f.bot.statuses = {LVENMO: 'member'}
    f.userbot_status = 'session dead: AuthKeyError'
    f._cashout_stopped = True
    sent.clear()
    await f.test_command(Message(f.LARRY_ID))
    check('still one reply, nothing else sent', len(sent) == 1, str(sent))
    report = sent[0][1]
    check('a dead userbot is ❌', '❌ Userbot: session dead' in report, report)
    check('a non-admin group is listed under problems',
          '❌ Problems:' in report and 'MH x LARRY VENMO' in report, report)
    check('a stopped cashout flow is shown', 'Cashout flow: ⏸ STOPPED' in report, report)
    check('/test does not use up the once-per-boot health check',
          f._health_checked is False)
    f.bot.statuses = {}
    f._cashout_stopped = False

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
