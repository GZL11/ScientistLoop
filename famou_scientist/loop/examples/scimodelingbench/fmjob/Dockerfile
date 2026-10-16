# SciModelingBench worker image with all supported CLI runtimes.
#
# Keep credentials out of this image.  The CLIs read their credentials from
# the Job environment or from a mounted HOME at runtime.
FROM naturebench-base:v3

ARG CLAUDE_CODE_VERSION=2.1.199
ARG CODEX_VERSION=0.147.0
ARG OPENCODE_VERSION=1.18.1
ARG DATASETS_VERSION=4.8.5
ARG HUGGINGFACE_HUB_VERSION=1.15.0
ARG PYARROW_VERSION=24.0.0

# naturebench-base already carries the Node runtime used by the CLI tools.
RUN npm install --global --no-fund --no-audit \
        @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
        @openai/codex@${CODEX_VERSION} \
        opencode-ai@${OPENCODE_VERSION} \
    && command -v claude \
    && command -v codex \
    && command -v opencode

# Kimi Code is distributed as a standalone Linux binary rather than an npm
# package. The build script stages the verified host binary here; no user
# configuration or authentication state is included.
COPY kimi /usr/local/bin/kimi
RUN chmod 0755 /usr/local/bin/kimi && command -v kimi

# z-code is the local name used by this project for Baidu Comate Zulu.  Zulu
# is distributed with its private Comate engine, so both are staged by the
# build script and copied as application files rather than fetched with npm.
COPY zulu-cli /opt/zulu-cli
COPY comate-engine /opt/comate-engine
ENV COMATE_ENGINE_PATH=/opt/comate-engine
RUN ln -s /opt/zulu-cli/bin/zulu /usr/local/bin/zulu \
    && ln -s /usr/local/bin/zulu /usr/local/bin/z-code \
    && command -v zulu \
    && command -v z-code

RUN python -m pip install --no-cache-dir \
        sci-modeling-bench==0.10.0 \
        datasets==${DATASETS_VERSION} \
        huggingface_hub==${HUGGINGFACE_HUB_VERSION} \
        pyarrow==${PYARROW_VERSION} \
    && claude --version \
    && codex --version \
    && opencode --version \
    && kimi --version \
    && zulu --version \
    && z-code --version
