"""A deleted cashout request is settled: no chasing, no reaction, out of the queue."""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
sent, reactions, failures = [], [], []
react_error = [None]


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        sent.append((chat_id, text)); return FakeMsg(7000 + len(sent))
    async def set_message_reaction(self, chat_id, message_id, reaction):
        if react_error[0]:
            raise RuntimeError(react_error[0])
        reactions.append((chat_id, message_id)); return True


class FakeEntity:
    def __init__(self, cid): self.id = cid


class FakeClient:
    """`alive` lists message ids that still exist."""
    def __init__(self, alive): self.alive = set(alive); self.userbot_reactions = []
    async def get_entity(self, cid): return FakeEntity(cid)
    async def get_messages(self, entity, ids=None):
        return [(object() if i in self.alive else None) for i in (ids or [])]
    async def __call__(self, request):
        self.userbot_reactions.append(request); return True


f.bot = FakeBot()


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def reset():
    sent.clear(); reactions.clear(); f._ledger.clear()
    f._seen_messages.clear(); f._pending_cashouts.clear()
    react_error[0] = None
    f.USERBOT_SEND = False; f._active_client = None


async def open_one(origin=PICCASO, origin_msg_id=901):
    now = datetime.now(timezone.utc)
    await f.observe_cashout(origin, 'CASHOUT REQUEST $500', origin_msg_id, now, user_id=42)
    return f.CASHOUT_ROUTES[origin]['handling']


async def main():
    # -- deletion in a known chat closes the request -------------------------
    reset()
    handling = await open_one()
    await f.close_deleted_cashouts(FakeClient(alive=[]), PICCASO, [901])
    check('a deleted request is dropped', not f._pending_cashouts, str(f._pending_cashouts))
    check('nothing was reacted to', reactions == [], str(reactions))

    # -- and it is then genuinely gone: a later /out does nothing -----------
    sent.clear()
    await f.observe_cashout(handling, '/out 500', 902, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('a /out after deletion is ignored', sent == [] and reactions == [], str(sent))

    # -- the watchdog no longer chases it ------------------------------------
    reset()
    await open_one()
    await f.close_deleted_cashouts(FakeClient(alive=[]), PICCASO, [901])
    sent.clear()                     # drop the original forward; watch for nudges only
    real_sleep = asyncio.sleep
    async def fast(_): await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(0.15)
    task.cancel()
    f.asyncio.sleep = real_sleep
    check('a deleted request is never chased', sent == [], str(sent))

    # -- a deletion in a DIFFERENT chat leaves it alone ---------------------
    reset()
    await open_one()
    await f.close_deleted_cashouts(FakeClient(alive=[]), GAFFER, [901])
    check('a deletion elsewhere does not touch it',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1, str(f._pending_cashouts))

    # -- an unrelated id leaves it alone ------------------------------------
    reset()
    await open_one()
    await f.close_deleted_cashouts(FakeClient(alive=[]), PICCASO, [999])
    check('an unrelated deletion does not touch it',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1)

    # -- unattributed deletion, message really gone -> dropped --------------
    reset()
    await open_one()
    await f.close_deleted_cashouts(FakeClient(alive=[]), None, [901])
    check('unattributed deletion drops it once confirmed gone',
          not f._pending_cashouts, str(f._pending_cashouts))

    # -- unattributed deletion, message still there -> kept -----------------
    reset()
    await open_one()
    await f.close_deleted_cashouts(FakeClient(alive=[901]), None, [901])
    check('unattributed deletion keeps it when the message survives',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1, str(f._pending_cashouts))

    # -- both chime groups, only the deleted one goes -----------------------
    reset()
    await open_one(PICCASO, 901)
    await open_one(GAFFER, 901)          # same id, different chat
    await f.close_deleted_cashouts(FakeClient(alive=[]), PICCASO, [901])
    check('only the matching chat is dropped',
          MHLARRY not in f._pending_cashouts
          and len(f._pending_cashouts.get(CHIMEREV, [])) == 1, str(f._pending_cashouts))

    # -- deleting the FORWARDED COPY in the handling group also settles it --
    reset()
    handling = await open_one(PICCASO, 901)
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    await f.close_deleted_cashouts(FakeClient(alive=[]), MHLARRY, [copy_id])
    check('deleting the copy in MH X LARRY settles it',
          not f._pending_cashouts, str(f._pending_cashouts))
    check('no reaction when the copy is deleted', reactions == [], str(reactions))

    reset()
    await open_one(GAFFER, 801)
    copy_id = f._pending_cashouts[CHIMEREV][0]['message_id']
    await f.close_deleted_cashouts(FakeClient(alive=[]), CHIMEREV, [copy_id])
    check('deleting the copy in Chime Rev settles it',
          not f._pending_cashouts, str(f._pending_cashouts))

    # -- the copy deleted, unattributed, confirmed gone ---------------------
    reset()
    await open_one(PICCASO, 901)
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    await f.close_deleted_cashouts(FakeClient(alive=[901]), None, [copy_id])
    check('unattributed copy deletion settles it once confirmed',
          not f._pending_cashouts, str(f._pending_cashouts))

    # -- the copy still alive, unattributed -> kept -------------------------
    reset()
    await open_one(PICCASO, 901)
    copy_id = f._pending_cashouts[MHLARRY][0]['message_id']
    await f.close_deleted_cashouts(FakeClient(alive=[901, copy_id]), None, [copy_id])
    check('unattributed copy deletion keeps it when the copy survives',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1, str(f._pending_cashouts))

    # -- a deletion in a chat with no cashout role is ignored ---------------
    reset()
    await open_one(PICCASO, 901)
    await f.close_deleted_cashouts(FakeClient(alive=[]), -5339749243, [901])
    check('a deletion in an unrelated chat is ignored',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1, str(f._pending_cashouts))

    # -- a lookup failure leaves it open rather than guessing ---------------
    reset()
    await open_one()
    class Broken(FakeClient):
        async def get_messages(self, entity, ids=None): raise RuntimeError('flood wait')
    await f.close_deleted_cashouts(Broken(alive=[]), None, [901])
    check('a failed confirmation leaves it open',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1, str(f._pending_cashouts))

    # -- reacting to an already-deleted message: quiet, no fallback ---------
    reset()
    client = FakeClient(alive=[])
    f.USERBOT_SEND = True; f._active_client = client
    react_error[0] = 'Bad Request: message to react not found'
    ok = await f.heart_request(PICCASO, 901)
    check('a deleted message is not treated as an error', ok is False)
    check('no user-account retry for a deleted message',
          client.userbot_reactions == [], str(client.userbot_reactions))

    # -- a real failure still falls back to the user account ---------------
    reset()
    client = FakeClient(alive=[901])
    f.USERBOT_SEND = True; f._active_client = client
    react_error[0] = 'Bad Request: not enough rights to send reactions'
    ok = await f.heart_request(PICCASO, 901)
    check('a genuine failure still retries via the account',
          ok is True and len(client.userbot_reactions) == 1,
          str(client.userbot_reactions))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all deletion checks passed")


asyncio.run(main())
