#!/usr/bin/with-contenv bashio

export DRY_RUN=$(bashio::config 'advanced_settings.dry_run')
export TOKEN_COUNT=$(bashio::config 'advanced_settings.token_count')
export MAX_LINES=$(bashio::config 'advanced_settings.max_lines')
export LITELLM_API_KEY=$(bashio::config 'litellm_api_key')
export MAX_HOURS=$(bashio::config 'advanced_settings.max_hours')
export LITELLM_ADDRESS=$(bashio::config 'litellm_address')
export MODEL_NAME=$(bashio::config 'model_name')

CUSTOM_NAME=$(bashio::config 'advanced_settings.sensor_name')
SENSOR_SLUG=$(echo "$CUSTOM_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '_')

python3 /usr/local/bin/ha_log_analyzer.py | python3 -c "
import sys, urllib.request, json, datetime

# 1. Grab the token directly from the passed Bash argument array
token = sys.argv[1]
friendly_title = sys.argv[2]
entity_id_slug = sys.argv[3]

if not token or token == 'None':
   raise RuntimeError('SUPERVISOR_TOKEN argument is missing')

log_text = sys.stdin.read()
iso_now = datetime.datetime.now().isoformat()

payload = {
    'state': iso_now,
    'attributes': {
        'friendly_name': friendly_title,
        'icon': 'mdi:text-search',
        'update_date': iso_now,
        'homeassistant': log_text
    }
}

req = urllib.request.Request(
    f'http://supervisor/core/api/states/sensor.{entity_id_slug}',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    },
    method='POST'
)

urllib.request.urlopen(req, timeout=10)
" "${SUPERVISOR_TOKEN}" "${CUSTOM_NAME}" "${SENSOR_SLUG}"

bashio::log.info "Sensor update command completed successfully."

exit 0
