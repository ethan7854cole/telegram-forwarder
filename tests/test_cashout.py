"""Exercise the cashout flow against a stubbed bot. No network, no Telegram."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
BOTID = 111222

sent, reactions, dms = [], [], []
_next_id = [5000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        if chat_id > 0:                      # a person, not a group
            dms.append((chat_id, text))
        else:
            sent.append((chat_id, text, reply_to_message_id))
        return FakeMsg(_next_id[0])

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id, reaction[0].emoji))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False          # no user account in the test
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


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. a request opens, is posted to the handling group, tagged ----------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $500 for Gabriel',
                            901, now, user_id=42, username='chimeguy')
    check('request forwarded to the handling group', len(sent) == 1 and sent[0][0] == MHLARRY)
    check('crew tagged on the forward', '@Maynuddin23' in sent[0][1] and '@MHSUPPORTZONE' in sent[0][1])
    check('original text preserved', 'CASHOUT REQUEST $500 for Gabriel' in sent[0][1])
    check('one request now open', len(f._pending_cashouts.get(MHLARRY, [])) == 1)
    posted_id = f._pending_cashouts[MHLARRY][0]['message_id']
    check('the origin message id is kept for the reaction',
          f._pending_cashouts[MHLARRY][0]['origin_msg_id'] == 901,
          str(f._pending_cashouts[MHLARRY][0]))

    # -- 2. GAFFER routes to its own group, not PICCASO's --------------------
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $80', 902, now, user_id=43)
    check('GAFFER routes to Chime Rev', sent[-1][0] == CHIMEREV)

    # -- 3. the /out answer goes home and earns the heart --------------------
    await f.observe_cashout(MHLARRY, '/out 500 done', 903, now,
                            user_id=77, username='Maynuddin23')
    check('/out sent back to the origin group',
          any(c == PICCASO for c, _, _ in sent), str(sent))
    check('/out text forwarded verbatim',
          any(c == PICCASO and t == '/out 500 done' for c, t, _ in sent), str(sent))
    check('❤ lands on the ORIGINAL request in the chime group',
          reactions == [(PICCASO, 901, '❤')], str(reactions))
    check('❤ does NOT land in the handling group',
          not any(c == MHLARRY for c, _, _ in reactions), str(reactions))
    check('request closed', MHLARRY not in f._pending_cashouts)
    check('origin Total Out booked from the /out',
          f.ledger_snapshot(PICCASO)[1] == 500.0, str(f.ledger_snapshot(PICCASO)))

    # -- 4. a /out with nothing pending is ignored entirely ------------------
    reset()
    await f.observe_cashout(MHLARRY, '/out 200', 910, now, user_id=77, username='Maynuddin23')
    check('/out with nothing pending is ignored', sent == [] and reactions == [])

    # -- 5. a non-keyword message in a chime group opens nothing -------------
    reset()
    await f.observe_cashout(PICCASO, 'You received $15.0 from Gabriel W.', 911, now, user_id=42)
    check('ordinary chime traffic opens no request', sent == [] and not f._pending_cashouts)

    # -- 6. our own posts never loop -----------------------------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $1', 912, now, user_id=BOTID)
    check('own bot message ignored', sent == [] and not f._pending_cashouts)

    # -- 7. dedup across the two input paths ---------------------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $99', 913, now, user_id=42)
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $99', 913, now, user_id=42)
    check('same message seen twice forwards once', len(sent) == 1)

    # -- 7b. the SAME request arriving as two DIFFERENT messages -------------
    # Message-id dedup cannot see this one: a double send, or two copies
    # carrying different ids, used to land as two identical posts in the
    # handling group, two sets of reminders and two things to answer for one
    # cashout.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $120 $Hawkins-Floral-Decor',
                            930, now, user_id=42)
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $120 $Hawkins-Floral-Decor',
                            931, now, user_id=42)
    check('an identical request under a different id is posted once',
          len(sent) == 1, str(sent))
    check('and only one request is left open',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1,
          str(f._pending_cashouts.get(MHLARRY, [])))

    await f.observe_cashout(PICCASO, 'cashout request  $120   $Hawkins-Floral-Decor',
                            932, now, user_id=42)
    check('reformatting the same request does not slip past it',
          len(sent) == 1, str(sent))

    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $75 for someone else',
                            933, now, user_id=42)
    check('a genuinely different request is still posted', len(sent) == 2, str(sent))

    # -- 7c. past the window it is taken at face value -----------------------
    # Asking for the same amount to the same cashtag again later is ordinary,
    # so the guard is a burst filter, not a permanent block.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $120', 934, now, user_id=42)
    f._pending_cashouts[MHLARRY][0]['opened'] -= timedelta(
        seconds=f.CASHOUT_DEDUP_SECONDS + 1)
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $120', 935, now, user_id=42)
    check('the same request asked for again later is a real second one',
          len(sent) == 2, str(sent))

    # -- 7d. and once the first is actioned, an identical one is welcome -----
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $120', 936, now, user_id=42)
    await f.observe_cashout(MHLARRY, '/out 120', 937, now,
                            user_id=77, username='Maynuddin23')
    check('the first is closed by its /out', MHLARRY not in f._pending_cashouts)
    sent.clear()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $120', 938, now, user_id=42)
    check('an identical request after the first is settled still posts',
          len(sent) == 1, str(sent))

    # -- 7e. acknowledged, then answered with anything but a /out ------------
    # Different in kind from silence: somebody is engaged and still not sending
    # the /out, which usually means they have hit a problem. Ethan and Larry
    # hear at once rather than after the 7-minute window.
    ETHAN, LARRY = f.ADMIN_ID, 7418675217
    f._user_ids['larryyxx'] = LARRY

    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $200', 940, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23',
                              'Maynuddin Ahmed')
    dms.clear(); sent.clear()

    await f.observe_cashout(MHLARRY, 'cashapp is not letting me', 941, now,
                            user_id=77, username='Maynuddin23',
                            full_name='Maynuddin Ahmed')
    alerts = [t for uid, t in dms if 'SOMETHING IS WRONG' in t]
    check('Ethan and Larry are both told at once', len(alerts) == 2, str(dms))
    check('the crew are NOT told', not [t for uid, t in dms if uid == 77], str(dms))
    check('it names which crew member',
          alerts and '@Maynuddin23' in alerts[0] and 'Maynuddin Ahmed' in alerts[0],
          str(alerts[:1]))
    check('it carries their id', alerts and 'Their id: 77' in alerts[0], str(alerts[:1]))
    check('it says to check the group', alerts and "check the group's messages" in alerts[0],
          str(alerts[:1]))
    check('it carries the routing',
          alerts and 'CHIME PICCASO' in alerts[0] and 'MH X LARRY GROUP 2' in alerts[0],
          str(alerts[:1]))
    check('nothing is posted in the group', sent == [], str(sent))
    check('the request stays open', MHLARRY in f._pending_cashouts)

    # once per request, however much they say
    dms.clear()
    await f.observe_cashout(MHLARRY, 'still stuck', 942, now,
                            user_id=77, username='Maynuddin23')
    check('the alert does not repeat',
          not [t for uid, t in dms if 'SOMETHING IS WRONG' in t], str(dms))

    # -- 7f. a screenshot with NO caption counts as the same signal ----------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $200', 943, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    dms.clear()
    await f.observe_cashout(MHLARRY, None, 944, now, user_id=77,
                            username='Maynuddin23', has_media=True)
    check('a bare screenshot after acknowledging raises the alert',
          len([t for uid, t in dms if 'SOMETHING IS WRONG' in t]) == 2, str(dms))

    # -- 7g. and the cases that must NOT raise it ---------------------------
    # The first thing anyone says is an acknowledgement, not a problem.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $200', 945, now, user_id=42)
    dms.clear()
    await f.observe_cashout(MHLARRY, 'looking now', 946, now,
                            user_id=77, username='Maynuddin23')
    check('the first message is just an acknowledgement',
          not [t for uid, t in dms if 'SOMETHING IS WRONG' in t], str(dms))

    # A /out is the answer, not a problem.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $200', 947, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    dms.clear()
    # reset() here does not clear the ledger, so measure the movement, not the
    # absolute figure.
    before_out = f.ledger_snapshot(PICCASO)[1]
    await f.observe_cashout(MHLARRY, '/out 200', 948, now,
                            user_id=77, username='Maynuddin23')
    check('a /out raises no alert',
          not [t for uid, t in dms if 'SOMETHING IS WRONG' in t], str(dms))
    check('and still completes the cashout',
          f.ledger_snapshot(PICCASO)[1] == before_out + 200.0,
          str((before_out, f.ledger_snapshot(PICCASO))))
    check('and closes the request', MHLARRY not in f._pending_cashouts)

    # A stranger talking is not the crew hitting a problem.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $200', 949, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    await f.note_cashout_seen(MHLARRY, req['message_id'], 77, 'Maynuddin23')
    dms.clear()
    await f.observe_cashout(MHLARRY, 'unrelated chatter', 950, now,
                            user_id=999, username='randomguy')
    check('a stranger raises no alert',
          not [t for uid, t in dms if 'SOMETHING IS WRONG' in t], str(dms))

    # With nothing open, the handling group is ordinary traffic.
    reset()
    dms.clear()
    await f.observe_cashout(MHLARRY, 'anything at all', 951, now,
                            user_id=77, username='Maynuddin23')
    check('nothing pending means no alert', dms == [] and sent == [], str(dms))

    # -- 8. alternate -100 id spelling still matches -------------------------
    reset()
    await f.observe_cashout(-1002335630148, '/out 5', 914, now, user_id=77, username='Maynuddin23')
    check('handling group recognised with nothing open', sent == [])

    # -- 9. two open requests: reply-to wins, else oldest --------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST A', 920, now, user_id=42)
    first = f._pending_cashouts[MHLARRY][0]['message_id']
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST B', 921, now, user_id=42)
    second = f._pending_cashouts[MHLARRY][1]['message_id']
    await f.observe_cashout(MHLARRY, '/out B', 922, now, user_id=77,
                            username='Maynuddin23', reply_to=second)
    # reply-to still matches on the handling-group copy (that is what they hit
    # reply on), but the ❤ lands on request B's ORIGIN message, 921.
    check('reply-to answers that exact request',
          reactions and reactions[-1] == (PICCASO, 921, '❤'), str(reactions))
    await f.observe_cashout(MHLARRY, '/out A', 923, now, user_id=77, username='Maynuddin23')
    check('bare /out answers the oldest remaining',
          reactions[-1] == (PICCASO, 920, '❤'), str(reactions))
    check('both requests closed', MHLARRY not in f._pending_cashouts)

    # -- 10. escalation: re-tag in group + private warnings ------------------
    reset()
    f._user_ids['maynuddin23'] = 555            # learned id, so the bot can DM
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $700', 930, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    req['last_seen'] = now - timedelta(minutes=6)        # push past the timeout
    sent.clear(); dms.clear()

    real_sleep = asyncio.sleep
    async def fast(_):
        await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(0.25)
    task.cancel()
    f.asyncio.sleep = real_sleep

    nudges = [s for s in sent if s[0] == MHLARRY]
    check('re-tagged in the handling group', len(nudges) >= 1, str(sent))
    check('reminder replies to the request', nudges and nudges[0][2] == req['message_id'])
    check('reminder carries the required wording',
          nudges and 'OUT REQUEST HAS CROSSED' in nudges[0][1], nudges[0][1] if nudges else '')
    check('reminder re-tags the crew', nudges and '@Maynuddin23' in nudges[0][1])
    check('private warning sent', any('OUT REQUEST HAS CROSSED' in t for _, t in dms), str(dms))

    # Through the real watchdog: Ethan and Larry get the routing, the crew do not.
    # 'OUT REQUEST HAS CROSSED' separates the escalation DM from the separate
    # notify_admin alert about who could not be reached, which also goes to Ethan.
    admin_dms = [t for uid, t in dms
                 if uid in (f.ADMIN_ID, 7418675217) and 'OUT REQUEST HAS CROSSED' in t]
    crew_dms = [t for uid, t in dms if uid == 555]        # learned id, above
    check('Ethan and Larry both warned', len(admin_dms) == 2, str(len(admin_dms)))
    check('admin DMs carry the routing',
          all('From:' in t and 'Waiting in:' in t for t in admin_dms), str(admin_dms))
    check('the crew were warned too', len(crew_dms) == 1, str(len(crew_dms)))
    check('crew DM carries no routing',
          all('From:' not in t and 'Waiting in:' not in t for t in crew_dms), str(crew_dms))
    check('crew DM names no group',
          not any(n in t for t in crew_dms
                  for n in ('CHIME PICCASO', 'MH X LARRY', 'CHIME GAFFER', 'Chime Rev')),
          str(crew_dms))
    check('group reminders stop after three rounds (5/10/15 min)',
          f.CASHOUT_MAX_NUDGES == 3, str(f.CASHOUT_MAX_NUDGES))
    check('an acknowledged request gets a longer window than a silent one',
          f.CASHOUT_SEEN_MINUTES == 7 and f.CASHOUT_TIMEOUT_MINUTES == 5,
          str((f.CASHOUT_SEEN_MINUTES, f.CASHOUT_TIMEOUT_MINUTES)))
    check('at least one reminder went out', req['nudges'] >= 1, str(req['nudges']))
    check('request stays open while unanswered', MHLARRY in f._pending_cashouts)
    check('the reminder is not signed -ETHAN',
          nudges and 'ETHAN' not in nudges[0][1], nudges[0][1] if nudges else '')

    # -- NOTHING the bot posts into a handling group carries Ethan's name ----
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $400', 960, now, user_id=42)
    await f.observe_cashout(GAFFER, 'CASHOUT REQUEST $60', 961, now, user_id=42)
    for chat in (MHLARRY, CHIMEREV):
        f._pending_cashouts[chat][0]['last_seen'] = now - timedelta(minutes=6)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(0.25)
    task.cancel()
    f.asyncio.sleep = real_sleep
    handling_posts = [t for c, t, _ in sent if c in (MHLARRY, CHIMEREV)]
    check('handling groups received messages at all', len(handling_posts) >= 3,
          str(len(handling_posts)))
    check('no ETHAN footprint in either handling group',
          not any('ETHAN' in t for t in handling_posts),
          str([t for t in handling_posts if 'ETHAN' in t]))

    # -- but the chime groups keep their sign-off ---------------------------
    check('milestone messages are still signed',
          '-ETHAN' in f.in_milestone_text(5000, 5000.0, 0.0)
          and '-ETHAN' in f.out_milestone_text(1000, 0.0, 1000.0))
    check('idle prompts are still signed', '-ETHAN' in f.idle_alert_text(GAFFER, 90, 0))

    # -- 11. a crew reply resets the clock -----------------------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $300', 940, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    req['last_seen'] = now - timedelta(minutes=10)
    await f.observe_cashout(MHLARRY, 'checking now', 941, now, user_id=77, username='MHSUPPORTZONE')
    check('crew reply resets the reminder clock',
          (datetime.now(timezone.utc) - req['last_seen']).total_seconds() < 5)
    check('acknowledgement alone does not close it', MHLARRY in f._pending_cashouts)

    # -- 12. a stranger talking does NOT reset the clock ---------------------
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $10', 950, now, user_id=42)
    req = f._pending_cashouts[MHLARRY][0]
    stale = now - timedelta(minutes=10)
    req['last_seen'] = stale
    await f.observe_cashout(MHLARRY, 'unrelated chatter', 951, now, user_id=999, username='randomguy')
    check('a stranger does not silence the alert', req['last_seen'] == stale)

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
