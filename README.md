# localvolts_hass
An integration for Home Assistant for customers of Localvolts electricity retailer in Australia

The key sensor exposed is the current cost of electricity FOR YOU per kWh until the end of the current 5 minute interval.
It's essentially the marginal cost of electricity for you and incldues loss factors and network fees involved in increasing your consumption by 1kW now.
Of course, this only lasts until then end of the 5 minute interval, during which you would only have pulled 1kW for 5 minutes = 1/12 kWh = 0.083kWh

To use this integration in Home Assistant, it is necessary to join Localvolts as a customer and request an API key using this form
https://localvolts.com/localvolts-api/

Then in homeassistant under the custom_components fodler, create a folder called "localvolts" and copy all of the files here into that folder.
__init__.py
manifest.json
sensor.py

Edit the file /homeassistant/configuration.yaml

Insert the lines below using your own values for each of the three entries

localvolts:
  api_key: "abc123abc123abc123abc123abc123ab"
  partner_id: "12345"
  nmi_id: "1234567890" #Ignore trailing checksum digit on Localvolts bill and dashboard


You may need to restart Home Asistant to get it working.
Look for a new sensor named "sensor.costsFlexUp"

You can create actions that orchestrate your smart appliances now knowing what electricity cost you will incur with Localvolts
