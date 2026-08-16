import logging

from fastapi import HTTPException, Request

from lib.PersonRequestService import save_identified_person_request
from lib.preview_keys import PreviewKeys
from Models.eIDAS_SP_Request import (
    Attribute,
    AuthenticationRequest,
    RequestedAuthenticationContext,
)
from Models.eIDAS_SP_Response import (
    SimpleResponse,
    SimpleResponseError,
    parse_response as parse_eidas_response,
)

from oots_lib.import_env import import_env

_logger = logging.getLogger(__name__)

EIDAS_SPECIFIC_CONNECTOR_URL = import_env(
    "EIDAS_SPECIFIC_CONNECTOR_URL",
    "https://connector.eidas.k8s/SpecificConnector/ServiceProvider",
)

EIDAS_SP_PROVIDER_NAME = import_env("EIDAS_SP_PROVIDER_NAME", "DEMO-SP-CA")
EIDAS_SP_REQUESTER_ID = import_env("EIDAS_SP_REQUESTER_ID", "https://eidas.example.org/RequesterId_CA")
EIDAS_SP_CITIZEN_COUNTRY = import_env("EIDAS_SP_CITIZEN_COUNTRY", "CA")
EIDAS_SP_LOA = import_env("EIDAS_SP_LEVEL_OF_ASSURANCE") or import_env("EIDAS_SP_LOA", "A")
EIDAS_SP_TYPE = import_env("EIDAS_SP_TYPE", "public")
EIDAS_SP_ID_POLICY = import_env("EIDAS_SP_ID_POLICY", "unspecified")
EIDAS_SP_PUBLIC_BASE_URL = import_env("EIDAS_SP_PUBLIC_BASE_URL")
EIDAS_SP_CALLBACK_PATH = import_env("EIDAS_SP_CALLBACK_PATH", "/auth/eidas/callback")


def _build_callback_url(public_base_url: str | None = None) -> str:
    if public_base_url:
        return f"{public_base_url.rstrip('/')}{EIDAS_SP_CALLBACK_PATH}"

    auth_url = import_env("AUTH_URL")
    if auth_url:
        return f"{auth_url.rstrip('/').removesuffix('/auth')}{EIDAS_SP_CALLBACK_PATH}"

    return f"http://localhost:8000{EIDAS_SP_CALLBACK_PATH}"


EIDAS_SP_CALLBACK_URL = import_env("EIDAS_SP_CALLBACK_URL") or _build_callback_url(
    EIDAS_SP_PUBLIC_BASE_URL
)

DEFAULT_ATTRIBUTES = ("FirstName", "FamilyName", "DateOfBirth", "PersonIdentifier")

SIMPLE_REQUEST_FIELD = "SMSSPRequest"
SIMPLE_RESPONSE_FIELD = "SMSSPResponse"
SEND_METHOD_FIELD = "sendmethods"
SEND_METHOD_VALUE = "POST"


def create_request():
    _logger.debug(
        "Creating eIDAS SimpleRequest with provider=%s requester_id=%s citizen_country=%s loa=%s callback_url=%s",
        EIDAS_SP_PROVIDER_NAME,
        EIDAS_SP_REQUESTER_ID,
        EIDAS_SP_CITIZEN_COUNTRY,
        EIDAS_SP_LOA,
        EIDAS_SP_CALLBACK_URL,
    )
    context = RequestedAuthenticationContext(
        comparison="minimum", context_class=[EIDAS_SP_LOA]
    )

    attribute_list = [
        Attribute(name=name, required=True) for name in DEFAULT_ATTRIBUTES
    ]
    attribute_names = [getattr(attr, "name", str(attr)) for attr in attribute_list]
    _logger.debug("eIDAS requested attributes: %s", ", ".join(attribute_names))
    attr_request = AuthenticationRequest(
        _name_="authentication_request",
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
    _logger.debug(
        "Built eIDAS SimpleRequest id=%s connector_url=%s",
        attr_request.id,
        EIDAS_SPECIFIC_CONNECTOR_URL,
    )
    return attr_request


async def prepare_eidas_redirect(
    client,
    message_id: str,
    *,
    keys: PreviewKeys | None = None,
) -> dict[str, object]:
    if keys is None:
        keys = PreviewKeys()

    auth_request = create_request()
    state_key = keys.get_eidas_state_key(auth_request.id)
    _logger.debug(
        "Preparing eIDAS redirect for message_id=%s request_id=%s state_key=%s",
        message_id,
        auth_request.id,
        state_key,
    )
    await client.save_to_redis(state_key, {"message_id": message_id})
    _logger.debug(
        "Saved eIDAS state for message_id=%s request_id=%s to redis key=%s",
        message_id,
        auth_request.id,
        state_key,
    )

    return {
        "specific_connector_url": EIDAS_SPECIFIC_CONNECTOR_URL,
        "simple_request_b64": auth_request.get_base64(),
        "send_method_field": SEND_METHOD_FIELD,
        "send_method_value": SEND_METHOD_VALUE,
        "request_id": auth_request.id,
    }


async def read_simple_response_body(request: Request) -> str | None:
    content_type = request.headers.get("content-type", "")
    _logger.debug("Reading eIDAS SimpleResponse with content_type=%s", content_type)
    if "application/json" in content_type:
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8") if body_bytes else None
        _logger.debug(
            "Received eIDAS callback body as JSON, length=%s",
            len(body_bytes or b""),
        )
        return body_text

    form = await request.form()
    form_value = form.get(SIMPLE_RESPONSE_FIELD)
    _logger.debug(
        "Received eIDAS callback form field %s present=%s",
        SIMPLE_RESPONSE_FIELD,
        form_value is not None,
    )
    if form_value is not None and not isinstance(form_value, str):
        raise HTTPException(
            status_code=400,
            detail="SimpleResponse must be a form text field, not a file upload",
        )
    return form_value


def parse_simple_response(raw_body: str | None):
    if not raw_body:
        _logger.debug("eIDAS callback payload is empty")
        raise HTTPException(status_code=400, detail="Missing SimpleResponse payload")
    _logger.debug(
        "Parsing eIDAS SimpleResponse payload, length=%s",
        len(raw_body),
    )
    try:
        parsed = parse_eidas_response(raw_body)
        _logger.debug(
            "Parsed eIDAS SimpleResponse successfully; inresponse_to=%s is_success=%s",
            getattr(parsed, "inresponse_to", None),
            getattr(parsed, "is_success", None),
        )
        return parsed
    except SimpleResponseError as exc:
        _logger.debug("Failed to parse eIDAS SimpleResponse: %s", exc)
        raise HTTPException(
            status_code=400, detail=f"Malformed SimpleResponse: {exc}"
        ) from exc


async def pop_eidas_message_id(
    client,
    request_id: str,
    *,
    keys: PreviewKeys | None = None,
) -> str:
    if keys is None:
        keys = PreviewKeys()

    state_key = keys.get_eidas_state_key(request_id)
    _logger.debug(
        "Looking up eIDAS state for request_id=%s state_key=%s",
        request_id,
        state_key,
    )
    state_data = await client.get_from_redis(state_key)
    await client.delete_from_redis(state_key)
    _logger.debug("Loaded eIDAS state_data=%s", state_data)

    if not isinstance(state_data, dict) or not state_data.get("message_id"):
        _logger.warning(
            "eIDAS callback: invalid or expired request id=%s state_key=%s",
            request_id,
            state_key,
        )
        raise HTTPException(
            status_code=400, detail="Invalid or expired eIDAS request id"
        )

    message_id = state_data["message_id"]
    _logger.debug(
        "Resolved eIDAS callback request_id=%s to message_id=%s",
        request_id,
        message_id,
    )
    return message_id


def raise_if_eidas_failed(simple_response, message_id: str, *, logger=None) -> None:
    if simple_response.is_success:
        _logger.debug(
            "eIDAS callback succeeded for message_id=%s status=%s",
            message_id,
            getattr(simple_response.status, "status_code", None),
        )
        return

    log = logger or _logger
    log.warning(
        "eIDAS authentication failed for message_id=%s: %s / %s",
        message_id,
        simple_response.status.status_code,
        simple_response.status.status_message,
    )
    log.debug(
        "eIDAS failure details for message_id=%s sub_status=%s",
        message_id,
        getattr(simple_response.status, "sub_status_code", None),
    )
    raise HTTPException(
        status_code=502,
        detail={
            "code": simple_response.status.sub_status_code
            or simple_response.status.status_code,
            "message": simple_response.status.status_message
            or "eIDAS authentication failed",
        },
    )


async def save_eidas_person(client, message_id: str, person_payload: dict) -> None:
    _logger.debug(
        "Saving eIDAS person for message_id=%s first_name=%s last_name=%s identifier=%s",
        message_id,
        person_payload.get("first_name"),
        person_payload.get("last_name"),
        person_payload.get("identifier"),
    )
    try:
        await save_identified_person_request(
            client,
            message_id=message_id,
            first_name=person_payload["first_name"],
            last_name=person_payload["last_name"],
            identifier=person_payload["identifier"],
            date_of_birth=person_payload["date_of_birth"],
            gender=person_payload["gender"],
            level_of_assurance=person_payload["level_of_assurance"],
        )
        _logger.debug("Saved eIDAS person data to Redis for message_id=%s", message_id)
    except ValueError as exc:
        _logger.debug("Invalid eIDAS person payload for message_id=%s: %s", message_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _logger.debug(
            "Failed to save eIDAS person data for message_id=%s: %s",
            message_id,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Не вдалося зберегти дані в Redis: {exc}",
        ) from exc


async def process_eidas_callback(
    request: Request,
    client,
    *,
    keys: PreviewKeys | None = None,
    logger=None,
) -> str:
    log = logger or _logger
    log.debug("Starting eIDAS callback processing")
    raw_body = await read_simple_response_body(request)
    simple_response = parse_simple_response(raw_body)

    message_id = await pop_eidas_message_id(client, simple_response.inresponse_to, keys=keys)
    raise_if_eidas_failed(simple_response, message_id, logger=log)

    person_payload = simple_response.to_person_payload()
    log.debug(
        "eIDAS callback resolved person payload for message_id=%s: %s",
        message_id,
        person_payload,
    )
    await save_eidas_person(client, message_id, person_payload)
    log.debug("Completed eIDAS callback processing for message_id=%s", message_id)
    return message_id


def parse_response(raw_body: str) -> SimpleResponse:
    return parse_eidas_response(raw_body)
