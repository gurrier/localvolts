# Localvolts
An integration for Home Assistant for customers of Localvolts electricity retailer in Australia

The integration exposes three sensors...

1) costsFlexUp is the current IMPORT cost of electricity FOR YOU per kWh until the end of the current 5 minute interval.
It's essentially the marginal cost of electricity for you and includes loss factors and network fees associated with increasing your consumption by 1kW right now.
Of course, this only lasts until the end of the 5 minute interval, during which you would only have pulled that extra 1kW for 5 minutes which is a total energy of 1/12 kWh = 0.083kWh

2) earningsFlexUp is the current EXPORT price of electricity FOR YOU per additional kWh exported until the end of the current 5 minute interval.

3) datalag which is the duration within the current 5 min interval before new data was discovered with the Localvolts API.  This is usually (hopefully) within 30 seconds and can be as low as 15 seconds.

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
