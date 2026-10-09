# Warmup for Home Assistant

A Home Assistant integration for Warmup underfloor heating thermostats, using
the same cloud API as the MyHeating app. It is a rewrite of
[ha-warmup/warmup](https://github.com/ha-warmup/warmup) with UI setup, energy
sensors and schedule control.

Developed and tested against a **7iE**. The API is shared with the 4iE, 5iE and
6iE, which should work but have not been tested here.

## What you get

For each thermostat:

| Entity | Notes |
| --- | --- |
| Climate | Off, Heat (fixed temperature) and Auto (the thermostat's weekly schedule). Away preset is frost protection. |
| Floor temperature, Air temperature | Both probes, where fitted. |
| Energy today | kWh as counted by Warmup. Works in the Energy dashboard. |
| Cost today | At the tariff set in your Warmup account. |
| Override remaining | Minutes left of a temporary override. |
| Rated power, sensor faults | Diagnostics. |

Changing the temperature in **Heat** mode sets a new fixed temperature.
Changing it in **Auto** mode starts a temporary override, as it does on the
thermostat itself; the length is set in the integration's options (60 minutes
by default).

## Install

1. In HACS, open the menu, choose **Custom repositories**, and add this
   repository with type **Integration**.
2. Install **Warmup** and restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration > Warmup** and sign
   in with your Warmup email and password.

The password is exchanged for an access token and is not stored.

## Energy dashboard

Go to **Settings > Dashboards > Energy > Individual devices** and add the
thermostat's **Energy today** sensor. Warmup's counter restarts each day, and
Home Assistant accounts for that on its own.

Warmup reports this figure in steps of 0.01 kWh, and only readings taken while
Home Assistant is running are recorded.

## Actions

`warmup.set_override` holds a temperature for a while and then resumes:

```yaml
action: warmup.set_override
target:
  entity_id: climate.bathroom
data:
  temperature: 23
  duration: "00:45:00"
```

`warmup.cancel_override` ends it early.

`warmup.set_schedule` replaces the heating periods for the days you list and
leaves the other days alone. Outside the periods the thermostat holds its
setback temperature.

```yaml
action: warmup.set_schedule
target:
  entity_id: climate.bathroom
data:
  schedule:
    saturday:
      - start: "07:30"
        end: "09:30"
        temperature: 21
    sunday:
      - start: "07:30"
        end: "09:30"
        temperature: 21
```

The current schedule is on the climate entity's `schedule` attribute.

## Limitations

- Cloud polling, once a minute. Warmup has no local API.
- Whether the floor is heating is worked out from the target and floor
  temperatures, because the 7iE does not report its relay state live.
- Day names assume Warmup's day 0 is Monday. This has not been confirmed, so
  check a day in the app after your first schedule change.
- Holidays and geofencing are shown if set in the app but cannot be changed
  from Home Assistant.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```

`scripts/probe.py` prints what the API returns for the account in `.env`
(`WARMUP_USER`, `WARMUP_PASSWORD`).
