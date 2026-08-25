"""Routes must be reconfigurable from env, including a separate /out target."""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

sent, reactions, failures = [], [], []


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        sent.append((chat_id, text)); return FakeMsg(7000 + len(sent))
    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id)); return True


f.bot = FakeBot(); f.USERBOT_SEND = False; f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def use_routes(spec):
    """Swap in a route table exactly as the env var would produce it."""
    sent.clear(); reactions.clear(); f._ledger.clear()
    f._seen_messages.clear(); f._pending_cashouts.clear()
    f.CASHOUT_ROUTES.clear()
    f.CASHOUT_ROUTES.update(f._parse_cashout_routes(spec))
    f._CASHOUT_HANDLERS.clear()
    f._CASHOUT_HANDLERS.update({r['handling']: s for s, r in f.CASHOUT_ROUTES.items()})


async def main():
    now = datetime.now(timezone.utc)

    # -- parsing -------------------------------------------------------------
    r = f._parse_cashout_routes('-100:-200')
    check('two fields parse, /out defaults to the asking group',
          r == {-100: {'handling': -200, 'out_to': -100}}, str(r))
    r = f._parse_cashout_routes('-100:-200:-300')
    check('three fields send the /out elsewhere',
          r == {-100: {'handling': -200, 'out_to': -300}}, str(r))
    r = f._parse_cashout_routes(' -100 : -200 , -400:-500:-600 ')
    check('whitespace and multiple routes parse', len(r) == 2 and r[-400]['out_to'] == -600,
          str(r))
    r = f._parse_cashout_routes('-100:-200,rubbish,-400:-500')
    check('a malformed route is dropped, the good ones survive',
          sorted(r) == [-400, -100][::-1] or sorted(r) == [-400, -100], str(r))
    check('a bad route does not crash the parser', len(r) == 2, str(r))
    r = f._parse_cashout_routes('abc:def')
    check('non-numeric ids are rejected', r == {}, str(r))
    r = f._parse_cashout_routes('')
    check('an empty setting yields no routes', r == {}, str(r))

    # -- the shipped default is unchanged behaviour --------------------------
    default = f._parse_cashout_routes('-5350880041:-1003894781195,'
                                      '-5580596463:-1002335630148')
    check('default PICCASO route unchanged',
          default[-5350880041] == {'handling': -1003894781195, 'out_to': -5350880041},
          str(default))
    check('default GAFFER route unchanged',
          default[-5580596463] == {'handling': -1002335630148, 'out_to': -5580596463},
          str(default))

    # -- a completely different pair of groups works end to end -------------
    NEWSRC, NEWHANDLE = -777001, -777002
    use_routes(f'{NEWSRC}:{NEWHANDLE}')
    await f.observe_cashout(NEWSRC, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 50', 501, now, user_id=42)
    check('a re-pointed request forwards to the new group',
          sent and sent[0][0] == NEWHANDLE, str(sent))
    await f.observe_cashout(NEWHANDLE, '/out 50', 502, now, user_id=77,
                            username='Maynuddin23')
    check('the /out returns to the new source',
          any(c == NEWSRC and t == '/out 50' for c, t in sent), str(sent))
    check('the new source books it', f.ledger_snapshot(NEWSRC) == (0.0, 50.0),
          str(f.ledger_snapshot(NEWSRC)))
    check('the ❤ goes on the new source request', reactions == [(NEWSRC, 501)],
          str(reactions))

    # -- /out routed to a THIRD group ---------------------------------------
    SRC, HANDLE, OUT = -888001, -888002, -888003
    use_routes(f'{SRC}:{HANDLE}:{OUT}')
    await f.observe_cashout(SRC, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 80', 601, now, user_id=42)
    check('request still forwards to the handling group',
          sent and sent[0][0] == HANDLE, str(sent))
    await f.observe_cashout(HANDLE, '/out 80', 602, now, user_id=77,
                            username='Maynuddin23')
    check('the /out goes to the third group', any(c == OUT and t == '/out 80' for c, t in sent),
          str(sent))
    check('the /out does NOT go back to the source',
          not any(c == SRC and t == '/out 80' for c, t in sent), str(sent))
    check('the third group books it, not the source',
          f.ledger_snapshot(OUT) == (0.0, 80.0) and SRC not in f._ledger,
          f"{f.ledger_snapshot(OUT)} / {f.ledger_snapshot(SRC)}")
    check('the totals block is posted where the books moved',
          any(c == OUT and 'Group Total' in t for c, t in sent), str(sent))
    check('the ❤ still goes on the original request in the source',
          reactions == [(SRC, 601)], str(reactions))

    # -- an in-flight request keeps its target if the route is re-pointed ---
    use_routes(f'{SRC}:{HANDLE}:{OUT}')
    await f.observe_cashout(SRC, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 10', 701, now, user_id=42)
    use_routes_keep = dict(f.CASHOUT_ROUTES)
    pending = f._pending_cashouts[HANDLE][0]
    f.CASHOUT_ROUTES[SRC] = {'handling': HANDLE, 'out_to': -999999}   # re-pointed
    sent.clear()
    await f.observe_cashout(HANDLE, '/out 10', 702, now, user_id=77,
                            username='Maynuddin23')
    check('an in-flight request keeps the target it opened with',
          any(c == OUT for c, _ in sent) and not any(c == -999999 for c, _ in sent),
          str(sent))

    # -- watched chats follow the configured routes -------------------------
    use_routes(f'{SRC}:{HANDLE}:{OUT}')
    chats = f._configured_source_chats()
    check('the new source and handling groups are watched',
          SRC in chats and HANDLE in chats, str(chats))
    check('the /out-only group is not watched', OUT not in chats, str(chats))
    check('payment sources are still watched',
          all(c in chats for c in f.FORWARD_RULES), str(chats))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all route checks passed")


asyncio.run(main())
