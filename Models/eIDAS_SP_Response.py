"""Parser for the Simple Protocol SimpleResponse (guide §12.3 / §12.4).

The Specific Connector posts this JSON back to our own `serviceUrl`
(see AuthenticationRequest.service_url) once the citizen has been
authenticated at their national IdP.
"""

import json
from dataclasses import dataclass, field
from typing import Any


class SimpleResponseError(ValueError):
    """Raised when a SimpleResponse payload cannot be parsed."""


@dataclass
class SimpleResponseStatus:
    status_code: str
    sub_status_code: str | None = None
    status_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status_code == "success"

    @classmethod
    def from_dict(cls, payload: dict) -> "SimpleResponseStatus":
        if "status_code" not in payload:
            raise SimpleResponseError("SimpleResponse.status.status_code is required")
        return cls(
            status_code=payload["status_code"],
            sub_status_code=payload.get("sub_status_code"),
            status_message=payload.get("status_message"),
        )


@dataclass
class SimpleResponseAttribute:
    name: str
    type: str
    # scalar value for "string"/"date"/"address"; list for "string_list"
    value: Any = None

    @classmethod
    def from_dict(cls, payload: dict) -> "SimpleResponseAttribute":
        attr_type = payload.get("type", "string")
        name = payload["name"]
        if attr_type == "string_list":
            values = payload.get("values", [])
            # Prefer the latin-script rendering when both are present,
            # since that's what plain text form fields expect.
            latin = next((v.get("value") for v in values if v.get("latin_script") is False), None)
            v = values[0].get("value") if len(values) == 1 else None
            value = latin if latin is not None else v
        else:
            value = payload.get("value")
        return cls(name=name, type=attr_type, value=value)


@dataclass
class SimpleResponse:
    version: str
    id: str
    inresponse_to: str
    created_on: str
    issuer: str
    status: SimpleResponseStatus
    authentication_context_class: str | None = None
    client_ip_address: str | None = None
    subject: str | None = None
    name_id_format: str | None = None
    attribute_list: list[SimpleResponseAttribute] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.status.is_success

    @classmethod
    def from_dict(cls, payload: dict) -> "SimpleResponse":
        body = payload.get("response", payload)
        try:
            status = SimpleResponseStatus.from_dict(body["status"])
        except KeyError as exc:
            raise SimpleResponseError("SimpleResponse.status is required") from exc

        for required in ("version", "id", "inresponse_to", "created_on", "issuer"):
            if required not in body:
                raise SimpleResponseError(f"SimpleResponse.{required} is required")

        attributes = [
            SimpleResponseAttribute.from_dict(item)
            for item in body.get("attribute_list", [])
        ]

        return cls(
            version=body["version"],
            id=body["id"],
            inresponse_to=body["inresponse_to"],
            created_on=body["created_on"],
            issuer=body["issuer"],
            status=status,
            authentication_context_class=body.get("authentication_context_class"),
            client_ip_address=body.get("client_ip_address"),
            subject=body.get("subject"),
            name_id_format=body.get("name_id_format"),
            attribute_list=attributes,
        )

    @classmethod
    def from_json(cls, raw: str) -> "SimpleResponse":
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SimpleResponseError("SimpleResponse is not valid JSON") from exc
        return cls.from_dict(payload)

    # -- Convenience accessors -------------------------------------------------

    # eIDAS core minimum dataset friendly names we requested (see
    # eidas_sp_service.DEFAULT_ATTRIBUTES) mapped to a few tolerant aliases,
    # in case the IdP echoes them back in a different casing/style.
    _ALIASES = {
        "first_name": ("firstname",),
        "family_name": ("familyname", "lastname", "last_name"),
        "date_of_birth": ("dateofbirth",),
        "gender": ("gender",),
        "person_identifier": ("personidentifier",),
    }

    def get_attribute(self, canonical_name: str) -> str | None:
        aliases = self._ALIASES.get(canonical_name, ())
        wanted = {canonical_name.replace("_", "").lower(), *aliases}
        for attr in self.attribute_list:
            if attr.name.replace("_", "").lower() in wanted:
                return attr.value
        return None

    def to_person_payload(self) -> dict:
        """Map the response onto the fields expected by
        PersonRequestService.save_identified_person_request (mirrors the
        shape already used by the id.gov.ua/ICEI integration)."""
        identifier = self.get_attribute("person_identifier") or self.subject
        loa_map = {"high": "High", "substantial": "Substantial", "low": "Low"}
        return {
            "first_name": self.get_attribute("first_name"),
            "last_name": self.get_attribute("family_name"),
            "identifier": identifier,
            "date_of_birth": self.get_attribute("date_of_birth"),
            "gender": self.get_attribute("gender"),
            "level_of_assurance": loa_map.get(
                (self.authentication_context_class or "").lower(), "High"
            ),
        }
