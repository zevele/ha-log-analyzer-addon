#!/usr/bin/with-contenv bashio

# 1. Extract the user configuration
TIME_STR=$(bashio::config 'advanced_settings.scheduled_time')
RUN_NOW=$(bashio::config 'advanced_settings.run_on_start')
SINGLE_RUN=$(bashio::config 'advanced_settings.single_run')
DRY_RUN=$(bashio::config 'advanced_settings.dry_run')

if bashio::var.true "${DRY_RUN}"; then
    bashio::log.info "dry_run is enabled."
fi

# 4. Optional: Execute immediately if run_on_start is true
if bashio::var.true "${RUN_NOW}"; then
    bashio::log.info "run_on_start is enabled. Executing initial analysis now..."
    /usr/local/bin/send_log_to_ha.sh
fi

if bashio::var.false "${SINGLE_RUN}"; then
  # 2. Parse the hour and minute out of the "HH:MM" string
  HOUR=$(echo "$TIME_STR" | cut -d: -f1)
  MINUTE=$(echo "$TIME_STR" | cut -d: -f2)

  bashio::log.info "Configuring Supercronic task to run daily at ${HOUR}:${MINUTE}."

  # 3. Overwrite/generate the cronfile with the dynamic schedule
  # Supercronic passes your environment variables automatically.
  echo "${MINUTE} ${HOUR} * * * /usr/local/bin/send_log_to_ha.sh" > /etc/cronfile

  # 5. Hand over execution to Supercronic to keep the add-on running
  bashio::log.info "Starting Supercronic daemon..."
  exec supercronic /etc/cronfile
else
  bashio::log.info "Analysis complete. Stopping add-on container gracefully."
  exit 0 # <-- This cleanly shuts down the container and tells HA UI it is "Stopped"
fi

