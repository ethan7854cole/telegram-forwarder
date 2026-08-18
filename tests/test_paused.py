"""Taking a group out of service: MH X LARRY GROUP 2 and CHIME PICCASO.

A pause, not an unwiring. The routes stay written down exactly as they were -
what changes is that the bot is deaf and mute in those two chats: nothing
forwarded, no cashout opened, answered, hearted or chased, no ledger moved, no
idle prompt, no mention DM, no retraction, no report, and no reply to a command
typed there.

Two things are easy to get wrong and are what most of this suite is about.

SILENCE is the whole point, and silence has to reach the DMs too. The
emergency stop deliberately reports what it swallows; a pause must not, or
Ethan and Larry get chased about groups nobody is working.

And RESUMING must not replay the pause. The boot sweep reads the source group's
history and forwards whatever is missing from the target - which, after a
pause, is everything that happened during it. Turning a group back on would
otherwise post and BOOK hours of stale payments.

The suite runs against the SHIPPED configuration: the env var is cleared below
so PAUSED_CHATS falls back to whatever forwarder.py actually ships with, which
is the thing that decides what production does.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
# Deliberately NOT set: this suite is about what ships, so the default in
# forwarder.py is what it must read. tests/run.py clears it for every other
# suite; popping it here undoes that for this one only.
os.environ.pop('PAUSED_CHATS', None)
os.environ.pop('RESUMED_CHATS', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
ETHAN, LARRY, CREW = 7578145913, 7418675217, 77
BOTID = 111222

sent, dms, replies, copies, reactions = [], [], [], [], []
_next_id = [9000]
real_sleep = asyncio.sleep
failures = []


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
        return FakeMsg(9500)

    async def reply_to(self, message, text):
        replies.append(text)
        return FakeMsg(9600)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id))
        return True

    async def delete_message(self, chat_id, message_id):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f.BOT_ID = BOTID
f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY,
                    'maynuddin23': CREW})


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); replies.clear(); copies.clear(); reactions.clear()
    f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()
    f._idle_state.clear(); f._cashout_stopped = False
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY,
                        'maynuddin23': CREW})


def payment(amount=25):
    return (f"You received ${amount}.00 from Person\n"
            "09:35 AM - 18 Aug 2026\n"
            "Total In : 100.00$\n"
            "Total Out: 20.00$")


def to(chat_id):
    return [t for c, t in sent if c == chat_id]


def all_dm_text():
    return ' | '.join(t for _c, t in dms)


class FakeUser:
    def __init__(self, uid, username=None, first_name=None):
        self.id, self.username, self.first_name = uid, username, first_name
        self.last_name, self.is_bot = None, False


class FakeChat:
    def __init__(self, cid):
        self.id = cid


class Incoming:
    """The shape telebot hands a handler."""
    def __init__(self, chat_id, text, user_id, username=None, mid=1):
        self.chat = FakeChat(chat_id)
        self.from_user = FakeUser(user_id, username)
        self.text, self.message_id = text, mid
        self.caption, self.content_type = None, 'text'
        self.reply_to_message, self.media_group_id = None, None
        self.date = int(datetime.now(timezone.utc).timestamp())


class ReactionUpdate:
    def __init__(self, chat_id, message_id, user_id, username):
        self.chat = FakeChat(chat_id)
        self.message_id, self.new_reaction = message_id, ['❤']
        self.user = FakeUser(user_id, username)


async def run_watchdog(coro, seconds=0.25):
    async def fast(_):
        await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(coro())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


async def seed_open_request(origin, mid=901, minutes_ago=0):
    """A request that was already open when the group went out of service.

    Opened with the pause lifted, because that is the true story: the pause
    landed on a request that was in flight, and the question this suite asks is
    what happens to it afterwards."""
    kept_ids, kept = f.PAUSED_CHAT_IDS, f.PAUSED_CHATS
    f.PAUSED_CHAT_IDS, f.PAUSED_CHATS = [], set()
    try:
        await f.observe_cashout(origin, 'CASHOUT REQUEST $500 for Gabriel W.',
                                mid, datetime.now(timezone.utc), user_id=42)
    finally:
        f.PAUSED_CHAT_IDS, f.PAUSED_CHATS = kept_ids, kept
    handling = f.CASHOUT_ROUTES[origin]['handling']
    queue = f._pending_cashouts.get(handling, [])
    for request in queue:
        request['opened'] = (datetime.now(timezone.utc)
                             - timedelta(minutes=minutes_ago))
    sent.clear(); dms.clear()
    return queue


# --------------------------------------------------------------------------
# 1. what ships
# --------------------------------------------------------------------------
def test_config():
    check('MH X LARRY GROUP 2 and CHIME PICCASO ship out of service',
          f.PAUSED_CHAT_IDS == [MHLARRY, PICCASO], str(f.PAUSED_CHAT_IDS))
    check('both are paused', f.chat_paused(MHLARRY) and f.chat_paused(PICCASO))
    check('the live route is not', not f.chat_paused(GAFFER)
          and not f.chat_paused(CHIMEREV))
    check('either id spelling is recognised',
          all(f.chat_paused(v) for v in f._id_variants(MHLARRY)),
          str(f._id_variants(MHLARRY)))
    check('pausing one end pauses the route',
          f.route_paused(MHLARRY) and f.route_paused(PICCASO))
    check('and leaves the other route alone',
          not f.route_paused(GAFFER) and not f.route_paused(CHIMEREV))


# --------------------------------------------------------------------------
# 2. payments
# --------------------------------------------------------------------------
async def test_forwarding():
    reset()
    f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
    await f.process_incoming(MHLARRY, payment(), 'test', from_bot=True,
                             source_msg_id=11)
    check('a payment in a paused group is not forwarded', to(PICCASO) == [],
          str(sent))
    check('and its books do not move',
          f._ledger[PICCASO] == {'in': 100.0, 'out': 20.0}, str(f._ledger))
    check('and nobody is DMed about it', dms == [], str(dms))

    # the door itself, for code that does not go through process_incoming
    reset()
    check('send_group refuses a paused chat outright',
          await f.send_group(PICCASO, 'anything at all') is None)
    check('and posts nothing', sent == [], str(sent))

    # the control: the live route is untouched
    reset()
    f._ledger[GAFFER] = {'in': 100.0, 'out': 20.0}
    await f.process_incoming(CHIMEREV, payment(), 'test', from_bot=True,
                             source_msg_id=12)
    check('the live route still forwards', len(to(GAFFER)) == 1, str(sent))
    check('and still books it', f._ledger[GAFFER]['in'] == 125.0, str(f._ledger))


# --------------------------------------------------------------------------
# 3. cashouts
# --------------------------------------------------------------------------
async def test_cashouts():
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $500 for Gabriel W.',
                            701, datetime.now(timezone.utc), user_id=42)
    check('a request in a paused chime group opens nothing',
          not f._pending_cashouts, str(f._pending_cashouts))
    check('nothing is posted anywhere', sent == [], str(sent))
    check('and nobody is told', dms == [], str(dms))

    reset()
    queue = await seed_open_request(PICCASO, mid=702)
    check('a request open when the pause landed is kept, not dropped',
          len(queue) == 1, str(f._pending_cashouts))

    await f.observe_cashout(MHLARRY, '/out 500', 703,
                            datetime.now(timezone.utc), user_id=CREW,
                            username='maynuddin23', reply_to=queue[0]['message_id'])
    check('a /out answering it is not relayed', to(PICCASO) == [], str(sent))
    check('not booked', PICCASO not in f._ledger, str(f._ledger))
    check('not hearted', reactions == [], str(reactions))
    check('and the request is still open', len(f._pending_cashouts.get(MHLARRY, [])) == 1)

    # Ethan's manual completion is the one thing that works with nothing open.
    # It must not work here either.
    reset()
    await f.observe_cashout(MHLARRY, '/out 250', 704,
                            datetime.now(timezone.utc), user_id=ETHAN,
                            username='ethannxxxx')
    check('an admin /out with nothing open does nothing either',
          sent == [] and dms == [], f"{sent} {dms}")

    # the control
    reset()
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $500 for Gabriel W.',
                            705, datetime.now(timezone.utc), user_id=42)
    check('the live route still opens requests',
          len(f._pending_cashouts.get(CHIMEREV, [])) == 1, str(f._pending_cashouts))
    check('and still posts them', len(to(CHIMEREV)) == 1, str(sent))


# --------------------------------------------------------------------------
# 4. the chase
# --------------------------------------------------------------------------
async def test_chase():
    reset()
    await seed_open_request(PICCASO, mid=801, minutes_ago=45)
    await run_watchdog(f.cashout_watchdog)
    check('nothing is chased in a paused group', sent == [], str(sent))
    check('the crew are not DMed about it', dms == [], str(dms))
    check('and the request is still there, waiting',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1, str(f._pending_cashouts))

    reset()
    await seed_open_request(GAFFER, mid=802, minutes_ago=45)
    await run_watchdog(f.cashout_watchdog)
    check('the live route is still chased', len(to(CHIMEREV)) >= 1, str(sent))
    check('and its admins still hear about it',
          any('OUT REQUEST' in t for _c, t in dms), str(dms))


# --------------------------------------------------------------------------
# 5. the quieter features
# --------------------------------------------------------------------------
async def test_idle_and_mentions():
    reset()
    old = datetime.now(timezone.utc) - timedelta(minutes=10 * f.IDLE_ALERT_MINUTES)
    for target in (PICCASO, GAFFER):
        f._idle_state[target] = {'last': None, 'since': old, 'sent': 0,
                                 'paused': False}
    await run_watchdog(f.idle_watchdog)
    check('a paused group is never asked whether it has a problem',
          to(PICCASO) == [], str(sent))
    check('the live group still is', len(to(GAFFER)) >= 1, str(sent))

    reset()
    await f.observe_mentions(PICCASO, 'hey @larryyxx look at this', 901,
                             datetime.now(timezone.utc), user_id=42,
                             username='someone')
    check('an @ in a paused group raises no DM', dms == [], str(dms))
    await f.observe_mentions(GAFFER, 'hey @larryyxx look at this', 902,
                             datetime.now(timezone.utc), user_id=42,
                             username='someone')
    check('an @ in a live group still does', len(dms) >= 1, str(dms))

    # a reaction in a paused handling group acknowledges nothing
    reset()
    queue = await seed_open_request(PICCASO, mid=903)
    await f.on_request_reaction(ReactionUpdate(MHLARRY, queue[0]['message_id'],
                                               CREW, 'maynuddin23'))
    check('a reaction in a paused group is not an acknowledgement',
          queue[0]['seen'] is False)
    check('and Larry is not told about it', dms == [], str(dms))


# --------------------------------------------------------------------------
# 6. commands typed in a paused group
# --------------------------------------------------------------------------
async def test_commands():
    reset()
    f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
    await f.ledger_command(Incoming(PICCASO, '/add 500', ETHAN, 'ethannxxxx'))
    check('/add in a paused group moves nothing',
          f._ledger[PICCASO] == {'in': 100.0, 'out': 20.0}, str(f._ledger))
    check('and answers nothing - not even a refusal', replies == [], str(replies))

    await f.ledger_set_command(Incoming(PICCASO, '/set in 9999', ETHAN, 'ethannxxxx'))
    check('/set in a paused group is ignored too',
          f._ledger[PICCASO] == {'in': 100.0, 'out': 20.0} and replies == [],
          f"{f._ledger} {replies}")

    await f.report_command(Incoming(PICCASO, '/report 24h', ETHAN, 'ethannxxxx'))
    check('/report posts nothing into a paused group',
          sent == [] and replies == [], f"{sent} {replies}")

    await f.cashout_switch_command(Incoming(MHLARRY, '/cashout off', ETHAN,
                                            'ethannxxxx'))
    check('the emergency stop cannot be worked from a paused group',
          f.cashout_stopped() is False)
    check('and it stays silent there', replies == [] and dms == [],
          f"{replies} {dms}")

    # ...but it still works where the bot is in service
    reset()
    await f.cashout_switch_command(Incoming(ETHAN, '/cashout off', ETHAN,
                                            'ethannxxxx'))
    check('the stop still works from a DM', f.cashout_stopped() is True)
    f._cashout_stopped = False

    # the payment-prompt pause is a different switch, and says so
    reset()
    f._idle_state.clear()
    await f.idle_pause_command(Incoming(ETHAN, '/pause piccaso', ETHAN,
                                        'ethannxxxx'))
    check('/pause piccaso says the group is out of service',
          any('Out of service' in r for r in replies), str(replies))
    check('and does not pretend to have paused it',
          f._idle_state.get(PICCASO, {}).get('paused') is not True,
          str(f._idle_state))


# --------------------------------------------------------------------------
# 7. the report
# --------------------------------------------------------------------------
def test_report():
    pairs = {p['chime'] for p in f.report_pairs()}
    check('the paused pair is left out of the daily report',
          PICCASO not in pairs, str(pairs))
    check('the live pair is still in it', GAFFER in pairs, str(pairs))
    summary = f.report_summary_text({'day': datetime.now(timezone.utc),
                                     'pairs': [], 'unreadable': []})
    check('and the report says which groups it is not counting',
          'CHIME PICCASO' in summary and 'MH X LARRY GROUP 2' in summary, summary)


async def test_status():
    reset()
    await f.status(Incoming(ETHAN, '/status', ETHAN, 'ethannxxxx'))
    check('/status leads with what is out of service',
          replies and 'OUT OF SERVICE' in replies[0], str(replies))
    check('and names both groups',
          replies and 'CHIME PICCASO' in replies[0]
          and 'MH X LARRY GROUP 2' in replies[0], str(replies))

    reset()
    await f.help_command(Incoming(ETHAN, '/help', ETHAN, 'ethannxxxx'))
    helped = ' '.join(t for _c, t in dms)
    check('/help says which groups the bot is not working',
          'OUT OF SERVICE' in helped and 'CHIME PICCASO' in helped, helped[-200:])


# --------------------------------------------------------------------------
# 8. resuming must not replay the pause
# --------------------------------------------------------------------------
class Entity:
    def __init__(self, cid):
        self.id, self.title = cid, str(cid)


class Sender:
    def __init__(self, uid, is_bot=True):
        self.id, self.bot = uid, is_bot


class HistMsg:
    def __init__(self, mid, text, minutes_ago, sender):
        self.id, self.raw_text = mid, text
        self.date = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        self.media, self._sender, self.reactions = None, sender, None

    async def get_sender(self):
        return self._sender


class FakeClient:
    def __init__(self, history):
        self.history, self.asked = history, []

    async def get_entity(self, cid):
        self.asked.append(cid)
        if cid in self.history:
            return Entity(cid)
        raise ValueError(f'no entity {cid}')

    def iter_messages(self, entity, limit=None):
        async def gen():
            for m in self.history.get(entity.id, [])[:limit]:
                yield m
        return gen()


async def test_catchup():
    reset()
    f.utils.get_peer_id = lambda e: e.id
    bot_sender = Sender(777)
    history = {MHLARRY: [HistMsg(501, payment(30), 5, bot_sender),
                         HistMsg(500, payment(20), 90, bot_sender)],
               PICCASO: []}
    rules = dict(f.FORWARD_RULES)
    f.FORWARD_RULES.clear(); f.FORWARD_RULES[MHLARRY] = [PICCASO]
    f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
    try:
        client = FakeClient(history)
        await f.catch_up(client)
        check('the boot sweep does not read a paused group at all',
              client.asked == [], str(client.asked))
        check('and delivers nothing into it', to(PICCASO) == [], str(sent))

        # ---- now bring it back, resumed 10 minutes ago -------------------
        reset()
        f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
        kept_ids, kept = f.PAUSED_CHAT_IDS, f.PAUSED_CHATS
        f.PAUSED_CHAT_IDS, f.PAUSED_CHATS = [], set()
        f.RESUMED_CHATS = f._parse_resume_marks(
            f"{MHLARRY}@{(datetime.now(timezone.utc) - timedelta(minutes=10)):%Y-%m-%dT%H:%M}")
        try:
            await f.catch_up(FakeClient(history))
        finally:
            f.PAUSED_CHAT_IDS, f.PAUSED_CHATS = kept_ids, kept
            f.RESUMED_CHATS = {}
        landed = to(PICCASO)
        check('a resumed group is not handed the payments it missed',
              not any('$20.00' in t for t in landed), str(landed))
        check('but is caught up on everything since it came back',
              len(landed) == 1 and '$30.00' in landed[0], str(landed))
    finally:
        f.FORWARD_RULES.clear(); f.FORWARD_RULES.update(rules)


# --------------------------------------------------------------------------
# 9. the silence itself
# --------------------------------------------------------------------------
async def test_silence():
    """Everything a paused group can throw at the bot, and not one word out.

    The emergency stop deliberately reports what it swallows. A pause must not:
    those groups are not being worked, and a DM about them is a chase nobody
    can act on."""
    reset()
    await seed_open_request(PICCASO, mid=1001, minutes_ago=45)
    reset_dms = len(dms)
    now = datetime.now(timezone.utc)
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $900 for Someone', 1002, now,
                            user_id=42)
    await f.observe_cashout(MHLARRY, '/out 900', 1003, now, user_id=CREW,
                            username='maynuddin23')
    await f.observe_cashout(MHLARRY, 'a screenshot with no /out', 1004, now,
                            user_id=CREW, username='maynuddin23', has_media=True)
    await f.process_incoming(MHLARRY, payment(), 'test', from_bot=True)
    await f.observe_mentions(MHLARRY, '@ethannxxxx @larryyxx', 1005, now,
                             user_id=CREW, username='maynuddin23')
    await f.retract_payment(MHLARRY, 1006, ETHAN)
    await run_watchdog(f.cashout_watchdog)
    check('a paused group produces no DMs at all', len(dms) == reset_dms,
          all_dm_text())
    check('and posts nothing, anywhere', sent == [], str(sent))
    check('no name of a paused group reaches anyone',
          'PICCASO' not in all_dm_text() and 'MH X LARRY' not in all_dm_text(),
          all_dm_text())


async def main():
    print('paused groups')
    test_config()
    await test_forwarding()
    await test_cashouts()
    await test_chase()
    await test_idle_and_mentions()
    await test_commands()
    test_report()
    await test_status()
    await test_catchup()
    await test_silence()

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
