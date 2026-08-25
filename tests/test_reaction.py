"""A crew reaction buys another timeout; silence keeps the chasing going."""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, MHLARRY = -5350880041, -1003894781195
LARRY, CREW = f.LARRY_ID, 77
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
    await f.observe_cashout(PICCASO, '!! Cashout Request !! Tag name : $jenny-buhr Amount : 500', 901,
                            datetime.now(timezone.utc), user_id=42)
    return f._pending_cashouts[MHLARRY][0]


def clock(req, waited, seen_min=None):
    """Place a request `waited` minutes after it opened.

    Both marks are set relative to 'opened', never to the wall clock, because
    the acknowledged ladder is measured from the gap between them - moving one
    without the other silently changes which mark Larry's notice lands on."""
    now = datetime.now(timezone.utc)
    req['opened'] = now - timedelta(minutes=waited)
    if seen_min is not None:
        req['seen_at'] = req['opened'] + timedelta(minutes=seen_min)


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

    # -- a crew reaction takes the chase OUT of the group --------------------
    reset()
    f._user_ids['larryyxx'] = LARRY
    req = await open_one()
    req['last_seen'] = now - timedelta(minutes=10)          # overdue
    ok = await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    check('a crew reaction is accepted', ok is True)
    check('it records that somebody engaged',
          (datetime.now(timezone.utc) - req['last_seen']).total_seconds() < 5)
    check('the request is marked seen', req['seen'] is True)
    check('it records when it was acknowledged', req['seen_at'] is not None)
    check('and by whom', bool(req['seen_by']), str(req['seen_by']))
    check('it does NOT close the request', MHLARRY in f._pending_cashouts)

    # -- nothing happens in the six minutes after the reaction ---------------
    sent.clear(); dms.clear()
    clock(req, 8, seen_min=3)                  # five minutes since the reaction
    await run_watchdog()
    check('nothing before the six minutes are up',
          sent == [] and dms == [], str((sent, dms)))

    # -- six minutes on, the GROUP stays silent and Larry is told instead ----
    clock(req, 9, seen_min=3)                  # six minutes since the reaction
    await run_watchdog()
    check('an acknowledged request is NOT re-tagged in the group',
          sent == [], str(sent))
    larry = [t for uid, t in dms if uid == LARRY]
    check('Larry is told six minutes after the reaction',
          len(larry) == 1, str(dms))
    check('his notice says acknowledged and still not processed',
          larry and 'ACKNOWLEDGED BUT STILL NOT PROCESSED' in larry[0], str(larry))
    check('it names who acknowledged it',
          larry and '@Maynuddin23' in larry[0], str(larry))
    check('it carries the routing, as every admin DM does',
          larry and 'Waiting in:' in larry[0] and 'From:' in larry[0], str(larry))
    check('the crew are not DMed', [t for uid, t in dms if uid == 77] == [], str(dms))
    check('the chasing is over', req['exhausted'] is True)
    check('but the request stays OPEN for a late /out', MHLARRY in f._pending_cashouts)

    # -- and nothing more, ever - including at the crew's 10-minute mark -----
    sent.clear(); dms.clear()
    for minutes in (10, 12, 17, 20, 30):
        clock(req, minutes, seen_min=3)
        await run_watchdog()
    check('no group post and no DM of any kind after that',
          sent == [] and dms == [], str((sent, dms)))

    # -- acknowledged AFTER everything else has run out ---------------------
    # The six minutes run from the acknowledgement, so reacting late does not
    # shorten them - and the request is picked back up even though chasing had
    # already stopped.
    reset()
    f._user_ids['larryyxx'] = LARRY
    req = await open_one()
    clock(req, 13)
    await run_watchdog()                       # burns the ladder and the crew DM
    check('chasing had already stopped', req['exhausted'] is True)
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    sent.clear(); dms.clear()

    clock(req, 18, seen_min=14)                # four minutes since the reaction
    await run_watchdog()
    check('a late acknowledgement does not shorten the six minutes',
          [t for uid, t in dms if uid == LARRY] == [], str(dms))

    clock(req, 20, seen_min=14)                # six minutes since the reaction
    await run_watchdog()
    check('a late acknowledgement still reaches Larry',
          [t for uid, t in dms if uid == LARRY] != [], str(dms))
    check('and the crew are not chased again on top of it',
          [t for uid, t in dms if uid == 77] == [], str(dms))
    check('nothing goes back into the group either', sent == [], str(sent))

    # -- unacknowledged: three group rounds across the whole ladder ----------
    reset()
    req = await open_one()
    rounds = 0
    for minutes in (4, 5, 6, 8, 9, 12, 13, 14, 16):
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        sent.clear()
        await run_watchdog()
        if sent: rounds += 1
    check('exactly three group reminders across the ladder', rounds == 3, str(rounds))
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

    # -- Ethan and Larry do NOT count ----------------------------------------
    # They used to. Acknowledgement now stops the group chase outright, so an
    # admin reacting would silence the very reminders meant for the crew.
    reset()
    req = await open_one()
    req['last_seen'] = datetime.now(timezone.utc) - timedelta(minutes=10)
    check('Larry reacting does NOT acknowledge it',
          await f.note_cashout_seen(MHLARRY, req['message_id'], LARRY, None) is False)
    check('and it stays unacknowledged', req['seen'] is False)
    check('so the group chase is untouched', req['seen_at'] is None)

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
          await f.note_cashout_seen(-1004298140797, 12345, 77, 'Maynuddin23') is False)

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
          submitted and '!! Cashout Request !! Tag name : $jenny-buhr Amount : 500' in submitted[0], str(submitted))
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
    check('it carries the request', larry_dms and '!! Cashout Request !! Tag name : $jenny-buhr Amount : 500' in larry_dms[0])
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

    # -- nobody reacts: Larry on the first rung, the crew not until 17 min ---
    reset()
    f._user_ids['larryyxx'] = f.LARRY_ID
    req = await open_one()
    dms.clear()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()
    larry = [t for uid, t in dms if uid == LARRY and 'OUT REQUEST HAS CROSSED' in t]
    crew = [t for uid, t in dms if uid == 77]
    check('Larry is told on the first rung', len(larry) == 1, str(dms))
    check('it carries the request and the routing',
          larry and '!! Cashout Request !! Tag name : $jenny-buhr Amount : 500' in larry[0]
          and 'CHIME PICCASO' in larry[0] and 'MH X LARRY GROUP 2' in larry[0], str(larry))
    check('it says nobody has sent a /out',
          larry and 'Nobody has sent a /out' in larry[0], str(larry))
    check('the crew are NOT told on the same rung', len(crew) == 0, str(dms))

    dms.clear()
    for minutes in (8, 9):
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        await run_watchdog()
    check('the crew are still not DMed before their mark', dms == [], str(dms))

    # 10 minutes, unacknowledged: the crew get their one private word. It sits
    # BETWEEN two group rungs, and must not cancel the 12-minute one.
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=10)
    sent.clear()
    await run_watchdog()
    crew = [t for uid, t in dms if uid == 77]
    check('the crew are told at 10 minutes', len(crew) == 1, str(dms))
    check('the crew DM carries no routing',
          crew and 'Waiting in:' not in crew[0] and 'From:' not in crew[0], str(crew))
    check('Larry is not told a second time',
          len([t for uid, t in dms if uid == LARRY
               and 'OUT REQUEST HAS CROSSED' in t]) == 0, str(dms))
    check('the chase is not over - the last rung is still to come',
          req['exhausted'] is False)

    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=12)
    await run_watchdog()
    check('the 12-minute rung still posts after the crew DM',
          len(sent) == 1, str(sent))
    check('and only then is the chase over', req['exhausted'] is True)

    dms.clear(); sent.clear()
    for minutes in (13, 16, 20, 30):
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        await run_watchdog()
    check('nothing repeats after both channels run out',
          sent == [] and dms == [], str((sent, dms)))

    # -- a reacted request escalates privately, never back into the group -----
    reset()
    req = await open_one()
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    dms.clear(); sent.clear()
    clock(req, 8, seen_min=1)
    await run_watchdog()
    check('an acknowledged request is never re-tagged in the group',
          sent == [], str(sent))
    check('and the crew get no private word either',
          [t for uid, t in dms if uid == 77] == [], str(dms))

    # -- a cap can still be re-imposed ---------------------------------------
    reset()
    f.CASHOUT_MAX_NUDGES = 2
    req = await open_one()
    for minutes in (5, 6, 8, 9, 12, 13, 14, 16):
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        await run_watchdog()
    check('CASHOUT_MAX_NUDGES still caps when set', req['nudges'] == 2, str(req['nudges']))
    f.CASHOUT_MAX_NUDGES = 0

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all reaction checks passed")


asyncio.run(main())
