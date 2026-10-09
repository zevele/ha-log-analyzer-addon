FROM ghcr.io/home-assistant/amd64-base:latest

RUN apk add --no-cache python3 py3-pip bash curl supercronic

COPY ha_log_analyzer.py /usr/local/bin/ha_log_analyzer.py
COPY send_log_to_ha.sh /usr/local/bin/send_log_to_ha.sh
COPY run.sh /run.sh

RUN chmod +x /run.sh

CMD ["/run.sh"]
