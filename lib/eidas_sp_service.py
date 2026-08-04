import base64
import os

from Models.eIDAS_SP_Request import (
    Attribute,
    AuthenticationRequest,
    RequestedAuthenticationContext,
)
from Models.eIDAS_SP_Response import parse_response as parse_eidas_response

EIDAS_SPECIFIC_CONNECTOR_URL = os.getenv(
    "EIDAS_SPECIFIC_CONNECTOR_URL",
    "https://connector.eidas.k8s/SpecificConnector/ServiceProvider",
)

EIDAS_SP_PROVIDER_NAME = os.getenv("EIDAS_SP_PROVIDER_NAME", "eIDAS")
EIDAS_SP_REQUESTER_ID = os.getenv("EIDAS_SP_REQUESTER_ID", "eIDAS")
EIDAS_SP_CITIZEN_COUNTRY = os.getenv("EIDAS_SP_CITIZEN_COUNTRY", "UA")
EIDAS_SP_LOA = os.getenv("EIDAS_SP_LEVEL_OF_ASSURANCE", "high")
EIDAS_SP_TYPE = os.getenv("EIDAS_SP_TYPE", "private")
EIDAS_SP_ID_POLICY = os.getenv("EIDAS_SP_ID_POLICY", "unspecified")

DEFAULT_ATTRIBUTES = ("FirstName", "FamilyName", "DateOfBirth", "PersonIdentifier")

SIMPLE_REQUEST_FIELD = "SMSSPRequest"
SIMPLE_RESPONSE_FIELD = "SMSSPResponse"
SEND_METHOD_FIELD = "sendmethods"
SEND_METHOD_VALUE = "POST"


def create_request():
    context = RequestedAuthenticationContext(
        comparison="minimum", context_class=[EIDAS_SP_LOA]
    )

    attribute_list = [
        Attribute(name=name, required=True) for name in DEFAULT_ATTRIBUTES
    ]
    attr_request = AuthenticationRequest(
        attribute_list=attribute_list,
        requested_authentication_context=context,
        citizen_country=EIDAS_SP_CITIZEN_COUNTRY,
        force_authentication=True,
        name_id_policy=EIDAS_SP_ID_POLICY,
        provider_name=EIDAS_SP_PROVIDER_NAME,
        requester_id=EIDAS_SP_REQUESTER_ID,
        service_url=EIDAS_SPECIFIC_CONNECTOR_URL,
        sp_type=EIDAS_SP_TYPE,
    )
    return (
        f"{SEND_METHOD_VALUE}\n"
        f"{SIMPLE_REQUEST_FIELD}:\n"
        f"{attr_request.to_base64()}\n"
        f"{SEND_METHOD_FIELD}:\n {SEND_METHOD_VALUE}"
    )

def parse_response(raw_body: str) -> dict:
    return parse_eidas_response(raw_body)