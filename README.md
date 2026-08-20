# Localvolts
An integration for Home Assistant for customers of Localvolts electricity retailer in Australia

The integration currently exposes five sensors...

1) costsFlexUp is the marginal IMPORT cost of electricity for you, in $/kWh (including loss factors and network fees) - how much extra your bill increases for each additional kWh you import between now and the end of the current 5-minute interval.

Because it's a rate, you need to convert any change in your power draw (kW) into the energy (kWh) it represents before it means anything in dollars. For example, drawing an extra 1kW for the rest of a freshly-started interval is 1kW × 1/12 hour = 0.083 kWh - multiply that by costsFlexUp to get the actual extra cost of that decision.

2) earningsFlexUp is the current EXPORT price of electricity FOR YOU per additional kWh exported until the end of the current 5 minute interval.

3) datalag which is the duration within the current 5 min interval before new data was discovered with the Localvolts API.  This is usually (hopefully) within 30 seconds and can be as low as 15 seconds.

4) intervalEnd contains attributes for all of the data from the Localvolts API for the current 5 minute interval.

5) forecasted_costs_flex_up state reflects the costsFlexUp of the next upcoming 5-minute interval, in c/kWh. The `forecast` attribute is a list covering the next 24 hours, one entry per 5-minute interval, and each entry includes every field the Localvolts API returns for that interval - not just earningsFlexUp/costsFlexUp, but demand, import/export, emissions and quality data too. `forecastcount` gives the total number of entries in the list. One entry, shown in full, looks like this:

```
forecast:
  - NMI: '4103326458'
    intervalDuration: '5'
    intervalDurationUnits: minutes
    intervalEnd: '2026-08-19T06:40:00Z'
    exportsAll: 0
    exportsAllUnits: kWh
    importsAll: 0.235
    importsAllUnits: kWh
    demandMain: 1.41
    demandMainUnits: kW
    demandPeriod: 30
    demandPeriodUnits: minutes
    demandInterval: 1
    earningsAll: 0
    earningsAllUnits: cents
    earningsAllVar: 0
    earningsAllVarUnits: cents
    earningsAllFixed: 0
    earningsAllFixedUnits: cents
    earningsAllVarRate: N/A
    earningsAllVarRateUnits: c/kWh
    earningsFlexUp: 7.48652
    earningsFlexDown: -7.48651605
    earningsFlexUnits: c/kWh
    costsAll: 3.54601201
    costsAllUnits: cents
    costsAllVar: 2.96613215
    costsAllVarUnits: cents
    costsAllFixed: 0.57987986
    costsAllFixedUnits: cents
    costsDemandMain: 39.485
    costsDemandMainUnits: c/kW/Day
    costsDemandRate: 39.485
    costsDemandRateUnits: c/kW/Day
    costsAllVarRate: '12.62183895'
    costsAllVarRateUnits: c/kWh
    costsFlexUp: 12.62184
    costsFlexDown: -12.62183895
    costsFlexUnits: c/kWh
    exportsAllEmissions: 0
    exportsAllEmissionsUnits: g-CO2e
    importsAllEmissions: 166.427
    importsAllEmissionsUnits: g-CO2e
    exportsAllZeroEE: 1
    exportsAllZeroEEUnits: '%'
    importsAllZeroEE: '0.21490000'
    importsAllZeroEEUnits: '%'
    quality: Fcst
    lastUpdate: '2026-08-19 06:31:44'
    duration: 5
    start_time: '2026-08-19T06:35:00+00:00'
    end_time: '2026-08-19T06:40:00+00:00'
  # ...286 more entries, same shape, one per 5-minute interval out to 24 hours

  forecastcount: 287
  unit_of_measurement: c/kWh
  device_class: monetary
  friendly_name: Forecasted Costs Flex Up
```

For example, use the following code in your configuration.yaml to access the attribute for 'DemandInterval' (reflecting whether the current 5-minute interval is within the time window for a Demand Tariff to be active).

```
template:
  - binary_sensor:
      - name: "In Demand Interval"
        unique_id: "demand_interval"
        state: >
          {{ state_attr('sensor.intervalend', 'demandInterval') | int == 1 }}
        icon: mdi:clock
```

The forecast list is also handy for looking ahead rather than just at the current interval - for example, working out the highest import cost and export earning you might see over the next 24 hours, and when:

```
template:
  - sensor:
      - name: "Max Forecast Cost Flex Up"
        unique_id: "max_forecast_cost_flex_up"
        unit_of_measurement: "c/kWh"
        state: >
          {{ state_attr('sensor.forecasted_costs_flex_up', 'forecast')
             | map(attribute='costsFlexUp') | max | round(3) }}
        attributes:
          at: >
            {{ (state_attr('sensor.forecasted_costs_flex_up', 'forecast')
                | sort(attribute='costsFlexUp') | last).start_time }}

      - name: "Max Forecast Earnings Flex Up"
        unique_id: "max_forecast_earnings_flex_up"
        unit_of_measurement: "c/kWh"
        state: >
          {{ state_attr('sensor.forecasted_costs_flex_up', 'forecast')
             | map(attribute='earningsFlexUp') | max | round(3) }}
        attributes:
          at: >
            {{ (state_attr('sensor.forecasted_costs_flex_up', 'forecast')
                | sort(attribute='earningsFlexUp') | last).start_time }}
```

To use this integration in Home Assistant, it is necessary to join Localvolts as a customer https://localvolts.com/register/
and request an API key using this form https://localvolts.com/localvolts-api/

# Using HACS to install the Localvolts Integration

If you already have HACS installed for Home Assistant you can add this integration as a custom repository

In HACS,

1. Click on the 3 dots in the top right corner.
2. Select "Custom repositories"
3. Add the URL to the repository. https://github.com/gurrier/localvolts
4. Select the integration category.
5. Click the "ADD" button.

Now you can browse for and install Localvolts in Home Assistant using HACS

# A setup dialog will appear to allow you to configure the three settings below (no longer necessary to edit configuration.yaml).

```
  api_key: "abc123abc123abc123abc123abc123ab"
  partner_id: "12345"
  nmi_id: "1234567890" #Ignore trailing checksum digit on Localvolts bill and dashboard
```

# Alternatively, use the manual method to get the integration installed in Home Assistant

In Home Assistant, copy the files in this repository into a subfolder of your existing Home Assistant's custom_components folder.

# Restart Home Assistant
In either case, you will need to restart Home Assistant to get the integration working.
Look for the sensors (sensor.costsFlexUp and sensor.earningsFlexUp) in Home Assistant to verify it worked.


Now you can create actions that orchestrate your smart appliances based on what electricity cost you will incur or price you will earn with Localvolts


<!-- HIDDEN until ready on HACS
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=%40gurrier&repository=localvolts&category=integration)
-->
