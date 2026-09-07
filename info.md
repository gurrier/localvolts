# Localvolts

Home Assistant integration for customers of Localvolts, the Australian electricity retailer with 5-minute wholesale pricing.

It exposes what a kilowatt-hour costs you right now, what you'd earn exporting one, and a 24-hour forecast of both - so your automations can decide when to run appliances, charge a battery, or export to the grid.

☕ If this integration's useful to you, [buy me a coffee](https://ko-fi.com/gurrier).

## Before you start

You need a Localvolts account. Your **API key** and **Partner ID** are both on the Localvolts website under **My Profile → API Key**.

You don't need to look up your NMI - the integration finds it for you.

## Installing

Download it here in HACS, then restart Home Assistant.

## Setting it up

Go to **Settings → Devices & Services → Add Integration** and search for Localvolts, then enter your API key and Partner ID. That's all you enter - the integration asks Localvolts which NMIs are registered to your account, and either selects the only one automatically or lets you choose if you have several sites.

## The sensors

- **sensor.costsflexup** – marginal import cost per kWh for the rest of the current 5-minute interval, in $/kWh.
- **sensor.earningsflexup** – export price per additional kWh sent to the grid during the current interval, in $/kWh.
- **sensor.forecasted_costs_flex_up** – cost of the next 5-minute interval in c/kWh, plus a `forecast` attribute covering the next 24 hours at 5-minute resolution.
- **sensor.datalag** – how far into the interval Localvolts published the data, in seconds.
- **sensor.intervalend** – every field the Localvolts API returned for the current interval, as attributes.

## More

- [README - template examples, charting, and EMHASS](https://github.com/gurrier/localvolts#readme)
- [Report an issue](https://github.com/gurrier/localvolts/issues)
- [Localvolts API guide](https://localvolts.com/localvolts-api/)
