import pytest

from Models.eIDAS_SP_Request import Attribute, RequestedAuthenticationContext, AuthenticationRequest


class TestEidasRequest:
    def test_create_request(self):
        request = AuthenticationRequest(
            attribute_list=[
                Attribute(name="FamilyName", required=True),
                Attribute(name="FirstName", required=True),
                Attribute(name="DateOfBirth", required=True),
                Attribute(name="Gender", required=True),
                Attribute(name="PersonIdentifier", required=True),
            ],
            requested_authentication_context=RequestedAuthenticationContext(
                comparison="minimum",
                context_class=["A"],
                non_notified_context_class=[]
            ),
            citizen_country="CA",
            force_authentication=True,
            name_id_policy="persistent",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        assert len(request.attribute_list) == 5
        assert request.requested_authentication_context.comparison == "minimum"
        assert request.citizen_country == "CA"
        assert request.force_authentication is True
        assert request.name_id_policy == "persistent"
        assert request.provider_name == "DEMO-SP-CA"
        assert request.sp_type == "private"
        assert request.version == "1"
        assert request.id is not None
        assert request.created_on is not None

    def test_create_request_from_json_structure(self):
        """Test that request can be created with structure matching the JSON example."""
        request = AuthenticationRequest(
            attribute_list=[
                Attribute(name="FamilyName", required=True),
                Attribute(name="FirstName", required=True),
                Attribute(name="DateOfBirth", required=True),
                Attribute(name="Gender", required=True),
                Attribute(name="PersonIdentifier", required=True),
            ],
            requested_authentication_context=RequestedAuthenticationContext(
                comparison="minimum",
                context_class=["A"],
                non_notified_context_class=[]
            ),
            citizen_country="CA",
            force_authentication=True,
            name_id_policy="persistent",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        assert request.citizen_country == "CA"
        assert request.force_authentication is True
        assert request.provider_name == "DEMO-SP-CA"
        assert request.requester_id == "https://eidas.example.org/RequesterId_CA"
        assert request.service_url == "https://sp.eidas.k8s/SP/ReturnPage"
        assert request.sp_type == "private"
        assert request.version == "1"

    def test_attribute_list_validation(self):
        """Test that all required attributes are correctly set."""
        attributes = [
            Attribute(name="FamilyName", required=True),
            Attribute(name="FirstName", required=True),
            Attribute(name="DateOfBirth", required=True),
            Attribute(name="Gender", required=True),
            Attribute(name="PersonIdentifier", required=True),
        ]

        request = AuthenticationRequest(
            attribute_list=attributes,
            requested_authentication_context=RequestedAuthenticationContext(
                comparison="minimum",
                context_class=["A"],
                non_notified_context_class=[]
            ),
            citizen_country="CA",
            force_authentication=True,
            name_id_policy="persistent",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        assert len(request.attribute_list) == 5
        attribute_names = [attr.name for attr in request.attribute_list]
        assert "FamilyName" in attribute_names
        assert "FirstName" in attribute_names
        assert "DateOfBirth" in attribute_names
        assert "Gender" in attribute_names
        assert "PersonIdentifier" in attribute_names

        for attr in request.attribute_list:
            assert attr.type == "requested_attribute"
            assert attr.required is True

    def test_requested_authentication_context(self):
        """Test requested authentication context properties."""
        context = RequestedAuthenticationContext(
            comparison="minimum",
            context_class=["A"],
            non_notified_context_class=[]
        )

        request = AuthenticationRequest(
            attribute_list=[Attribute(name="PersonIdentifier", required=True)],
            requested_authentication_context=context,
            citizen_country="CA",
            force_authentication=True,
            name_id_policy="persistent",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        assert request.requested_authentication_context.comparison == "minimum"
        assert request.requested_authentication_context.context_class == ["A"]
        assert request.requested_authentication_context.non_notified_context_class == []

    def test_default_field_values(self):
        """Test that default fields are properly generated."""
        request = AuthenticationRequest(
            attribute_list=[Attribute(name="PersonIdentifier", required=True)],
            requested_authentication_context=RequestedAuthenticationContext(
                comparison="minimum",
                context_class=["A"],
                non_notified_context_class=[]
            ),
            citizen_country="CA",
            force_authentication=True,
            name_id_policy="persistent",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        # Test default values
        assert request.sp_type == "private"
        assert request.version == "1"

        # Test generated values
        assert request.id is not None
        assert len(request.id) == 36  # UUID format
        assert request.created_on is not None
        assert "T" in request.created_on  # ISO format

    def test_citizen_country_field(self):
        """Test citizen_country field accepts different country codes."""
        for country_code in ["CA", "UA", "DE", "FR"]:
            request = AuthenticationRequest(
                attribute_list=[Attribute(name="PersonIdentifier", required=True)],
                requested_authentication_context=RequestedAuthenticationContext(
                    comparison="minimum",
                    context_class=["A"],
                    non_notified_context_class=[]
                ),
                citizen_country=country_code,
                force_authentication=True,
                name_id_policy="persistent",
                provider_name="DEMO-SP",
                requester_id="https://eidas.example.org",
                service_url="https://sp.eidas.k8s/SP/ReturnPage",
            )
            assert request.citizen_country == country_code

    def test_force_authentication_and_name_id_policy(self):
        """Test force_authentication and name_id_policy fields."""
        request_forced = AuthenticationRequest(
            attribute_list=[Attribute(name="PersonIdentifier", required=True)],
            requested_authentication_context=RequestedAuthenticationContext(
                comparison="minimum",
                context_class=["A"],
                non_notified_context_class=[]
            ),
            citizen_country="CA",
            force_authentication=True,
            name_id_policy="persistent",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        request_not_forced = AuthenticationRequest(
            attribute_list=[Attribute(name="PersonIdentifier", required=True)],
            requested_authentication_context=RequestedAuthenticationContext(
                comparison="minimum",
                context_class=["A"],
                non_notified_context_class=[]
            ),
            citizen_country="CA",
            force_authentication=False,
            name_id_policy="transient",
            provider_name="DEMO-SP-CA",
            requester_id="https://eidas.example.org/RequesterId_CA",
            service_url="https://sp.eidas.k8s/SP/ReturnPage",
        )

        assert request_forced.force_authentication is True
        assert request_forced.name_id_policy == "persistent"
        assert request_not_forced.force_authentication is False
        assert request_not_forced.name_id_policy == "transient"
