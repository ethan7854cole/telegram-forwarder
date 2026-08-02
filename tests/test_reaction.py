"""A crew reaction buys another timeout; silence keeps the chasing going."""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, MHLARRY = -5350880041, -1003894781195
LARRY, CREW = 7418675217, 77
sent, dms, failures = [], [], []

# Learned ids, so the bot can actually DM them. Without these every private
# escalation lands in the "could not reach them" pile instead, and a test that
# expects a DM passes or fails for the wrong reason.
f_user_seed = {'larryyxx': LARRY, 'maynuddin23': CREW}


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        (dms if chat_id > 0 else sent).append((chat_id, text)); return FakeMsg(7000 + len(sent))
    async def set_message_reaction(self, *a, **k): return True


f.bot = FakeBot(); f.USERBOT_SEND = False; f._active_client = None
real_sleep = asyncio.sleep


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def reset():
    sent.clear(); dms.clear(); f._ledger.clear()
    f._seen_messages.clear(); f._pending_cashouts.clear()
    f._user_ids.update(f_user_seed)


async def open_one():
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $500', 901,
                            datetime.now(timezone.utc), user_id=42)
    return f._pending_cashouts[MHLARRY][0]


async def run_watchdog(seconds=0.2):
    async def fast(_): await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


class U:
    def __init__(s, uid, username): s.id, s.username = uid, username


class C:
    def __init__(s, cid): s.id = cid


class Reaction:
    def __init__(s, cid, mid, user, new=('❤',)):
        s.chat, s.message_id, s.user = C(cid), mid, user
        s.new_reaction, s.old_reaction = list(new), []


async def main():
    now = datetime.now(timezone.utc)

    # -- a crew reaction resets the clock ------------------------------------
    reset()
    req = await open_one()
    req['last_seen'] = now - timedelta(minutes=10)          # overdue
    ok = await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    check('a crew reaction is accepted', ok is True)
    check('the clock is back to zero',
          (datetime.now(timezone.utc) - req['last_seen']).total_seconds() < 5)
    check('the request is marked seen', req['seen'] is True)
    check('it does NOT close the request', MHLARRY in f._pending_cashouts)

    # -- and that buys a full timeout of quiet -------------------------------
    sent.clear()
    await run_watchdog()
    check('no reminder inside the fresh timeout', sent == [], str(sent))

    # -- a reaction buys 7 minutes, not the 5 an unanswered request gets ------
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    sent.clear(); dms.clear()
    await run_watchdog()
    check('6 minutes is not yet up for an acknowledged request',
          sent == [] and dms == [], str((sent, dms)))

    # -- when the 7 minutes lapse, the chase goes PRIVATE ---------------------
    # They acknowledged it in the group, so tagging them there again is noise.
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=8)
    sent.clear(); dms.clear()
    await run_watchdog()
    check('an acknowledged request is never re-tagged in the group',
          sent == [], str(sent))
    crew = [t for uid, t in dms if uid == 77]
    check('the crew are told privately instead', len(crew) == 1, str(dms))
    check('and their DM carries no routing',
          crew and 'Waiting in:' not in crew[0], str(crew))
    check('Larry is not pulled in yet',
          not [t for uid, t in dms if uid == LARRY], str(dms))

    # -- one window later it is handed to Larry, and the chasing stops --------
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=8)
    sent.clear(); dms.clear()
    await run_watchdog()
    check('Larry gets the acknowledged-but-stuck notice',
          any('Acknowledged in the group' in t for _, t in dms), str(dms))
    check('the chasing is now exhausted', req['exhausted'] is True)
    check('but the request stays OPEN for a late /out', MHLARRY in f._pending_cashouts)

    sent.clear(); dms.clear()
    for _ in range(3):
        req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=8)
        await run_watchdog()
    check('nothing at all repeats after that', sent == [] and dms == [],
          str((sent, dms)))

    # -- unacknowledged: three group rounds, then reminders stop -------------
    reset()
    req = await open_one()
    rounds = 0
    for _ in range(9):
        req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=6)
        sent.clear()
        await run_watchdog()
        if sent: rounds += 1
    check('group reminders stop after the 15-minute cap', rounds == 3, str(rounds))
    check('the request is still open', MHLARRY in f._pending_cashouts)

    # -- a reaction from someone not tagged means nothing --------------------
    reset()
    req = await open_one()
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    req['last_seen'] = stale
    ok = await f.note_cashout_seen(MHLARRY, req['message_id'], 999, 'randomguy')
    check('a stranger reaction is rejected', ok is False)
    check('a stranger reaction does not move the clock', req['last_seen'] == stale)
    check('a stranger reaction does not mark it seen', req['seen'] is False)

    # -- Ethan and Larry count too -------------------------------------------
    reset()
    req = await open_one()
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=10)
    check('Larry reacting counts',
          await f.note_cashout_seen(MHLARRY, req['message_id'], 7418675217, None) is True)

    # -- a reaction on some OTHER message is ignored -------------------------
    reset()
    req = await open_one()
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    req['last_seen'] = stale
    check('a reaction on an unrelated message is ignored',
          await f.note_cashout_seen(MHLARRY, 999999, 77, 'Maynuddin23') is False)
    check('the clock is untouched', req['last_seen'] == stale)

    # -- a reaction in a chat with no open request -----------------------------
    reset()
    check('a reaction with nothing pending is ignored',
          await f.note_cashout_seen(MHLARRY, 12345, 77, 'Maynuddin23') is False)
    check('a reaction in a non-cashout chat is ignored',
          await f.note_cashout_seen(-5339749243, 12345, 77, 'Maynuddin23') is False)

    # -- the handler: removals and anonymous admins are not answers ----------
    reset()
    req = await open_one()
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    req['last_seen'] = stale

    await f.on_request_reaction(Reaction(MHLARRY, req['message_id'],
                                         U(77, 'Maynuddin23'), new=()))
    check('removing a reaction is not an answer', req['last_seen'] == stale)

    await f.on_request_reaction(Reaction(MHLARRY, req['message_id'], None))
    check('an anonymous admin reaction is ignored', req['last_seen'] == stale)

    await f.on_request_reaction(Reaction(MHLARRY, req['message_id'], U(77, 'Maynuddin23')))
    check('a real crew reaction goes through the handler',
          req['last_seen'] != stale and req['seen'] is True)
    check('the handler learned the reactor id', f._user_ids.get('maynuddin23') == 77,
          str(f._user_ids))

    # -- a /out still closes it after a reaction -----------------------------
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    await f.observe_cashout(MHLARRY, '/out 500', 902, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('the /out still closes it after a reaction', not f._pending_cashouts)
    check('and it still books', f.ledger_snapshot(PICCASO) == (0.0, 500.0),
          str(f.ledger_snapshot(PICCASO)))

    # -- Larry is told the moment the request is submitted -------------------
    reset()
    req = await open_one()
    submitted = [t for uid, t in dms if uid == LARRY]
    check('Larry is told on submission', len(submitted) == 1, str(dms))
    check('it says SUBMITTED', submitted and 'SUBMITTED' in submitted[0], str(submitted))
    check('the submission names both groups',
          submitted and 'CHIME PICCASO' in submitted[0]
          and 'MH X LARRY GROUP 2' in submitted[0], str(submitted))
    check('it carries the request text',
          submitted and 'CASHOUT REQUEST $500' in submitted[0], str(submitted))
    check('it says what happens next',
          submitted and 'Waiting on a reaction' in submitted[0], str(submitted))
    check('submission fires before any reaction', req['seen'] is False)

    # -- then again the moment it is picked up -------------------------------
    dms.clear()
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    larry_dms = [t for uid, t in dms if uid == LARRY]
    check('Larry is told it was picked up', len(larry_dms) == 1, str(dms))
    check('the notice says who is handling it',
          larry_dms and 'cashout process is being handled by' in larry_dms[0],
          str(larry_dms))
    check('it names the @username', larry_dms and '@Maynuddin23' in larry_dms[0],
          str(larry_dms))
    check('it carries the request', larry_dms and 'CASHOUT REQUEST $500' in larry_dms[0])
    check('it says the /out is still awaited',
          larry_dms and 'Waiting on the /out' in larry_dms[0], str(larry_dms))

    # -- told once, however many people react --------------------------------
    dms.clear()
    await f.note_cashout_seen(MHLARRY, req['message_id'], 78, 'MHSUPPORTZONE')
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    check('Larry is not told again for the same request',
          not [t for uid, t in dms if uid == LARRY], str(dms))

    # -- and told again when the /out completes ------------------------------
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 500', 902, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    done = [t for uid, t in dms if uid == LARRY]
    check('Larry is told the out completed', len(done) == 1, str(dms))
    check('the display name is included too',
          f.describe_user('Maynuddin23', 'Maynuddin Ahmed')
          == '@Maynuddin23 (Maynuddin Ahmed)', f.describe_user('Maynuddin23', 'Maynuddin Ahmed'))
    check('a missing display name degrades cleanly',
          f.describe_user('Maynuddin23', None) == '@Maynuddin23')
    check('a missing username degrades cleanly',
          f.describe_user(None, 'Maynuddin Ahmed') == 'Maynuddin Ahmed')
    check('it says COMPLETED SUCCESSFULLY',
          done and 'COMPLETED SUCCESSFULLY' in done[0], str(done))
    check('it states the amount', done and 'CASHOUT OF 500.00$' in done[0], str(done))
    check('it names the destination in the headline',
          done and 'TO CHIME PICCASO COMPLETED' in done[0], str(done))
    check('it asks for the screenshot',
          done and 'send the required screenshot to CHIME PICCASO' in done[0], str(done))

    # -- a bare /out completes without claiming a figure ---------------------
    reset()
    req = await open_one()
    await f.observe_cashout(MHLARRY, '/out', 903, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    done = [t for uid, t in dms if uid == LARRY and 'COMPLETED SUCCESSFULLY' in t]
    check('a bare /out still tells Larry', len(done) == 1, str(dms))
    check('a bare /out claims no amount',
          done and 'CASHOUT TO CHIME PICCASO COMPLETED' in done[0], str(done))
    check('it still names the group', done and 'CHIME PICCASO' in done[0], str(done))

    # -- completing without any reaction still notifies ----------------------
    reset()
    await open_one()
    await f.observe_cashout(MHLARRY, '/out 25', 904, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('an unreacted request still reports completion',
          len([t for uid, t in dms if uid == LARRY and 'COMPLETED SUCCESSFULLY' in t]) == 1,
          str(dms))
    check('and it was submitted first',
          len([t for uid, t in dms if uid == LARRY and 'SUBMITTED' in t]) == 1, str(dms))

    # -- the completion notice comes AFTER the chime group is hearted --------
    reset()
    order = []
    real_heart = f.heart_request
    async def traced_heart(chat_id, message_id):
        order.append('heart')
        return await real_heart(chat_id, message_id)
    f.heart_request = traced_heart
    real_dm = f.dm_handles
    async def traced_dm(handles, text):
        if 'COMPLETED SUCCESSFULLY' in text:
            order.append('completed-dm')
        return await real_dm(handles, text)
    f.dm_handles = traced_dm

    await open_one()
    await f.observe_cashout(MHLARRY, '/out 75', 905, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    f.heart_request, f.dm_handles = real_heart, real_dm
    check('the heart is applied before Larry is told it completed',
          order == ['heart', 'completed-dm'], str(order))

    # -- nobody reacts: Larry AND the crew are told once, on the first round --
    reset()
    f._user_ids['larryyxx'] = 7418675217
    req = await open_one()
    dms.clear()
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()
    larry = [t for uid, t in dms if uid == LARRY and 'OUT REQUEST HAS CROSSED' in t]
    crew = [t for uid, t in dms if uid == 77]
    check('Larry is told on the first round', len(larry) == 1, str(dms))
    check('it carries the request and the routing',
          larry and 'CASHOUT REQUEST $500' in larry[0]
          and 'CHIME PICCASO' in larry[0] and 'MH X LARRY GROUP 2' in larry[0], str(larry))
    check('it says nobody has sent a /out',
          larry and 'Nobody has sent a /out' in larry[0], str(larry))
    check('the crew are told on the same round', len(crew) == 1, str(dms))
    check('the crew DM carries no routing',
          crew and 'Waiting in:' not in crew[0] and 'From:' not in crew[0], str(crew))

    dms.clear()
    for _ in range(3):
        req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=6)
        await run_watchdog()
    check('no DM is ever repeated on later rounds', dms == [], str(dms))

    # -- a reacted request escalates privately, never back into the group -----
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    dms.clear(); sent.clear()
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=8)
    await run_watchdog()
    check('an acknowledged request is not re-tagged in the group', sent == [], str(sent))
    check('the crew get the private word instead',
          [t for uid, t in dms if uid == 77], str(dms))

    # -- a cap can still be re-imposed ---------------------------------------
    reset()
    f.CASHOUT_MAX_NUDGES = 2
    req = await open_one()
    for _ in range(5):
        req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=6)
        await run_watchdog()
    check('CASHOUT_MAX_NUDGES still caps when set', req['nudges'] == 2, str(req['nudges']))
    f.CASHOUT_MAX_NUDGES = 0

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all reaction checks passed")


asyncio.run(main())
