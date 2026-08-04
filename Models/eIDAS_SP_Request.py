import base64
import datetime
import json
import uuid
from dataclasses import dataclass, field

from lxml import etree

from Models.base import Base, MainBase

# --- Simple Protocol (guide §12) constants ------------------------------
#
# §12.1 / §12.2: the LevelOfAssurance requested by the SP is carried in
# "requested_authentication_context.context_class" using the *notified*
# short tokens "A".."E", which the Node/Connector map internally to the
# full eIDAS LoA URIs:
#   "A" | "B" -> http://eidas.europa.eu/LoA/low
#   "C" | "D" -> http://eidas.europa.eu/LoA/substantial
#   "E"       -> http://eidas.europa.eu/LoA/high
LOA_TO_CONTEXT_CLASS = {
    "low": "A",
    "substantial": "C",
    "high": "E",
}

# §12.2 mapping table: name_id_policy is sent as the *short* value
# ("persistent" | "transient" | "unspecified") in the SimpleRequest.
# The Node/Connector perform the mapping to the full SAML NameIDFormat
# URNs themselves - the SP must NOT send the URN directly.
VALID_NAME_ID_POLICIES = {"persistent", "transient", "unspecified"}


@dataclass
class Attribute(Base):
    name: str
    type: str = "requested_attribute"
    required: bool = True

    def get_element(self) -> etree._Element:
        atritbute_element = etree.Element("Attribute")
        atritbute_element.set("Name", self.name)
        atritbute_element.set("NameFormat", "urn:oasis:names:tc:SAML:2.0:attrname-format:uri")

        return atritbute_element

    def to_dict(self) -> dict:
        """Serialize per §12.2 SimpleRequest 'attribute_list' entry."""
        return {
            "type": self.type,
            "name": self.name,
            "required": self.required,
        }


@dataclass
class RequestedAuthenticationContext(Base):
    comparison: str
    context_class: list[str]
    non_notified_context_class: list[str] = field(default_factory=list)

    def get_element(self) -> etree._Element:
        context_element = etree.Element("RequestedAuthenticationContext")
        context_element.set("Comparison", self.comparison)
        context_element.set("ContextClassRef", self.context_class)
        if self.non_notified_context_class:
            context_element.set("NonNotifiedContextClassRef", self.non_notified_context_class)
            context_element.set("AllowCreate", "true")
            context_element.set("RequestType", "true")

        return context_element

    def to_dict(self) -> dict:
        payload = {
            "comparison": self.comparison,
            "context_class": self.context_class,
        }
        if self.non_notified_context_class:
            payload["non_notified_context_class"] = self.non_notified_context_class
        return payload


@dataclass
class AuthenticationRequest(MainBase):
    attribute_list: list[Attribute]
    requested_authentication_context: RequestedAuthenticationContext
    citizen_country: str
    force_authentication: bool
    name_id_policy: str
    provider_name: str
    requester_id: str
    service_url: str
    sp_type: str = "private"
    version: str = "1"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_on: str = field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC).isoformat()
    )

    def __post_init__(self) -> None:
        if self.name_id_policy not in VALID_NAME_ID_POLICIES:
            raise ValueError(
                f"name_id_policy must be one of {sorted(VALID_NAME_ID_POLICIES)}, "
                f"got {self.name_id_policy!r} (send the short value, not the SAML URN - "
                "the Node/Connector map it internally, per guide §12.2)"
            )

    def get_element(self) -> etree._Element:
        request_element = etree.Element("AuthenticationRequest")
        request_element.set("ID", self.id)
        request_element.set("Version", self.version)
        request_element.set("IssueInstant", self.created_on)
        request_element.set("ProviderName", self.provider_name)
        request_element.set("AssertionConsumerServiceURL", self.service_url)
        request_element.set("ForceAuthn", str(self.force_authentication).lower())
        request_element.set("IsPassive", "false")
        request_element.append(self.requested_authentication_context.get_element())
        for attr in self.attribute_list:
            request_element.append(attr.get_element())

        return request_element

    def to_dict(self) -> dict:
        """Serialize to the SimpleRequest JSON envelope shown in guide §12.2."""
        return {
            "authentication_request": {
                "attribute_list": [attr.to_dict() for attr in self.attribute_list],
                "requested_authentication_context": self.requested_authentication_context.to_dict(),
                "citizen_country": self.citizen_country,
                "created_on": self.created_on,
                "force_authentication": self.force_authentication,
                "id": self.id,
                "name_id_policy": self.name_id_policy,
                "provider_name": self.provider_name,
                "requester_id": self.requester_id,
                # NB: the field is "serviceUrl" (camelCase) on the wire per
                # the §12.2 field-mapping table, even though every other
                # field is snake_case.
                "serviceUrl": self.service_url,
                "sp_type": self.sp_type,
                "version": self.version,
            }
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_base64(self) -> str:
        return base64.b64encode(self.to_json().encode("utf-8")).decode("utf-8")

    @classmethod
    def loa_to_context_class(cls, level_of_assurance: str) -> str:
        """Map a UI-facing LoA string (Low/Substantial/High) to the notified
        context_class token expected by the SimpleRequest (§12.1 table)."""
        key = (level_of_assurance or "").strip().lower()
        try:
            return LOA_TO_CONTEXT_CLASS[key]
        except KeyError as exc:
            raise ValueError(
                f"Unknown level_of_assurance {level_of_assurance!r}, "
                f"expected one of {sorted(LOA_TO_CONTEXT_CLASS)}"
            ) from exc
