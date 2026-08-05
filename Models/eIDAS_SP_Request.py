import base64
import datetime
import uuid
from dataclasses import dataclass, field

from lxml import etree

from Models.base import Base, MainBase

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


@dataclass
class RequestedAuthenticationContext(Base):
    comparison: str
    context_class: list[str]
    non_notified_context_class: list[str] = field(default_factory=list)

    def get_element(self) -> etree._Element:
        context_element = etree.Element("RequestedAuthenticationContext")
        context_element.set("Comparison", self.comparison)
        context_element.set("ContextClassRef", ",".join(self.context_class))
        if self.non_notified_context_class:
            context_element.set(
                "NonNotifiedContextClassRef",
                ",".join(self.non_notified_context_class),
            )
            context_element.set("AllowCreate", "true")
            context_element.set("RequestType", "true")

        return context_element


@dataclass
class AuthenticationRequest(MainBase):
    _name_ = "authentication_request"
    attribute_list: list[Attribute] = field(default_factory=list)
    requested_authentication_context: RequestedAuthenticationContext = field(
        default_factory=lambda: RequestedAuthenticationContext(
            comparison="minimum",
            context_class=[],
        )
    )
    citizen_country: str = ""
    force_authentication: bool = False
    provider_name: str = ""
    requester_id: str = ""
    serviceUrl: str = ""
    name_id_policy: str = "unspecified"
    sp_type: str = "private"
    version: str = "1"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_on: str = field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC).isoformat()
    )

    def get_element(self) -> etree._Element:
        request_element = etree.Element("AuthenticationRequest")
        request_element.set("ID", self.id)
        request_element.set("Version", self.version)
        request_element.set("IssueInstant", self.created_on)
        request_element.set("ProviderName", self.provider_name)
        request_element.set("AssertionConsumerServiceURL", self.serviceUrl)
        request_element.set("ForceAuthn", str(self.force_authentication).lower())
        request_element.set("IsPassive", "false")
        request_element.append(self.requested_authentication_context.get_element())
        for attr in self.attribute_list:
            request_element.append(attr.get_element())

        return request_element

    def get_base64(self) -> str:
        return base64.b64encode(self.get_json().encode("utf-8")).decode("utf-8")
