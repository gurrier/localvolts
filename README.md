# localvolts
An integration for Home Assistant for customers of Localvolts electricity retailer in Australia

The key sensor exposed, costsFlexUp, is the current cost of electricity FOR YOU per kWh until the end of the current 5 minute interval.
It's essentially the marginal cost of electricity for you and includes loss factors and network fees associated with increasing your consumption by 1kW right now.
Of course, this only lasts until the end of the 5 minute interval, during which you would only have pulled that extra 1kW for 5 minutes which is a total energy of 1/12 kWh = 0.083kWh

To use this integration in Home Assistant, it is necessary to join Localvolts as a customer and request an API key using this form
https://localvolts.com/localvolts-api/

Then in Home Assistant, copy the localvolts subfolder of custom_components in this repository into your existing Home Assistant's custom_components folder.

Next edit the file `/homeassistant/configuration.yaml` and insert the lines below using your own values for each of the three entries
```
localvolts:
  api_key: "abc123abc123abc123abc123abc123ab"
  partner_id: "12345"
  nmi_id: "1234567890" #Ignore trailing checksum digit on Localvolts bill and dashboard
```

You may need to restart Home Assistant to get it working.
Look for a new sensor named "sensor.costsFlexUp" in Home Assistant to verify it worked.

Now you can create actions that orchestrate your smart appliances based on what electricity cost you will incur with Localvolts
