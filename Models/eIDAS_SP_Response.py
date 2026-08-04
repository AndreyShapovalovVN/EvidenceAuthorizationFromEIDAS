import base64
import json
from dataclasses import dataclass
from datetime import datetime

from lxml import etree

from Models.base import Base, MainBase


class SimpleResponseError(ValueError):
    """Raised when a SimpleResponse payload cannot be parsed."""


@dataclass
class ResponseStatus(Base):
    status_code: str
    sub_status_code: str | None = None
    status_message: str | None = None

    def get_element(self) -> etree._Element:
        status_element = etree.Element("Status")
        status_code_element = etree.SubElement(status_element, "StatusCode")
        status_code_element.set("Value", self.status_code)

        if self.sub_status_code:
            sub_status_code_element = etree.SubElement(
                status_code_element, "StatusCode"
            )
            sub_status_code_element.set("Value", self.sub_status_code)

        if self.status_message:
            status_message_element = etree.SubElement(status_element, "StatusMessage")
            status_message_element.text = self.status_message

        return status_element


@dataclass
class Attribute(Base):
    value: list[str]
    type: str
    name: str

    def get_element(self) -> etree._Element:
        attribute_element = etree.Element("Attribute")
        attribute_element.set("Name", self.name)
        attribute_element.set("Type", self.type)

        for val in self.value:
            value_element = etree.SubElement(attribute_element, "AttributeValue")
            value_element.text = val

        return attribute_element


@dataclass
class SimpleResponse(MainBase):
    attribute_list: list[Attribute]
    authentication_context_class: str
    created_on: datetime
    id: str
    inresponse_to: str
    issuer: str
    name_id: str
    status: ResponseStatus
    subject: str
    version: str = "1"

    def get_element(self) -> etree._Element:
        response_element = etree.Element("Response")
        response_element.set("ID", self.id)
        response_element.set("InResponseTo", self.inresponse_to)
        response_element.set("Issuer", self.issuer)
        response_element.set("Version", self.version)
        response_element.set("IssueInstant", self.created_on.isoformat())
        response_element.set("NameID", self.name_id)
        response_element.set(
            "AuthenticationContextClass", self.authentication_context_class
        )
        response_element.set("Subject", self.subject)
        response_element.append(self.status.get_element())
        for attr in self.attribute_list:
            response_element.append(attr.get_element())
        return response_element


def parse_response(row_body):
    row = row_body.split("\n")
    if len(row) < 2:
        raise ValueError("Invalid response format")
    body = json.loads(base64.b64decode(row[-1].encode("utf-8")).decode("utf-8"))
    response = body.get("response", {})

    al = [
        Attribute(
            value=v.get("value", []), type=v.get("type", ""), name=v.get("name", "")
        )
        for v in response.get("attribute_list", [])
    ]
    status = ResponseStatus(
        status_code=response.get("status", {}).get("status_code", ""),
        sub_status_code=response.get("status", {}).get("sub_status_code", ""),
        status_message=response.get("status", {}).get("status_message", ""),
    )

    return SimpleResponse(
        attribute_list=al,
        authentication_context_class=response.get("authentication_context_class", ""),
        created_on=datetime.fromisoformat(response.get("created_on", "")),
        id=response.get("id", ""),
        inresponse_to=response.get("inresponse_to", ""),
        issuer=response.get("issuer", ""),
        name_id=response.get("name_id", ""),
        status=status,
        subject=response.get("subject", ""),
        version=response.get("version", "1"),
    )
