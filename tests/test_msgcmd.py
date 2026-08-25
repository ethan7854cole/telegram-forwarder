"""/del and /edit — Ethan and Larry acting on messages through the bot.

Larry is NOT a Telegram administrator in Chime Rev & out no-7, and may not be
in groups added later, so he cannot remove a message by hand however obviously
it needs removing. The bot IS an administrator everywhere, so it does it for
him — including messages posted by other bots.

The one thing worth refusing: a message carrying BOTH running totals.
recover_ledgers() rebuilds each group's books from the newest of those, so
removing one reverts the books at the next deploy — later, silently, and
nowhere near the action that caused it.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ['PAUSED_CHATS'] = ''
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

GAFFER, CHIMEREV = -5580596463, -1002335630148
ETHAN, LARRY, MAY = f.ETHAN_ID, f.LARRY_ID, 77
BOTID = 111222
OTHERBOT = 555

replies, dms, deleted, edits, admin = [], [], [], [], []
failures = []
delete_error = [None]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        dms.append((chat_id, text))
        return FakeMsg(4000 + len(dms))

    async def reply_to(self, message, text):
        replies.append(text)
        return FakeMsg(4100)

    async def delete_message(self, chat_id, message_id):
        if delete_error[0]:
            raise RuntimeError(delete_error[0])
        deleted.append((chat_id, message_id))
        return True

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        edits.append((chat_id, message_id, text))
        return FakeMsg(message_id)


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f.BOT_ID = BOTID


async def fake_notify(text):
    admin.append(text)


f.notify_admin = fake_notify


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    replies.clear(); dms.clear(); deleted.clear(); edits.clear(); admin.clear()
    delete_error[0] = None
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY})


class User:
    def __init__(self, uid, username=None):
        self.id, self.username = uid, username
        self.first_name = self.last_name = None


class Chat:
    def __init__(self, cid):
        self.id = cid


class Message:
    """A /del or /edit typed as a reply."""
    def __init__(self, text, user, chat=CHIMEREV, reply=None, mid=300):
        self.text, self.from_user = text, user
        self.chat, self.reply_to_message, self.message_id = Chat(chat), reply, mid
        self.caption = None


def target(mid=200, sender=BOTID, text='⏰ OUT REQUEST HAS CROSSED 5 MINUTES'):
    t = Message(text, User(sender), mid=mid)
    return t


LEDGER_MSG = ('You received $15.00 from Gabriel W.\n'
              'Total In : 1,265.00$\nTotal Out:   340.00$')


# --------------------------------------------------------------------------
async def test_who_may():
    for who, name in ((ETHAN, 'Ethan'), (LARRY, 'Larry')):
        reset()
        await f.message_command(Message('/del', User(who), reply=target()))
        check(f'{name} can delete', (CHIMEREV, 200) in deleted, str(deleted))

    reset()
    await f.message_command(Message('/del', User(MAY, 'Maynuddin23'),
                                    reply=target()))
    check('a crew member cannot', deleted == [], str(deleted))
    check('and is told so plainly',
          replies and 'Not permitted' in replies[0], str(replies))

    reset()
    f.set_paused_chats([CHIMEREV])
    try:
        await f.message_command(Message('/del', User(ETHAN), reply=target()))
        check('a paused group gets no action and no refusal',
              deleted == [] and replies == [], str(replies))
    finally:
        f.set_paused_chats([])


async def test_deleting():
    reset()
    cmd = Message('/del', User(ETHAN, 'ethannxxxx'), reply=target(), mid=301)
    await f.message_command(cmd)
    check('the target goes', (CHIMEREV, 200) in deleted, str(deleted))
    check('and so does the /del itself', (CHIMEREV, 301) in deleted, str(deleted))
    check('nothing is left in the group', replies == [], str(replies))
    check('the person who ran it is told privately',
          [t for c, t in dms if c == ETHAN and 'Deleted' in t], str(dms))
    check('and the other one is not', [c for c, _ in dms if c == LARRY] == [],
          str(dms))

    # Another bot's message - the whole reason this exists.
    reset()
    await f.message_command(Message('/del', User(LARRY, 'larryyxx'),
                                    reply=target(mid=210, sender=OTHERBOT)))
    check("another bot's message can be deleted too",
          (CHIMEREV, 210) in deleted, str(deleted))

    reset()
    delete_error[0] = 'Bad Request: message can\'t be deleted'
    await f.message_command(Message('/del', User(ETHAN), reply=target()))
    check('a refusal from Telegram is reported, not swallowed',
          replies and 'Could not delete it' in replies[0], str(replies))
    check('and it says what the bot would need',
          replies and 'administrator' in replies[0], str(replies))


async def test_editing():
    reset()
    cmd = Message('/edit still waiting, sorry', User(LARRY, 'larryyxx'),
                  reply=target(), mid=302)
    await f.message_command(cmd)
    check('the bot rewrites its own message',
          edits == [(CHIMEREV, 200, 'still waiting, sorry')], str(edits))
    check('the /edit command goes', (CHIMEREV, 302) in deleted, str(deleted))
    check('and the target is NOT deleted',
          (CHIMEREV, 200) not in deleted, str(deleted))

    reset()
    await f.message_command(Message('/edit nope', User(ETHAN),
                                    reply=target(mid=210, sender=OTHERBOT)))
    check("another bot's message cannot be edited", edits == [], str(edits))
    check('and the reason given is Telegram\'s, not ours',
          replies and 'no account to edit' in replies[0], str(replies))
    check('with the workaround named',
          replies and '/del' in replies[0], str(replies))

    reset()
    await f.message_command(Message('/edit', User(ETHAN), reply=target()))
    check('an /edit with no text asks for some',
          replies and 'Usage: /edit' in replies[0], str(replies))


async def test_needs_a_reply():
    reset()
    await f.message_command(Message('/del', User(ETHAN)))
    check('with nothing replied to, it explains itself',
          replies and 'Reply to the message' in replies[0], str(replies))
    check('and nothing is deleted', deleted == [], str(deleted))


async def test_the_ledger_guard():
    reset()
    await f.message_command(Message('/del', User(ETHAN),
                                    reply=target(text=LEDGER_MSG)))
    check('a message carrying both totals is refused', deleted == [], str(deleted))
    check('the refusal shows the figures',
          replies and '1,265.00$ in' in replies[0] and '340.00$ out' in replies[0],
          str(replies))
    check('and says WHEN it would bite',
          replies and 'next time the bot restarts' in replies[0], str(replies))
    check('and offers the way through',
          replies and '/del force' in replies[0], str(replies))

    reset()
    await f.message_command(Message('/edit Total In : 1\nTotal Out: 1', User(ETHAN),
                                    reply=target(text=LEDGER_MSG)))
    check('rewriting one is refused too', edits == [], str(edits))
    check('and points at /set instead',
          replies and '/set' in replies[0], str(replies))

    reset()
    await f.message_command(Message('/del force', User(LARRY, 'larryyxx'),
                                    reply=target(text=LEDGER_MSG), mid=303))
    check('force goes through', (CHIMEREV, 200) in deleted, str(deleted))
    check('the confirmation warns what it did',
          [t for c, t in dms if c == LARRY and 'read differently' in t], str(dms))
    check('and Ethan is told either way, since it is his books too',
          admin and 'force' in admin[0], str(admin))

    # An ordinary message with only ONE total is not a ledger message.
    reset()
    await f.message_command(Message('/del', User(ETHAN),
                                    reply=target(text='Total Out: 340.00$')))
    check('one total alone is not the ledger message',
          (CHIMEREV, 200) in deleted, str(deleted))


async def test_other_groups():
    reset()
    await f.message_command(Message('/del', User(LARRY), chat=GAFFER,
                                    reply=target(), mid=304))
    check('it works in a chime group as well',
          (GAFFER, 200) in deleted, str(deleted))


# --------------------------------------------------------------------------
# The private-chat form: a named group, a numbered menu, then one of them.
# @ethannxxxx is in none of the handling groups, so this is the only route in.

class HistMsg:
    def __init__(self, mid, text, sender_id, when, media=None):
        self.id, self.raw_text, self.date = mid, text, when
        self.sender_id, self.media = sender_id, media
        self.sender = User(sender_id, 'Maynuddin23' if sender_id == MAY else None)
        self.message = text


class FakeEntity:
    def __init__(self, cid): self.id = cid


class FakeClient:
    def __init__(self, history, fail=False):
        self.history, self.fail = history, fail
    async def get_entity(self, cid):
        if self.fail:
            raise ValueError('no entity')
        return FakeEntity(cid)
    def iter_messages(self, entity, limit=None):
        async def gen():
            for m in self.history[:limit]:
                yield m
        return gen()


def history():
    from datetime import datetime, timezone
    at = datetime(2026, 8, 25, 3, 40, tzinfo=timezone.utc)
    return [
        HistMsg(500, '⏰ OUT REQUEST HAS CROSSED 5 MINUTES', BOTID, at),
        HistMsg(501, 'sending it now boss', MAY, at),
        HistMsg(502, LEDGER_MSG, BOTID, at),
        HistMsg(503, '', OTHERBOT, at, media=object()),
    ]


def dm(text, user=None):
    """A private chat: the chat id IS the sender's id."""
    uid = ETHAN if user is None else user
    return Message(text, User(uid, 'ethannxxxx'), chat=uid, mid=400)


async def test_dm_listing():
    reset()
    f._active_client = FakeClient(history())
    f._del_listings.clear()
    try:
        await f.message_command(dm('/del rev'))
        check('the menu is sent', len(replies) == 1, str(replies))
        menu = replies[0] if replies else ''
        check('it names the group', 'Chime Rev & out no-7' in menu, menu)
        check('it lists the bot\'s message', '1. [the bot]' in menu, menu)
        check("and the CREW's, which is the point",
              '2. [@Maynuddin23]' in menu and 'sending it now boss' in menu, menu)
        check("and another bot's media", '[media]' in menu, menu)
        check('a totals message is flagged in the menu',
              'carries the totals' in menu, menu)
        check('nothing is deleted just by looking', deleted == [], str(deleted))

        # The crew's message, by number.
        replies.clear()
        await f.message_command(dm('/del rev 2'))
        check('picking 2 deletes the crew message',
              (CHIMEREV, 501) in deleted, str(deleted))
        check('and says what went',
              replies and 'sending it now boss' in replies[0], str(replies))
        check('the menu is dropped afterwards',
              f._del_listings == {}, str(f._del_listings))
    finally:
        f._active_client = None


async def test_dm_guards():
    reset()
    f._del_listings.clear()
    f._active_client = FakeClient(history())
    try:
        # The ledger guard applies here too.
        await f.message_command(dm('/del rev'))
        replies.clear()
        await f.message_command(dm('/del rev 3'))
        check('a totals message is refused from a DM too',
              deleted == [], str(deleted))
        check('and the override is spelled out',
              replies and '/del rev 3 force' in replies[0], str(replies))
        await f.message_command(dm('/del rev 3 force'))
        check('force goes through', (CHIMEREV, 502) in deleted, str(deleted))
        check('and the admin account is told', admin and 'force' in admin[0], str(admin))

        # Numbering can only ever act on the id it showed.
        reset(); f._del_listings.clear()
        await f.message_command(dm('/del rev'))
        replies.clear()
        await f.message_command(dm('/del rev 9'))
        check('an out-of-range number is refused',
              deleted == [] and replies and 'Pick 1 to' in replies[0], str(replies))

        # A stale menu is not acted on.
        reset(); f._del_listings.clear()
        await f.message_command(dm('/del rev'))
        f._del_listings[ETHAN]['at'] -= __import__('datetime').timedelta(hours=1)
        replies.clear()
        await f.message_command(dm('/del rev 1'))
        check('a stale menu is refused, not guessed at',
              deleted == [] and replies and 'minutes old' in replies[0], str(replies))

        # Acting before listing.
        reset(); f._del_listings.clear()
        await f.message_command(dm('/del rev 1'))
        check('a number with no menu asks for one first',
              deleted == [] and replies and 'first' in replies[0], str(replies))

        # One person's menu is not the other's.
        reset(); f._del_listings.clear()
        await f.message_command(dm('/del rev'))
        replies.clear()
        await f.message_command(dm('/del rev 1', user=LARRY))
        check("the other account cannot pick from a menu it never saw",
              deleted == [] and replies and 'first' in replies[0], str(replies))
    finally:
        f._active_client = None


async def test_both_accounts():
    """Both accounts, both forms. They are one person, and either may be the
    one holding the phone."""
    for who, name in ((ETHAN, '@ethannxxxx'), (LARRY, '@Larryyxx')):
        reset()
        f._del_listings.clear()
        f._active_client = FakeClient(history())
        try:
            await f.message_command(Message('/del', User(who), chat=who, mid=400))
            check(f'{name}: the private menu opens', replies and '1. [the bot]'
                  not in replies[0], str(replies))   # no group named -> usage
            replies.clear()
            await f.message_command(Message('/del rev', User(who), chat=who, mid=401))
            check(f'{name}: /del rev lists the group',
                  replies and 'Chime Rev' in replies[0], str(replies))
            replies.clear()
            await f.message_command(Message('/del rev 2', User(who), chat=who, mid=402))
            check(f'{name}: and can remove the crew message',
                  (CHIMEREV, 501) in deleted, str(deleted))
        finally:
            f._active_client = None

    # In a group, both may run it - but only where the account is a member,
    # which is a Telegram fact the bot cannot do anything about.
    for who, name in ((ETHAN, '@ethannxxxx'), (LARRY, '@Larryyxx')):
        reset()
        await f.message_command(Message('/del', User(who), chat=GAFFER,
                                        reply=target(), mid=403))
        check(f'{name}: the in-group form works where it can type',
              (GAFFER, 200) in deleted, str(deleted))


async def test_dm_needs_the_userbot():
    reset()
    f._active_client = None
    f._del_listings.clear()
    await f.message_command(dm('/del rev'))
    check('with no user account it says so plainly',
          replies and 'user account is not connected' in replies[0], str(replies))
    check('and does not pretend the group is empty',
          replies and 'Nothing readable' not in replies[0], str(replies))

    reset()
    f._del_listings.clear()
    await f.message_command(dm('/del nosuchgroup'))
    check('an unknown group lists the ones that work',
          replies and 'chimerev' in replies[0] and 'gaffer' in replies[0],
          str(replies))
    await f.message_command(dm('/del'))
    check('and so does no group at all',
          len(replies) == 2 and 'Usage:' in replies[1], str(replies))


async def test_dm_editing():
    reset()
    f._active_client = FakeClient(history())
    f._del_listings.clear()
    try:
        await f.message_command(dm('/del rev'))
        replies.clear()
        await f.message_command(dm('/edit rev 1 quieter wording'))
        check('the bot rewrites its own message from a DM',
              edits == [(CHIMEREV, 500, 'quieter wording')], str(edits))

        reset(); f._del_listings.clear()
        await f.message_command(dm('/del rev'))
        replies.clear()
        await f.message_command(dm('/edit rev 2 nope'))
        check("the crew's message cannot be edited", edits == [], str(edits))
        check('and /del is offered instead',
              replies and '/del rev 2' in replies[0], str(replies))
    finally:
        f._active_client = None


# --------------------------------------------------------------------------
async def main():
    await test_who_may()
    await test_deleting()
    await test_editing()
    await test_needs_a_reply()
    await test_the_ledger_guard()
    await test_other_groups()
    await test_dm_listing()
    await test_dm_guards()
    await test_both_accounts()
    await test_dm_needs_the_userbot()
    await test_dm_editing()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("message-command suite passed")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
