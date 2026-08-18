"""Both routes must behave identically at every stage.

CHIME PICCASO -> MH X LARRY GROUP 2   and   CHIME GAFFER -> Chime Rev & out no-7
"""
import asyncio, os, sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
LARRY = 7418675217
CREW = 555
sent, dms, reactions, failures = [], [], [], []
real_sleep = asyncio.sleep


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(7000 + len(sent) + len(dms))
    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id)); return True


f.bot = FakeBot(); f.USERBOT_SEND = False; f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def reset():
    sent.clear(); dms.clear(); reactions.clear(); f._ledger.clear()
    f._seen_messages.clear(); f._pending_cashouts.clear()
    f._user_ids['larryyxx'] = LARRY
    # A learned crew id, so a crew DM would actually be delivered here. Without
    # one, "the crew were not DMed" passes for the wrong reason.
    f._user_ids['maynuddin23'] = CREW


async def run_watchdog(seconds=0.2):
    async def fast(_): await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


async def full_flow(origin, base):
    """Drive one route end to end and record what happened at each stage."""
    handling = f.CASHOUT_ROUTES[origin]['handling']
    reset()
    now = datetime.now(timezone.utc)
    r = {'handling': handling}

    # 1. submitted
    await f.observe_cashout(origin, 'CASHOUT REQUEST $500 for Gabriel W.',
                            base + 1, now, user_id=42)
    r['forwarded'] = len([1 for c, _ in sent if c == handling])
    r['tagged'] = any('@Maynuddin23' in t for c, t in sent if c == handling)
    r['wrong_group'] = any(c not in (handling,) for c, _ in sent)
    r['submitted_dm'] = len([1 for uid, t in dms if uid == LARRY and 'SUBMITTED' in t])
    req = f._pending_cashouts[handling][0]

    # 2. nobody responds. The ladder is measured from 'opened'.
    sent.clear(); dms.clear()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()
    r['nudge'] = len([1 for c, _ in sent if c == handling])
    r['nudge_is_reply'] = all('OUT REQUEST HAS CROSSED' in t for c, t in sent if c == handling)
    r['no_ethan'] = not any('ETHAN' in t for c, t in sent if c == handling)
    r['escalation_dm'] = len([1 for _, t in dms if 'OUT REQUEST HAS CROSSED' in t])
    # Larry hears about it on the FIRST round, once, with the routing.
    r['larry_told'] = len([1 for uid, t in dms
                           if uid == LARRY and 'OUT REQUEST HAS CROSSED' in t])
    # The crew are tagged in the group on this rung, and NOT DMed.
    r['crew_dm_early'] = len([1 for uid, _ in dms if uid == CREW])
    # ...and it never repeats on the rounds after it.
    dms.clear()
    for _ in range(3):
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
        await run_watchdog()
    r['no_repeat_dm'] = len(dms)

    # Past the whole group ladder: now, and only now, the crew get one DM.
    dms.clear()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=18)
    await run_watchdog()
    r['crew_dm_late'] = len([1 for uid, _ in dms if uid == CREW])
    # Reset for the rest of the walk-through, which expects a live request.
    req['opened'] = datetime.now(timezone.utc)
    req['exhausted'] = False
    req['crew_told'] = False

    # 3. a crew reaction
    dms.clear()
    await f.note_cashout_seen(handling, req['message_id'], 77,
                              'Maynuddin23', 'Maynuddin Ahmed')
    r['picked_up_dm'] = len([1 for uid, t in dms
                             if uid == LARRY and 'being handled by' in t])
    r['seen'] = req['seen']

    # 4. the /out
    sent.clear(); dms.clear(); reactions.clear()
    await f.observe_cashout(handling, '/out 500', base + 2,
                            datetime.now(timezone.utc), user_id=77, username='Maynuddin23')
    r['out_home'] = len([1 for c, t in sent if c == origin and t == '/out 500'])
    r['totals_posted'] = len([1 for c, t in sent if c == origin and 'Group Total' in t])
    r['ledger'] = f.ledger_snapshot(origin)
    r['hearted'] = reactions[:]
    r['completed_dm'] = len([1 for uid, t in dms
                             if uid == LARRY and 'COMPLETED SUCCESSFULLY' in t])
    r['names_group'] = any(f.chat_name(origin) in t for uid, t in dms
                           if uid == LARRY and 'COMPLETED SUCCESSFULLY' in t)
    r['closed'] = handling not in f._pending_cashouts
    return r


async def main():
    a = await full_flow(PICCASO, 900)
    b = await full_flow(GAFFER, 800)

    for name, r, origin, handling in (('PICCASO', a, PICCASO, MHLARRY),
                                      ('GAFFER', b, GAFFER, CHIMEREV)):
        print(f"\n{name} -> {f.chat_name(handling)}")
        check(f'{name}: request forwarded to its own handling group',
              r['forwarded'] == 1 and not r['wrong_group'], str(r))
        check(f'{name}: crew tagged', r['tagged'])
        check(f'{name}: Larry told it was submitted', r['submitted_dm'] == 1)
        check(f'{name}: re-tagged in the group after 5 min', r['nudge'] == 1)
        check(f'{name}: reminder carries the headline', r['nudge_is_reply'])
        check(f'{name}: no ETHAN footprint in the handling group', r['no_ethan'])
        check(f'{name}: escalation DMs sent', r['escalation_dm'] >= 1)
        check(f'{name}: Larry told once on the first round', r['larry_told'] == 1)
        check(f'{name}: no DM is repeated on later rounds', r['no_repeat_dm'] == 0,
              str(r['no_repeat_dm']))
        check(f'{name}: the crew are not DMed while the group ladder runs',
              r['crew_dm_early'] == 0, str(r['crew_dm_early']))
        check(f'{name}: the crew get one DM once past 17 min',
              r['crew_dm_late'] == 1, str(r['crew_dm_late']))
        check(f'{name}: a reaction marks it seen', r['seen'] is True)
        check(f'{name}: Larry told who picked it up', r['picked_up_dm'] == 1)
        check(f'{name}: /out returned to its own chime group', r['out_home'] == 1)
        check(f'{name}: totals posted where the books moved', r['totals_posted'] == 1)
        check(f'{name}: Total Out booked', r['ledger'] == (0.0, 500.0), str(r['ledger']))
        check(f'{name}: ❤ on the original request in the chime group',
              r['hearted'] == [(origin, (900 if name == 'PICCASO' else 800) + 1)],
              str(r['hearted']))
        check(f'{name}: Larry told it completed', r['completed_dm'] == 1)
        check(f'{name}: completion names its own group', r['names_group'])
        check(f'{name}: request closed', r['closed'])

    # -- the two routes must be structurally identical -----------------------
    print("\nparity")
    shape = lambda r: {k: v for k, v in r.items()
                       if k not in ('handling', 'hearted', 'ledger')}
    check('every stage behaves identically on both routes',
          shape(a) == shape(b),
          str({k: (shape(a)[k], shape(b)[k]) for k in shape(a)
               if shape(a)[k] != shape(b)[k]}))
    check('each books only its own ledger', a['ledger'] == b['ledger'] == (0.0, 500.0))
    check('each hearts in its own chime group',
          a['hearted'][0][0] == PICCASO and b['hearted'][0][0] == GAFFER,
          f"{a['hearted']} {b['hearted']}")

    # -- cross-contamination: one route must never touch the other ----------
    reset()
    now = datetime.now(timezone.utc)
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $80', 700, now, user_id=42)
    check('a GAFFER request never reaches MH X LARRY',
          not any(c == MHLARRY for c, _ in sent), str(sent))
    await f.observe_cashout(MHLARRY, '/out 80', 701, now, user_id=77, username='Maynuddin23')
    check('a /out in MH X LARRY cannot answer a GAFFER request',
          CHIMEREV in f._pending_cashouts and f.ledger_snapshot(GAFFER) == (0.0, 0.0),
          str(f._pending_cashouts))
    await f.observe_cashout(CHIMEREV, '/out 80', 702, now, user_id=77, username='Maynuddin23')
    check('the right group closes it', CHIMEREV not in f._pending_cashouts)
    check('and books only GAFFER', f.ledger_snapshot(GAFFER) == (0.0, 80.0)
          and PICCASO not in f._ledger, str(f.ledger_snapshot(GAFFER)))

    # -- deletion parity ------------------------------------------------------
    for name, origin, handling, mid in (('PICCASO', PICCASO, MHLARRY, 601),
                                        ('GAFFER', GAFFER, CHIMEREV, 602)):
        reset()
        await f.observe_cashout(origin, 'CASHOUT REQUEST $10', mid, now, user_id=42)
        copy_id = f._pending_cashouts[handling][0]['message_id']

        class FakeClient:
            async def get_entity(self, cid): return type('E', (), {'id': cid})()
            async def get_messages(self, entity, ids=None): return [None]
        await f.close_deleted_cashouts(FakeClient(), origin, [mid])
        check(f'{name}: deleting the request settles it', not f._pending_cashouts)

        reset()
        await f.observe_cashout(origin, 'CASHOUT REQUEST $10', mid, now, user_id=42)
        copy_id = f._pending_cashouts[handling][0]['message_id']
        await f.close_deleted_cashouts(FakeClient(), handling, [copy_id])
        check(f'{name}: deleting the forwarded copy settles it', not f._pending_cashouts)

    # -- a /out with nothing pending is ignored on both ---------------------
    for name, handling in (('PICCASO', MHLARRY), ('GAFFER', CHIMEREV)):
        reset()
        await f.observe_cashout(handling, '/out 200', 500, now, user_id=77,
                                username='Maynuddin23')
        check(f'{name}: /out with nothing pending is ignored',
              sent == [] and reactions == [], str(sent))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("both routes verified identical")


asyncio.run(main())
