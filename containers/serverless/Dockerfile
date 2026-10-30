FROM --platform=linux/amd64 runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851 AS build

ARG RAG_CODE_REVISION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/ragbench \
    PATH=/opt/venv/bin:${PATH}

USER root
WORKDIR /tmp/build

COPY repository.tar /tmp/build/repository.tar
COPY context-manifest.json /tmp/build/context-manifest.json
COPY Dockerfile /tmp/build/Dockerfile

RUN command -v git >/dev/null \
    && command -v tar >/dev/null \
    && python3 -c 'import sys; sys.version_info[:2] == (3, 12) or sys.exit("Python 3.12 is required")'

RUN python3 -c 'import hashlib,json,os,pathlib,re,sys; revision=os.environ["RAG_CODE_REVISION"]; manifest=json.loads(pathlib.Path("/tmp/build/context-manifest.json").read_text(encoding="utf-8")); re.fullmatch(r"[0-9a-f]{40}", revision) or sys.exit("RAG_CODE_REVISION must be a full lowercase SHA"); expected={"schema_version":"serverless-build-context.v2","code_revision":revision,"dockerfile":{"path":"Dockerfile","sha256":hashlib.sha256(pathlib.Path("/tmp/build/Dockerfile").read_bytes()).hexdigest()},"repository_snapshot":{"path":"repository.tar","sha256":hashlib.sha256(pathlib.Path("/tmp/build/repository.tar").read_bytes()).hexdigest()}}; manifest == expected or sys.exit("build context manifest mismatch")'

RUN install -d /opt/ragbench \
    && tar --extract --file /tmp/build/repository.tar --directory /opt/ragbench --no-same-owner \
    && test "$(git -C /opt/ragbench rev-parse HEAD)" = "${RAG_CODE_REVISION}" \
    && test "$(git -C /opt/ragbench rev-list --count HEAD)" = "1" \
    && test -z "$(git -C /opt/ragbench status --porcelain=v1 --untracked-files=all)"

WORKDIR /opt/ragbench

RUN python3 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/python -m pip install \
        --require-hashes \
        --no-deps \
        -r requirements-serverless-gpu.lock.txt

FROM --platform=linux/amd64 runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/ragbench \
    PATH=/opt/venv/bin:${PATH} \
    RAG_MODEL_ROOT=/opt/models \
    HF_HOME=/opt/models/huggingface

USER root
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/ragbench /opt/ragbench

WORKDIR /opt/ragbench

RUN /opt/venv/bin/python -c 'import sys,torch,runpod,FlagEmbedding; torch.__version__ == "2.8.0+cu128" or sys.exit(f"unexpected torch version: {torch.__version__}"); torch.version.cuda == "12.8" or sys.exit(f"unexpected CUDA version: {torch.version.cuda}")' \
    && test -z "$(git status --porcelain=v1 --untracked-files=all)" \
    && groupadd --gid 10001 ragbench \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin ragbench \
    && install -d -m 0750 -o ragbench -g ragbench /opt/models \
    && chown -R ragbench:ragbench /opt/ragbench/data/results

USER ragbench
WORKDIR /opt/ragbench

ENTRYPOINT ["/opt/venv/bin/python", "-m", "scripts.runpod_serverless_handler"]
