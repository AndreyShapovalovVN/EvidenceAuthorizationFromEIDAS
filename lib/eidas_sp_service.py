"""Simple Protocol (guide §12) integration: SP -> Specific Connector -> SP.

Flow implemented here (mirrors the id.gov.ua/ICEI integration already in
this codebase, see lib/ICEI.py + main.py icei_start/icei_callback):

1. `build_auth_request()` builds a SimpleRequest (§12.2) for a given
   message_id.
2. main.py stores {request.id -> message_id} in Redis and renders an
   auto-submitting HTML form (templates/eidas_redirect.html) that POSTs
   the base64-encoded SimpleRequest to the Specific Connector.
3. The citizen authenticates at their national IdP; the Specific
   Connector eventually POSTs a SimpleResponse (§12.4) back to our own
   `serviceUrl` (the /auth/eidas/callback route).
4. `parse_response()` decodes/validates/parses that payload; main.py looks
   up the original message_id via `inresponse_to`, then persists the
   person via PersonRequestService.save_identified_person_request.

WIRE FORMAT (confirmed from a captured request/response against a real
Specific Connector - not just the guide's §12 JSON schema):
  * POST application/x-www-form-urlencoded to the Specific Connector's
    `/SpecificConnector/ServiceProvider` path.
  * The request JSON is base64-encoded and sent in a field named
    "SMSSPRequest" (not "SimpleRequest").
  * A second hidden field "sendmethods" = "POST" is sent alongside it.
  * By symmetry, the SimpleResponse comes back base64-encoded in a field
    named "SMSSPResponse" - this half is not yet confirmed against a real
    capture, so `parse_response()` also transparently accepts a plain
    (non-base64) JSON body for safety.
"""

import base64
import binascii
import os
from dataclasses import dataclass

from Models.eIDAS_SP_Request import (
    Attribute,
    AuthenticationRequest,
    RequestedAuthenticationContext,
)
from Models.eIDAS_SP_Response import SimpleResponse, SimpleResponseError

# Destination Specific Connector endpoint that receives the SimpleRequest.
# Corresponds to `specific.connector.request.url` in specificConnector.xml
# (guide §6, Table 7). Set this to your real cluster's connector URL, e.g.
# "https://connector.eidas.k8s/SpecificConnector/ServiceProvider".
EIDAS_SPECIFIC_CONNECTOR_URL = os.getenv(
    "EIDAS_SPECIFIC_CONNECTOR_URL",
    "https://connector.eidas.k8s/SpecificConnector/ServiceProvider",
)

EIDAS_SP_PROVIDER_NAME = os.getenv("EIDAS_SP_PROVIDER_NAME", "eIDAS")
EIDAS_SP_REQUESTER_ID = os.getenv("EIDAS_SP_REQUESTER_ID", "eIDAS")
EIDAS_SP_CITIZEN_COUNTRY = os.getenv("EIDAS_SP_CITIZEN_COUNTRY", "UA")
EIDAS_SP_LOA = os.getenv("EIDAS_SP_LEVEL_OF_ASSURANCE", "high")
EIDAS_SP_TYPE = os.getenv("EIDAS_SP_TYPE", "private")

# eIDAS minimum dataset requested from the citizen. Keep in sync with
# Models/eIDAS_SP_Response.py's `_ALIASES`.
DEFAULT_ATTRIBUTES = ("FirstName", "FamilyName", "DateOfBirth", "PersonIdentifier", "Gender")

# Field names used on the wire for the auto-submit form POST, confirmed
# from a real captured request/response (see module docstring).
SIMPLE_REQUEST_FIELD = "SMSSPRequest"
SIMPLE_RESPONSE_FIELD = "SMSSPResponse"
SEND_METHOD_FIELD = "sendmethods"
SEND_METHOD_VALUE = "POST"


class EidasSpConfigError(RuntimeError):
    pass


@dataclass
class EidasSpService:
    specific_connector_url: str = EIDAS_SPECIFIC_CONNECTOR_URL
    provider_name: str = EIDAS_SP_PROVIDER_NAME
    requester_id: str = EIDAS_SP_REQUESTER_ID
    citizen_country: str = EIDAS_SP_CITIZEN_COUNTRY
    level_of_assurance: str = EIDAS_SP_LOA
    sp_type: str = EIDAS_SP_TYPE

    def build_auth_request(
        self,
        service_url: str,
        citizen_country: str | None = None,
        required_attributes: tuple[str, ...] = DEFAULT_ATTRIBUTES,
    ) -> AuthenticationRequest:
        """Build the SimpleRequest for a citizen about to be redirected to
        the Specific Connector. `service_url` must be the absolute URL of
        our own callback route (/auth/eidas/callback), so the Node knows
        where to send the SimpleResponse."""
        if not service_url:
            raise EidasSpConfigError("service_url (callback URL) is required")

        context = RequestedAuthenticationContext(
            comparison="minimum",
            context_class=[AuthenticationRequest.loa_to_context_class(self.level_of_assurance)],
        )
        attribute_list = [Attribute(name=name, required=True) for name in required_attributes]

        return AuthenticationRequest(
            attribute_list=attribute_list,
            requested_authentication_context=context,
            citizen_country=citizen_country or self.citizen_country,
            force_authentication=False,
            name_id_policy="transient",
            provider_name=self.provider_name,
            requester_id=self.requester_id,
            service_url=service_url,
            sp_type=self.sp_type,
        )

    @staticmethod
    def encode_request(auth_request: AuthenticationRequest) -> str:
        """base64-encode the SimpleRequest JSON for the SMSSPRequest form field."""
        return base64.b64encode(auth_request.to_json().encode("utf-8")).decode("ascii")

    def parse_response(self, raw_body: str) -> SimpleResponse:
        return SimpleResponse.from_json(self._decode_response_body(raw_body))

    @staticmethod
    def _decode_response_body(raw_body: str) -> str:
        """Decode a base64 SMSSPResponse field; falls back to treating the
        value as plain JSON if it isn't valid base64 (e.g. a raw JSON body
        sent with Content-Type: application/json)."""
        stripped = raw_body.strip()
        if stripped.startswith("{"):
            return raw_body
        return base64.b64decode(stripped, validate=True).decode("utf-8")
