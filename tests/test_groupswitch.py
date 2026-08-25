"""/group off and /group on — taking a route out of service from a private chat.

The pause used to be a variable somebody had to edit and push. It is now a
command Larry can send from the bot DM on his phone, which means three things
have to be true that were not before.

It has to take effect at once, and take the WHOLE route with it — naming one
end and leaving the other running is the failure the gate exists to prevent.

It has to survive a redeploy. Railway wipes the disk on every push, so the
state lives in the bot's own message to Ethan and Larry and is read back on
boot by the userbot — the same mechanism as the emergency stop, for the same
reason: a group silenced from a phone must not start forwarding real money
again just because somebody deployed.

And coming back must never replay the window it was off. The boot sweep reads
source history and forwards whatever is missing from the target, which after a
pause is everything that happened during it. The resume mark travels in the
marker so the NEXT deploy still knows where that window ended.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ['PAUSED_CHATS'] = ''            # nothing paused: the command does it
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
ETHAN, LARRY, CREW = f.ETHAN_ID, f.LARRY_ID, 77
BOTID = 111222

sent, dms, replies = [], [], []
_next_id = [4000]
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

    async def reply_to(self, message, text):
        replies.append(text)
        return FakeMsg(4900)

    async def set_message_reaction(self, *a, **k):
        return True

    async def copy_message(self, *a, **k):
        return FakeMsg(4950)


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f.BOT_ID = BOTID


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset(paused=()):
    sent.clear(); dms.clear(); replies.clear()
    f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()
    f._cashout_stopped = False
    f.RESUMED_CHATS.clear()
    f.set_paused_chats(paused)
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY})


class Cmd:
    """A message shaped the way telebot delivers one."""
    def __init__(self, text, chat_id=LARRY, uid=LARRY, username='larryyxx'):
        self.chat = type('Chat', (), {'id': chat_id, 'type': 'private'})()
        self.from_user = type('U', (), {'id': uid, 'username': username})()
        self.text = text
        self.message_id = 4100


class TeleMessage:
    def __init__(self, text, when, sender_id=BOTID):
        self.raw_text, self.date, self._sender_id = text, when, sender_id

    async def get_sender(self):
        return type('S', (), {'id': self._sender_id})()


class FakeClient:
    def __init__(self, history=None, explode=False):
        self.history, self.explode = history or {}, explode

    async def get_entity(self, cid):
        if self.explode == 'entity':
            raise RuntimeError('CHANNEL_PRIVATE')
        return type('E', (), {'id': cid})()

    def iter_messages(self, entity, limit=100):
        if self.explode == 'iter':
            raise AttributeError('no iter_messages here')

        async def gen():
            for m in self.history.get(entity.id, [])[:limit]:
                yield m
        return gen()


def payment(amount=25):
    return (f"You received ${amount}.00 from Person\n"
            "09:35 AM - 18 Aug 2026\n"
            "Total In : 100.00$\n"
            "Total Out: 20.00$")


def admin_dms():
    return [t for c, t in dms if c in (ETHAN, LARRY)]


def markers():
    return [t for t in admin_dms()
            if f.GROUP_PAUSE_MARK in t or f.GROUP_RESUME_MARK in t]


# --------------------------------------------------------------------------
# 1. the switch itself
# --------------------------------------------------------------------------
async def test_off_and_on():
    reset()
    await f.group_switch_command(Cmd('/group off piccaso'))
    check('/group off piccaso takes CHIME PICCASO out of service',
          f.chat_paused(PICCASO))
    check('and MH X LARRY GROUP 2 with it — naming one end takes the route',
          f.chat_paused(MHLARRY), str(f.PAUSED_CHAT_IDS))
    check('the other route keeps running',
          not f.chat_paused(GAFFER) and not f.chat_paused(CHIMEREV))
    check('the confirmation is private', replies and 'OUT OF SERVICE' in replies[0],
          str(replies))
    check('and nothing at all is posted in a group', sent == [], str(sent))

    reset(paused=[PICCASO, MHLARRY])
    f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
    await f.process_incoming(MHLARRY, payment(), 'test', from_bot=True)
    check('while off, a payment there is not forwarded',
          not [t for c, t in sent if c == PICCASO], str(sent))

    await f.group_switch_command(Cmd('/group on piccaso'))
    check('/group on puts the whole route back',
          not f.chat_paused(PICCASO) and not f.chat_paused(MHLARRY),
          str(f.PAUSED_CHAT_IDS))
    check('and says so privately',
          any('BACK IN SERVICE' in r for r in replies), str(replies))

    sent.clear()
    await f.process_incoming(MHLARRY, payment(30), 'test', from_bot=True,
                             source_msg_id=77)
    check('a payment forwards again immediately',
          len([t for c, t in sent if c == PICCASO]) == 1, str(sent))
    check('and books normally', f._ledger[PICCASO]['in'] == 130.0, str(f._ledger))


async def test_naming():
    reset()
    await f.group_switch_command(Cmd('/group off larry2'))
    check('either end of the route can be named',
          f.chat_paused(PICCASO) and f.chat_paused(MHLARRY), str(f.PAUSED_CHAT_IDS))

    reset()
    await f.group_switch_command(Cmd(f'/group off {PICCASO}'))
    check('a raw chat id works too', f.chat_paused(PICCASO), str(f.PAUSED_CHAT_IDS))

    reset()
    await f.group_switch_command(Cmd('/group off nowhere'))
    check('an unknown name changes nothing', f.PAUSED_CHAT_IDS == [],
          str(f.PAUSED_CHAT_IDS))
    check('and says which names it knows',
          replies and 'piccaso' in replies[0].lower(), str(replies))

    reset()
    await f.group_switch_command(Cmd('/group off'))
    check('/group off with no name takes everything out',
          f.chat_paused(PICCASO) and f.chat_paused(GAFFER)
          and f.chat_paused(MHLARRY) and f.chat_paused(CHIMEREV),
          str(f.PAUSED_CHAT_IDS))
    await f.group_switch_command(Cmd('/group on'))
    check('and /group on brings it all back', f.PAUSED_CHAT_IDS == [],
          str(f.PAUSED_CHAT_IDS))

    reset(paused=[PICCASO, MHLARRY])
    replies.clear()
    await f.group_switch_command(Cmd('/group off piccaso'))
    check('asking for a state it is already in does nothing',
          any('already' in r.lower() for r in replies), str(replies))

    reset(paused=[PICCASO, MHLARRY])
    replies.clear()
    await f.group_switch_command(Cmd('/group'))
    check('bare /group reports both sides',
          replies and 'CHIME PICCASO' in replies[0] and 'CHIME GAFFER' in replies[0],
          str(replies))


async def test_permission():
    reset()
    await f.group_switch_command(Cmd('/group off piccaso', chat_id=CREW, uid=CREW,
                                     username='maynuddin23'))
    check('the crew cannot work it', f.PAUSED_CHAT_IDS == [], str(f.PAUSED_CHAT_IDS))
    check('and are not answered', replies == [] and dms == [],
          f"{replies} {dms}")

    reset()
    await f.group_switch_command(Cmd('/group off piccaso', chat_id=CHIMEREV,
                                     uid=CREW, username='maynuddin23'))
    check('nor from inside a group', f.PAUSED_CHAT_IDS == [], str(f.PAUSED_CHAT_IDS))
    check('and nothing is posted there', sent == [], str(sent))

    reset(paused=[PICCASO, MHLARRY])
    await f.group_switch_command(Cmd('/group on piccaso', chat_id=MHLARRY, uid=LARRY,
                                     username='larryyxx'))
    check('a group that is out of service ignores the command too',
          f.chat_paused(PICCASO), str(f.PAUSED_CHAT_IDS))
    check('and stays silent', sent == [] and replies == [], f"{sent} {replies}")

    # ...from a live group it works, and answers privately
    reset()
    await f.group_switch_command(Cmd('/group off piccaso', chat_id=CHIMEREV,
                                     uid=LARRY, username='larryyxx'))
    check('an admin can work it from a group still in service',
          f.chat_paused(PICCASO), str(f.PAUSED_CHAT_IDS))
    check('the answer goes to their DM, never the group',
          sent == [] and any('OUT OF SERVICE' in t for _c, t in dms),
          f"{sent} {dms}")


# --------------------------------------------------------------------------
# 2. it has to survive a redeploy
# --------------------------------------------------------------------------
async def test_marker():
    reset()
    await f.group_switch_command(Cmd('/group off piccaso'))
    written = markers()
    check('taking a group out writes the durable marker to both admins',
          sorted(c for c, t in dms if f.GROUP_PAUSE_MARK in t)
          == sorted([ETHAN, LARRY]),
          str([c for c, t in dms if f.GROUP_PAUSE_MARK in t]))
    check('the marker carries the state a machine can read',
          written and 'STATE ' in written[0], str(written))
    check('and both ids are in it',
          written and str(PICCASO) in written[0] and str(MHLARRY) in written[0],
          str(written))
    check('it names the groups for a person too',
          written and 'CHIME PICCASO' in written[0], str(written))
    check('nothing about it is posted in a group', sent == [], str(sent))

    reset(paused=[PICCASO, MHLARRY])
    await f.group_switch_command(Cmd('/group on piccaso'))
    written = markers()
    check('putting it back writes a marker too',
          sorted(c for c, t in dms if f.GROUP_RESUME_MARK in t)
          == sorted([ETHAN, LARRY]),
          str([c for c, t in dms if f.GROUP_RESUME_MARK in t]))
    check('whose state line is now empty',
          written and 'STATE \n' in written[0] + '\n', repr(written[0][-160:]))
    check('and which records WHEN it came back',
          written and 'RESUMED ' in written[0] and str(PICCASO) in
          written[0].split('RESUMED ')[1], repr(written[0][-160:]))


async def test_recovery():
    now = datetime.now(timezone.utc)

    # a redeploy: memory is empty, the marker is not
    reset()
    marker = f.group_switch_marker(True, [PICCASO, MHLARRY], [PICCASO, MHLARRY],
                                   '@larryyxx')
    await f.recover_group_switch(FakeClient({BOTID: [TeleMessage(marker, now)]}))
    check('a restart finds the groups still out of service',
          f.chat_paused(PICCASO) and f.chat_paused(MHLARRY), str(f.PAUSED_CHAT_IDS))
    check('and says so, privately',
          any('still out of' in t for t in admin_dms()), str(admin_dms()))

    # the newest marker wins
    reset(paused=[PICCASO, MHLARRY])
    older = f.group_switch_marker(True, [PICCASO], [PICCASO, MHLARRY], '@larryyxx')
    newer = f.group_switch_marker(False, [PICCASO, MHLARRY], [], '@larryyxx')
    await f.recover_group_switch(FakeClient(
        {BOTID: [TeleMessage(newer, now), TeleMessage(older, now - timedelta(hours=2))]}))
    check('a resume marker puts them back after a restart',
          f.PAUSED_CHAT_IDS == [], str(f.PAUSED_CHAT_IDS))
    check('and nobody is told about groups that are working',
          not any('out of service' in t.lower() for t in admin_dms()),
          str(admin_dms()))

    # somebody else's messages in the same DM are not markers
    reset()
    await f.recover_group_switch(FakeClient(
        {BOTID: [TeleMessage('⏸️ GROUPS OUT OF SERVICE fake', now, sender_id=LARRY)]}))
    check('a message from anyone but the bot is not a marker',
          f.PAUSED_CHAT_IDS == [], str(f.PAUSED_CHAT_IDS))

    # no marker at all: the boot default stands
    reset(paused=[PICCASO, MHLARRY])
    await f.recover_group_switch(FakeClient({BOTID: []}))
    check('with no marker the boot state is kept',
          f.chat_paused(PICCASO), str(f.PAUSED_CHAT_IDS))

    # unreadable: guess neither way
    for mode in ('entity', 'iter'):
        reset(paused=[PICCASO, MHLARRY])
        try:
            await asyncio.wait_for(
                f.recover_group_switch(FakeClient({}, explode=mode)), 2)
        except Exception as e:
            check(f'an unreadable chat ({mode}) does not propagate', False,
                  f'{type(e).__name__}: {e}')
            continue
        check(f'an unreadable chat ({mode}) leaves the switch alone',
              f.chat_paused(PICCASO), str(f.PAUSED_CHAT_IDS))
        check(f'and tells a person ({mode})',
              any('could not read back' in t for t in admin_dms()), str(admin_dms()))


# --------------------------------------------------------------------------
# 3. coming back must not replay the window
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


class SweepClient:
    def __init__(self, history):
        self.history = history

    async def get_entity(self, cid):
        if cid in self.history:
            return Entity(cid)
        raise ValueError(f'no entity {cid}')

    def iter_messages(self, entity, limit=None):
        async def gen():
            for m in self.history.get(entity.id, [])[:limit]:
                yield m
        return gen()


async def test_no_replay():
    reset(paused=[PICCASO, MHLARRY])
    f.utils.get_peer_id = lambda e: e.id
    src = Sender(777)
    history = {MHLARRY: [HistMsg(601, payment(30), 4, src),      # after it came back
                         HistMsg(600, payment(20), 60, src)],    # while it was off
               PICCASO: []}
    rules = dict(f.FORWARD_RULES)
    f.FORWARD_RULES.clear(); f.FORWARD_RULES[MHLARRY] = [PICCASO]
    try:
        # back in service ten minutes ago, from the command
        await f.group_switch_command(Cmd('/group on piccaso'))
        f.RESUMED_CHATS.update(f._parse_resume_marks(
            f"{MHLARRY}@{(datetime.now(timezone.utc) - timedelta(minutes=10)):%Y-%m-%dT%H:%M}"))

        # ...and now a deploy, so the sweep runs
        sent.clear()
        f._ledger[PICCASO] = {'in': 100.0, 'out': 20.0}
        await f.catch_up(SweepClient(history))
        landed = [t for c, t in sent if c == PICCASO]
        check('the sweep does not replay what happened while it was off',
              not any('$20.00' in t for t in landed), str(landed))
        check('but does deliver what it missed since coming back',
              len(landed) == 1 and '$30.00' in landed[0], str(landed))

        # the resume mark has to survive the redeploy too, in the marker
        marker = [t for t in markers() if f.GROUP_RESUME_MARK in t]
        check('the resume time is written into the marker', bool(marker), str(dms))
        reset()
        await f.recover_group_switch(FakeClient(
            {BOTID: [TeleMessage(marker[0], datetime.now(timezone.utc))]}))
        check('and is read back on the next boot',
              f.resumed_at(MHLARRY) is not None, str(f.RESUMED_CHATS))
    finally:
        f.FORWARD_RULES.clear(); f.FORWARD_RULES.update(rules)


async def test_undeliverable():
    """The DM is the record. If it cannot be delivered, say so plainly."""
    reset()
    f._user_ids.pop('ethannxxxx', None)
    f._user_ids.pop('larryyxx', None)
    await f.group_switch_command(Cmd('/group off piccaso'))
    check('the group still goes out of service at once', f.chat_paused(PICCASO),
          str(f.PAUSED_CHAT_IDS))
    check('and the reply warns it will not survive a redeploy',
          any('NOT survive a redeploy' in r for r in replies), str(replies))


async def main():
    print('group switch')
    await test_off_and_on()
    await test_naming()
    await test_permission()
    await test_marker()
    await test_recovery()
    await test_no_replay()
    await test_undeliverable()

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
