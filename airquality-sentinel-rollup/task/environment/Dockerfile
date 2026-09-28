FROM python:3.12-slim

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends bash ca-certificates procps util-linux \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir \
      "numpy==2.4.2" "pandas==2.3.3" "scikit-learn==1.7.2" "scipy==1.17.0" "PyYAML==6.0.3"

RUN useradd --uid 1000 --create-home --shell /bin/bash ubuntu \
 && useradd --uid 1002 --create-home --shell /usr/sbin/nologin envrun


COPY envd/envd.py /opt/envd/envd.py
COPY hidden/ /opt/task/hidden/
COPY derive_fixtures.py /opt/task/derive_fixtures.py
RUN python3 /opt/task/derive_fixtures.py
COPY probe/ /opt/task/probe/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chown -R root:root /opt/envd /opt/task /usr/local/bin/entrypoint.sh \
 && chmod 700 /opt/envd && chmod 600 /opt/envd/envd.py \
 && chmod 700 /opt/task /opt/task/hidden /opt/task/probe \
 && chmod 600 /opt/task/hidden/* /opt/task/probe/* \
 && chmod 755 /usr/local/bin/entrypoint.sh \
 && mkdir -p /var/lib/envstate /run/envd && chmod 700 /var/lib/envstate

COPY workspace/ /workspace/target/
RUN chown -R ubuntu:ubuntu /workspace/target \
 && find /workspace/target -name '__pycache__' -prune -exec rm -rf {} + || true

RUN set -e; \
  for d in _private gold oracle solution alt alt2 hidden probe; do \
    if [ -e "/workspace/target/$d" ]; then echo "REFUSAL: reference dir in workspace ($d)" >&2; exit 1; fi; \
  done; \
  for f in solve.sh alt_solve.sh grade.py terminal_probe.py envd.py \
           terminal_labels.csv terminal_batch.csv \
           sanity_labels.csv sanity_batch.csv; do \
    if [ -e "/workspace/target/$f" ] || [ -e "/workspace/target/data/$f" ]; then \
      echo "REFUSAL: verifier material in workspace ($f)" >&2; exit 1; fi; \
  done; \
  if grep -R -I -n -E "rollup_wrong|terminal_labels|NOT_RECORDED|GOLD FIX|alt2_solve" \
       /workspace/target 2>/dev/null; then \
    echo "REFUSAL: answer-like leakage in workspace" >&2; exit 1; \
  fi; \
  for p in /opt/task/hidden /opt/task/probe; do \
    if [ "$(stat -c '%U %a' $p)" != "root 700" ]; then \
      echo "REFUSAL: $p is not root-only" >&2; exit 1; fi; \
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
