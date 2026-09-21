# Runbook — restore the HOPEFX database

| Field | Value |
|---|---|
| Severity | **SEV1** — data loss or corruption |
| Owner | hacklove340 |
| Last verified | 2026-09-08, by executing the round trip against PostgreSQL 16.13 and SQLite |
| Review cadence | After every restore, real or rehearsed |
| Related | `database/backup.py` · `database/restore.py` · Group 2 Ch 9 |

---

## Quick checklist

- [ ] 1. **Stop writing to the damaged database** (§2)
- [ ] 2. **Copy what is left before touching it** (§3) — this is not optional
- [ ] 3. **Verify a backup before restoring it** (§4)
- [ ] 4. Restore: SQLite (§5) or PostgreSQL (§6)
- [ ] 5. **Check the restored data is the data** (§7)
- [ ] 6. If no backup verifies, escalate (§9) — do not keep trying older ones silently

Work top to bottom. Step 2 is the one people skip under stress and the one that
makes every later mistake recoverable.

> **Run every command in this runbook from the repository root.**
> `python -m database.restore` resolves the `database` package from the working
> directory; from anywhere else it exits with `No module named 'database'`, which
> looks like a broken backup and is not. Found by running the §8 sweep from the
> wrong directory while writing this file — it reported the *good* backup as
> refused.

---

## 1. What this runbook does not tell you

**There is no agreed RPO or RTO.** How much data the business will accept losing,
and how long a restore may take, have not been decided — they are open decision
A1 in `docs/ai/MASTER_OUTSTANDING.md`. Backups are taken every 24 hours by
`celery_app.database_backup`, so **in the worst case you are restoring to a point
up to 24 hours old**, and that is a consequence of the current schedule, not a
target anybody signed off.

Say this out loud in the incident channel before you restore. The decision about
what is acceptable to lose belongs to the owner, not to the person holding the
terminal at 3am.

## 2. Stop the writers

```bash
# Whichever applies to this deployment.
docker compose stop api worker beat        # compose
kubectl -n hopefx scale deploy/api deploy/worker --replicas=0   # kubernetes
```

**Prerequisite:** you can reach the orchestrator.
**If this fails:** carry on to §3 anyway — a copy of a moving database is worth
more than no copy — but say in the channel that writes were still live.

## 3. Copy what is left, before anything else

A damaged database is still evidence, and it may hold rows the backup does not.

```bash
# SQLite — copy the sidecars too, they hold committed rows
cp -a hopefx.db hopefx.db-wal hopefx.db-shm /var/tmp/incident-$(date +%s)/ 2>/dev/null

# PostgreSQL — a dump of the damaged database, if it will still dump
pg_dump --no-password -Fc "$DATABASE_URL" > /var/tmp/incident-$(date +%s).dump
```

**If `pg_dump` fails:** the database is too damaged to dump. Copy the data
directory instead if you have filesystem access, then continue.

Do not proceed until something is copied. Everything after this point can be
undone; skipping this step cannot.

## 4. Verify the backup *before* you restore it

```bash
ls -lt backups/ | head -10
python -m database.restore --verify backups/<file>
```

**Expected output:**

```
hopefx_20260908T000000Z.db.gz: sqlite · 1,234,567 bytes · 14 tables · 0 statements
```

If it prints `REFUSED`, the backup is not usable. Find the message below.

### What each refusal means

| Message | What happened | Do this |
|---|---|---|
| `backup does not exist` | Wrong path, or retention already deleted it | `ls backups/`. `BACKUP_KEEP` defaults to 7 |
| `backup is empty` | Zero bytes — the dump died before writing | Try the next-oldest backup |
| `backup is not gzip` | Not a backup, or written by something else | Check you are in the right directory |
| `backup is truncated or unreadable` | The dump was cut off — disk full, or the worker was killed mid-write | Try the next-oldest. Check free space on the backup volume |
| `backup decompressed to nothing` | Valid gzip wrapping zero bytes | Try the next-oldest |
| `backup contains no tables` | **See §8 — this is the known-bad class.** The artefact is a valid SQLite database with nothing in it | Treat as lost. Try the next-oldest, and read §8 before trusting any backup dated before 2026-09-08 |
| `backup contains no statements` | A PostgreSQL dump of the wrong database, or of one with no objects | Check which database was dumped. Try the next-oldest |
| `unrecognised backup content` | Neither a SQLite database nor a SQL dump | Not a HOPEFX backup |

**Never restore an artefact that refuses.** The refusal is the only thing
standing between you and a restore that appears to succeed and silently produces
an empty database.

## 5. Restore — SQLite

```bash
# Restore to a NEW path first. Never straight over the live file.
python -m database.restore backups/<file> --target /var/tmp/recovered.db
```

**Expected output:** `restored → /var/tmp/recovered.db (14 tables, 20,341 rows)`

Check it, then swap it in:

```bash
sqlite3 /var/tmp/recovered.db "SELECT count(*) FROM trades;"   # or use python
mv hopefx.db hopefx.db.damaged-$(date +%s)
mv /var/tmp/recovered.db hopefx.db
rm -f hopefx.db-wal hopefx.db-shm    # stale sidecars belong to the old file
```

`--target` refuses to overwrite an existing file. `--overwrite` exists but do not
reach for it during an incident: restoring to a new path and moving is the same
number of commands and leaves you somewhere to go back to.

## 6. Restore — PostgreSQL

Supervised, and never into the live database on the first attempt.

```bash
# 1. A scratch database to restore into
createdb hopefx_restored

# 2. Load it. ON_ERROR_STOP is what turns a partial restore into a visible failure.
gunzip -c backups/<file> | psql -v ON_ERROR_STOP=1 -d hopefx_restored
```

**If psql stops with an error:** the restore is incomplete. Do not promote this
database. Drop it (`dropdb hopefx_restored`), take the next-oldest backup, and
start again.

```bash
# 3. Check it holds what you expect (adjust to the tables that matter)
psql -tAq -d hopefx_restored -c "SELECT count(*) FROM trades;"

# 4. Promote, only once you are satisfied
psql -d postgres -c 'ALTER DATABASE hopefx RENAME TO hopefx_damaged;'
psql -d postgres -c 'ALTER DATABASE hopefx_restored RENAME TO hopefx;'
```

**WARNING before step 4** — rename needs no active connections:

```sql
-- DRY RUN: how many sessions are attached?
SELECT count(*) FROM pg_stat_activity WHERE datname IN ('hopefx', 'hopefx_restored');

-- Only if that count is what you expect, and §2 was done:
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE datname = 'hopefx' AND pid <> pg_backend_pid();
```

Keep `hopefx_damaged` until the postmortem is written. It costs disk; it may cost
much less than the rows nobody has noticed are missing yet.

## 7. Verify the restore is the data, not just a database

Row counts alone are not proof — a restore of the wrong backup also has rows.

```sql
-- Newest record: is it as recent as you expect, given §1's 24h worst case?
SELECT max(created_at) FROM trades;
-- Does anything obviously dangle?
SELECT count(*) FROM positions p LEFT JOIN trades t ON t.id = p.trade_id WHERE t.id IS NULL;
```

Then bring one writer back (§2 in reverse) and watch it for five minutes before
restoring the rest.

## 8. The known-bad artefact class — SQLite backups written before 2026-09-08

**Any SQLite backup taken before this date may be worthless, and will look fine.**

`database/connection.py` sets `PRAGMA journal_mode=WAL`. Committed rows live in
the `-wal` sidecar until a checkpoint. The old backup copied the main database
file alone, so those rows were left behind. The artefact compresses, decompresses
and opens cleanly — it simply has no tables in it. The scheduled job logged
success every time.

Reproduced before the fix: a database with one committed row produced a backup
where `SELECT count(*) FROM trades` raised *no such table: trades*.

**What to do about it:**

* `python -m database.restore --verify` refuses these with `backup contains no
  tables`. That refusal is the detector — trust it.
* Sweep the backup directory now rather than during an incident:

  ```bash
  for f in backups/*.gz; do
    python -m database.restore --verify "$f" >/dev/null 2>&1 \
      && echo "OK      $f" || echo "REFUSED $f"
  done
  ```

* Backups written after the fix use `sqlite3.Connection.backup()`, which is
  transactionally consistent and includes WAL content, and are named `.db.gz`
  rather than the misleading `.sql.gz`.

PostgreSQL backups are unaffected — `pg_dump` was always consistent.

## 9. Escalation — when no backup verifies

Stop working down the list in silence. After **two** refused backups:

1. Post in the incident channel: which files you tried, and the exact refusal for
   each.
2. Escalate to the owner. This is now a data-loss decision, not a recovery task.
3. Do not delete anything — not the damaged database, not the refused artefacts.
   Both are evidence, and a refused backup may still be partially readable by
   someone with more time than you have right now.

| Situation | Escalate to | When |
|---|---|---|
| Two or more backups refuse | Owner | Immediately |
| Restore succeeds but data looks wrong (§7) | Owner | Before promoting |
| No backups exist at all | Owner | Immediately, and preserve everything |

## 10. After the incident

* Write the postmortem. The `postmortem-writing` skill has the structure.
* Update the **Last verified** date at the top of this runbook.
* If any step here was wrong, fix it in the same change as the postmortem. A
  runbook is only trustworthy if the last person through it corrected it.

## 11. Rehearsing this, so the first run is not during an incident

The restore path is exercised automatically on every CI run:

* `tests/unit/test_database_restore.py` — SQLite round trip with real rows, plus
  every refusal above proven by handing the code the broken artefact.
* `tests/integration/test_database_restore_postgres.py` — a real `pg_dump`
  restored into a real database, checksums compared.

To rehearse by hand, take a backup of a scratch database and walk §4–§7. The
whole point of this phase was that **a backup nobody has restored is not a
backup** — the same is true of a runbook nobody has walked.
