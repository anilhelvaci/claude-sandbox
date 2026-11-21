FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_MAJOR=22
ARG WITH_FOUNDRY=1
ARG WITH_SLITHER=1
ARG SLITHER_VERSION=

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git gnupg sudo tmux less vim nano jq ripgrep fd-find \
      build-essential python3 python3-pip python3-venv unzip procps lsof \
      iptables ipset iproute2 dnsutils aggregate \
 && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# Firewall (init-firewall is a Python script; python3 is installed above).
# The non-root user may run the firewall script via sudo (no
# arguments) and nothing else, so an agent can refresh the rules but can't
# remove them or install packages. Install packages as root from the host
# instead: sbx root <name>
COPY init-firewall /usr/local/bin/init-firewall
COPY allowlist/ /etc/sbx/allowlist/
RUN chmod 0755 /usr/local/bin/init-firewall \
 && mkdir -p /etc/sbx/allowlist.local \
 && gpasswd -d ubuntu sudo \
 && echo 'ubuntu ALL=(root) NOPASSWD: /usr/local/bin/init-firewall ""' > /etc/sudoers.d/ubuntu-firewall \
 && chmod 0440 /etc/sudoers.d/ubuntu-firewall

USER ubuntu
ENV HOME=/home/ubuntu \
    PATH=/opt/sbx/bin:/home/ubuntu/.local/bin:/home/ubuntu/.foundry/bin:/home/ubuntu/.npm-global/bin:$PATH \
    NPM_CONFIG_PREFIX=/home/ubuntu/.npm-global \
    CLAUDE_CONFIG_DIR=/home/ubuntu/.claude \
    DISABLE_AUTOUPDATER=1 \
    SANDBOX=true \
    TERM=xterm-256color

# Pre-create the volume targets so Docker gives them to ubuntu, not root.
RUN mkdir -p ~/.claude ~/.cache

# Claude Code updates come from rebuilding the image (sbx build).
RUN curl -fsSL https://claude.ai/install.sh | bash

RUN if [ "$WITH_FOUNDRY" = "1" ]; then \
      curl -fsSL https://foundry.paradigm.xyz | bash && ~/.foundry/bin/foundryup; \
    fi

# Slither (static analysis) in its own venv; pin with --build-arg SLITHER_VERSION=x.y.z.
# It drives the project's own compiler (forge build) through crytic-compile.
RUN if [ "$WITH_SLITHER" = "1" ]; then \
      python3 -m venv ~/.venvs/slither \
      && ~/.venvs/slither/bin/pip install --no-cache-dir "slither-analyzer${SLITHER_VERSION:+==$SLITHER_VERSION}" \
      && mkdir -p ~/.local/bin && ln -s ~/.venvs/slither/bin/slither ~/.local/bin/slither; \
    fi

# Trust any repo path (bind mounts are owned by a different uid on the host).
RUN git config --global --add safe.directory '*' \
 && git config --global user.name "Claude (sandbox)" \
 && git config --global user.email "claude-sandbox@localhost" \
 && printf '%s\n' 'set -g default-shell /bin/bash' 'set -g mouse on' 'set -g history-limit 50000' \
      'set -g base-index 1' 'set -g renumber-windows on' > ~/.tmux.conf

WORKDIR /home/ubuntu
CMD ["sleep", "infinity"]
