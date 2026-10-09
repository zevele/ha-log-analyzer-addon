<p align="center">
  <img src="log_analyzer_addon/icon.png" alt="Log Analyzer Logo" width="128" height="128">
</p>

# Home Assistant AI Log Analyzer Add-on

A secure, lightweight Home Assistant add-on that gathers system logs, processes them using an external **LiteLLM** proxy engine, and pushes custom-styled markdown analysis reports natively into a local Home Assistant sensor entity.

Designed as an efficient "one-shot" container pipeline to run automatically and self-terminate, ensuring zero idle RAM memory footprint on your host server hardware.

## Features

- **Dynamic Native Entities:** Spawns a custom named sensor entity (e.g., `sensor.homeassistant_log_analyzer`) with multi-line report attributes natively on your dashboard.
- **LiteLLM Network Proxy:** Integrates with any downstream LLM layout (GPT-4o, Claude 3.5, local models) via centralized configuration keys.
- **Nested Advanced Interface:** Keeps standard settings prominent while keeping runtime tweaks tucked cleanly away in an `advanced_settings` configuration box.
- **Zero-RAM Footprint:** Automatically executes its log analysis routines and completely shuts down (`exit 0`) immediately following transmission.

---

## Installation

1. Copy the URL of this GitHub repository.
2. In your Home Assistant dashboard, navigate to **Settings** > **Add-ons** > **Add-on Store** (bottom right).
3. Click the three dots menu in the top-right corner and select **Repositories**.
4. Paste the repository URL into the field, click **Add**, and close the dialog box.
5. Click the three dots menu again and click **Refresh**.
6. Scroll down to find the **Log Analyzer Add-on**, click **Install**, and wait for the compilation to complete.

---

## Configuration settings

### Main Options
- **LiteLLM Server Address (`litellm_address`):** The network address link pointing to your LiteLLM instance (e.g., `http://192.168.1.50:4000`).
- **LiteLLM API Key (`litellm_api_key`):** The server authentication string token password needed by your proxy instance.
- **AI Model Name (`model_name`):** The core identifier string representing the model you wish to engage (e.g., `gpt-4o`).

### Advanced Group Options (`advanced_settings`)
- **Sensor Friendly Name (`sensor_name`):** The clean display label shown on cards. Defaults to `Homeassistant Log Analyzer`.
- **Dry Run Mode (`dry_run`):** Processes logs but avoids spending execution tokens by skipping network LLM requests.
- **Run Analysis on Startup (`run_on_start`):** Forces a log analysis sweep instantly when the add-on process container wakes up.
- **Single Run Execution (`single_run`):** If enabled, runs the analyzer once and terminates the container process context instead of keeping an active daemon loop alive.
- **Daily Execution Time (`scheduled_time`):** Defines the background processing window timeline constraint (HH:MM string regex format).
- **Max Analysis Tokens (`token_count`):** Sets the bounding threshold limit for the context payload size response window.
- **Max Log Lines to Parse (`max_lines`):** Restricts the log sweep size depth to an explicit max count tracking limit.
- **Log History Horizon (`max_hours`):** Limits data collection to historical events falling within this specific trailing hourly window frame.

---

## Automating a Daily Run (Recommended setup)

To save hardware resource memory, configure your add-on parameters to **Single Run Execution: True** and **Run Analysis on Startup: True**. 

Because you are installing from a GitHub repository, Home Assistant will prefix the add-on identifier slug with a unique installation hash (e.g., `abe4d64a_log_analyzer_addon`). 

Go to your Home Assistant engine (**Settings** > **Automations & Scenes**) and use the visual editor to target the add-on, or use this YAML block matching your specific instance name to run the logs check automatically at 2:30 AM every night:

```yaml
alias: Daily AI Log Analysis Timer
description: Triggers the Log Analyzer add-on daily and releases host memory when complete.
triggers:
  - trigger: time
    at: '02:30:00'
actions:
  - data:
      addon: abe4d64a_log_analyzer_addon
    action: hassio.addon_start
mode: single
```
*(Tip: You can easily verify your custom prefix hash slug by clicking on the add-on inside your panel and checking the very end of your web browser's address URL bar).*

---

## Lovelace UI Dashboard Integration

Because the script parses the markdown report string directly into the sensor's `homeassistant` attribute block, you can render your complete analysis report natively on your main control dashboard layout using a standard **Markdown Card**:

````yaml
type: markdown
title: 🤖 AI Log Summary Report
content: >-
  ```text
  {{ state_attr('sensor.homeassistant_log_analyzer', 'homeassistant') }}
  ```
````
*(If you customized the `sensor_name` parameter under advanced settings, adjust `sensor.homeassistant_log_analyzer` to match your resulting entity slug name instead).*

## License

This project is open-source software distributed under the terms of the permissive **MIT License**.
