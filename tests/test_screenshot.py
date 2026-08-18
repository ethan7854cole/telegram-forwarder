"""The payment screenshot travels to the chime group with the /out on it.

The crew answer a CASHOUT REQUEST with the Cash App screenshot proving they
sent the money, and write the /out as its caption. The /out was relayed and the
picture was dropped, so the group that asked was told the cashout was done but
never shown the proof.

The whole point is HOW it travels. A forward carries a "Forwarded from" header
naming the account it came from and links back to the handling group, and the
chime groups are never told who handles their cashouts or that the handling
group exists. copy_message arrives as an ordinary message from the bot, with
nothing attached to it. This suite fails if a forward is ever used, and fails
if any identifying detail reaches the chime group.

It also pins the fallback: the picture is a nice-to-have, the /out is not. A
copy that fails must still deliver the instruction, or the cashout is stranded.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148

# The crew member who answers. None of this may reach the chime group.
CREW_ID, CREW_USER, CREW_NAME = 77, 'Maynuddin23', 'Crew Member'

real_bot = f.bot                       # keeps the registered handler table

sent, dms, copies, forwards, reactions, copy_kwargs = [], [], [], [], [], []
_next_id = [7500]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    fail_copy = False

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        if chat_id > 0:
            dms.append((chat_id, text))
        else:
            sent.append((chat_id, text, reply_to_message_id))
        return FakeMsg(_next_id[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None,
                           **kwargs):
        if self.fail_copy:
            raise RuntimeError('MEDIA_EMPTY')
        _next_id[0] += 1
        copies.append((chat_id, from_chat_id, message_id, caption))
        copy_kwargs.append(kwargs)
        return FakeMsg(_next_id[0])

    async def forward_message(self, chat_id, from_chat_id, message_id):
        # Never acceptable: this is the call that would name the sender and the
        # handling group in the chime group.
        forwards.append((chat_id, from_chat_id, message_id))
        return FakeMsg(0)

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
    sent.clear(); dms.clear(); copies.clear(); forwards.clear(); reactions.clear()
    copy_kwargs.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f.bot.fail_copy = False


async def open_request(chime=PICCASO, mid=901):
    now = datetime.now(timezone.utc)
    await f.observe_cashout(chime, 'CASHOUT REQUEST $25 $jenny-buhr', mid, now,
                            user_id=42)
    sent.clear()                       # drop the forward into the handling group


async def answer(handling, text, mid=902, has_media=True):
    await f.observe_cashout(handling, text, mid, datetime.now(timezone.utc),
                            user_id=CREW_ID, username=CREW_USER,
                            full_name=CREW_NAME, has_media=has_media)


async def main():
    # -- 1. the screenshot reaches the group that asked ----------------------
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25', mid=902)

    check('the screenshot is copied to the chime group',
          len(copies) == 1, str(copies))
    if copies:
        to, frm, mid, caption = copies[0]
        check('copied TO the group that asked', to == PICCASO, str(to))
        check('copied FROM the handling group', frm == MHLARRY, str(frm))
        check('the crew message is the one copied', mid == 902, str(mid))
        check('the /out rides along as the caption', caption == '/out 25', str(caption))

    # -- 2. and it is a COPY, never a forward -------------------------------
    check('no forward_message anywhere', forwards == [], str(forwards))

    # Nothing but the caption rides along. A caption sent with entities could
    # carry a text_mention - a clickable link to the sender's profile, which
    # exists even for an account with no @username at all - and that would put
    # their identity into the chime group by another door. No parse_mode and no
    # caption_entities means the /out lands as plain text and any entity on the
    # original is dropped.
    check('the copy passes nothing but the caption',
          copy_kwargs == [{}], str(copy_kwargs))

    # -- 3. nothing identifying reaches the chime group ---------------------
    to_chime = [t for c, t, _ in sent if c == PICCASO]
    to_chime += [cap or '' for c, _, _, cap in copies if c == PICCASO]
    blob = '\n'.join(to_chime)
    check('the crew username does not appear', CREW_USER.lower() not in blob.lower(), blob)
    check('the crew name does not appear', CREW_NAME.lower() not in blob.lower(), blob)
    check('the crew numeric id does not appear', str(CREW_ID) not in blob, blob)
    check('the handling group is not named',
          f.chat_name(MHLARRY).lower() not in blob.lower(), blob)

    # -- 4. the /out is not ALSO sent as its own message --------------------
    # One message, not two: the picture with the /out written on it.
    check('the /out is not posted a second time on its own',
          not any(t == '/out 25' for c, t, _ in sent if c == PICCASO), str(sent))

    # -- 5. the rest of the flow is untouched -------------------------------
    check('the request is closed', MHLARRY not in f._pending_cashouts)
    check('the original request is hearted',
          any(c == PICCASO and m == 901 for c, m, _ in reactions), str(reactions))
    check('Total Out is booked on the asking group',
          f.ledger_snapshot(PICCASO)[1] == 25.0, str(f.ledger_snapshot(PICCASO)))

    # -- 6. a typed /out with no screenshot behaves exactly as before -------
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25', mid=903, has_media=False)
    check('no copy is attempted when there is no media', copies == [], str(copies))
    check('the /out is relayed as plain text',
          any(c == PICCASO and t == '/out 25' for c, t, _ in sent), str(sent))
    check('and it still closes the request', MHLARRY not in f._pending_cashouts)

    # -- 7. a failed copy must still deliver the /out -----------------------
    # Losing the picture is a nuisance. Losing the instruction strands a real
    # cashout, so the fallback is the part that matters most here.
    reset()
    await open_request()
    f.bot.fail_copy = True
    await answer(MHLARRY, '/out 25', mid=904)
    check('the /out still lands when the copy fails',
          any(c == PICCASO and t == '/out 25' for c, t, _ in sent), str(sent))
    check('the request is still closed', MHLARRY not in f._pending_cashouts)
    check('and it is still booked',
          f.ledger_snapshot(PICCASO)[1] == 25.0, str(f.ledger_snapshot(PICCASO)))

    # -- 8. the other route behaves identically -----------------------------
    reset()
    await open_request(chime=GAFFER, mid=905)
    await answer(CHIMEREV, '/out 40', mid=906)
    check('the Gaffer route copies too', len(copies) == 1, str(copies))
    if copies:
        check('to the group that asked on that route', copies[0][0] == GAFFER, str(copies[0]))
        check('from its own handling group', copies[0][1] == CHIMEREV, str(copies[0]))

    # -- 9. media with no /out is still not relayed -------------------------
    # A screenshot sent INSTEAD of the /out means the crew are stuck. It raises
    # the alarm; it must not be posted to the chime group as if it were an
    # answer, and it must not close anything.
    reset()
    await open_request()
    await answer(MHLARRY, '', mid=907)          # a bare screenshot, no caption
    check('a screenshot with no /out is not copied out', copies == [], str(copies))
    check('and the request stays open',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1)

    # -- 10b. the crew's words are relayed; their names are not -------------
    # copy_message strips what TELEGRAM attaches. It cannot strip what a person
    # typed, and the crew do write "sent by @Maynuddin23" on their own
    # screenshots. The chime groups are never told who handles their cashouts,
    # so the relayed text is cleaned of crew handles and names first.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 - sent by @Maynuddin23', mid=920)
    cap = copies[0][3] if copies else ''
    check('a typed crew handle never reaches the chime group',
          'maynuddin' not in cap.lower(), cap)
    check('the /out itself survives redaction', '/out 25' in cap, cap)
    check('and the full amount is still booked',
          f.ledger_snapshot(PICCASO)[1] == 25.0, str(f.ledger_snapshot(PICCASO)))

    # Every crew handle, not just the sender's.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 @MHSUPPORTZONE @maynuddin233 all done', mid=921)
    cap = copies[0][3] if copies else ''
    check('the other crew handles go too',
          'mhsupportzone' not in cap.lower() and 'maynuddin233' not in cap.lower(), cap)

    # Written without the @, it is still a name.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 maynuddin233 sent it', mid=922)
    check('a bare crew name goes as well',
          'maynuddin' not in (copies[0][3] or '').lower(), str(copies))

    # Somebody new on the crew is exactly what a fixed list would miss.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 @somebrandnewguy handled it', mid=923)
    check('an unknown @handle is stripped too',
          'somebrandnewguy' not in (copies[0][3] or '').lower(), str(copies))

    # The display name, which is not a handle at all.
    reset()
    await open_request()
    await f.observe_cashout(MHLARRY, '/out 25 done by Maynuddin Ahmed', 924,
                            datetime.now(timezone.utc), user_id=CREW_ID,
                            username=CREW_USER, full_name='Maynuddin Ahmed',
                            has_media=True)
    check('the sender display name is stripped',
          'maynuddin ahmed' not in (copies[0][3] or '').lower(), str(copies))

    # The plain-text /out relays verbatim too, so it needs the same cleaning.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 - @Maynuddin23 sent it', mid=925, has_media=False)
    relayed = [t for c, t, _ in sent if c == PICCASO]
    check('the no-screenshot path is cleaned as well',
          relayed and 'maynuddin' not in relayed[0].lower(), str(relayed))
    check('and that amount is booked in full too',
          f.ledger_snapshot(PICCASO)[1] == 25.0, str(f.ledger_snapshot(PICCASO)))

    # The exact shape, pinned. Subtracting words would leave "/out 25 - sent
    # by", which reads like a bug and still hints a name was removed. The
    # message is rebuilt from the figure and the cashtag instead.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 $jenny-buhr sent by @Maynuddin23', mid=927)
    check('a named /out is rebuilt, not patched',
          copies and copies[0][3] == '/out 25\n$jenny-buhr', str(copies))

    reset()
    await open_request()
    await answer(MHLARRY, '/out 40 maynuddin233 handled', mid=928)
    check('with no cashtag it is just the figure',
          copies and copies[0][3] == '/out 40', str(copies))

    # A clean /out keeps the crew's own wording, exactly as it always has.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 25 all good mate', mid=929)
    check('a clean /out is still relayed verbatim',
          copies and copies[0][3] == '/out 25 all good mate', str(copies))

    # What must NOT be touched: the cashtag is the whole point of the message.
    reset()
    await open_request()
    await answer(MHLARRY, '/out 120\n$Hawkins-Floral-Decor', mid=926)
    cap = copies[0][3] if copies else ''
    check('a cashtag is left alone', '$Hawkins-Floral-Decor' in cap, cap)
    check('and so is the figure', '/out 120' in cap, cap)

    # -- 10. a captioned CASHOUT REQUEST is never dispatched at all ---------
    # This gate sits UPSTREAM of observe_cashout(), in media_concerns_cashout():
    # captioned media reaches the cashout flow only when the caption carries a
    # /out, or when it lands in a handling group. A screenshot captioned
    # "CASHOUT REQUEST" in a chime group is neither, so it opens nothing -
    # asserting it against observe_cashout() would test the wrong door, since
    # calling that directly bypasses the gate entirely.
    reset()

    class GateMsg:
        def __init__(self, cid, caption):
            self.chat = type('Chat', (), {'id': cid})()
            self.caption = caption

    check('a captioned CASHOUT REQUEST in a chime group is not dispatched',
          f.media_concerns_cashout(GateMsg(PICCASO, 'CASHOUT REQUEST $25')) is False)
    check('a captioned /out still is',
          f.media_concerns_cashout(GateMsg(PICCASO, '/out 25')) is True)
    check('and anything in a handling group still is',
          f.media_concerns_cashout(GateMsg(MHLARRY, 'just a screenshot')) is True)

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
