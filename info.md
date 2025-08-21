# Localvolts

## Overview
Localvolts is a Home Assistant integration for customers of the Localvolts electricity retailer in Australia. It exposes real-time price and interval data so automations can make cost-aware decisions.

## Key sensors
- **sensor.costsFlexUp** – import cost per kWh for the rest of the current five-minute interval.
- **sensor.earningsFlexUp** – export price per extra kWh sent to the grid during the current interval.
- **sensor.dataLag** – delay between new data appearing in the Localvolts API and being retrieved.
- **sensor.intervalEnd** – attributes describing the current five-minute interval, including demand and pricing information.

## Configuration
1. Join Localvolts and request an API key.
2. Install this integration via [HACS](https://hacs.xyz) (add this repository as a custom integration) or copy `custom_components/localvolts` into your Home Assistant `custom_components` folder.
3. Provide your API key, partner ID, and NMI ID when prompted.
4. Restart Home Assistant and confirm the sensors above appear.

## Full documentation
- [Full README](README.md)
- [Localvolts API documentation](https://github.com/gurrier/localvolts)
