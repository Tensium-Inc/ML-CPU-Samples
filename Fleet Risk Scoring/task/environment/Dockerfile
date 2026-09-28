FROM python:3.12-slim

RUN pip install --no-cache-dir \
      "pandas==2.3.3" \
      "numpy==2.2.6" \
      "scikit-learn==1.7.2" \
      "PyYAML==6.0.3"

RUN useradd -m ubuntu
WORKDIR /workspace/target

COPY workspace/ /workspace/target/

# The answer must not be reachable from the workspace.
RUN set -e; \
    for d in _private solution tests oracle skeleton; do \
      if [ -e "/workspace/target/$d" ]; then \
        echo "REFUSAL: verifier material inside the workspace ($d)" >&2; exit 1; \
      fi; \
    done; \
    if [ -e "/workspace/target/out" ]; then \
      echo "REFUSAL: a completed run left in the workspace (out/)" >&2; exit 1; \
    fi; \
    for f in grade.py solve.sh alt_solve.sh alt2_solve.sh expected_current.csv.gz \
             expected_reference.csv.gz; do \
      if find /workspace/target -name "$f" -print -quit | grep -q .; then \
        echo "REFUSAL: verifier material inside the workspace ($f)" >&2; exit 1; \
      fi; \
    done

RUN chown -R ubuntu:ubuntu /workspace/target
USER ubuntu
