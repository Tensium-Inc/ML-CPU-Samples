FROM python:3.12-slim

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends bash ca-certificates procps util-linux \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir \
      "numpy==2.4.2" "pandas==2.3.3" "scikit-learn==1.7.2" "scipy==1.17.0" "PyYAML==6.0.3"

RUN useradd --uid 1000 --create-home --shell /bin/bash ubuntu \
 && useradd --uid 1002 --create-home --shell /usr/sbin/nologin envrun

# These read a password straight off stdin and block forever when no input arrives, and a step
# that never returns cannot be cut short by a step budget. Stripping setuid stops them
# succeeding, not prompting, so the binaries go.
RUN rm -f /bin/su /usr/bin/su /usr/bin/newgrp /usr/bin/passwd /usr/bin/chsh /usr/bin/chfn

COPY workspace/ /workspace/target/
RUN chown -R ubuntu:ubuntu /workspace/target \
 && find /workspace/target -name '__pycache__' -prune -exec rm -rf {} + || true

COPY envd/ /opt/envd/
COPY hidden/ /opt/task/hidden/
COPY derive_fixtures.py /opt/task/derive_fixtures.py
RUN python3 /opt/task/derive_fixtures.py
COPY probe/ /opt/task/probe/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chown -R root:root /opt/envd /opt/task /usr/local/bin/entrypoint.sh \
 && chmod 700 /opt/envd && chmod 600 /opt/envd/*.py \
 && chmod 700 /opt/task /opt/task/hidden /opt/task/probe \
 && chmod 600 /opt/task/hidden/* /opt/task/probe/* \
 && chmod 755 /usr/local/bin/entrypoint.sh \
 && mkdir -p /var/lib/envstate /run/envd && chmod 700 /var/lib/envstate

RUN set -e; \
  for d in _private gold oracle solution alt alt2 hidden probe envd; do \
    if [ -e "/workspace/target/$d" ]; then echo "REFUSAL: reference dir in workspace ($d)" >&2; exit 1; fi; \
  done; \
  for f in solve.sh alt_solve.sh alt2_solve.sh grade.py terminal_probe.py envd.py envd_core.py \
           DEV_NOTES.md SEED_SPEC.md terminal_batch.csv terminal_labels.csv \
           checkpoint_batch.csv checkpoint_labels.csv canary_batch.csv \
           archive_full.csv archive_trimmed.csv; do \
    if [ -e "/workspace/target/$f" ] || [ -e "/workspace/target/data/$f" ]; then \
      echo "REFUSAL: verifier material in workspace ($f)" >&2; exit 1; fi; \
  done; \
  if grep -R -I -n -E "register_disagreement|archive_not_reread|archive_trimmed|terminal_labels|config_drift|GOLD FIX|alt2_solve" \
       /workspace/target 2>/dev/null; then \
    echo "REFUSAL: answer-like leakage in workspace" >&2; exit 1; \
  fi; \
  for p in /opt/task/hidden /opt/task/probe /opt/envd; do \
    if [ "$(stat -c '%U %a' $p)" != "root 700" ]; then \
      echo "REFUSAL: $p is not root-only" >&2; exit 1; fi; \
  done; \
  for b in /bin/su /usr/bin/su /usr/bin/newgrp /usr/bin/passwd; do \
    if [ -e "$b" ]; then echo "REFUSAL: hanging escalation binary still present ($b)" >&2; exit 1; fi; \
  done; \
  true

ENV WORKSPACE_DIR=/workspace/target \
    ENVD_STATE=/var/lib/envstate \
    ENVD_HIDDEN=/opt/task/hidden \
    ENVD_SOCK=/run/envd/envd.sock \
    ENVD_PATH=/opt/envd/envd.py \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace/target
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]
