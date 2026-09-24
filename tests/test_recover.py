"""Open cashout requests are picked back up after a redeploy - quietly.

Open requests live in memory, so every deploy forgot them, and a crew /out
answering one then found nothing open and was not relayed. The groups are the
durable record: a request whose copy is still in the handling group, whose
original carries no ❤ and which no /out has answered is still owed.

The user's call on 2026-09-24: a recovered request WAITS QUIETLY. Nothing is
posted, nobody is re-tagged, the crew are not DMed. Ethan and Larry get one DM.

Also the sharp edge: both chime groups are BASIC groups, where each account
numbers messages its own way. The original's id was read by the user account,
so the bot must never be handed it - the ❤ goes through the account.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
GVENMO, LVENMO = -5100231154, -1004298140797
ETHAN, LARRY, CREW, ASKER = f.ETHAN_ID, f.LARRY_ID, 77, 4242
BOT = f.BOT_ID

sent, dms, copies, bot_hearts, user_hearts = [], [], [], [], []
_ids = [1000]
NOW = datetime.now(timezone.utc)

REQUEST = '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 150'
VENMO_REQUEST = '!! Cashout Request !!\nTag name : @michelle-surman-2\nAmount : 80'


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _ids[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text, reply_to_message_id))
        return FakeMsg(_ids[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        copies.append((chat_id, from_chat_id, message_id, caption))
        return FakeMsg(9500)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        bot_hearts.append((chat_id, message_id))
        return True

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        return True


# -- Telethon stand-ins ------------------------------------------------------

class Sender:
    def __init__(self, uid, username=None):
        self.id, self.username = uid, username


class Emoji:
    def __init__(self, emoticon):
        self.emoticon = emoticon


class Count:
    def __init__(self, emoticon):
        self.reaction, self.count = Emoji(emoticon), 1


class Reactions:
    def __init__(self, *emoticons):
        self.results = [Count(e) for e in emoticons]
        self.recent_reactions = []


class Msg:
    def __init__(self, mid, text, minutes_ago, sender_id, reply_to=None,
                 reactions=None, username=None):
        self.id, self.raw_text, self.message = mid, text, text
        self.date = NOW - timedelta(minutes=minutes_ago)
        self.sender_id = sender_id
        self.sender = Sender(sender_id, username)
        self.reply_to_msg_id = reply_to
        self.reactions = reactions


class Entity:
    def __init__(self, cid):
        self.id = cid


class FakeClient:
    def __init__(self, history, unreadable=()):
        self.history = history              # chat -> messages, NEWEST first
        self.unreadable = set(unreadable)

    async def get_entity(self, cid):
        for chat in list(self.history) + list(self.unreadable):
            if cid == chat or cid in f._id_variants(chat):
                if chat in self.unreadable:
                    raise ValueError('cannot see that chat')
                return Entity(chat)
        return Entity(cid)                  # a group with nothing in it

    def iter_messages(self, entity, limit=None):
        async def gen():
            for m in self.history.get(entity.id, [])[:limit]:
                yield m
        return gen()

    async def __call__(self, request):      # SendReactionRequest
        user_hearts.append((request.peer.id, request.msg_id))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = True
f._active_client = None
f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY, 'maynuddin23': CREW})

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); copies.clear(); bot_hearts.clear(); user_hearts.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._cashout_stopped = False
    f.ledger_commit(GAFFER, (500.0, 0.0))
    f.ledger_commit(GVENMO, (500.0, 0.0))


def chime(origin_id=301, minutes_ago=40, reactions=None, text=REQUEST):
    """The original, as the user account reads it in CHIME GAFFER."""
    return Msg(origin_id, text, minutes_ago, ASKER, reactions=reactions,
               username='asker')


def copy(copy_id=801, minutes_ago=39, text=REQUEST):
    """The bot's copy in the handling group, with the crew tag on the end."""
    return Msg(copy_id, f"{text}\n\n@Maynuddin23 @MHSUPPORTZONE", minutes_ago, BOT)


def admin_dm(fragment):
    return [t for c, t, _ in dms if fragment in t]


async def main():
    # -- 1. an unhearted, unanswered request comes back, quietly ------------
    reset()
    client = FakeClient({GAFFER: [chime()], CHIMEREV: [copy()]})
    f._active_client = client
    n = await f.recover_open_requests(client)
    queue = f._pending_cashouts.get(CHIMEREV, [])
    check('it is picked back up', n == 1 and len(queue) == 1, str(queue))
    req = queue[0] if queue else {}
    check('against the copy in the handling group', req.get('message_id') == 801)
    check('and the original in the chime group', req.get('origin_msg_id') == 301)
    check('marked as read by the user account', req.get('origin_via_user') is True)
    check('dated from when it was really asked',
          abs((req.get('opened', NOW) - (NOW - timedelta(minutes=39))).total_seconds()) < 1)
    check('nothing is posted into any group', sent == [], str(sent))
    told = admin_dm('Picked back up')
    check('both admin accounts get one DM', len(told) == 2, str(dms))
    check('naming the tag and the amount',
          told and '$jenny-buhr' in told[0] and '150.00$' in told[0], str(told))
    check('and saying nobody was re-tagged',
          told and 'not tagged again' in told[0], str(told))
    check('the crew are not DMed',
          not any(c == CREW for c, _, _ in dms), str(dms))

    # -- 2. the ladder stays silent ------------------------------------------
    dms.clear()
    await f.chase_cashout(CHIMEREV, req, 60.0)
    check('a watchdog pass posts no reminder', sent == [], str(sent))
    check('and DMs nobody', dms == [], str(dms))
    check('it is marked as already chased out', req['exhausted'] is True)

    # -- 3. the crew's /out now completes it as normal ------------------------
    dms.clear()
    await f.observe_cashout(CHIMEREV, '/out 150', 905, NOW, user_id=CREW,
                            username='Maynuddin23')
    check('the /out reaches CHIME GAFFER', any(c == GAFFER for c, _, _ in sent), str(sent))
    check('and is booked there', f.ledger_snapshot(GAFFER)[1] == 150.0,
          str(f.ledger_snapshot(GAFFER)))
    check('the request is closed', CHIMEREV not in f._pending_cashouts)
    check('the ❤ goes on the original through the user account',
          user_hearts == [(GAFFER, 301)], str(user_hearts))
    check('and NEVER through the bot, which numbers that group differently',
          bot_hearts == [], str(bot_hearts))
    check('no "not relayed" warning', admin_dm('WAS NOT RELAYED') == [], str(dms))

    # -- 4. a hearted original is settled -----------------------------------
    reset()
    client = FakeClient({GAFFER: [chime(reactions=Reactions('❤️'))],
                         CHIMEREV: [copy()]})
    n = await f.recover_open_requests(client)
    check('a ❤ on the original settles it', n == 0 and not f._pending_cashouts)
    check('and there is nothing to say', dms == [], str(dms))

    # A different reaction is not the ❤.
    reset()
    client = FakeClient({GAFFER: [chime(reactions=Reactions('👍'))],
                         CHIMEREV: [copy()]})
    check('a 👍 on the original does not settle it',
          await f.recover_open_requests(client) == 1)

    # -- 5. answered, but the ❤ never landed ---------------------------------
    reset()
    answered = [Msg(802, '/out 150', 20, CREW, username='Maynuddin23'), copy()]
    client = FakeClient({GAFFER: [chime()], CHIMEREV: answered})
    n = await f.recover_open_requests(client)
    check('a request a /out answered is not re-opened', n == 0 and not f._pending_cashouts)
    flagged = admin_dm('never marked')
    check('but the admins are told it has no ❤', len(flagged) == 2, str(dms))
    check('naming which one', flagged and '$jenny-buhr' in flagged[0], str(flagged))

    # Ethan's own /out, with nothing open at the time, counts the same way.
    reset()
    answered = [Msg(803, '/out 150', 20, ETHAN, username='ethannxxxx'), copy()]
    client = FakeClient({GAFFER: [chime()], CHIMEREV: answered})
    check("Ethan's /out settles it too", await f.recover_open_requests(client) == 0)

    # -- 6. the bot's own reminder says "/out" and answers nothing ----------
    reset()
    nudged = [Msg(804, 'This cashout request is still waiting on a /out.', 30, BOT,
                  reply_to=801), copy()]
    client = FakeClient({GAFFER: [chime()], CHIMEREV: nudged})
    check("the bot's reminder is not read as the answer",
          await f.recover_open_requests(client) == 1)

    # -- 7. a deleted original means withdrawn --------------------------------
    reset()
    client = FakeClient({GAFFER: [], CHIMEREV: [copy()]})
    n = await f.recover_open_requests(client)
    check('with the original gone it stays closed', n == 0 and not f._pending_cashouts)
    check('and nobody is DMed about a withdrawn request', dms == [], str(dms))

    # -- 8. a group that cannot be read recovers nothing, and says so -------
    reset()
    client = FakeClient({GAFFER: [chime()]}, unreadable=[CHIMEREV])
    n = await f.recover_open_requests(client)
    check('nothing is recovered from a group it cannot read',
          n == 0 and not f._pending_cashouts)
    unread = admin_dm('Could not read')
    check('and the admins are told which pair', len(unread) == 2
          and 'Chime Rev' in unread[0], str(dms))

    # -- 9. a reconnect in the same process does not double it --------------
    reset()
    client = FakeClient({GAFFER: [chime()], CHIMEREV: [copy()]})
    await f.recover_open_requests(client)
    await f.recover_open_requests(client)
    check('running twice leaves one request',
          len(f._pending_cashouts.get(CHIMEREV, [])) == 1, str(f._pending_cashouts))

    # -- 10. too old to come back --------------------------------------------
    reset()
    old = f.CASHOUT_RECOVER_HOURS * 60 + 30
    client = FakeClient({GAFFER: [chime(minutes_ago=old + 1)],
                         CHIMEREV: [copy(minutes_ago=old)]})
    check('a request older than the window is left alone',
          await f.recover_open_requests(client) == 0)

    # -- 11. two open, one paid: only the unpaid one comes back ------------
    reset()
    second = '!! Cashout Request !!\nTag name : $Hawkins-Floral-Decor\nAmount : 60'
    client = FakeClient({
        GAFFER: [chime(302, 30, text=second), chime(301, 40)],
        CHIMEREV: [Msg(805, '/out 60', 10, CREW, username='Maynuddin23'),
                   copy(806, 29, text=second), copy(801, 39)]})
    await f.recover_open_requests(client)
    queue = f._pending_cashouts.get(CHIMEREV, [])
    check('the /out settles the request it PAID, not the oldest',
          [r['origin_msg_id'] for r in queue] == [301], str(queue))

    # -- 12. the venmo route recovers the same way ---------------------------
    reset()
    client = FakeClient({GVENMO: [chime(401, 40, text=VENMO_REQUEST)],
                         LVENMO: [copy(901, 39, text=VENMO_REQUEST)]})
    f._active_client = client
    check('a venmo request comes back', await f.recover_open_requests(client) == 1)
    await f.observe_cashout(LVENMO, '/out 80', 906, NOW, user_id=CREW,
                            username='Maynuddin23')
    check('and its /out reaches GAFFER VENMO',
          any(c == GVENMO for c, _, _ in sent), str(sent))
    check('hearted through the account', user_hearts == [(GVENMO, 401)], str(user_hearts))

    # -- 13. an edit down the BOT path does not open a second request ------
    # The bot knows the original by its own id, which the recovered request
    # does not have. Without the tag match this would post a fresh copy and
    # tag the crew over a cashout already in hand.
    reset()
    client = FakeClient({GAFFER: [chime()], CHIMEREV: [copy()]})
    f._active_client = client
    await f.recover_open_requests(client)
    sent.clear(); dms.clear()
    edited = REQUEST.replace('150', '175')
    await f.observe_cashout(GAFFER, edited, 55555, NOW, user_id=ASKER, is_edit=True)
    queue = f._pending_cashouts.get(CHIMEREV, [])
    check('the edit updates the recovered request',
          len(queue) == 1 and '175' in queue[0]['text'], str(queue))
    check('no fresh copy of the request is posted',
          not any(c == CHIMEREV and 'Cashout Request' in t and r is None
                  for c, t, r in sent), str(sent))
    to_chime = [(t, r) for c, t, r in sent if c == GAFFER]
    check('the note back to the chime group is NOT a reply by the account\'s id',
          to_chime and all(r is None for _, r in to_chime), str(to_chime))

    f._active_client = None
    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
