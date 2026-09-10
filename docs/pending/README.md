# Work that is finished, tested, and cannot land

A change parked here is **complete and passing**. It is not here because it is
half-done; it is here because landing it requires a decision only the owner can
make, and taking that decision unilaterally would mean weakening a gate.

Each entry states the measurement, the blocker, and the options. Nothing here
is a draft, and nothing here should be merged by hand without the decision it
is waiting on.

---

## `ws-privileged-channels.patch` — a role check on WebSocket subscriptions

**Status:** written, 11 tests, all passing. Cannot be committed.

### What it does

`LiveConnectionManager.subscribe()` adds whatever channel names it is given,
with no check of who is asking. `_PRIVATE_CHANNELS` solves a different problem —
it keeps private data out of the "empty subscription means every channel"
firehose (S8-02) — and says nothing about a client that *does* subscribe.

For `prices` that is correct. For the support operator queue it is a
disclosure: the channel carries other customers' subject lines and escalation
reasons, and any authenticated account could subscribe to it and watch the
operator's screen.

The patch adds `_PRIVILEGED_CHANNELS` (channel → the roles admitted), records
the token's `role` claim on the connection at auth time, and makes `subscribe()`
refuse a privileged channel and **return** what it refused so the client is
told. A token with no role claim gets `None`, and `None` is refused — an absent
value is not a permissive one. Every privileged channel must also be private, or
the role check is bypassed by not subscribing at all; a test asserts that
containment. The role is dropped on disconnect so a reused connection id cannot
inherit an operator's role.

One refused channel does not discard the rest of the request, and the
`subscribed` reply now echoes what was **granted** rather than what was asked
for — a client that believes it is subscribed and receives nothing looks
exactly like a quiet channel, which on the support queue is an operator
watching an empty screen while customers wait.

`test_ws_privileged_channels.py.txt` is the suite, verbatim. All 629 existing
WebSocket tests also pass against the patch.

### Why it cannot land

`api/ws_live.py` measures **34%** against the per-module coverage gate's 80%
floor, and is **not** in `docs/COVERAGE_UNMEASURABLE.txt`. So the gate blocks
any commit touching the file — measured on the clean tree with the change
stashed, so this is pre-existing and not caused by the patch. (The patch in
fact raises it to 35%.)

The file is 2,425 lines. There is no version of this change that does not touch
it: the check has to live where `subscribe` lives.

### The three ways out, and why I did not take two of them

1. **Record `api/ws_live.py` in `docs/COVERAGE_UNMEASURABLE.txt`.** That list's
   contract, stated in its own header and enforced by
   `tests/unit/test_coverage_gate_ratchet.py`, is that it may only **shrink**.
   Adding to it is expanding an allowlist, which is the owner's decision and not
   mine. It is arguably the *correct* one — the module was already in debt, and
   the static seed ("every module whose resolved test file never mentions it")
   simply missed it because `tests/unit/test_api.py` mentions it. If the owner
   agrees, the entry is honest and keeps its own pressure: it blocks the moment
   the module clears the floor.
2. **`SKIP_COVERAGE_GATE=1`.** The hook calls this "not recommended" and
   CLAUDE.md forbids weakening a gate without instruction. Not taken.
3. **Raise `api/ws_live.py` from 34% to 80%.** Roughly 500 more statements
   covered in a 2,425-line module — a project of its own, and out of proportion
   to a 40-line security fix.

### What this blocks downstream

The support desk's real-time handoff. `GET /api/support/queue` is a poll today;
the owner asked to watch the queue live and take over. Broadcasting it needs a
channel that only operators can join, which is this patch.

### To land it

Once the owner picks option 1 or 3:

```bash
git apply docs/pending/ws-privileged-channels.patch
cp docs/pending/test_ws_privileged_channels.py.txt tests/unit/test_ws_privileged_channels.py
pytest tests/unit/ -k "ws_" -q      # 640 tests
```

Then delete this directory entry.
