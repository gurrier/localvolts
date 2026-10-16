"""Constants for the Localvolts integration."""

DOMAIN = "localvolts"

CONF_API_KEY = "api_key"
CONF_PARTNER_ID = "partner_id"
CONF_NMI_ID = "nmi_id"

# The API quotes prices in c/kWh; the sensors publish them in $/kWh, rounded
# to a tenth of a cent. The statistics repair rebuilds hours from the same raw
# records, so it must scale and round in exactly one place - this one - or a
# repaired hour and a live one could disagree about what the price was.
MONETARY_CONVERSION_FACTOR = 100
PRICE_DECIMALS = 3


def to_dollars(raw) -> float:
    """Convert an API price in c/kWh to the $/kWh value the sensors publish.

    Raises TypeError or ValueError for anything that isn't numeric - the API
    is inconsistent about types and documents "N/A" for some rate fields.
    """
    return round(float(raw) / MONETARY_CONVERSION_FACTOR, PRICE_DECIMALS)
