FROM python:3.8-slim-bullseye

RUN apt update && apt install -y libmagic-dev bash curl wget jq
RUN  set -ex; \
     \
     curl -o /usr/local/bin/su-exec.c https://raw.githubusercontent.com/ncopa/su-exec/master/su-exec.c; \
     \
     fetch_deps='gcc libc-dev'; \
     apt-get update; \
     apt-get install -y --no-install-recommends $fetch_deps; \
     rm -rf /var/lib/apt/lists/*; \
     gcc -Wall \
         /usr/local/bin/su-exec.c -o/usr/local/bin/su-exec; \
     chown root:root /usr/local/bin/su-exec; \
     chmod 0755 /usr/local/bin/su-exec; \
     rm /usr/local/bin/su-exec.c; \
     \
     apt-get purge -y --auto-remove $fetch_deps
# Latest on https://launchpad.net/~rmescandon/+archive/ubuntu/yq is 4.9.6
ARG VERSION=v4.9.6
ARG BINARY=yq_linux_386
RUN wget https://github.com/mikefarah/yq/releases/download/${VERSION}/${BINARY} -O /usr/bin/yq \ 
    && chmod +x /usr/bin/yq

WORKDIR /opt/mautrix-wechat
COPY . .
RUN chmod +x ./docker-run.sh
RUN pip install pdm
RUN pdm install

ENV WECHAT_FILES_DIR=
ENV PYTHONPATH=/opt/mautrix-wechat/__pypackages__/3.8/lib
EXPOSE 29380
VOLUME /data

CMD ["sh", "-c", "/opt/mautrix-wechat/docker-run.sh"]
