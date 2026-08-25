"""A deleted cashout request is settled: no chasing, no reaction, out of the queue."""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
sent, dms, deleted, reactions, failures = [], [], [], [], []
react_error = [None]
delete_error = [None]
ETHAN, LARRY = f.ETHAN_ID, f.LARRY_ID


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    # Ethan and Larry are administrators in every group and the bot posts its
    # own messages, so a delete lands - except past Telegram's 48-hour limit,
    # which is what delete_error stands in for.
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        if chat_id > 0:
            dms.append((chat_id, text)); return FakeMsg(7000 + len(dms))
        sent.append((chat_id, text)); return FakeMsg(7000 + len(sent))
    async def set_message_reaction(self, chat_id, message_id, reaction):
        if react_error[0]:
            raise RuntimeError(react_error[0])
        reactions.append((chat_id, message_id)); return True
    async def delete_message(self, chat_id, message_id):
        if delete_error[0]:
            raise RuntimeError(delete_error[0])
        deleted.append((chat_id, message_id)); return True


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
    sent.clear(); dms.clear(); deleted.clear(); reactions.clear(); f._ledger.clear()
    f._seen_messages.clear(); f._pending_cashouts.clear()
    react_error[0] = None; delete_error[0] = None
    f.USERBOT_SEND = False; f._active_client = None
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY})


async def open_one(origin=PICCASO, origin_msg_id=901):
    now = datetime.now(timezone.utc)
    await f.observe_cashout(origin, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500', origin_msg_id, now, user_id=42)
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

    # -- the chime side deleting it takes it back off the crew --------------
    for origin in (PICCASO, GAFFER):
        reset()
        handling = await open_one(origin, origin_msg_id=901)
        request = f._pending_cashouts[handling][0]
        copy_id = request['message_id']
        request['group_notice'] = [5001, 5002]
        request['crew_notice'] = [('bot', 77, 6001)]
        sent.clear(); dms.clear()      # only what the DELETION does, from here
        await f.close_deleted_cashouts(FakeClient(alive=[]), origin, [901])
        label = f.chat_name(origin)

        check(f'{label}: the forwarded copy is deleted',
              (handling, copy_id) in deleted, str(deleted))
        check(f'{label}: the reminders go with it',
              (handling, 5001) in deleted and (handling, 5002) in deleted,
              str(deleted))
        check(f"{label}: and the crew's chase DM",
              (77, 6001) in deleted, str(deleted))
        check(f'{label}: nothing is deleted in the chime group itself',
              not [d for d in deleted if d[0] == origin], str(deleted))

        for who, name in ((ETHAN, 'Ethan'), (LARRY, 'Larry')):
            note = [t for c, t in dms if c == who and 'WAS DELETED' in t]
            check(f'{label}: {name} is told', len(note) == 1, str(dms))
            check(f'{label}: {name} is told which group it was deleted in',
                  note and f'Deleted in: {label}' in note[0], str(note))
            check(f'{label}: {name} is warned to check it was not already paid',
                  note and 'worth checking' in note[0], str(note))
        check(f'{label}: the crew are not DMed about it',
              [t for c, t in dms if c == 77] == [], str(dms))
        check(f'{label}: and nothing is posted in either group', sent == [],
              str(sent))

    # -- the crew deleting the copy is NOT the same thing -------------------
    reset()
    handling = await open_one(PICCASO, origin_msg_id=901)
    request = f._pending_cashouts[handling][0]
    sent.clear(); dms.clear()
    await f.close_deleted_cashouts(FakeClient(alive=[]), handling,
                                   [request['message_id']])
    check('a copy deleted in the handling group settles the request',
          not f._pending_cashouts, str(f._pending_cashouts))
    check('and the chime group\'s own message is never deleted for them',
          deleted == [], str(deleted))
    check('nor is a withdrawal reported', dms == [], str(dms))

    # -- a copy too old to delete is reported, not swallowed ----------------
    reset()
    handling = await open_one(PICCASO, origin_msg_id=901)
    delete_error[0] = 'Bad Request: message can\'t be deleted'
    dms.clear()
    await f.close_deleted_cashouts(FakeClient(alive=[]), PICCASO, [901])
    note = [t for c, t in dms if c == ETHAN and 'WAS DELETED' in t]
    check('a copy that cannot be deleted is called out',
          note and 'Could not remove: the forwarded request' in note[0], str(note))
    check('and they are pointed at /del, which works without admin rights',
          note and 'reply to it with /del' in note[0], str(note))
    check('the request is still dropped from the queue',
          not f._pending_cashouts, str(f._pending_cashouts))

    # -- a copy already gone is not an error --------------------------------
    reset()
    handling = await open_one(PICCASO, origin_msg_id=901)
    delete_error[0] = 'Bad Request: message to delete not found'
    dms.clear()
    await f.close_deleted_cashouts(FakeClient(alive=[]), PICCASO, [901])
    note = [t for c, t in dms if c == ETHAN and 'WAS DELETED' in t]
    check('a copy already gone is not reported as a failure',
          note and 'Could not remove' not in note[0]
          and 'already gone' in note[0], str(note))

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
    await f.close_deleted_cashouts(FakeClient(alive=[]), -1004298140797, [901])
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
