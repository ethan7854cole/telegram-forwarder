"""Ethan and Larry talking to the crew is chatter, not traffic.

They work in the same groups the bot reads, and two of the words they use are
the two words it routes on. "@Maynuddin23 what about that CASHOUT REQUEST"
opened a second request for money already asked for and ran the whole chase
ladder over a question; "@Maynuddin23 he never got the 200 you received" was
forwarded into a chime group looking like a fresh deposit.

The rule has two halves and needs both: Ethan or Larry wrote it, AND it names
the crew. So a real request is untouched however it is worded, the crew's own
posts are untouched, and Ethan's and Larry's own /out, /add and ordinary
messages keep working exactly as they did.

Both directions of every route, because the amendment was asked for on both:
nothing goes out as a cashout request, and nothing comes back as a payment.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ['PAUSED_CHATS'] = ''          # every route live: this is about who spoke
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
GVENMO, LVENMO = -5100231154, -1004298140797
ETHAN, LARRY = f.ETHAN_ID, f.LARRY_ID
MAY, NPR, STRANGER = 77, 88, 999
BOTID = 111222

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

sent, dms, copies = [], [], []
failures = []
_next_id = [8000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_next_id[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        copies.append((chat_id, caption))
        return FakeMsg(8500)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        return True

    async def delete_message(self, chat_id, message_id):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f.BOT_ID = BOTID


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); copies.clear()
    f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()
    f._cashout_stopped = False
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY,
                        'maynuddin23': MAY, 'npr_ca': NPR})


def to(chat_id):
    return [t for c, t in sent if c == chat_id]


def payment(amount=200):
    return (f"You received ${amount}.00 from Gabriel W.\n"
            "Total In: 1,000\nTotal Out: 500")


# The three routes, and where a request asked in each one is handled.
ROUTES = [(PICCASO, MHLARRY), (GAFFER, CHIMEREV), (GVENMO, LVENMO)]
# The payment direction: source -> the group it feeds.
PAYMENTS = [(MHLARRY, PICCASO), (CHIMEREV, GAFFER), (LVENMO, GVENMO)]


# --------------------------------------------------------------------------
def test_mentions_crew():
    check('an @handle is a mention', f.mentions_crew('@Maynuddin23 hello'))
    check('so is the bare name', f.mentions_crew('Maynuddin23 hello'))
    check('case does not matter', f.mentions_crew('MAYNUDDIN23 hello'))
    check('every standing crew handle counts',
          all(f.mentions_crew('ping @' + h) for h in
              ('Maynuddin23', 'MHSUPPORTZONE', 'maynuddin233')))
    check('a one-group crew member counts too', f.mentions_crew('@NPR_CA ping'))
    check('mid-sentence is still a mention',
          f.mentions_crew('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 20 - @Maynuddin23 can you take this'))

    check('an email tail is not a mention', not f.mentions_crew('bob@maynuddin23'))
    check('nor a doubled @', not f.mentions_crew('hi @@maynuddin23'))
    check('nor a name inside a longer word',
          not f.mentions_crew('xmaynuddin23x'))
    check('a shorter prefix does not match the longer handle',
          not f.mentions_crew('maynuddin2 is not one of them'))
    check('but the longer handle matches itself',
          f.mentions_crew('maynuddin233 is'))
    check('an ordinary request names nobody',
          not f.mentions_crew('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500'))
    check('empty text is not a mention',
          not f.mentions_crew('') and not f.mentions_crew(None))


def test_who_wrote_it():
    tagged = ('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 20\n@Maynuddin23 any update?')
    check("Ethan tagging the crew is chatter",
          f.is_admin_crew_note(tagged, ETHAN, 'ethannxxxx'))
    check('so is Larry', f.is_admin_crew_note(tagged, LARRY, 'larryyxx'))
    check('Ethan naming nobody is not',
          not f.is_admin_crew_note('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 20', ETHAN, 'ethannxxxx'))
    check('the crew tagging each other is not',
          not f.is_admin_crew_note(tagged, MAY, 'Maynuddin23'))
    check('a one-group crew member is not',
          not f.is_admin_crew_note(tagged, NPR, 'NPR_CA'))
    check('a stranger is not',
          not f.is_admin_crew_note(tagged, STRANGER, 'someone'))
    check('nor the bot itself',
          not f.is_admin_crew_note(tagged, BOTID, None))

    check('with no id, their handle identifies them',
          f.is_admin_crew_note(tagged, None, 'ethannxxxx')
          and f.is_admin_crew_note(tagged, None, '@larryyxx'))
    check('an unknown handle with no id is not them',
          not f.is_admin_crew_note(tagged, None, 'someone'))
    check('and no id and no handle is nobody',
          not f.is_admin_crew_note(tagged, None, None))
    check('a known id beats a claimed handle',
          not f.is_admin_crew_note(tagged, STRANGER, 'ethannxxxx'))


# --------------------------------------------------------------------------
async def test_no_request_opened():
    """The headline case, on all three routes."""
    for origin, handling in ROUTES:
        for who, name in ((ETHAN, 'ethannxxxx'), (LARRY, 'larryyxx')):
            reset()
            await f.observe_cashout(
                origin, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200\n@Maynuddin23 any update on this?',
                901, NOW, user_id=who, username=name)
            label = f"{f.chat_name(origin)}: their tagged message"
            check(f'{label} opens no request',
                  f._pending_cashouts.get(handling, []) == [],
                  str(f._pending_cashouts))
            check(f'{label} posts nothing into {f.chat_name(handling)}',
                  to(handling) == [], str(to(handling)))
            check(f'{label} DMs nobody', dms == [], str(dms))


async def test_real_requests_still_open():
    """The other half of the rule: nothing else is touched."""
    for origin, handling in ROUTES:
        reset()
        await f.observe_cashout(origin, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500',
                                902, NOW, user_id=STRANGER, username='someone')
        check(f'{f.chat_name(origin)}: a real request still opens',
              len(f._pending_cashouts.get(handling, [])) == 1,
              str(f._pending_cashouts))
        check(f'{f.chat_name(origin)}: it still reaches {f.chat_name(handling)}',
              len(to(handling)) == 1, str(to(handling)))

    reset()
    await f.observe_cashout(GAFFER, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500', 903,
                            NOW, user_id=ETHAN, username='ethannxxxx')
    check('Ethan can still raise a request himself, as long as he tags nobody',
          len(f._pending_cashouts.get(CHIMEREV, [])) == 1, str(f._pending_cashouts))

    reset()
    await f.observe_cashout(GAFFER, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500', 904,
                            NOW, user_id=MAY, username='Maynuddin23')
    check('and a crew member tagging crew still opens one',
          len(f._pending_cashouts.get(CHIMEREV, [])) == 1, str(f._pending_cashouts))


async def test_no_payment_forwarded():
    """The same message going the other way."""
    text = '@Maynuddin23 he says he never got it - You received $200.00 from him'
    for source, target in PAYMENTS:
        for who, name in ((ETHAN, 'ethannxxxx'), (LARRY, 'larryyxx')):
            reset()
            await f.process_incoming(source, text, 'test', from_bot=False,
                                     sent_at=NOW, user_id=who, username=name)
            label = f"{f.chat_name(source)}: their tagged message"
            check(f'{label} is not forwarded to {f.chat_name(target)}',
                  to(target) == [], str(to(target)))
            check(f'{label} moves no books',
                  target not in f._ledger, str(f._ledger))


async def test_real_payments_still_forwarded():
    for source, target in PAYMENTS:
        reset()
        f._ledger[target] = {'in': 1000.0, 'out': 500.0}
        await f.process_incoming(source, payment(), 'test', from_bot=True,
                                 sent_at=NOW, user_id=BOTID, username='notifier')
        check(f'{f.chat_name(source)}: a real notification still lands',
              len(to(target)) == 1, str(to(target)))
        check(f'{f.chat_name(source)}: and still books',
              f._ledger[target]['in'] == 1200.0, str(f._ledger.get(target)))

    # The one place a human paste IS forwarded, and it stays that way: this
    # change is about who is being addressed, not about who is typing.
    reset()
    await f.process_incoming(MHLARRY, payment(), 'test', from_bot=False,
                             sent_at=NOW, user_id=ETHAN, username='ethannxxxx')
    check('Ethan pasting a notification that names nobody is forwarded as before',
          len(to(PICCASO)) == 1, str(to(PICCASO)))
    check('and still moves no books, as before', PICCASO not in f._ledger,
          str(f._ledger))

    # A bot notification can never be held back by this rule, however worded.
    reset()
    f._ledger[PICCASO] = {'in': 0.0, 'out': 0.0}
    await f.process_incoming(MHLARRY, '@Maynuddin23 ' + payment(), 'test',
                             from_bot=True, sent_at=NOW, user_id=ETHAN,
                             username='ethannxxxx')
    check('a message from the notification bot is forwarded even if it names crew',
          len(to(PICCASO)) == 1, str(to(PICCASO)))


async def test_the_out_still_works():
    """The rule must not reach the crew's answer, or Ethan's and Larry's."""
    for origin, handling in ROUTES:
        for who, name in ((MAY, 'Maynuddin23'), (LARRY, 'larryyxx'),
                          (ETHAN, 'ethannxxxx')):
            reset()
            await f.observe_cashout(origin, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500',
                                    905, NOW, user_id=STRANGER, username='someone')
            sent.clear()
            await f.observe_cashout(handling, '/out 500 @Maynuddin23 sending now',
                                    906, NOW, user_id=who, username=name)
            label = f"{f.chat_name(handling)}: {name}'s /out"
            check(f'{label} still settles the request',
                  f._pending_cashouts.get(handling, []) == [],
                  str(f._pending_cashouts))
            check(f'{label} still reaches {f.chat_name(origin)}',
                  to(origin) != [], str(to(origin)))


async def test_ordinary_admin_messages():
    """Nothing else they type changes meaning."""
    reset()
    await f.observe_cashout(GAFFER, '@Maynuddin23 morning', 907, NOW,
                            user_id=ETHAN, username='ethannxxxx')
    check('a tagged message with no keyword was never traffic anyway',
          f._pending_cashouts == {} and sent == [], str(sent))

    reset()
    await f.process_incoming(MHLARRY, '@Maynuddin23 morning', 'test',
                             from_bot=False, sent_at=NOW, user_id=LARRY,
                             username='larryyxx')
    check('and neither was it on the payment side', sent == [], str(sent))


# --------------------------------------------------------------------------
class Sender:
    def __init__(self, username=None, uid=None):
        self.username, self.id = username, uid
        self.first_name = self.last_name = None


class Msg:
    def __init__(self, mid, text, sender=None, sender_id=None):
        self.id, self.raw_text, self.date = mid, text, NOW
        self.sender, self.sender_id, self.reply_to_msg_id = sender, sender_id, None
        self.media = None


def test_report_does_not_count_it():
    """History is read by the same rule, or the day's figures show a phantom."""
    read = f._read_handling_side([
        Msg(1, '📨 CASHOUT REQUEST $500 for Gabriel W.\n\n@Maynuddin23',
            Sender('somebot', BOTID), BOTID),
        Msg(2, '@Maynuddin23 what happened to that CASHOUT REQUEST?',
            Sender('ethannxxxx', ETHAN), ETHAN),
        Msg(3, '@Maynuddin23 chasing the CASHOUT REQUEST again',
            Sender('larryyxx', LARRY), LARRY),
    ])
    check('the forwarded request is counted', len(read['requests']) == 1,
          str(read['requests']))
    check('and it is the bot\'s one', read['requests']
          and read['requests'][0]['id'] == 1, str(read['requests']))
    check('their two questions are not', len(read['requests']) == 1,
          str(read['requests']))

    read = f._read_handling_side([
        Msg(4, '📨 CASHOUT REQUEST $500', Sender('somebot', BOTID), BOTID),
        Msg(5, '/out 500', Sender('Maynuddin23', MAY), MAY),
    ])
    check('a real request and its /out still pair up',
          len(read['requests']) == 1 and len(read['outs']) == 1, str(read))


# --------------------------------------------------------------------------
# The shape a request must take. Three parts, all required:
#
#     !! Cashout Request !!
#     Tag name : $CelsoValero88
#     Amount : 150

GOOD = '!! Cashout Request !!\nTag name : $CelsoValero88\nAmount : 150'


def test_the_format():
    check('the real shape is a request', f.is_cashout_request(GOOD))
    check('lower case and tight colons still count',
          f.is_cashout_request('!! cashout request !!\ntag name: $x\namount: 20'))
    check('a dash instead of a colon still counts',
          f.is_cashout_request('Cashout Request\nTag name - $x\nAmount - 20'))
    check('the !! decoration is not required',
          f.is_cashout_request('Cashout Request\nTag name : $x\nAmount : 20'))
    check('a tag written without the $ still counts',
          f.is_cashout_request('Cashout Request\nTag name : CelsoValero88\nAmount : 20'))

    check('the keyword ALONE is not a request',
          not f.is_cashout_request('CASHOUT REQUEST'))
    check('nor the keyword with a bare figure',
          not f.is_cashout_request('CASHOUT REQUEST $500 for Gabriel W.'))
    check('nor a request missing its amount',
          not f.is_cashout_request('!! Cashout Request !!\nTag name : $x'))
    check('nor one missing its tag',
          not f.is_cashout_request('!! Cashout Request !!\nAmount : 150'))
    check('nor the tag and amount without the header',
          not f.is_cashout_request('Tag name : $x\nAmount : 150'))
    check('and ordinary talk is not', not f.is_cashout_request('any cashouts today?'))

    check('the tag is read from its own line',
          f.request_tag(GOOD) == '$CelsoValero88', str(f.request_tag(GOOD)))
    check('and the amount from its own line',
          f.request_amount(GOOD) == 150.0, str(f.request_amount(GOOD)))


async def test_only_the_format_opens():
    for origin, handling in ROUTES:
        reset()
        await f.observe_cashout(origin, GOOD, 950, NOW, user_id=STRANGER,
                                username='someone')
        check(f'{f.chat_name(origin)}: the real shape opens a request',
              len(f._pending_cashouts.get(handling, [])) == 1,
              str(f._pending_cashouts))

        reset()
        await f.observe_cashout(origin, 'CASHOUT REQUEST $500 for Gabriel W.',
                                951, NOW, user_id=STRANGER, username='someone')
        check(f'{f.chat_name(origin)}: the old loose wording opens nothing',
              f._pending_cashouts.get(handling, []) == [], str(f._pending_cashouts))
        check(f'{f.chat_name(origin)}: and forwards nothing',
              to(handling) == [], str(to(handling)))
        check(f'{f.chat_name(origin)}: but says so, rather than going silent',
              [t for c, t in dms if 'WAS NOT PICKED UP' in t] != [], str(dms))

    reset()
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $500', 952, NOW,
                            user_id=STRANGER, username='someone')
    told = [t for c, t in dms if 'WAS NOT PICKED UP' in t]
    check('the alert reaches both accounts', len(told) == 2, str(dms))
    check('it shows the shape that works',
          told and 'Tag name : $CelsoValero88' in told[0], str(told))
    check('and names the group', told and 'CHIME GAFFER' in told[0], str(told))
    check('the crew are not told about a malformed request',
          [c for c, _ in dms if c == MAY] == [], str(dms))

    # Chatter still wins: their own message must not raise this either.
    reset()
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST @Maynuddin23 any update?',
                            953, NOW, user_id=ETHAN, username='ethannxxxx')
    check('their own chatter raises no malformed alert', dms == [], str(dms))


# --------------------------------------------------------------------------
async def main():
    test_the_format()
    test_mentions_crew()
    test_who_wrote_it()
    await test_only_the_format_opens()
    await test_no_request_opened()
    await test_real_requests_still_open()
    await test_no_payment_forwarded()
    await test_real_payments_still_forwarded()
    await test_the_out_still_works()
    await test_ordinary_admin_messages()
    test_report_does_not_count_it()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("chatter suite passed")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
