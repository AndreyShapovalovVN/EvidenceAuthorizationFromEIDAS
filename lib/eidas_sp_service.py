"""Simple Protocol (guide §12) integration: SP -> Specific Connector -> SP.

Flow implemented here (mirrors the id.gov.ua/ICEI integration already in
this codebase, see lib/ICEI.py + main.py icei_start/icei_callback):

1. `build_auth_request()` builds a SimpleRequest (§12.2) for a given
   message_id.
2. main.py stores {request.id -> message_id} in Redis and renders an
   auto-submitting HTML form (templates/eidas_redirect.html) that POSTs
   the SimpleRequest JSON to the Specific Connector.
3. The citizen authenticates at their national IdP; the Specific
   Connector eventually POSTs a SimpleResponse (§12.4) back to our own
   `serviceUrl` (the /auth/eidas/callback route).
4. `parse_response()` validates/parses that payload; main.py looks up the
   original message_id via `inresponse_to`, then persists the person via
   PersonRequestService.save_identified_person_request.

ASSUMPTIONS (please verify against your actual Specific Connector demo
deployment - the guide's §12 only documents the JSON payload shape, not
the transport):
  * The SimpleRequest is delivered via an HTML form POST (field name
    "SimpleRequest") to EIDAS_SPECIFIC_CONNECTOR_URL, analogous to the
    SAML POST binding used by the "real" AuthnRequest.
  * The Specific Connector POSTs the SimpleResponse back the same way
    (field name "SimpleResponse", or a raw JSON body) to our serviceUrl.
"""

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
# (guide §6, Table 7). Defaults to the value already present in this repo's
# eidas_autofill_service.py prototype.
EIDAS_SPECIFIC_CONNECTOR_URL = os.getenv(
    "EIDAS_SPECIFIC_CONNECTOR_URL", "https://e-id.gov.ua/eidas/sp/saml2/post"
)

EIDAS_SP_PROVIDER_NAME = os.getenv("EIDAS_SP_PROVIDER_NAME", "eIDAS")
EIDAS_SP_REQUESTER_ID = os.getenv("EIDAS_SP_REQUESTER_ID", "eIDAS")
EIDAS_SP_CITIZEN_COUNTRY = os.getenv("EIDAS_SP_CITIZEN_COUNTRY", "UA")
EIDAS_SP_LOA = os.getenv("EIDAS_SP_LEVEL_OF_ASSURANCE", "high")
EIDAS_SP_TYPE = os.getenv("EIDAS_SP_TYPE", "private")

# eIDAS minimum dataset requested from the citizen. Keep in sync with
# Models/eIDAS_SP_Response.py's `_ALIASES`.
DEFAULT_ATTRIBUTES = ("FirstName", "FamilyName", "DateOfBirth", "PersonIdentifier", "Gender")

# Field names used on the wire for the auto-submit form POST (see module
# docstring - unconfirmed against the real Specific Connector demo source).
SIMPLE_REQUEST_FIELD = "SimpleRequest"
SIMPLE_RESPONSE_FIELD = "SimpleResponse"


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

    def parse_response(self, raw_body: str) -> SimpleResponse:
        try:
            return SimpleResponse.from_json(raw_body)
        except SimpleResponseError:
            raise
