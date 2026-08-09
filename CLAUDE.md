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

849 checks across 25 suites, all stubbed — nothing touches Telegram, the
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
  and books that group's Total Out, exactly as a typed `/out` does. **The
  screenshot travels with it** — see "Relaying the screenshot" below.
- **Anything at all posted in a handling group** — `media_concerns_cashout()`
  on the Bot API side, the `in_handling` gate on the Telethon side. A
  screenshot sent *instead* of the `/out` is the crew signalling they are
  stuck, and it must not look like silence. See `flag_cashout_issue()`.

A captioned `CASHOUT REQUEST` still opens nothing, and a captioned `/add` does
nothing.

## Invariants — do not break these without being asked

- **A `/out` is acted on only while a request the bot forwarded is still open in
  that chat** — with **one** exception, below. Otherwise it is ordinary traffic
  and must be left completely alone, including the `/add`/`/out`/`/set` ledger
  commands.
- **The exception: a `/out` from Ethan or Larry in a handling group always
  completes a cashout**, open request or not — `force_complete_cashout()`.
  Open requests live in memory, so a redeploy wipes them, and a redeploy is
  exactly when somebody needs to finish a cashout the bot has forgotten. Before
  this their `/out` did nothing at all: it sat in the group looking actioned to
  everyone reading it while the group that asked was told nothing and its books
  never moved. It relays, books and tells both admins what it did; there is no
  ❤, because the request it answers is not in memory and neither is its message
  id. **The crew's `/out` with nothing open is still ignored** — that is what
  keeps this from firing on chatter.
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
- **The crew are never told about anything that has gone wrong with the bot.**
  They get exactly one message — the chase, "this is still waiting on a /out" —
  and nothing else. A failed ❤, a failed send, a request ignored because the
  flow is stopped, an unreachable DM: all of it goes to Ethan, or Ethan and
  Larry. The crew cannot act on any of it, and telling them turns a chase they
  respond to into noise they learn to ignore. Pinned by `test_redaction.py`.
- **A private DM is a one-off, never a recurring chase.** `crew_told` and
  `admin_told` gate each to once per request. The repeating part is the group
  post, and it runs whether or not anybody has acknowledged it.
- **The crew get no timer DM until the group ladder has run out** (17 min).
  Ethan and Larry still get theirs on the first rung.

## The escalation ladder

The group post is the loud, repeating part; a DM is the quiet, one-off part.
There is **one** ladder, and it runs on absolute minutes since the request was
posted — `chase_cashout()`, off `request['opened']`.

| Time | What happens |
|---|---|
| 5 min | group reminder #1, **plus** one DM to Ethan + Larry |
| 8 min | group reminder #2 |
| 10 min | one DM to the crew — **only** for a request nobody has acknowledged |
| 12 min | group reminder #3 |

The crew's DM is for **silence**, not for lateness: reacting stops it firing at
all. It deliberately sits *between* two group rungs, which is why chasing ends
only once **both** channels have run out — `ladder_done and crew_done`. Firing
one must never cancel the other.

**It is deleted the moment the `/out` lands** — see below.

**Acknowledging it takes the chase out of the group** — `chase_acknowledged()`.
A reaction, or any of the crew speaking in the handling group, stops the group
reminders dead. Larry gets **one** DM instead, `CASHOUT_SEEN_DM_MINUTES` (6)
after the acknowledgement rather than at the moment of it: "still not processed"
is not worth saying the instant somebody reacts, and six minutes later it is.

| Acknowledged | What happens |
|---|---|
| at any time | group reminders **stop**; Larry told it was picked up |
| +6 min | one DM to Larry: acknowledged, still not processed → chasing **stops** |
| 10 min | **no** crew DM — that one is only ever for silence |

- **Only the crew count** — `_is_responder()`. Ethan and Larry used to
  (`user_id in LEDGER_ADMINS`) and no longer do: acknowledgement now stops the
  group chase outright, so an admin reacting would silence the very reminders
  meant to reach the crew.
- **Only the first acknowledgement counts** (`_mark_acknowledged()`).
  Re-stamping on every later reaction would keep pushing Larry's notice out,
  which is the recurring chase this shape exists to avoid.
- **An acknowledgement reopens a chase that had already run out.** It is new
  information: somebody has just picked up a request everything had given up on,
  and it is still not paid. `chase_acknowledged()` fires once and stops it
  again, so there is no loop.
- The six minutes run from the **acknowledgement**, so reacting late does not
  shorten them.

Rungs are **absolute marks, not gaps**, so replaying a pass cannot double-post
and nothing that happens in between can push the ladder out. A request that
comes back from a `/cashout off` pause already past several rungs catches up
with **one** post, never one per missed rung.

`CASHOUT_NUDGE_MINUTES` (`5,8,12`), `CASHOUT_CREW_DM_MINUTES` (`10`) and
`CASHOUT_SEEN_DM_MINUTES` (`6`) are the knobs; `CASHOUT_MAX_NUDGES` still caps group rounds on top of the ladder, and
`CASHOUT_TIMEOUT_MINUTES=0` still disables chasing altogether.

**They answer with something that is not a `/out`** — `flag_cashout_issue()`.
Not a rung on either ladder, and on its own short clock: a crew member who has
already acknowledged a request and then sends a message or a screenshot with no
`/out` is engaged but stuck, which is a different problem from silence and needs
a person, not another timer.

| Trigger | What happens |
|---|---|
| acknowledged, then any non-`/out` message or media from a responder | **held 60s**, then one DM to Ethan + Larry, naming the crew member and their numeric id |

**The alert is held, not sent.** The crew routinely post the message and *edit*
the `/out` onto it seconds later, so firing on the first version makes an alert
out of the ordinary way they work. `flag_cashout_issue()` arms it;
`flush_pending_issue()` sends it once `CASHOUT_ISSUE_DELAY_SECONDS` (60) is up.
An edit carrying a `/out` settles the request, which drops it from the queue —
so the alert is never sent at all, rather than being cancelled.

- **Armed once.** A second message during the hold does *not* push the deadline
  out, or somebody typing steadily would defer it forever.
- **Flushed before the `exhausted` guard** in the watchdog: a problem raised
  while the chase was running must still be reported after chasing stops.
- `CASHOUT_ISSUE_DELAY_SECONDS=0` restores the old immediate behaviour.

The crew are **not** told — they are the ones being asked about. Nothing is
posted in the group. Once per request (`issue_told`), and the ladder it was
already on carries on underneath. The *first* thing anyone says is an
acknowledgement, not a problem, so the alert needs a prior acknowledgement.

## Edited messages

**A `/out` edited onto a message the crew already sent is how a great deal of
real traffic answers a cashout.** Until 2026-08-09 the bot could not see it:
`edited_message` was not in `allowed_updates` and neither listener registered an
edit handler. The request stayed open, the ❤ never landed, the money was never
booked, and the chase ran on against a cashout that had actually been paid —
silently, every time.

- **Edits reach the cashout path ONLY.** `process_incoming()` is never called
  from an edit handler and must never be: an edited `You received` would be
  forwarded and booked a **second** time, inventing a deposit. Same reasoning as
  `cashout_caption()`.
- **An edit needs its own dedup key.** The original message already registered
  `('cashout-reply', handling, id)`, so reusing it drops every edit as a replay
  — which is exactly the bug. The edited **text** is part of the key, so one
  edit arriving down both input paths is still one event, while a second,
  different edit (fixing the figure) gets its turn.
- **A `/out` is acted on once per message** (`('out-done', handling, id)`),
  however often it is edited afterwards. Without this, editing the cashtag on an
  already-paid `/out` books it twice — and with the request settled and gone,
  Ethan's or Larry's edit reaches `force_complete_cashout()`, which takes a
  `/out` at face value. Reproduced by `tests/test_edits.py`.
- **Editing a `CASHOUT REQUEST` opens nothing.** The request-opening branch
  keeps its original key, so edits there are ignored rather than posting a
  second request.

A `/out` at any point completes it. Stopping is not giving up — the request
stays **open**, so a late `/out` is still forwarded, booked and hearted, and
deleting either copy still settles it.

**A late `/out` takes back the crew's 10-minute chase** — `delete_crew_notice()`.
That DM says the request is "still waiting on a `/out`". The moment one arrives
it is untrue, and a chase left sitting in their inbox reads as work still
outstanding — which on this flow means somebody paying a second time. Telegram
has no edit that unsends a delivered notification, so it is deleted outright.
`dm_handles(..., receipts=…)` is what records where each copy landed; the client
that sent it travels with the id, because an id only means anything alongside
the chat it went through. **Only the crew's copy** — Ethan's and Larry's notices
are a record rather than an instruction and stay put. A delete that fails is not
cosmetic (the stale instruction is still live), so Ethan is told, and told the
money is already booked so nobody pays it again.

## Paying the wrong figure

**A `/out` that does not pay what was asked for DMs Larry immediately** —
`flag_amount_mismatch()`. A request for `$200` answered with `/out 150` settles
and hearts exactly like any other: the money really did move, and pretending
otherwise would strand a real payment. But nothing else in the flow would ever
mention the gap.

- **Immediate, not on a timer.** An underpayment is only cheap to fix while
  somebody still remembers the cashout.
- **Larry only, once** (`mismatch_told`). The crew are not told — see the
  invariant above; they are the ones being asked about.
- **The books follow what was actually sent**, never what was asked for. The
  alert says so explicitly, so nobody "corrects" the ledger to the request.
- **Both figures must be readable or nothing fires.** `request_amount()` and
  `out_amount()` both return `None` rather than guessing, and a `None` on either
  side is silence — never a comparison against a default. Same rule as
  [the empty ledger](#): a missing figure is "unknown", not zero.
- Overpayment is flagged the same way, worded `OVER BY`.

**This compares the `/out` against the REQUEST, not against the screenshot.**
Reading a figure off the Cash App image would need OCR or a vision model; the
bot never downloads media and has no such capability. It catches the same error
one step earlier, from text it already parses.

## The emergency stop

`/cashout off` takes the whole cashout flow out of service; `/cashout on` puts
it back; bare `/cashout` says which it is. Ethan and Larry only, from a DM or
from any of the four cashout groups — when this is needed it is needed from
whatever chat is already open.

Stopped means **stopped**: no request forwarded, nothing chased, no ledger
moved, no `/out` booked. One check at the top of `observe_cashout()` covers
every branch, and `cashout_watchdog()` skips its whole round.

- **Nothing about it is ever posted in a group.** Not the stop, not the
  resume, not a refusal — a refusal in a group would announce that a kill switch
  exists, to exactly the people it is kept from. Typed in a group, even the
  confirmation comes back as a DM to whoever ran it.
- **It survives a redeploy.** Railway wipes the disk on every push, and the
  incident that made somebody stop the flow is very often the reason a push is
  coming — a switch held only in memory would turn itself back on at the worst
  possible moment. The state lives in the DM to Ethan and Larry, which is both
  the notification and the durable record.
- **Recovery reads a private chat, which only the userbot can do.** A bot cannot
  read its own history at all. `recover_cashout_switch()` asks the userbot for
  the BOT as an entity — from a user account's side that is simply the DM with
  it — and reads the newest marker back. This works because the userbot **is**
  Ethan's or Larry's account. If that ever stops being true the switch stops
  being durable, and the boot warning is what says so.
- **Open requests are kept, not cancelled.** Stopping is a pause. Dropping them
  would strand cashouts that were already in flight.
- **It is not a silent hole.** A `CASHOUT REQUEST` or a `/out` arriving while
  stopped is DMed to Ethan and Larry with its text, saying plainly that it was
  not forwarded, booked or chased. Ordinary chatter is not reported.
- **`/help` documents it and `/status` leads with it.** When the flow is
  stopped `/status` says so on its first line, before the counts — which all
  look perfectly normal while nothing is being forwarded. Both are rendered from
  the live code and covered by tests, so the entry cannot quietly drift out.
- **Failing to read it back changes nothing.** Guessing "running" could start
  moving money that was deliberately stopped; guessing "stopped" would take the
  flow out of service with nobody knowing why. The flag is left alone and a
  person is told.
- **Reading it back can never take the userbot down.** It runs inside
  `run_userbot()`'s reconnect loop, so an exception escaping it is retried
  forever and the userbot never finishes starting. The whole scan is guarded.
  This was a real bug, caught by `test_caption` hanging.

## Guarding against a duplicate request

One cashout must produce one post, one ladder and one thing to answer. Three
guards stack, and they catch different things:

| Guard | Catches |
|---|---|
| `_is_duplicate(('cashout', source, id))` | The **same message** reaching both input paths. Keys off the message id. |
| `_cashout_claims` | The same request **still being posted** — the window between deciding to post and having posted. |
| `_pending_cashouts` fingerprint scan | The same request text arriving again while the first is **open**, within `CASHOUT_DEDUP_SECONDS` (120). |

The middle one is the fix for the 2026-08-04 duplicate, and it is worth
understanding why the other two could not catch it. The fingerprint scan
compares against `_pending_cashouts`, but that entry is only written **after**
`bot.send_message()` returns — and that is an `await` on a network call. asyncio
runs the next ready task inside it, so a second copy arriving in the window
compared itself against a list that was still empty, passed, and posted. Both
then appended, so the group got two posts, two ladders and two DMs. **This needs
no second container** — one process racing itself is enough, which is why it
survived every fix aimed at the deploy changeover.

- **Claim before the send, with no `await` in between.** The look and the claim
  have to be one indivisible step, or it is the same race one level down.
- **Hand over on success.** The claim is released the moment the request is on
  `_pending_cashouts`, which then answers the question. Two windows that can
  disagree is how the guard would start refusing a *genuine* second cashout —
  the one that legitimately arrives right after the first is paid.
- **Release on failure.** A claim held for a post that never happened would
  swallow the retry, and the group would then be told nothing at all. A silent
  miss is worse than the duplicate this guards against.
- Reproduced by `tests/test_race.py`, which drives the copies through
  `asyncio.gather`. The sequential version of the same case (`test_cashout.py`
  7b) passed throughout — **awaiting two calls one after the other cannot
  reproduce a race**, because the first completes before the second starts.

## Relaying the screenshot

The `/out` answering a request is usually written as the caption on the Cash App
screenshot proving the money went. Both travel to the chime group that asked, as
**one message**: the picture, with the `/out` as its caption.

- **`copy_message`, never `forward_message`.** A forward carries a "Forwarded
  from" header naming the account it came from and links back to the handling
  group. The chime groups are never told who handles their cashouts, or that the
  handling group exists at all. A copy arrives as an ordinary message from the
  bot with no sender, no username and no back-link.
- **The `/out` outranks the picture.** If the copy fails for any reason the
  instruction is still sent on its own, because losing the screenshot is a
  nuisance and losing the `/out` strands a real cashout.
- **Only when the `/out` is on it.** A screenshot posted *instead* of the `/out`
  is the crew signalling they are stuck — it raises the alarm through
  `flag_cashout_issue()` and is not relayed anywhere.

**Every picture in the album travels, not just the captioned one.** The crew
routinely send several screenshots at once — the payment and the history behind
it. Telegram sends an album as **separate messages that merely share a
`media_group_id`**, and only one of them carries the caption, so copying "the
message the `/out` was on" relayed one picture and silently dropped the rest.
Seen live in `Chime Rev & out no-7` on 2026-08-09: two screenshots sent, one
arrived in `CHIME GAFFER`.

- **Both orderings have to work.** The caption normally sits on the *first* of
  the album, so the siblings arrive *after* the `/out` has already been dealt
  with — `note_album_part()` copies those on sight. Parts seen *before* the
  caption are buffered and flushed by `relay_album_siblings()`.
- **The siblings go after the `/out` has landed**, never before, so an extra
  screenshot failing can never cost the instruction itself. Same reasoning as
  the plain-text fallback above.
- **Each sibling is copied with `caption=''`.** Telegram allows one caption per
  album so a sibling normally has none, but `copy_message` keeps whatever *is*
  there, and anything a crew member typed could carry a name into a group that
  must never see one. The captioned copy is still redacted by
  `clean_out_for_relay()` as before.
- **`copyMessages` (plural) is deliberately not used.** It would preserve the
  album as an album, but it cannot replace the caption — only keep or drop it —
  and keeping it would put an unredacted crew name in a chime group.
- Bounded by `ALBUM_MEMORY` (40 albums) and `ALBUM_RELAY_SECONDS` (180).
  Reproduced by `tests/test_album.py`.

## No crew name ever reaches a target group

`copy_message` strips what *Telegram* attaches. It cannot strip what a person
typed, and the crew do write "sent by @Maynuddin23" on their own screenshots.
The chime and VENMO groups are told figures, never who moved them.

- **Guarded at the door, not at each caller.** `send_group()` is the single
  outbound function; it redacts whenever the destination is in `TARGET_CHATS`.
  That is what makes "never" true for messages that do not exist yet — a new
  milestone, a new correction, anything added later.
- **`strip_identities()` takes out ANY `@mention`**, not only the configured
  ones, because somebody new on the crew is exactly what a fixed list misses.
  Bare names go too: a handle written without its `@` is still a name. The
  known set is read from `CASHOUT_CREW_HANDLES`, `CASHOUT_RESPONDERS` and
  `CASHOUT_MENTIONS`, so there is no second list to forget.
- **A named `/out` is rebuilt, not patched.** Subtracting words leaves
  `/out 25 - sent by`, which reads like a bug and still hints a name was
  removed. `clean_out_for_relay()` rebuilds it as the figure and the cashtag —
  `/out 25` and `$jenny-buhr` — and the screenshot still travels. A `/out` with
  nothing to hide is relayed **verbatim**, exactly as before.
- **The ledger reads the original.** `book_cashout_out()` is passed the
  untouched text, so redaction can never change the figure that reaches the
  books.
- **The mirror matters just as much**, and is the easier thing to break: the
  handling groups are tagged with those exact handles on every request, and the
  DM naming who is stuck would be worthless redacted. Both are pass-throughs
  and both are tested.

## Marking a cashout done

The ❤ on the original request is the **only durable record** that a cashout was
actioned: the open requests live in memory and a redeploy wipes them. A request
that was paid but never marked reads as still outstanding to anyone scrolling.

**A `/out` settles the request it PAID, not the oldest one.** With two
requests open in a handling group, taking `queue[0]` blindly hearted the wrong
one: the person who asked was left with an unmarked request still being chased,
and somebody else's — for a different figure — was marked done without being
paid. Seen live in `Chime Rev & out no-7` on 2026-08-04. `_match_request()` now
reads the figure out of the `/out` and matches it against what each open request
asked for. An explicit reply still wins outright; the oldest is still the
fallback for a `/out` with no figure, or one matching nothing, because settling
the wrong request can be undone and dropping a real `/out` strands a cashout.

**Nothing in the code looks at who sent the request.** `open_cashout_request()`
takes any sender, both dispatchers explicitly accept humans and bots, and
`heart_request()` is called unconditionally. A ❤ that lands for some requests
and not others is Telegram refusing the reaction at runtime, never routing.

`heart_request()` tries the bot token first and falls back to the user account,
which can react where the bot often cannot. **That fallback has its own switch,
`USERBOT_REACT` (default on), deliberately separate from `USERBOT_SEND`.**
Reacting is not sending: `USERBOT_SEND=0` exists to stop the account posting
messages on your behalf, and while the two shared a switch, turning off userbot
messaging silently turned off the ❤ as well — leaving it dependent on the bot
token alone, which frequently cannot react on somebody else's message. A paid
cashout then reads as still outstanding. **When both fail, Ethan is DMed with
the error** — it is not a cosmetic miss, and the alert says plainly that the
money side is already done so nobody pays twice. A request that has simply been
deleted is not a failure and raises nothing.

The usual causes are the bot not being an administrator in that group, or the
group restricting which reactions may be used. Neither is visible from the code,
which is why the error text is carried into the DM.

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
  containers each see a clean slate. The logs from 2026-08-03 show `[CONFLICT]
  Another process is polling this token` and two independent `reminder #1`
  rounds for one request. Three things narrow the window — the SIGTERM fix
  above, `TELETHON_START_DELAY`, and `BOT_START_DELAY` — but a genuine second
  *service* would defeat all of them. That is a Railway-side fix.

  **This is no longer the only way to get a duplicate, and was not the cause of
  the one on 2026-08-04.** See below.
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
| `tests/test_race.py` | Two copies of one request arriving at the same moment |
| `tests/test_screenshot.py` | The screenshot travels with the `/out`, carrying no identity |
| `tests/test_heart.py` | A cashout that cannot be marked done is not silent |
| `tests/test_switch.py` | `/cashout off` stops everything, and survives a redeploy |
| `tests/test_redaction.py` | No crew name reaches a target group; every other route keeps them |
| `tests/test_matching.py` | A `/out` settles the request it paid, not the oldest |
| `tests/test_manual.py` | Ethan and Larry can finish a cashout with nothing open |
| `tests/test_amounts.py` | A /out paying the wrong figure; taking back the chase DM |
| `tests/test_edits.py` | A /out edited onto a message, and the double-book guard |
| `tests/test_album.py` | Every screenshot in an album reaches the group that asked |
| `backfill.py` | Manual one-off backfill, separate from the boot sweep |
| `telethon_login.py` | Generates a `TELETHON_SESSION`; `--deploy` for Railway |

Config is environment variables with working defaults — see the top of
`forwarder.py` and each section header.
