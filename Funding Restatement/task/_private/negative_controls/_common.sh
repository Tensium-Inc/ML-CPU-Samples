# Shared helpers for the negative controls. _private only; never shipped.
#
# Each control is meant to floor for ONE reason, so the parts that are not under
# test -- reading the notes, driving the gates, writing a correct build -- are
# written once here.
WS="${WORKSPACE_DIR:-/workspace/target}"
CLI="python3 $WS/env_cli.py"
RECEIPT=""
# env_cli emits ONE json object and nothing else, so a plain json.load is safe.
op() {
  local out
  out="$($CLI "$@" ${RECEIPT:+--receipt "$RECEIPT"})"
  printf '%s\n' "$out"
  RECEIPT="$(printf '%s' "$out" | python3 -c 'import json,sys
print(json.load(sys.stdin).get("receipt") or "")')"
  printf '%s' "$out" | python3 -c 'import json,sys
sys.exit(0 if json.load(sys.stdin).get("ok") else 1)'
}
obs() { $CLI "$@"; }
read_all_notes() {
  for topic in $(obs policy.list | python3 -c 'import json,sys
print(" ".join(json.load(sys.stdin)["topics"]))'); do
    obs policy.read --topic "$topic" >/dev/null
  done
}
drive() {
  op reproduce; op deploy; op validate; op diagnostics.read
  op recovery.apply --family stale_applicant_cache
  op validate; op check.release; op submit
}

# Write a build correct except for the defects named in $1.
# WRONG may contain: restated_money, cancelled_undecided, name_key
write_build() {
  python3 - "$WS" "${1:-}" <<'PY'
import pathlib, sys
ws, wrong = pathlib.Path(sys.argv[1]), sys.argv[2]
src = ws / "src"; src.mkdir(parents=True, exist_ok=True)

money_key = "adjudicated" if "restated_money" in wrong else "filed"
# `one_provenance` works out that the as-filed row is the observation and then
# applies that single rule to the whole table, including the field that is not
# read off it. It is the plausible partial answer.
committed_src = "filed" if "one_provenance" in wrong else "adj"
(src / "requests.py").write_text(
    '"""Group form-version rows into requests."""\n'
    "from __future__ import annotations\n\n"
    "AS_FILED = 'Original'\nAS_ADJUDICATED = 'Current'\n\n"
    "def cents(raw):\n"
    "    t = (raw or '').strip()\n"
    "    if not t:\n        return ''\n"
    "    try:\n        return str(int(round(float(t) * 100)))\n"
    "    except ValueError:\n        return ''\n\n"
    "def collect(rows):\n"
    "    filed, adj = {}, {}\n"
    "    for row in rows:\n"
    "        frn = row['funding_request_number']\n"
    "        if not frn:\n            continue\n"
    "        if row['form_version'] == AS_FILED:\n            filed.setdefault(frn, row)\n"
    "        elif row['form_version'] == AS_ADJUDICATED:\n            adj.setdefault(frn, row)\n"
    "    return {f: {'filed': filed.get(f), 'adjudicated': adj.get(f)}\n"
    "            for f in set(filed) | set(adj)}\n\n"
    "def audit(rows):\n"
    "    seen = {}\n"
    "    for row in rows:\n"
    "        frn = row['funding_request_number']\n"
    "        if frn:\n            seen.setdefault(frn, set()).add(row['form_version'])\n"
    "    return {'rows': len(rows), 'requests': len(collect(rows)),\n"
    "            'carrying_both_versions': sum(1 for v in seen.values() if len(v) > 1)}\n")

decided = ("{'QK7', 'VR9', 'VD4'}" if "cancelled_undecided" in wrong
           else "{'QK7', 'VR9', 'ZP2', 'VD4'}")
(src / "labels.py").write_text(
    '"""The outcome of a request."""\n'
    "from __future__ import annotations\n\n"
    f"DECIDED = {decided}\n"
    + ("FUNDED = {'QK7'}\n\n" if 'miss_second_funded' in wrong else "FUNDED = {'QK7', 'VR9'}\n\n")
    + "def label(adjudicated):\n"
    "    if adjudicated is None or adjudicated.get('form_471_frn_status_name') not in DECIDED:\n"
    "        return 'undecided'\n"
    "    if adjudicated['form_471_frn_status_name'] not in FUNDED:\n"
    "        return 'not_funded'\n"
    + ("    return 'funded'\n" if 'label_status_only' in wrong else
       "    try:\n"
       "        money = float((adjudicated.get('funding_commitment_request') or '').strip())\n"
       "    except ValueError:\n"
       "        money = None\n"
       "    wave = bool((adjudicated.get('wave_sequence_number') or '').strip())\n"
       "    return 'funded' if (money not in (None, 0.0) and wave) else 'not_funded'\n"))

key = "row['organization_name']" if "name_key" in wrong else "row['ben']"
(src / "keys.py").write_text(
    '"""The applicant key."""\n'
    "from __future__ import annotations\n\n"
    f"def applicant_key(row):\n    return {key}\n")

(src / "schema.py").write_text(
    '"""Deliverable shape and writer."""\n'
    "from __future__ import annotations\n"
    "import csv\n"
    "COLUMNS = ['funding_request_number', 'label', 'applicant_key',\n"
    "           'committed_cents', 'filed_months',\n"
    "           'filed_commitment_cents', 'filed_pre_discount_cents', 'filed_discount_pct']\n\n"
    "def contract():\n    return {'columns': list(COLUMNS), 'rows_per_request': 1}\n\n"
    "def write(table, out_path):\n"
    "    with open(out_path, 'w', newline='', encoding='utf-8') as fh:\n"
    "        w = csv.writer(fh); w.writerow(COLUMNS)\n"
    "        for frn in sorted(table):\n"
    "            r = table[frn]\n"
    "            w.writerow([frn] + [r[c] for c in COLUMNS[1:]])\n")

(ws / "harness.py").write_text(
    '#!/usr/bin/env python3\n"""Funding-request table entry point."""\n'
    "from __future__ import annotations\n"
    "import argparse, sys\nfrom pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
    "from src import keys, labels, loading, requests, schema\n\n"
    "def build(data_root):\n"
    "    rows = loading.read_rows(data_root)\n"
    "    table = {}\n"
    "    for frn, pair in requests.collect(rows).items():\n"
    "        filed, adj = pair['filed'], pair['adjudicated']\n"
    f"        money = pair[{money_key!r}]\n"
    "        table[frn] = {\n"
    "            'label': labels.label(adj),\n"
    "            'applicant_key': keys.applicant_key(filed or adj),\n"
    "            'filed_commitment_cents': requests.cents(money['funding_commitment_request']) if money else '',\n"
    "            'filed_pre_discount_cents': requests.cents(money['total_pre_discount_costs']) if money else '',\n"
    "            'filed_discount_pct': (money['dis_pct'] if money else ''),\n"
    f"            'committed_cents': requests.cents({committed_src}['funding_commitment_request']) if {committed_src} else '',\n"
    "            'filed_months': (filed['months_of_service'] if filed else ''),\n"
    "        }\n"
    "    return table\n\n"
    "def main():\n"
    "    ap = argparse.ArgumentParser()\n"
    "    ap.add_argument('--data-root', required=True); ap.add_argument('--out', required=True)\n"
    "    a = ap.parse_args()\n"
    "    t = build(a.data_root)\n"
    "    schema.write(t, Path(a.out))\n"
    "    print(f'built {len(t)} requests')\n    return 0\n\n"
    "if __name__ == '__main__':\n    raise SystemExit(main())\n")
PY
}
