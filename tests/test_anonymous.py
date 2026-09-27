"""Ethan and Larry keep their access when they post as an anonymous admin.

Telegram hides an anonymous admin behind the group itself. Larry is one in
MH x LARRY VENMO, so until 2026-09-27 nothing he did there reached the bot as
him: a retraction that worked in Chime Rev silently did nothing in venmo, and
his /out, /del, /edit and the rest were read as nobody's.

The user's rule: the same access through the bot in every group - for Ethan
and Larry ONLY. So an anonymous post is theirs only when every anonymous admin
in that chat is one of them. Anybody else anonymous there too, and nothing is
attributed.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace as NS

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telebot.types import Update

import forwarder as f

GVENMO, LVENMO = -5100231154, -1004298140797
CHIMEREV = -1002335630148
ETHAN, LARRY, CREW, OWNER = f.ETHAN_ID, f.LARRY_ID, 77, 6030387329
BOT = 8614082158
ANON_BOT = 1087968824          # GroupAnonymousBot, what the Bot API shows

sent, dms = [], []
_ids = [1000]
failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def admin(uid, anonymous):
    return NS(user=NS(id=uid), is_anonymous=anonymous)


# The live list in MH x LARRY VENMO on 2026-09-27, and in Chime Rev, where the
# BOT is the anonymous one and Larry is an ordinary member.
VENMO_ADMINS = [admin(BOT, False), admin(LARRY, True), admin(OWNER, False)]
CHIMEREV_ADMINS = [admin(BOT, True)]


class FakeBot:
    admins = {}
    calls = 0

    async def get_chat_administrators(self, chat_id):
        FakeBot.calls += 1
        found = self.admins.get(chat_id, [])
        if isinstance(found, Exception):
            raise found
        return found

    async def send_message(self, chat_id, text, reply_to_message_id=None, **kw):
        _ids[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return NS(message_id=_ids[0])

    async def reply_to(self, message, text, **kw):
        sent.append((message.chat.id, text))

    async def set_message_reaction(self, *a, **k):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = False
f._active_client = None


def reset(admins=None):
    sent.clear(); dms.clear()
    f._anon_admin_cache.clear()
    f._pending_cashouts.clear(); f._seen_messages.clear()
    f._cashout_claims.clear(); f._ledger.clear()
    f._cashout_stopped = False
    f.bot.admins = admins if admins is not None else {LVENMO: VENMO_ADMINS,
                                                       CHIMEREV: CHIMEREV_ADMINS}
    FakeBot.calls = 0


def update(chat_id, text, chat_type='supergroup', sender_chat=None,
           from_id=ANON_BOT, from_username='GroupAnonymousBot', mid=500):
    """A real telebot Update, built from the JSON Telegram actually sends."""
    message = {
        'message_id': mid, 'date': int(datetime.now(timezone.utc).timestamp()),
        'chat': {'id': chat_id, 'type': chat_type, 'title': 'x'},
        'from': {'id': from_id, 'is_bot': from_id == ANON_BOT,
                 'first_name': 'Group', 'username': from_username},
        'text': text,
    }
    if sender_chat is not None:
        message['sender_chat'] = {'id': sender_chat, 'type': chat_type, 'title': 'x'}
    return Update.de_json({'update_id': mid, 'message': message})


async def dispatch(*updates):
    """Run the real attribution wrapper, then hand each message to /out."""
    seen = []

    async def raw(batch):
        for u in batch:
            seen.append(u.message)
            await f.ledger_command(u.message)

    f._process_new_updates_raw = raw
    await f._process_new_updates_attributed(list(updates))
    return seen


def event(chat_id, sender_id, is_group=True):
    return NS(chat_id=chat_id, is_group=is_group,
              message=NS(sender_id=sender_id))


async def main():
    # -- 1. Larry, anonymous in venmo, is Larry again -----------------------
    reset()
    msg = (await dispatch(update(LVENMO, '/out 25', sender_chat=LVENMO)))[0]
    check('an anonymous post in venmo is read as Larry',
          msg.from_user.id == LARRY and msg.from_user.username == 'Larryyxx',
          str(vars(msg.from_user)))
    check('as a person, not a bot', msg.from_user.is_bot is False)
    # The interaction, not just the unit: his /out with nothing open is the
    # admin's force-complete, relayed and booked exactly as in Chime Rev.
    check('his /out reaches GAFFER VENMO',
          any(c == GVENMO for c, _ in sent), str(sent))
    check('and books Total Out there', f.ledger_snapshot(GVENMO)[1] == 25.0,
          str(f.ledger_snapshot(GVENMO)))

    # -- 2. ONLY Ethan and Larry --------------------------------------------
    reset({LVENMO: VENMO_ADMINS + [admin(CREW, True)]})
    msg = (await dispatch(update(LVENMO, '/out 25', sender_chat=LVENMO)))[0]
    check('not when a crew member is anonymous there too',
          msg.from_user.id == ANON_BOT, str(msg.from_user.id))
    check('so nothing reaches GAFFER VENMO',
          not any(c == GVENMO for c, _ in sent), str(sent))
    check('and nothing is booked', f.ledger_snapshot(GVENMO) == (0.0, 0.0),
          str(f.ledger_snapshot(GVENMO)))

    reset({LVENMO: VENMO_ADMINS[:1] + [admin(ETHAN, True), admin(LARRY, True)]})
    msg = (await dispatch(update(LVENMO, 'hi', sender_chat=LVENMO)))[0]
    check('both admins anonymous is still one of them',
          msg.from_user.id in (ETHAN, LARRY), str(msg.from_user.id))

    reset({LVENMO: [admin(LARRY, False)]})
    msg = (await dispatch(update(LVENMO, 'hi', sender_chat=LVENMO)))[0]
    check('nobody anonymous: nothing attributed', msg.from_user.id == ANON_BOT)

    reset({LVENMO: RuntimeError('chat not found')})
    msg = (await dispatch(update(LVENMO, 'hi', sender_chat=LVENMO)))[0]
    check('admin list unreadable: nothing attributed, nothing crashes',
          msg.from_user.id == ANON_BOT)

    # -- 3. the bot's own anonymity in Chime Rev ---------------------------
    # The bot is the anonymous admin there. Its own posts must never be read
    # as Larry's - its /out relay would otherwise be a /out from an admin.
    reset()
    check('Chime Rev: the bot being anonymous attributes nothing',
          await f.anonymous_telethon_sender(event(CHIMEREV, CHIMEREV)) is None)

    # -- 4. what an anonymous admin is NOT ---------------------------------
    reset()
    msg = (await dispatch(update(LVENMO, 'hi', sender_chat=-1009999999)))[0]
    check('posting as some other channel is nobody',
          msg.from_user.id == ANON_BOT)
    msg = (await dispatch(update(LVENMO, 'hi', from_id=CREW,
                                 from_username='Maynuddin23')))[0]
    check('an ordinary member is left exactly as they are',
          msg.from_user.id == CREW and FakeBot.calls == 0, str(FakeBot.calls))
    msg = (await dispatch(update(-1001111111111, 'hi', chat_type='channel',
                                 sender_chat=-1001111111111)))[0]
    check('a channel post is the channel', msg.from_user.id == ANON_BOT)

    # -- 5. the userbot path reads the same way ----------------------------
    reset()
    who = await f.anonymous_telethon_sender(event(LVENMO, LVENMO))
    check('userbot: anonymous post in venmo is Larry',
          who is not None and who.id == LARRY and who.username == 'Larryyxx')
    check('userbot: the short id spelling matches too',
          (await f.anonymous_telethon_sender(event(LVENMO, -4298140797))) is not None)
    check('userbot: an ordinary sender is left alone',
          await f.anonymous_telethon_sender(event(LVENMO, CREW)) is None)
    check('userbot: a broadcast channel is never a person',
          await f.anonymous_telethon_sender(event(LVENMO, LVENMO, is_group=False)) is None)

    # -- 6. one lookup serves a burst, and does not outlive its window -----
    reset()
    for _ in range(5):
        await f.anonymous_ledger_admin(LVENMO)
    check('the admin list is asked once for a burst', FakeBot.calls == 1,
          str(FakeBot.calls))
    f.bot.admins = {LVENMO: VENMO_ADMINS + [admin(CREW, True)]}
    stamp, who = f._anon_admin_cache[LVENMO]
    f._anon_admin_cache[LVENMO] = (stamp - f.ANON_ADMIN_CACHE_SECONDS - 1, who)
    check('a crew member turning anonymous is picked up once it expires',
          await f.anonymous_ledger_admin(LVENMO) is None)

    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print('all checks passed')


asyncio.run(main())
