"""Contract examples from the bundled eIDAS-Node Demo Tools guide v3.0.0 §12.

The request fixture transcribes §12.2, page 21, independently of our serializer.
"""

import base64
import json
from pathlib import Path

from Models.eIDAS_SP_Request import (
    Attribute,
    AuthenticationRequest,
    RequestedAuthenticationContext,
)


def test_request_serializers_match_node_3_0_guide():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/eidas_simple_request_3_0.json").read_text()
    )
    fields = expected["authentication_request"].copy()
    fields["attribute_list"] = [Attribute(**item) for item in fields["attribute_list"]]
    fields["requested_authentication_context"] = RequestedAuthenticationContext(
        **fields["requested_authentication_context"]
    )
    request = AuthenticationRequest(_name_="authentication_request", **fields)

    assert request.get_dict() == expected["authentication_request"]
    assert json.loads(request.get_json()) == expected
    assert json.loads(base64.b64decode(request.get_base64(), validate=True)) == expected
