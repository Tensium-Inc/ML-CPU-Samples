# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Pinned. The reference table is exact strings and does not move under a wheel
# bump, but the local report fits a scorer, and an unpinned scikit-learn would
# change the number the desk quotes between one run and the next.
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash ca-certificates util-linux \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --no-cache-dir numpy==2.1.3 pandas==2.2.3 scipy==1.14.1 \
       scikit-learn==1.5.2

RUN groupadd --gid 1000 ubuntu && useradd --uid 1000 --gid 1000 -m ubuntu

# --- the ops service, root-owned and outside the agent's tree ---------------
COPY backend/ /opt/task/
RUN chown -R root:root /opt/task \
  && chmod 755 /opt/task \
  && chmod 700 /opt/task/policies.py /opt/task/reference.py /opt/task/grading.py \
       /opt/task/broker.py /opt/task/sandbox.py /opt/task/corpus.py \
  && chmod 755 /opt/task/daemon.py /opt/task/task-entrypoint.sh \
  && mkdir -p /var/lib/fundops \
  && chown root:root /var/lib/fundops \
  && chmod 700 /var/lib/fundops

# The trusted copy of the extract. Root-only. It is the same bytes the agent has in
# its workspace -- what is withheld is not the data but which events may be
# scored and which rows are one incident, which exist only in reference.py and
# are reachable only through the service.
COPY trusted/ /opt/task/data/
RUN chown -R root:root /opt/task/data && chmod -R 700 /opt/task/data

WORKDIR /workspace/target
COPY workspace/ /workspace/target/
RUN chown -R ubuntu:ubuntu /workspace/target \
  && mkdir -p /workspace/target/.ops /logs/verifier/ops /logs/agent /logs/artifacts \
  && chown -R root:root /workspace/target/.ops /logs/verifier \
  && chmod 755 /logs /logs/artifacts /workspace/target/.ops \
  && chmod 777 /logs/agent \
  && chmod 700 /logs/verifier /logs/verifier/ops \
  && chmod 1755 /workspace/target

# --- anti-leak build guard -------------------------------------------------
# The workspace must not carry the reference, the notes, or any statement of the
# two withheld rules. The greps are for the ANSWERS, not for the vocabulary: the
# workspace is entitled to say "episode" and "blank" all day, and has to, or the
# TODOs could not name what is undecided.
RUN set -e; \
  for d in _private gold oracle alt alt2 backend trusted negative_controls; do \
    if [ -e "/workspace/target/$d" ]; then echo "REFUSAL: reference dir in workspace ($d)" >&2; exit 1; fi; \
  done; \
  for f in solve.sh alt_solve.sh alt2_solve.sh grade.py reference.py policies.py broker.py grading.py sandbox.py corpus.py; do \
    if [ -e "/workspace/target/$f" ]; then echo "REFUSAL: verifier material in workspace ($f)" >&2; exit 1; fi; \
  done; \
  if grep -rIn -E "form_version.*==.*Original|Original.*==.*form_version|row\[.ben.\]|\"ben\"\]|Cancelled.*not_funded|not_funded.*Cancelled" \
       /workspace/target --include='*.py' 2>/dev/null; then \
    echo "REFUSAL: a shipped answer leaked into the workspace" >&2; exit 1; \
  fi; \
  true

ENV WORKSPACE_DIR=/workspace/target
ENV OPS_SOCKET=/run/fundops.sock

# Explicit, because the container MUST start privileged: the service owns
# /var/lib/fundops at 0700 and binds its socket before the agent exists, and a
# served sandbox sets no_new_privs, so there is no way back up afterwards.
USER root
ENTRYPOINT ["/opt/task/task-entrypoint.sh"]
