# Examples

The entity IDs below are the long-standing ones (`sensor.costsflexup` and so on). If yours are of the form `sensor.localvolts_<nmi>_costsflexup`, substitute them - they're listed on the device page.

## Knowing when a demand window is open

Two ways, depending on the question.

**"Is the current interval inside my tariff's demand window?"** - the `demandInterval` attribute on `sensor.intervalend` is 1 inside the window and 0 outside, whether or not this month's peak is being tracked:

```yaml
template:
  - binary_sensor:
      - name: "In Demand Interval"
        unique_id: "demand_interval"
        state: >
          {{ state_attr('sensor.intervalend', 'demandInterval') | int == 1 }}
        icon: mdi:clock
```

**"Would more load right now cost me a demand charge?"** - that is what `Demand flex up` answers directly. It is 0 whenever the answer is no, including in months the tariff doesn't track, so `states('sensor.localvolts_<nmi>_demand_flex_up') | float(0) > 0` is the condition.

## The true cost of one more kilowatt

The energy price (`costsFlexUp`, $/kWh) and the demand cost (`Demand flex up`, c/kW) are different kinds of cost in different units, and Localvolts deliberately publish them separately. For one extra kW during one 5-minute interval:

- energy: `costsFlexUp` × 1/12 kWh
- demand: `flexDemandUp` × 1 kW

Dividing through by the 1/12 kWh gives an effective price of adding load now, in the price sensor's unit:

```yaml
template:
  - sensor:
      - name: "Effective import price"
        unique_id: "effective_import_price"
        unit_of_measurement: "$/kWh"
        state_class: measurement
        state: >
          {% set e = states('sensor.costsflexup') | float(none) %}
          {% set d = states('sensor.localvolts_<nmi>_demand_flex_up') | float(none) %}
          {{ (e + 0.12 * d) | round(3) if e is not none and d is not none else none }}
        availability: >
          {{ has_value('sensor.costsflexup') and has_value('sensor.localvolts_<nmi>_demand_flex_up') }}
```

The `0.12` converts c/kW per interval to $/kWh (×12 intervals per hour, ÷100 cents). It is exact for "should this one interval carry an extra kW". It overstates for a sustained addition: the demand cost is paid once when the peak is set, not again for every interval held at that level, and the API reasons from yesterday's settled peak, so read it as the cost of the first interval at a new level rather than summing it over an hour.

## Being told when prices stop arriving

The sensors going `unavailable` is itself the signal that no fresh interval has arrived. These two automations tell you about an outage while it is happening. Replace `notify.mobile_app_your_phone` with your own notify service.

```yaml
automation:
  - alias: NOTIFY Localvolts prices stalled
    description: costsflexup has been unavailable for 5 minutes, meaning no settled interval has arrived
    triggers:
      - trigger: state
        entity_id: sensor.costsflexup
        to: unavailable
        for: "00:05:00"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: >-
            Localvolts prices stalled: no settled interval since
            {{ (as_timestamp(trigger.to_state.last_changed) - 90) | timestamp_custom('%H:%M', true) }},
            about {{ ((as_timestamp(now()) - as_timestamp(trigger.to_state.last_changed) + 90) / 60) | round | int }}
            minutes ago. The integration logs the detail as a warning.
    mode: single

  - alias: NOTIFY Localvolts prices recovered
    description: costsflexup is available again after an outage long enough to have alerted
    triggers:
      - trigger: state
        entity_id: sensor.costsflexup
        from: unavailable
    conditions:
      - condition: template
        value_template: >-
          {{ trigger.to_state.state not in ['unknown', 'unavailable']
             and (as_timestamp(trigger.to_state.last_changed)
                  - as_timestamp(trigger.from_state.last_changed)) >= 300 }}
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: >-
            {% set out = as_timestamp(trigger.to_state.last_changed) - as_timestamp(trigger.from_state.last_changed) %}
            {%- set gap = out + 90 %}
            Localvolts prices are back at {{ trigger.to_state.state }} $/kWh.
            Unavailable for {{ (out / 60) | round(1) }} minutes; no settled interval for
            {{ (gap / 60) | round(1) }} minutes, since
            {{ (as_timestamp(trigger.from_state.last_changed) - 90) | timestamp_custom('%H:%M', true) }}.
    mode: single
```

The five-minute thresholds keep the occasional late interval off your phone: the first automation needs five continuous minutes, and the second only reports recoveries from outages at least that long. The recovery message gives two durations because they differ - the time the sensors were unavailable, and the total time without a settled interval, which is 90 seconds longer.

One caveat: the recovery automation triggers on any change out of `unavailable`, which includes Home Assistant restarting. After a restart longer than five minutes you'll get a recovery notification with the downtime as its duration.

## Highest cost and earnings in the next 24 hours

The forecast list is also handy for looking ahead - for example, the highest import cost and export earning in the next 24 hours, and when:

```yaml
template:
  - sensor:
      - name: "Max Forecast Cost Flex Up"
        unique_id: "max_forecast_cost_flex_up"
        unit_of_measurement: "c/kWh"
        state: >
          {% set forecast = state_attr('sensor.forecasted_costs_flex_up', 'forecast') %}
          {{ (forecast | map(attribute='costsFlexUp') | max | round(3)) if forecast else 0 }}
        attributes:
          at: >
            {% set forecast = state_attr('sensor.forecasted_costs_flex_up', 'forecast') %}
            {{ (forecast | sort(attribute='costsFlexUp') | last).start_time if forecast else None }}

      - name: "Max Forecast Earnings Flex Up"
        unique_id: "max_forecast_earnings_flex_up"
        unit_of_measurement: "c/kWh"
        state: >
          {% set forecast = state_attr('sensor.forecasted_costs_flex_up', 'forecast') %}
          {{ (forecast | map(attribute='earningsFlexUp') | max | round(3)) if forecast else 0 }}
        attributes:
          at: >
            {% set forecast = state_attr('sensor.forecasted_costs_flex_up', 'forecast') %}
            {{ (forecast | sort(attribute='earningsFlexUp') | last).start_time if forecast else None }}
```

The chart and EMHASS examples are in the [README](../README.md#examples).
