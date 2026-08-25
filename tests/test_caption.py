"""A /out written as the caption on the payment screenshot answers a request.

The crew reply to a CASHOUT REQUEST with the Cash App screenshot proving they
sent the money and write the /out as its caption. Both input paths used to drop
captioned media before the cashout flow ever saw it, so the request stayed
open, the heart never landed, the reminders kept firing and the money was never
booked.

Both paths are driven through their REAL dispatch here - telebot's own filter
matching, and the Telethon handler exactly as run_userbot() registers it -
because the failure being guarded against is a message never reaching the flow
at all, which a direct call to observe_cashout() could never detect.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ['TELEGRAM_API_ID'] = '12345'
os.environ['TELEGRAM_API_HASH'] = 'fakehash'
os.environ['TELETHON_START_DELAY'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
BOTID = 111222

# The AsyncTeleBot the @bot.message_handler decorators registered on at import.
# Grab it before the stub replaces the module global, or the handler table -
# which is what routing correctness actually lives in - goes with it.
real_bot = f.bot

sent, reactions, dms = [], [], []
_next_id = [7000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        if chat_id > 0:
            dms.append((chat_id, text))
        else:
            sent.append((chat_id, text, reply_to_message_id))
        return FakeMsg(_next_id[0])

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id, reaction[0].emoji))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); reactions.clear(); dms.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._ledger.clear()


# --------------------------------------------------------------------------
# Bot API side: a message shaped the way telebot delivers one
# --------------------------------------------------------------------------

class Chat:
    def __init__(self, cid):
        self.id, self.type = cid, 'supergroup'


class User:
    def __init__(self, uid, username=None, is_bot=False):
        self.id, self.username = uid, username
        # The Bot API spells it is_bot, Telethon spells it bot, and this fake
        # is handed to both paths. Setting only one made every bot-sender check
        # below pass for the wrong reason.
        self.is_bot = self.bot = is_bot
        self.first_name, self.last_name = 'Crew', None


class BotApiMsg:
    """Only the attributes the handlers and telebot's filters actually read."""

    def __init__(self, chat_id, content_type='text', text=None, caption=None,
                 mid=800, uid=77, username='Maynuddin23', reply_to=None):
        self.chat = Chat(chat_id)
        self.content_type = content_type
        self.text, self.caption = text, caption
        self.message_id = mid
        self.from_user = User(uid, username)
        self.date = int(datetime.now(timezone.utc).timestamp())
        self.reply_to_message = FakeMsg(reply_to) if reply_to else None


async def route(message):
    """Which handler telebot would hand this message to, in registration order."""
    for handler in real_bot.message_handlers:
        if await real_bot._test_message_handler(handler, message):
            return handler['function'].__name__
    return None


# --------------------------------------------------------------------------
# Telethon side: capture the handler run_userbot() registers, then drive it
# --------------------------------------------------------------------------

class Media:
    pass


class TeleMsg:
    def __init__(self, text, media=None, reply_to_msg_id=None):
        self.raw_text = text
        self.media = media
        self.date = datetime.now(timezone.utc)
        self.reply_to_msg_id = reply_to_msg_id


class TeleEvent:
    def __init__(self, chat_id, text, mid, media=None, sender=None, reply_to=None):
        self.chat_id, self.id = chat_id, mid
        self.raw_text = text
        self.message = TeleMsg(text, media, reply_to)
        self._sender = sender or User(77, 'Maynuddin23')

    async def get_sender(self):
        return self._sender


class FakeEntity:
    def __init__(self, cid):
        self.id, self.title, self.username = cid, str(cid), None


captured = {}


class FakeTelethonClient:
    def __init__(self, *a, **k):
        self._forever = asyncio.Event()

    async def connect(self): return True
    async def is_user_authorized(self): return True
    async def get_me(self): return User(999, 'userbot')
    async def get_dialogs(self): return []
    async def get_entity(self, cid): return FakeEntity(cid)
    async def disconnect(self): pass

    def on(self, event):
        # events.NewMessage arrives instantiated, events.MessageDeleted as the
        # class itself.
        name = getattr(event, '__name__', None) or type(event).__name__

        def register(fn):
            captured[name] = fn
            return fn
        return register

    async def run_until_disconnected(self):
        await self._forever.wait()          # hold the listener open


async def start_userbot():
    """Run run_userbot() until its handlers are live and the ready gate is open."""
    f.TelegramClient = FakeTelethonClient
    f.StringSession = lambda s: s

    async def noop(_client):
        return
    f.recover_ledgers = noop
    f.catch_up = noop

    task = asyncio.create_task(f.run_userbot())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if 'NewMessage' in captured:
            break
    return task


async def main():
    now = datetime.now(timezone.utc)
    screenshot_out = '/out 120\n$Hawkins-Floral-Decor'

    # -- 1. the predicate itself ---------------------------------------------
    check('a caption carrying /out is recognised', f.is_caption_out(screenshot_out))
    check('a bare /out caption is recognised', f.is_caption_out('/out'))
    check('/out mid-caption is recognised', f.is_caption_out('sent it, /out 500 done'))
    check('a captioned CASHOUT REQUEST is not a /out',
          not f.is_caption_out('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500'))
    check('an ordinary caption is not a /out', not f.is_caption_out('here is the proof'))
    check('an empty caption is not a /out',
          not f.is_caption_out('') and not f.is_caption_out(None))
    check('a word merely containing out is not a /out',
          not f.is_caption_out('checkout done') and not f.is_caption_out('/output 5'))

    # -- 2. Bot API routing, through telebot's own filters --------------------
    photo = BotApiMsg(MHLARRY, 'photo', caption=screenshot_out)
    check('a screenshot captioned /out reaches the cashout handler',
          await route(photo) == 'cashout_caption', str(await route(photo)))
    check('a document captioned /out reaches it too',
          await route(BotApiMsg(MHLARRY, 'document', caption='/out 75')) == 'cashout_caption')
    # In a HANDLING group any media now reaches the cashout flow, caption or
    # not: a screenshot sent instead of the /out is the crew signalling a
    # problem, and it must not look like silence.
    check('a screenshot with an ordinary caption reaches the cashout flow',
          await route(BotApiMsg(MHLARRY, 'photo', caption='here is the proof'))
          == 'cashout_caption')
    check('a screenshot with no caption at all reaches it too',
          await route(BotApiMsg(MHLARRY, 'photo')) == 'cashout_caption')

    # Everywhere else media is still ignored unless it carries a /out.
    check('a screenshot in a chime group is still ignored',
          await route(BotApiMsg(PICCASO, 'photo', caption='here is the proof')) is None)
    check('a captioned CASHOUT REQUEST reaches no handler',
          await route(BotApiMsg(PICCASO, 'photo', caption='!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500')) is None)
    check('a captioned payment notification in a chime group is ignored',
          await route(BotApiMsg(PICCASO, 'photo',
                                caption='You received $15.0 from Gabriel W.')) is None)
    check('a sticker is still ignored',
          await route(BotApiMsg(MHLARRY, 'sticker')) is None)

    # unchanged routing for everything that already worked
    check('a typed /out still routes to the ledger command',
          await route(BotApiMsg(MHLARRY, 'text', text='/out 120')) == 'ledger_command')
    check('a typed /add still routes to the ledger command',
          await route(BotApiMsg(MHLARRY, 'text', text='/add 100')) == 'ledger_command')
    check('/out-50 still routes to the joined-command handler',
          await route(BotApiMsg(MHLARRY, 'text', text='/out-50')) == 'ledger_joined_command')
    check('ordinary text still routes to forward_text',
          await route(BotApiMsg(PICCASO, 'text',
                                text='You received $15.0 from Gabriel W.')) == 'forward_text')

    # -- 3. Bot API: the whole flow, end to end ------------------------------
    reset()
    await f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 120', 901, now,
                            user_id=42, username='chimeguy')
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    sent.clear()

    await f.cashout_caption(BotApiMsg(MHLARRY, 'photo', caption=screenshot_out,
                                      mid=902, reply_to=copy_id))
    to_chime = [(c, t) for c, t, _ in sent if c == PICCASO]
    check('the caption is forwarded to the chime group',
          any(t == screenshot_out for _, t in to_chime), str(sent))
    check('the ❤ lands on the ORIGINAL request',
          reactions == [(PICCASO, 901, '❤')], str(reactions))
    check('Total Out is booked from the caption',
          f.ledger_snapshot(PICCASO)[1] == 120.0, str(f.ledger_snapshot(PICCASO)))
    check('the booking posts BOTH totals, so a redeploy cannot revert it',
          any('Total In' in t and 'Total Out' in t for _, t in to_chime), str(to_chime))
    check('the request is closed', MHLARRY not in f._pending_cashouts)
    check('Larry is told it completed',
          any('SCREENSHOT' in t.upper() for _, t in dms), str(dms))

    # -- 4. a captioned /out with nothing pending is left completely alone ---
    reset()
    await f.cashout_caption(BotApiMsg(MHLARRY, 'photo', caption=screenshot_out, mid=903))
    check('a captioned /out with nothing pending is ignored',
          sent == [] and reactions == [] and f.ledger_snapshot(MHLARRY) == (0.0, 0.0),
          str(sent))

    # -- 5. a caption is never a payment notification ------------------------
    # Both keywords in one caption, posted in MH X LARRY - which is a cashout
    # handling group AND the payment source feeding PICCASO. The cashout path
    # may relay it; the payment path must not touch it, or a screenshot would
    # invent a deposit that never happened.
    reset()
    mixed = 'You received $15.0 from Gabriel W. /out 5'
    f.ledger_commit(PICCASO, (100.0, 0.0))      # books already open, so a
    f.ledger_commit(MHLARRY, (100.0, 0.0))      # deposit would really land
    await f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 5', 904, now, user_id=42)
    sent.clear()
    await f.cashout_caption(BotApiMsg(MHLARRY, 'photo', mid=905, caption=mixed))
    check('a caption never moves Total In',
          f.ledger_snapshot(PICCASO)[0] == 100.0 and f.ledger_snapshot(MHLARRY)[0] == 100.0,
          str((f.ledger_snapshot(PICCASO), f.ledger_snapshot(MHLARRY))))
    # A relay is the caption verbatim. A forward would carry a corrected
    # timestamp and this target's own totals, so it cannot be byte-identical -
    # which is what separates the two here.
    relays = [t for c, t, _ in sent if c == PICCASO and 'You received' in t]
    check('the caption is relayed verbatim, never forwarded as a payment',
          relays == [mixed], str(relays))

    # -- 6. Telethon: the same message, through the registered handler -------
    task = await start_userbot()
    check('the Telethon listener registered a handler', 'NewMessage' in captured)

    reset()
    await f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 120', 906, now,
                            user_id=42, username='chimeguy')
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    sent.clear()

    handler = captured['NewMessage']
    await handler(TeleEvent(MHLARRY, screenshot_out, 907, media=Media(),
                            reply_to=copy_id))
    check('userbot: the captioned /out answers the request',
          any(c == PICCASO and t == screenshot_out for c, t, _ in sent), str(sent))
    check('userbot: the ❤ lands on the original', reactions == [(PICCASO, 906, '❤')],
          str(reactions))
    check('userbot: Total Out is booked', f.ledger_snapshot(PICCASO)[1] == 120.0,
          str(f.ledger_snapshot(PICCASO)))
    check('userbot: the request is closed', MHLARRY not in f._pending_cashouts)

    # -- 7. Telethon: captions that are not a /out stay dropped --------------
    reset()
    await handler(TeleEvent(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500', 908, media=Media(),
                            sender=User(42, 'chimeguy')))
    check('userbot: a captioned CASHOUT REQUEST opens nothing',
          sent == [] and not f._pending_cashouts, str(sent))

    # Posted in the real payment SOURCE, by a bot, so everything except the
    # caption itself says "forward this".
    reset()
    f.ledger_commit(PICCASO, (100.0, 0.0))
    await handler(TeleEvent(MHLARRY, 'You received $15.0 from Gabriel W.', 909,
                            media=Media(), sender=User(500, 'notifier', is_bot=True)))
    check('userbot: a captioned payment notification is never forwarded',
          sent == [], str(sent))
    check('userbot: it never touches the books',
          f.ledger_snapshot(PICCASO) == (100.0, 0.0), str(f.ledger_snapshot(PICCASO)))

    # -- 8. plain text through the same handler is untouched -----------------
    reset()
    await f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 30', 910, now, user_id=42)
    sent.clear()
    await handler(TeleEvent(MHLARRY, '/out 30', 911))
    check('userbot: a typed /out still behaves exactly as before',
          any(c == PICCASO and t == '/out 30' for c, t, _ in sent)
          and reactions == [(PICCASO, 910, '❤')]
          and f.ledger_snapshot(PICCASO)[1] == 30.0, str(sent))

    # The identical message WITHOUT media must still forward, or the gate above
    # is closing on more than captions. The books are seeded first: on an empty
    # ledger a payment only opens the balance from its own totals block, and
    # this one deliberately has none.
    reset()
    f.ledger_commit(PICCASO, (100.0, 0.0))
    await handler(TeleEvent(MHLARRY, 'You received $15.0 from Gabriel W.', 912,
                            sender=User(500, 'notifier', is_bot=True)))
    check('userbot: a plain payment notification still forwards',
          any(c == PICCASO and 'You received' in t for c, t, _ in sent), str(sent))
    check('userbot: and still books Total In',
          f.ledger_snapshot(PICCASO)[0] == 115.0, str(f.ledger_snapshot(PICCASO)))

    # -- 9. dedup still holds across the two paths, with a caption -----------
    reset()
    await f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 60', 913, now, user_id=42)
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    sent.clear()
    photo = BotApiMsg(MHLARRY, 'photo', caption='/out 60', mid=914, reply_to=copy_id)
    await handler(TeleEvent(MHLARRY, '/out 60', 914, media=Media(), reply_to=copy_id))
    await f.cashout_caption(photo)
    check('the same captioned /out on both paths books once',
          f.ledger_snapshot(PICCASO)[1] == 60.0, str(f.ledger_snapshot(PICCASO)))
    check('and is forwarded once',
          len([1 for c, t, _ in sent if c == PICCASO and t == '/out 60']) == 1, str(sent))

    # -- 10. the GAFFER route behaves identically, and stays separate --------
    # The caption goes back to the chime group the request CAME FROM, and that
    # group's books are the ones that move - never the other route's.
    reset()
    gaffer_out = '/out 200\n$Some-Other-Cashtag'
    await f.observe_cashout(GAFFER, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200', 915, now, user_id=43)
    check('the GAFFER request is handled in Chime Rev',
          sent and sent[0][0] == CHIMEREV, str(sent))
    copy_id = f._pending_cashouts[CHIMEREV][0]['message_id']
    sent.clear()

    await f.cashout_caption(BotApiMsg(CHIMEREV, 'photo', caption=gaffer_out,
                                      mid=916, reply_to=copy_id))
    check('the caption goes back to GAFFER, where it came from',
          any(c == GAFFER and t == gaffer_out for c, t, _ in sent), str(sent))
    check('GAFFER Total Out is booked', f.ledger_snapshot(GAFFER)[1] == 200.0,
          str(f.ledger_snapshot(GAFFER)))
    check('PICCASO books are untouched by the GAFFER route',
          f.ledger_snapshot(PICCASO) == (0.0, 0.0), str(f.ledger_snapshot(PICCASO)))
    check('nothing was posted into PICCASO', not any(c == PICCASO for c, _, _ in sent),
          str(sent))
    check('the ❤ lands on the original in GAFFER', reactions == [(GAFFER, 915, '❤')],
          str(reactions))
    check('the GAFFER request is closed', CHIMEREV not in f._pending_cashouts)

    # -- 11. the relayed /out must never book a SECOND time ------------------
    # The bot posts "/out 120" into the chime group, and that group is a
    # TARGET_CHAT where /out is a real ledger command. If that copy were ever
    # acted on, every cashout would come off the books twice.
    reset()
    await f.observe_cashout(PICCASO, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 120', 917, now, user_id=42)
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    await f.cashout_caption(BotApiMsg(MHLARRY, 'photo', caption='/out 120',
                                      mid=918, reply_to=copy_id))
    check('the cashout flow books it once', f.ledger_snapshot(PICCASO)[1] == 120.0,
          str(f.ledger_snapshot(PICCASO)))

    # The relay coming back round through the userbot, which DOES see the
    # bot's own posts because the chime groups are watched chats.
    sent.clear()
    await handler(TeleEvent(PICCASO, '/out 120', 919,
                            sender=User(BOTID, 'larrysbot', is_bot=True)))
    check('the bot\'s own relayed /out is ignored, not re-booked',
          f.ledger_snapshot(PICCASO)[1] == 120.0 and sent == [],
          str((f.ledger_snapshot(PICCASO), sent)))

    # ...and the totals message the booking itself posted, likewise.
    await handler(TeleEvent(PICCASO, '📤 Out = -120.00$\n\n📊 Group Total:\n'
                            '➕ Total In : 0.00$\n➖ Total Out: 120.00$', 920,
                            sender=User(BOTID, 'larrysbot', is_bot=True)))
    check('the booking confirmation is not re-read as a payment',
          f.ledger_snapshot(PICCASO) == (0.0, 120.0) and sent == [],
          str((f.ledger_snapshot(PICCASO), sent)))

    # A human typing the same /out on top of it is a DIFFERENT matter - that
    # is the manual double-count the docs warn about, and it is allowed.
    check('a chime group is a target chat, so /out there is a real command',
          PICCASO in f.TARGET_CHATS)

    task.cancel()

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
