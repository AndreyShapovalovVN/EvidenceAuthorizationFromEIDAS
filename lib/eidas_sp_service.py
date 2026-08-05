import os

from Models.eIDAS_SP_Request import (
    Attribute,
    AuthenticationRequest,
    RequestedAuthenticationContext,
)
from Models.eIDAS_SP_Response import SimpleResponse, parse_response as parse_eidas_response

EIDAS_SPECIFIC_CONNECTOR_URL = os.getenv(
    "EIDAS_SPECIFIC_CONNECTOR_URL",
    "https://connector.eidas.k8s/SpecificConnector/ServiceProvider",
)

EIDAS_SP_PROVIDER_NAME = os.getenv("EIDAS_SP_PROVIDER_NAME", "DEMO-SP-CA")
EIDAS_SP_REQUESTER_ID = os.getenv("EIDAS_SP_REQUESTER_ID", "https://eidas.example.org/RequesterId_CA")
EIDAS_SP_CITIZEN_COUNTRY = os.getenv("EIDAS_SP_CITIZEN_COUNTRY", "CA")
EIDAS_SP_LOA = os.getenv("EIDAS_SP_LEVEL_OF_ASSURANCE") or os.getenv("EIDAS_SP_LOA", "A")
EIDAS_SP_TYPE = os.getenv("EIDAS_SP_TYPE", "public")
EIDAS_SP_ID_POLICY = os.getenv("EIDAS_SP_ID_POLICY", "unspecified")
_public_base_url = os.getenv("AUTH_URL")
EIDAS_SP_CALLBACK_URL = os.getenv("EIDAS_SP_CALLBACK_URL") or (
    f"{_public_base_url.rstrip('/')}/eidas/callback"
    if _public_base_url
    else "http://localhost:8000/auth/eidas/callback"
)

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
        _name_= "authentication_request",
        attribute_list=attribute_list,
        requested_authentication_context=context,
        citizen_country=EIDAS_SP_CITIZEN_COUNTRY,
        force_authentication=True,
        provider_name=EIDAS_SP_PROVIDER_NAME,
        requester_id=EIDAS_SP_REQUESTER_ID,
        serviceUrl=EIDAS_SP_CALLBACK_URL,
        sp_type=EIDAS_SP_TYPE,
        name_id_policy=EIDAS_SP_ID_POLICY,
    )
    return attr_request


def parse_response(raw_body: str) -> SimpleResponse:
    return parse_eidas_response(raw_body)
