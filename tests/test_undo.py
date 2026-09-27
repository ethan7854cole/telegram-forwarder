"""Reply /undo to a payment: the same as reacting to it.

Larry is an anonymous admin in MH x LARRY VENMO, and Telegram rejects a
reaction made as the group there - it shows for half a second and vanishes,
and the bot never hears of it (screen recording, 2026-09-27). His messages do
arrive, so a reply names the payment where a reaction cannot.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace as NS

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ.pop('RETRACT_SOURCES', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telebot.types import Update

import forwarder as f

CHIMEREV, GAFFER = -1002335630148, -5580596463
MHLARRY = -1003894781195
LVENMO, GVENMO = -1004298140797, -5100231154
ETHAN, LARRY, CREW, OWNER = f.ETHAN_ID, f.LARRY_ID, 77, 6030387329
BOT = 8614082158
ANON_BOT = 1087968824

NOW = datetime(2026, 9, 27, 5, 43, tzinfo=timezone.utc)
PAYMENT = ("🟢 Hi Robert-Nettles-27,\n\nYou received $200.0 from Thomas Doherty\n\n"
           "11:28 AM - 27 Sep 2026\n➕ Total In : 11372.44$\n➖ Total Out: 2745.00$")

sent, dms, deleted, reactions = [], [], [], []
_ids = [4000]
failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


class FakeBot:
    fail_react = False
    admins = {LVENMO: [NS(user=NS(id=BOT), is_anonymous=False),
                       NS(user=NS(id=LARRY), is_anonymous=True),
                       NS(user=NS(id=OWNER), is_anonymous=False)]}

    async def send_message(self, chat_id, text, reply_to_message_id=None, **kw):
        _ids[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return NS(message_id=_ids[0])

    async def delete_message(self, chat_id, message_id):
        deleted.append((chat_id, message_id))
        return True

    async def set_message_reaction(self, chat_id, message_id, reaction):
        if self.fail_react:
            raise RuntimeError('REACTION_INVALID')
        reactions.append((chat_id, message_id, reaction[0].emoji))
        return True

    async def get_chat_administrators(self, chat_id):
        return self.admins.get(chat_id, [])


REAL_BOT = f.bot
f.bot = FakeBot()
f.BOT_ID = BOT
f.USERBOT_SEND = False
f._active_client = None


def reset():
    sent.clear(); dms.clear(); deleted.clear(); reactions.clear()
    f._ledger.clear(); f._delivered.clear(); f._seen_messages.clear()
    f._anon_admin_cache.clear()
    f.bot.fail_react = False
    for chat in (GAFFER, GVENMO):
        f.ledger_commit(chat, (11172.44, 2745.0))


async def forward(source, mid, text=PAYMENT):
    await f.process_incoming(source, text, 'test', from_bot=True, sent_at=NOW,
                             source_msg_id=mid)


def copy_id(target):
    """The id the fake bot gave the forwarded copy in `target`."""
    return next((tid for entries in f._delivered.values()
                 for t, tid, _, _ in entries if t == target), None)


def undo(chat, uid, reply_to=None, reply_text=PAYMENT, mid=9000):
    reply = (NS(message_id=reply_to, text=reply_text)
             if reply_to is not None else None)
    return NS(chat=NS(id=chat, type='supergroup'), message_id=mid,
              from_user=NS(id=uid, username=None, is_bot=False),
              text='/undo', reply_to_message=reply)


def said(uid):
    return [t for c, t in dms if c == uid]


async def main():
    # -- 1. Larry replies /undo to a venmo payment --------------------------
    reset()
    await forward(LVENMO, 700)
    vcopy = copy_id(GVENMO)
    sent.clear()
    await f.undo_command(undo(LVENMO, LARRY, reply_to=700))
    check('the copy in GAFFER VENMO is deleted', (GVENMO, vcopy) in deleted,
          str(deleted))
    check('and 200 comes back off its Total In',
          f.ledger_snapshot(GVENMO) == (11172.44, 2745.0),
          str(f.ledger_snapshot(GVENMO)))
    check('the correction reads like /add -200 there',
          any(c == GVENMO and t.startswith('✏️ Total In adjusted by -200.00$')
              for c, t in sent), str(sent))
    check('the bot marks the original with its own reaction',
          reactions == [(LVENMO, 700, f.UNDO_MARK)], str(reactions))
    check('the /undo itself is removed from the group', (LVENMO, 9000) in deleted,
          str(deleted))
    check('Larry is told privately what happened',
          any('Undone: 200.00$' in t and 'GAFFER VENMO' in t for t in said(LARRY)),
          str(dms))
    check('nothing is posted in MH x LARRY VENMO',
          not any(c == LVENMO for c, _ in sent), str(sent))

    # -- 2. a second /undo on the same payment does nothing ----------------
    sent.clear(); reactions.clear(); dms.clear()
    await f.undo_command(undo(LVENMO, LARRY, reply_to=700))
    check('a second /undo moves nothing',
          f.ledger_snapshot(GVENMO) == (11172.44, 2745.0))
    check('and says it was already taken back',
          any('Nothing undone' in t and 'already taken back' in t
              for t in said(LARRY)), str(dms))
    check('and adds no second mark', reactions == [], str(reactions))

    # -- 3. the whole way in, as the anonymous admin Larry really is -------
    reset()
    await forward(LVENMO, 701)
    vcopy = copy_id(GVENMO)
    upd = Update.de_json({'update_id': 1, 'message': {
        'message_id': 9001, 'date': int(NOW.timestamp()),
        'chat': {'id': LVENMO, 'type': 'supergroup', 'title': 'MH x Larry venmo'},
        'sender_chat': {'id': LVENMO, 'type': 'supergroup', 'title': 'MH x Larry venmo'},
        'from': {'id': ANON_BOT, 'is_bot': True, 'first_name': 'Group',
                 'username': 'GroupAnonymousBot'},
        'text': '/undo',
        'entities': [{'type': 'bot_command', 'offset': 0, 'length': 5}],
        'reply_to_message': {
            'message_id': 701, 'date': int(NOW.timestamp()),
            'chat': {'id': LVENMO, 'type': 'supergroup', 'title': 'x'},
            'from': {'id': 555, 'is_bot': True, 'first_name': 'Notifier'},
            'text': PAYMENT}}})

    async def raw(batch):
        for u in batch:
            await f.undo_command(u.message)

    f._process_new_updates_raw = raw
    await f._process_new_updates_attributed([upd])
    check('an anonymous /undo from Larry undoes it', (GVENMO, vcopy) in deleted,
          str(deleted))
    check('and the books follow', f.ledger_snapshot(GVENMO) == (11172.44, 2745.0),
          str(f.ledger_snapshot(GVENMO)))

    # -- 4. only Ethan and Larry --------------------------------------------
    reset()
    await forward(LVENMO, 702)
    await f.undo_command(undo(LVENMO, CREW, reply_to=702))
    check('a crew /undo moves nothing',
          f.ledger_snapshot(GVENMO) == (11372.44, 2745.0),
          str(f.ledger_snapshot(GVENMO)))
    check('and is left alone - not deleted, not answered',
          deleted == [] and dms == [], f"{deleted} {dms}")

    # -- 5. the shapes that are not an undo --------------------------------
    reset()
    await f.undo_command(undo(LVENMO, LARRY))
    check('no reply: Larry is told how', any('Reply /undo' in t for t in said(LARRY)),
          str(dms))
    check('and nothing moves', f.ledger_snapshot(GVENMO) == (11172.44, 2745.0))
    reset()
    await f.undo_command(undo(LVENMO, LARRY, reply_to=703, reply_text='ok thanks'))
    check('a reply to chatter is not a payment',
          any('not a payment' in t for t in said(LARRY)), str(dms))

    # -- 6. Chime Rev too; the paused route not at all ---------------------
    reset()
    await forward(CHIMEREV, 704)
    ccopy = copy_id(GAFFER)
    await f.undo_command(undo(CHIMEREV, ETHAN, reply_to=704))
    check('Ethan can /undo in Chime Rev', (GAFFER, ccopy) in deleted, str(deleted))
    check('CHIME GAFFER is back', f.ledger_snapshot(GAFFER) == (11172.44, 2745.0),
          str(f.ledger_snapshot(GAFFER)))
    reset()
    await f.undo_command(undo(MHLARRY, LARRY, reply_to=705))
    check('MH X LARRY GROUP 2 is not a retract source: silence',
          deleted == [] and dms == [], f"{deleted} {dms}")

    # -- 7. the mark that cannot be placed is not silent --------------------
    reset()
    await forward(LVENMO, 706)
    f.bot.fail_react = True
    await f.undo_command(undo(LVENMO, LARRY, reply_to=706))
    check('the undo still happens', f.ledger_snapshot(GVENMO) == (11172.44, 2745.0))
    check('and the admin is warned the next deploy may re-send it',
          any('may send that payment again' in t for _, t in dms), str(dms))

    # -- 7b. telebot routes /undo to it, ahead of the catch-all text handler
    names = [h['function'].__name__ for h in REAL_BOT.message_handlers]
    check('/undo has its own handler, registered before forward_text',
          'undo_command' in names and 'forward_text' in names
          and names.index('undo_command') < names.index('forward_text'), str(names))
    spec = next(h for h in REAL_BOT.message_handlers
                if h['function'].__name__ == 'undo_command')
    check('and it is registered for the undo command',
          spec['filters'].get('commands') == ['undo'], str(spec['filters']))

    # -- 8. the sweep reads the bot's mark as a retraction ------------------
    def msg(*peers):
        return NS(reactions=NS(results=[1], recent_reactions=[
            NS(peer_id=NS(user_id=p)) for p in peers]))
    check("the bot's mark holds a payment back after a deploy",
          f._retraction_mark(msg(BOT)) == 'admin')
    check("a stranger's reaction still does not", f._retraction_mark(msg(CREW)) is None)

    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print('all checks passed')


asyncio.run(main())
