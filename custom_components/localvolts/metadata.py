"""What Localvolts know about the site: network, tariff, meter provider.

This comes from the v2 API's /customer/metadata call - the one v2 call the
integration makes. Interval prices stay on v1, which remains supported, and
nothing here is required for them: if this call fails the prices carry on
and the site sensor simply reports unavailable.

The API returns one record per circuit (Import, Export, CLoad, ...), each
carrying the site-level facts again. Site-level values are taken from the
first record; tariffs are kept per circuit, because they differ - an import
tariff and a feed-in tariff are different things.

This module parses only, so it can be tested without Home Assistant.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

# Tariffs and networks change rarely, but a long-running instance would
# otherwise describe the site as it was at the last restart.
REFRESH_INTERVAL = datetime.timedelta(hours=24)


@dataclass(frozen=True)
class Circuit:
    """One metered circuit at the site."""

    circuit: str
    suffix: str | None
    tariff: str | None

    @classmethod
    def from_record(cls, item: dict[str, Any]) -> Circuit | None:
        circuit = _text(item.get("Circuit"))
        if circuit is None:
            return None
        return cls(circuit, _text(item.get("Suffix")), _text(item.get("Tariff")))


@dataclass(frozen=True)
class SiteInfo:
    """The site as the API describes it."""

    region: str | None
    jurisdiction: str | None
    lnsp: str | None
    dlf: str | None
    tni: str | None
    mdp: str | None
    read_type: str | None
    joined: str | None
    circuits: tuple[Circuit, ...]

    @property
    def import_circuit(self) -> Circuit | None:
        """The main load circuit, or whichever comes first if none is named so."""
        for circuit in self.circuits:
            if circuit.circuit.lower() == "import":
                return circuit
        return self.circuits[0] if self.circuits else None

    @property
    def import_tariff(self) -> str | None:
        circuit = self.import_circuit
        return circuit.tariff if circuit else None

    @property
    def export_circuit(self) -> Circuit | None:
        """The feed-in circuit, if the site has one. No guessing: a site with
        no export circuit has no export tariff, and saying so is the answer."""
        for circuit in self.circuits:
            if circuit.circuit.lower() == "export":
                return circuit
        return None

    @property
    def export_tariff(self) -> str | None:
        circuit = self.export_circuit
        return circuit.tariff if circuit else None

    @property
    def model(self) -> str | None:
        """Network and tariff, as the device's model - "Ausgrid EA116"."""
        parts = [p for p in (self.lnsp, self.import_tariff) if p]
        return " ".join(parts) or None

    def as_attributes(self) -> dict[str, Any]:
        """Everything, for the site sensor's attributes."""
        return {
            "region": self.region,
            "jurisdiction": self.jurisdiction,
            "network": self.lnsp,
            "dlf": self.dlf,
            "tni": self.tni,
            "meter_data_provider": self.mdp,
            "read_type": self.read_type,
            "joined": self.joined,
            "circuits": [
                {"circuit": c.circuit, "suffix": c.suffix, "tariff": c.tariff}
                for c in self.circuits
            ],
        }


def _text(value: Any) -> str | None:
    """A non-empty string, or None - the API leaves unknowns blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_metadata(payload: Any) -> SiteInfo | None:
    """Build a SiteInfo from the API's response, or None if it isn't one."""
    if not isinstance(payload, list):
        return None
    records = [item for item in payload if isinstance(item, dict)]
    circuits = tuple(c for c in map(Circuit.from_record, records) if c is not None)
    if not circuits:
        return None
    first = records[0]
    return SiteInfo(
        region=_text(first.get("Region")),
        jurisdiction=_text(first.get("Jurisdiction")),
        lnsp=_text(first.get("LNSP")),
        dlf=_text(first.get("DLF")),
        tni=_text(first.get("TNI")),
        mdp=_text(first.get("MDP")),
        read_type=_text(first.get("ReadType")),
        joined=_text(first.get("LastJoin")),
        circuits=circuits,
    )
