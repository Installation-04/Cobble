# Allow-list forward proxy for agent containers (tinyproxy, GPL-2.0-or-later, used as a
# separate unmodified program). Default deny: only the hosts in AGENT_PROXY_ALLOW pass.
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
# Optional build secret "ca": a CA bundle for networks with TLS inspection.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    apk add --no-cache 'tinyproxy~=1.11' \
    && adduser -S -D -H -u 10004 proxy
COPY tinyproxy.conf.tmpl /etc/tinyproxy/tinyproxy.conf.tmpl
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh
USER 10004
EXPOSE 3128
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
