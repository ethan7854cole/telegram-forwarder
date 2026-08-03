# telegram-forwarder

A Telegram bot that moves payment notifications and cashout requests between
private groups, and keeps a running ledger for each one. It handles real money
figures for real people.

## Read this first

**Pushing to `main` is a production release.** Railway deploys from `main` with
no staging step. A bad forward posts wrong money figures into live groups, and
a duplicate cannot be taken back.

**Run the tests before every push:**

```bash
python3 tests/run.py            # all suites
python3 tests/run.py cashout    # only matching suites
```

559 checks across 16 suites, all stubbed — nothing touches Telegram, the
network, or the live groups. They cover the pre-existing behaviour as well as
the new, so they are the guard against a change quietly altering something that
already worked.

**Testing the unit is not enough.** Both real bugs found on 2026-08-03 came
from *interactions*: a sweep that was correct in isolation but compared against
text another function had rewritten, and a rename that left one call site
pointing at a name that no longer existed. Reasoning that a code path is
"untouched" is not evidence. Exercise it.

## The two directions

Payments travel outward. Cashout requests travel back.

```
MH X LARRY GROUP 2   --"You received"------>  CHIME PICCASO      (Total In  ↑)
Chime Rev & out no-7 --"You received"------>  CHIME GAFFER       (Total In  ↑)

CHIME PICCASO  --"CASHOUT REQUEST"-------->  MH X LARRY GROUP 2
CHIME GAFFER   --"CASHOUT REQUEST"-------->  Chime Rev & out no-7
        ^                                            |
        +--------------- /out --------------------- +   (Total Out ↑, ❤ on the request)
```

`FORWARD_RULES` drives the first. `CASHOUT_ROUTES` drives the second, and is
deliberately a **separate table** — putting the pairs in `FORWARD_RULES` would
drag the chime groups into `TARGET_CHATS` and fire the ledger, the milestones
and the idle watchdog on the wrong side of the flow.

## Two input paths

The Bot API cannot see messages posted by *other* bots, so a Telethon userbot
reads the source chats as a user account. Everything outbound still goes
through the bot token. Both paths funnel into `process_incoming()` and
`observe_cashout()` so the filtering and routing exist in one place.

The user account is allowed to **send** in exactly one case: an escalation DM
the bot cannot deliver, because a bot cannot open a chat with someone who has
never pressed Start and cannot address an `@username` at all. `USERBOT_SEND=0`
disables that.

Both paths take **plain text only** for payments, and always will:
`process_incoming()` is never reached from media, or a screenshot of a
notification would be read as the notification and invent a deposit.

Media reaches the **cashout flow** in two cases, and no others:

- **A `/out` written as a caption**, anywhere — `is_caption_out()`. The crew
  answer with the Cash App screenshot proving they sent the money and put the
  `/out` on it. The caption is relayed verbatim to the chime group that asked
  and books that group's Total Out, exactly as a typed `/out` does; the
  screenshot itself is not forwarded.
- **Anything at all posted in a handling group** — `media_concerns_cashout()`
  on the Bot API side, the `in_handling` gate on the Telethon side. A
  screenshot sent *instead* of the `/out` is the crew signalling they are
  stuck, and it must not look like silence. See `flag_cashout_issue()`.

A captioned `CASHOUT REQUEST` still opens nothing, and a captioned `/add` does
nothing.

## Invariants — do not break these without being asked

- **A `/out` is acted on only while a request the bot forwarded is still open in
  that chat.** With nothing pending it is ordinary traffic and must be left
  completely alone, including the `/add`/`/out`/`/set` ledger commands.
- **Only Ethan (`7578145913`) and Larry (`7418675217`) may move ledger figures.**
- **Anything that changes the ledger must post a message containing BOTH total
  lines.** `recover_ledgers()` rebuilds each group's books after a deploy by
  reading its own newest such message back. Booking silently means the next
  redeploy reverts it. See `book_cashout_out()` for the pattern.
- **Never commit the ledger before the message carrying it has been sent.** The
  books must not run ahead of what the group can see.
- **The ledger follows wherever the `/out` was posted**, never the source —
  otherwise one group's books move while another group displays the figures,
  and both end up wrong.
- **Nothing the bot posts into MH X LARRY or Chime Rev is signed `-ETHAN`.** The
  milestone and idle messages keep the sign-off; those only go to chime groups.
- **The crew's escalation DM names no group.** Routing between groups is for
  Ethan and Larry only.
- **Never act on the bot's own messages.** The handling groups are also payment
  sources, so without that guard a forward would loop.
- **A private DM is a one-off, never a recurring chase.** `crew_told` and
  `admin_told` gate each to once per request. The repeating part is the group
  post, and only while nobody has acknowledged it.

## The escalation ladder

The group post is the loud, repeating part; a DM is the quiet, one-off part.
Which ladder a request climbs depends on whether anyone has acknowledged it —
a reaction from the crew, or any of them speaking in the handling group.

**Nobody acknowledges it** — `nudge_unacknowledged()`:

| Time | What happens |
|---|---|
| 5 min | group reminder #1, **plus** one DM to Ethan + Larry and one to the crew |
| 10 min | group reminder #2 |
| 15 min | group reminder #3, then reminders **stop** |

**Somebody reacts** — `escalate_acknowledged()`. The reaction resets the clock
and widens the window to `CASHOUT_SEEN_MINUTES` (7). Nothing further is posted
in the group: they have acknowledged it there, so re-tagging them is noise.

| Time | What happens |
|---|---|
| +7 min | one DM to the crew |
| +14 min | one DM to Ethan + Larry, then chasing **stops** |

**They answer with something that is not a `/out`** — `flag_cashout_issue()`.
Not a rung on either ladder: it fires **immediately**, without waiting for a
window. A crew member who has already acknowledged a request and then sends a
message or a screenshot with no `/out` is engaged but stuck, which is a
different problem from silence and needs a person, not another timer.

| Trigger | What happens |
|---|---|
| acknowledged, then any non-`/out` message or media from a responder | one DM to Ethan + Larry, naming the crew member and their numeric id |

The crew are **not** told — they are the ones being asked about. Nothing is
posted in the group. Once per request (`issue_told`), and the ladder it was
already on carries on underneath. The *first* thing anyone says is an
acknowledgement, not a problem, so the alert needs a prior acknowledgement.

A `/out` at any point completes it. Stopping is not giving up — the request
stays **open**, so a late `/out` is still forwarded, booked and hearted, and
deleting either copy still settles it.

## Retracting a payment

A payment is forwarded and booked within seconds of landing, so by the time
anyone can see it should not count, the money is on the target's books and the
copy is in the group. **Reacting to the original** in `Chime Rev & out no-7`
undoes both: `retract_payment()` deletes the forwarded copy in `CHIME GAFFER`
and takes the amount back off that group's Total In.

- **ANY reaction retracts** — the user's explicit choice, with no confirmation
  step. A stray tap on a payment in that group really does move the books.
- **Only Ethan and Larry**, like every other ledger movement.
- **Only the Gaffer route** (`RETRACT_SOURCES`). A reaction on a payment in
  `MH X LARRY GROUP 2` does nothing.
- **Post, commit, delete — in that order.** The message being deleted is itself
  one of the messages `recover_ledgers()` reads back, so the correction has to
  publish both totals *first*. A delete that fails then still leaves the
  corrected figures as the newest ones, and Ethan is told to remove the stray
  copy by hand.
- **Once.** The delivery record is popped, so a second reaction does nothing.
- **Memory first, then the groups.** The delivery record is in memory, so a
  redeploy wipes it — which made the feature work only for payments forwarded
  since the last restart, and deploys are frequent. `retract_from_history()` is
  the fallback: read the original back through the userbot, take the amount
  from its own `You received` line, and find the copy in the target by
  `_catchup_signature()`. The timestamp and the totals are both rewritten on
  the way out, so the name and the amount are all that survive forwarding —
  the same basis the catch-up sweep already uses.
- **It posts what `/add -N` posts**, word for word — `✏️ Total In adjusted by
  -10.00$` and the totals block. Same event, same familiar shape, and an
  overshoot is **refused** exactly as `/add -N` refuses one rather than being
  clamped: clamping would invent a figure and then delete the evidence for it.
- **An empty `_ledger` means "not loaded yet", NEVER "zero".** Subtracting from
  the assumed zero wrote `0.00/0.00` into a live group on 2026-08-03 and made
  that the newest totals message — which is exactly what `recover_ledgers()`
  reads back, so the wipe would have survived a redeploy. The Bot API handles
  updates on its own schedule and does **not** wait for the boot sweep, so a
  reaction really can arrive before the books exist. `retract_payment()` calls
  `recover_one_ledger()` first and refuses outright if that fails.
- **A found message id travels with its entity.** An id only means anything
  alongside the chat it was read from. Handing the Bot API an id the userbot
  found produced `message to delete not found`; `delete_forwarded_copy()` tries
  the bot token first, then the user account holding that entity.
- **Still bounded by Telegram**, which refuses to let a bot delete a group
  message more than 48 hours old, and by `RETRACT_SCAN_LIMIT` (300 messages).

## Mention watch

The four cashout groups are **muted**, so an `@Larryyxx` or `@ethannxxxx` in one
of them reaches nobody until somebody happens to scroll back. `observe_mentions()`
turns it into a DM carrying the group, who sent it, their numeric id, the time
and the message itself — enough not to have to open the group at all.

Watched in `MENTION_CHATS`, which defaults to the four `CASHOUT_ROUTES`
endpoints (both chime groups, both handling groups). The VENMO targets are
deliberately out. Both id spellings are matched.

- **Telegram never tells a bot whether a chat is muted.** That is a per-user
  notification setting the API does not expose, so this does not try to detect
  it — the groups are simply watched.
- **Every mention is sent.** Unlike the cashout escalations, these are separate
  events rather than repeats of one, so the once-per-request rule does not apply.
- **Skipped:** the bot's own posts, since it tags people on every request and
  reminder; and whoever sent the message, who does not need telling about their
  own.
- Only real `@handle` mentions count. `bob@larryyxx` and `@larryyxxx` do not.
- Reaches only messages the input paths already see, so a mention inside a media
  caption in a chime group is missed. Mentions are plain text in practice, and
  widening the media gates for this would put the payment path at risk.

## The deploy changeover

Railway boots the replacement container before the outgoing one has gone, so
for a few seconds two of everything is live. Three separate things keep that
from doing damage, and all three are needed:

| | What it protects |
|---|---|
| `_schedule_disconnect()` | The outgoing container actually **leaves** on SIGTERM. It is PID 1, so an unhandled signal is ignored; and until 2026-08-03 the handler itself crashed and never reached `os._exit`. |
| `TELETHON_START_DELAY` | Two user sessions on one auth key from two IPs makes Telegram **destroy the key**, stopping all forwarding. Both sessions also receive every message, which is what **duplicates** posts. |
| `BOT_START_DELAY` | Two pollers **split** the updates — Telegram gives each to exactly one. The container holding the open cashout requests may not be the one that gets the `/out`, and it is then dropped as ordinary traffic. |

The two holds are not equivalent in cost. Deferring the Bot API poll loses
**nothing**: Telegram queues updates server-side for 24 hours and delivers the
backlog on the first poll. The userbot hold is genuinely deaf, which is what
`catch_up()` exists to repair afterwards — and it repairs payments only, not
cashout requests.

## Gotchas

- A stale `~/forwarder.py` (unrelated, 1.5 KB) sits in the home directory, and
  shells often start there. Always use the absolute path when compiling or
  grepping, or you will silently check the wrong file.
- Reaction updates only reach a bot that is an **administrator** in the chat,
  and `message_reaction` must be listed in `allowed_updates` explicitly.
- Telegram only says which chat a deletion happened in when it was a channel.
  With no chat, look the message up before acting — dropping the wrong pending
  request silently strands a real cashout.
- Telegram credits a channel post to the channel, not the bot that sent it, so
  filtering history on the bot's own id can match nothing.
- Railway wipes the disk on deploy: no state can live on it. The messages in the
  groups are the durable record.
- **The SIGTERM callback must reach `os._exit` no matter what.** This process is
  PID 1, so an unhandled SIGTERM is ignored and the container lingers until
  SIGKILL — which is the deploy overlap. On 2026-08-03 the callback itself
  raised (`create_task()` on the Future that Telethon's `disconnect()` returns)
  and never scheduled the exit, so the handler caused the exact failure it was
  written to prevent. Schedule the exit last and outside anything that can
  raise. See `_schedule_disconnect()`.

## Known gaps

- **Open cashout requests do not survive a redeploy.** They live in memory, so a
  restart stops the chasing, loses the ❤, and a later `/out` finds nothing
  pending. Fixable with a boot sweep: re-open any `CASHOUT REQUEST` not yet
  carrying a ❤, which already works as a durable "done" marker.
- **A duplicate payment is not detected.** When the catch-up sweep re-sent a
  window in Aug 2026, it re-booked every amount and nothing noticed. Cashout
  *requests* are guarded (`CASHOUT_DEDUP_SECONDS`); payments are not.
- **Two containers still cannot be prevented from in-process.** The duplicate
  guard is per-request state held in memory, so two overlapping Railway
  containers each see a clean slate. **Confirmed as the real cause** of the
  2026-08-03 duplicate: the logs show `[CONFLICT] Another process is polling
  this token` and two independent `reminder #1` rounds for one request. Three
  things now narrow the window — the SIGTERM fix above, `TELETHON_START_DELAY`,
  and `BOT_START_DELAY` — but a genuine second *service* would defeat all of
  them. That is a Railway-side fix.
- **A near-miss keyword is silent.** `CASH OUT REQUEST` matches nothing,
  forwards nowhere, and tells nobody — indistinguishable from a quiet day.
- **The idle watchdog covers only the two CHIME groups**, not the VENMO targets.

## Layout

| Path | What it is |
|---|---|
| `forwarder.py` | The whole bot. Sectioned with comments explaining *why*, not what |
| `tests/run.py` | Test runner; exits non-zero on any failure |
| `tests/test_regress*.py` | Guard the pre-existing behaviour |
| `tests/test_parity.py` | Both cashout routes must behave identically |
| `tests/test_caption.py` | A `/out` captioning a screenshot, through both real dispatchers |
| `tests/test_shutdown.py` | SIGTERM always reaches the exit, however the disconnect goes |
| `tests/test_startup.py` | Polling waits out the changeover; the conflict watcher |
| `tests/test_mentions.py` | An `@` in a muted group arrives as a DM |
| `tests/test_retract.py` | Reacting to a payment undoes it in the target |
| `backfill.py` | Manual one-off backfill, separate from the boot sweep |
| `telethon_login.py` | Generates a `TELETHON_SESSION`; `--deploy` for Railway |

Config is environment variables with working defaults — see the top of
`forwarder.py` and each section header.
