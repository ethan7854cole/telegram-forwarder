"""Another bot's message in a handling group is never a /out.

MAYAN'S BOT answers a /out it will not accept with "🚫 Only bot admin/staff can
use /out. Your ID: 7578145913 ...". That carries the word /out, so with a
request open it settled the request, hearted it and was relayed - Larry's id
and all - into the group that asked. It must reach none of CHIME PICCASO, CHIME
GAFFER, GAFFER VENMO or PICCASO VENMO, and the request must stay open for the
real /out.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

# The Status press is test_status.py's business.
f.STATUS_BUTTON_CHATS = set()

ROUTES = [(-5350880041, -1003894781195), (-5580596463, -1002335630148),
          (-5100231154, -1004298140797), (-5306739731, -1004298140797)]

REFUSAL = ("🚫 Only bot admin/staff can use /out.\nYour ID: 7578145913\n"
           "Ask an admin to run: /addadmin 7578145913")

sent, dms, reactions = [], [], []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(7000 + len(sent) + len(dms))

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None):
        sent.append((chat_id, caption))
        return FakeMsg(7900)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = False
f._active_client = None

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); reactions.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()


async def main():
    now = datetime.now(timezone.utc)
    for source, handling in ROUTES:
        name = f.chat_name(source)
        reset()
        await f.observe_cashout(source, '!! Cashout Request !!\nTag name : $jenny-buhr\n'
                                'Amount : 25', 910, now, user_id=42)
        sent.clear(); dms.clear()

        # Larry's bare /out is refused by MAYAN'S BOT in the handling group.
        await f.observe_cashout(handling, REFUSAL, 911, now, user_id=555,
                                username='mayans_bot', reply_to=None,
                                from_bot=True)
        check(f'{name}: the refusal is not relayed',
              not any(c == source for c, _ in sent), str(sent))
        check(f'{name}: Larry\'s id goes nowhere',
              not any('7578145913' in (t or '') for _, t in sent), str(sent))
        check(f'{name}: nothing is booked', f.ledger_snapshot(source)[1] in (0, 0.0, None)
              or source not in f._ledger, str(f._ledger))
        check(f'{name}: the request is not hearted', reactions == [], str(reactions))
        check(f'{name}: the request stays open',
              len(f._pending_cashouts.get(handling, [])) == 1)
        check(f'{name}: no completed DM',
              not any('COMPLETED' in t for _, t in dms), str(dms))

        # ...and the crew's real /out after it still completes it.
        await f.observe_cashout(handling, '/out 25', 912, now, user_id=77,
                                username='Maynuddin23', reply_to=None)
        check(f'{name}: the real /out still goes home',
              any(c == source for c, _ in sent), str(sent))
        check(f'{name}: and is booked', f.ledger_snapshot(source)[1] == 25.0)

    # A bot's /out with nothing open is not reported as "WAS NOT RELAYED" either.
    reset()
    await f.observe_cashout(-1002335630148, '/out 25', 920, now, user_id=555,
                            username='mayans_bot', from_bot=True)
    check('nothing open: no admin DM about a bot', dms == [], str(dms))

    # A person's message is untouched by the flag defaulting off.
    check('from_bot defaults off',
          f.observe_cashout.__defaults__[-1] is False)

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("all passed")


asyncio.run(main())
