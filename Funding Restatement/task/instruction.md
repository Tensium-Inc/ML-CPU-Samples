# Funding requests: the harness table

The desk scores E-Rate funding requests for whether they will be funded. The
local check reports a held-out AUC of **1.0**. The team consuming the scores says
they are worthless in production and has stopped using them.

Rebuild the table the harness stands on and get a release through.

## The deliverable

`workspace/harness.py`, run as:

```
python3 harness.py --data-root <DIR> --out <FILE>
```

It writes csv with one row for every distinct funding request:

```
funding_request_number,label,applicant_key,committed_cents,filed_months,
filed_commitment_cents,filed_pre_discount_cents,filed_discount_pct
```

`committed_cents` and `filed_commitment_cents` are the same money column of the
extract read off two different versions of the request. They are not the same
number, and neither is a spelling of the other.

Grading is by value against every request in the extract and **per field**. The
seven graded fields are scored separately, each against a tolerance band, and
getting one right does not carry the others. A field with nothing to report is
the empty string, never a zero — those are different facts.

## Where the rules live

They are not in this file. They are ops notes held by the incident service:

```
python3 env_cli.py policy.list
python3 env_cli.py policy.read --topic <name>
```

**Read all of them — `submit` is refused until you have.** Everything the
deliverable is graded on is specified there. There is no hidden rule in this task
and no oracle to ration: the difficulty is not that something is being withheld
from you, it is that the extract is not shaped the way it looks and the desk's own
check gets *better* as the table gets worse.

`python3 env_cli.py profile` describes the shape of the extract for free, as often
as you like. `sample_rows` shows you two real rows. Both cost nothing.

## What you have

Your workspace carries the **whole extract** — every row, every column. The same
bytes the service validates against and the same bytes grading scores against.
Nothing is held back.

What it does not carry is the corrected table. So local testing tells you about
your code and never about your table.

`check_report.py` runs the desk's check and prints the number quoted in a release
request. Read it before you believe it.

## Getting a release through

The service gates the work and expects the steps in order. `status` always tells
you which one it wants next **and prints the exact command line to run**:

```
python3 env_cli.py status
python3 env_cli.py inspect
```

Every gated step returns a receipt and the next one has to carry it — `status`
fills it in for you under `next_command`. Deploying a build arms a serving fault
that must be diagnosed and repaired before release; `diagnostics.read` names the
family and prints the repair command. Budgets for validates and repairs are
visible in `status` and neither refills.
