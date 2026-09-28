# syntax=docker/dockerfile:1
FROM python:3.12-slim

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends bash jq ripgrep \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --no-cache-dir \
       numpy==2.3.3 \
       pandas==2.3.3 \
       scikit-learn==1.8.0

RUN groupadd --gid 1000 ubuntu \
  && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash ubuntu

COPY backend/ /opt/task/backend/
COPY entrypoint.sh /usr/local/bin/capital-bike-task-entrypoint
RUN chown -R root:root /opt/task/backend /usr/local/bin/capital-bike-task-entrypoint \
  && chmod 700 /opt/task/backend /opt/task/backend/service.py \
  && chmod 700 /opt/task/backend/private \
  && chmod 600 /opt/task/backend/private/*.csv \
  && chmod 755 /usr/local/bin/capital-bike-task-entrypoint \
  && mkdir -p /var/lib/capital-bike-task /run/capital-bike-task \
  && chown root:root /var/lib/capital-bike-task /run/capital-bike-task \
  && chmod 700 /var/lib/capital-bike-task \
  && chmod 755 /run/capital-bike-task

COPY workspace/ /workspace/target/
RUN chown -R ubuntu:ubuntu /workspace/target \
  && chmod 755 /workspace/target/env_cli.py /workspace/target/scripts/*.py

RUN set -eu; \
  for name in _private gold oracle solution; do \
    if [ -e "/workspace/target/$name" ]; then echo "reference directory leaked: $name" >&2; exit 1; fi; \
  done; \
  for name in service.py terminal_probe.py terminal.csv terminal_requests.csv validation_wave1.csv validation_wave2.csv base_history.csv terminal-predictions.csv; do \
    if find /workspace/target -name "$name" -print -quit | grep -q .; then echo "private file leaked: $name" >&2; exit 1; fi; \
  done

ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV PYTHONHASHSEED=0

WORKDIR /workspace/target
ENTRYPOINT ["/usr/local/bin/capital-bike-task-entrypoint"]
CMD ["sleep", "infinity"]
