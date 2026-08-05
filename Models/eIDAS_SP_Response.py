import base64
import json
import re
from binascii import Error as BinasciiError
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs

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
    _name_ = "simple_response"
    attribute_list: list[Attribute] = field(default_factory=list)
    authentication_context_class: str = ""
    created_on: datetime = field(default_factory=datetime.now)
    id: str = ""
    inresponse_to: str = ""
    issuer: str = ""
    name_id: str = ""
    status: ResponseStatus = field(default_factory=lambda: ResponseStatus(status_code=""))
    subject: str = ""
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

    @property
    def is_success(self) -> bool:
        code = (self.status.status_code or "").strip().lower()
        if not code:
            return False
        return code == "success" or code.endswith(":success")

    def _attributes_by_name(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for attribute in self.attribute_list:
            key = attribute.name.strip().lower()
            if not key:
                continue
            result[key] = [item for item in attribute.value if item]
        return result

    def to_person_payload(self) -> dict[str, str | None]:
        attrs = self._attributes_by_name()

        def pick(*names: str) -> str | None:
            for name in names:
                values = attrs.get(name.strip().lower())
                if values:
                    return values[0]
            return None

        first_name = pick("FirstName", "GivenName", "CurrentGivenName")
        last_name = pick("FamilyName", "CurrentFamilyName")
        identifier = pick("PersonIdentifier")
        date_of_birth = pick("DateOfBirth")
        gender = pick("Gender")

        missing = [
            name
            for name, value in (
                ("FirstName", first_name),
                ("FamilyName", last_name),
                ("PersonIdentifier", identifier),
            )
            if not value
        ]
        if missing:
            raise SimpleResponseError(
                f"SimpleResponse does not contain required attributes: {', '.join(missing)}"
            )

        return {
            "first_name": first_name,
            "last_name": last_name,
            "identifier": identifier,
            "date_of_birth": date_of_birth,
            "gender": gender,
            "level_of_assurance": self.authentication_context_class or "High",
        }


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    clean = value.strip()
    if clean.endswith("Z"):
        clean = f"{clean[:-1]}+00:00"
    try:
        return datetime.fromisoformat(clean)
    except ValueError as exc:
        raise SimpleResponseError(f"Invalid response timestamp: {value}") from exc


def _pick(payload: dict, *keys: str, default=None):
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _coerce_attribute_values(raw_attribute: dict) -> list[str]:
    if "value" in raw_attribute:
        raw_value = raw_attribute["value"]
        if isinstance(raw_value, list):
            return [str(item) for item in raw_value if item not in (None, "")]
        if raw_value in (None, ""):
            return []
        return [str(raw_value)]

    if "values" in raw_attribute:
        values = raw_attribute["values"]
        if not isinstance(values, list):
            return [str(values)]
        result: list[str] = []
        for item in values:
            if isinstance(item, dict):
                value = _pick(item, "value", "Value")
                if value not in (None, ""):
                    result.append(str(value))
            elif item not in (None, ""):
                result.append(str(item))
        return result

    return []


def _load_json_from_raw(raw_body: str) -> dict:
    trimmed = raw_body.strip()
    if not trimmed:
        raise SimpleResponseError("Empty SimpleResponse payload")

    if trimmed.startswith("{"):
        try:
            payload = json.loads(trimmed)
        except json.JSONDecodeError as exc:
            raise SimpleResponseError("SimpleResponse payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SimpleResponseError("SimpleResponse JSON must be an object")
        return payload

    qs = parse_qs(trimmed, keep_blank_values=True)
    smssp_values = qs.get("SMSSPResponse") if qs else None
    if smssp_values:
        trimmed = smssp_values[-1].strip()

    if trimmed.startswith("{"):
        try:
            payload = json.loads(trimmed)
        except json.JSONDecodeError as exc:
            raise SimpleResponseError("SimpleResponse payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SimpleResponseError("SimpleResponse JSON must be an object")
        return payload

    compact = re.sub(r"\s+", "", trimmed)
    try:
        decoded = base64.b64decode(compact, validate=True).decode("utf-8")
    except (BinasciiError, UnicodeDecodeError) as exc:
        raise SimpleResponseError(
            "SimpleResponse is neither JSON nor a valid base64-encoded JSON payload"
        ) from exc

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise SimpleResponseError("Decoded SimpleResponse is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise SimpleResponseError("Decoded SimpleResponse JSON must be an object")
    return payload


def parse_response(raw_body: str) -> SimpleResponse:
    payload = _load_json_from_raw(raw_body)
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        raise SimpleResponseError("SimpleResponse JSON does not contain object response")

    al = [
        Attribute(
            value=_coerce_attribute_values(v),
            type=str(_pick(v, "type", "Type", default="")),
            name=str(_pick(v, "name", "Name", "friendlyName", default="")),
        )
        for v in _pick(response, "attribute_list", "attributes", default=[])
        if isinstance(v, dict)
    ]

    status_raw = _pick(response, "status", "Status", default={})
    if not isinstance(status_raw, dict):
        status_raw = {}
    status = ResponseStatus(
        status_code=str(
            _pick(status_raw, "status_code", "statusCode", "StatusCode", default="")
        ),
        sub_status_code=_pick(
            status_raw,
            "sub_status_code",
            "subStatusCode",
            "SubStatusCode",
            default=None,
        ),
        status_message=_pick(
            status_raw,
            "status_message",
            "statusMessage",
            "StatusMessage",
            default=None,
        ),
    )

    return SimpleResponse(
        attribute_list=al,
        authentication_context_class=str(
            _pick(
                response,
                "authentication_context_class",
                "authenticationContextClass",
                "AuthnContextClassRef",
                default="",
            )
        ),
        created_on=_parse_datetime(
            _pick(response, "created_on", "createdOn", "issueInstant", "IssueInstant")
        ),
        id=str(_pick(response, "id", "ID", default="")),
        inresponse_to=str(
            _pick(response, "inresponse_to", "inResponseTo", "InResponseTo", default="")
        ),
        issuer=str(_pick(response, "issuer", "Issuer", default="")),
        name_id=str(_pick(response, "name_id", "nameId", "NameID", default="")),
        status=status,
        subject=str(_pick(response, "subject", "Subject", default="")),
        version=str(_pick(response, "version", "Version", default="1")),
    )
