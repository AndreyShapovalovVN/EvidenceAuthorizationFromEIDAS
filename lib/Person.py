import datetime
import logging
from dataclasses import dataclass

from lxml import etree

from lib.NS import NS

_logger = logging.getLogger(__name__)


class Identifier(NS):
    """
    Represents an identifier with a specific format and scheme.

    This class is used to parse, validate, and represent an identifier in the format
    'country/country_nationality/identifier'. It provides properties to access individual
    components of the identifier and ensures that the identifier adheres to the required format.

    :ivar schemeID: The scheme ID associated with the identifier.
    :type schemeID: str
    """

    def __init__(self, value: str | None, schemeID: str = "eidas"):
        """
        Represents an object for managing a structured identifier with a specific scheme.

        This class is designed to process and store a structured identifier in the
        format 'country/country_nationality/identifier', as well as an associated
        scheme ID. If no value is provided, it initializes with a default structure
        containing None values. The scheme ID defaults to 'eidas' if not otherwise
        specified.

        :param value: The structured identifier in the format
                      'country/country_nationality/identifier'. If None, the
                      structure will be initialized with default None values.
        :type value: str | None
        :param schemeID: The scheme ID associated with the identifier. Defaults to 'eidas'.
        :type schemeID: str
        :raises ValueError: If the `value` does not match the required format 
                            'country/country_nationality/identifier'.
        """
        self._value: list = [None, None, None]
        self.value = value
        self.schemeID = schemeID

    @property
    def country_identifier(self) -> str | None:
        """
        Retrieves the country identifier from an internal value.

        This property provides access to the first element of the internal value, 
        which represents the country identifier. If the value is not set, it 
        returns None.

        :return: The country identifier as a string or None if not available
        :rtype: str or None
        """
        return self._value[0]

    @property
    def country_nationality(self) -> str | None:
        """
        Provides access to the nationality of a country.

        This property retrieves the nationality associated with a country from
        the stored value. If the value is not set, it will return None.

        :return: The nationality of the country, or None if not available.
        :rtype: str or None
        """
        return self._value[1]

    @property
    def identifier(self) -> str | None:
        """
        Gets the identifier value from a specific index in the internal value storage.

        This property retrieves the identifier value, which may either be a string or
        None, depending on the state of the internal data. It accesses and returns the
        data from the third position (index 2) of the internal storage. The design
        ensures encapsulation by not exposing the internal storage directly.

        :return: The identifier contained in the third position (index 2) of the 
            internal value storage, or None if the value is not available or is unset.
        :rtype: str | None
        """
        return self._value[2]

    @property
    def value(self) -> str | None:
        """
        Provides a property to retrieve a computed value based on internal elements.

        :attribute value: A read-only property returning the formatted value derived 
            from joining the internal elements with '/' separator. If no internal 
            elements exist, returns None.

        :return: Computed string representation of the internal elements separated 
            by '/', or None if no elements exist.
        :rtype: str | None
        """

        if self._value == [None, None, None]:
            return None
        return '/'.join(self._value)

    @value.setter
    def value(self, value: str | None) -> None:
        if value is None:
            self._value = [None, None, None]
        elif len(value.split("/")) != 3:
            raise ValueError("Значення має бути у форматі 'country/country_nationality/identifier'")
        else:
            self._value = value.split("/")


@dataclass
class Person(NS):
    LevelOfAssurance: str = "High"
    identifier: Identifier | None = None  # РНОКПП
    FamilyName: str | None = None  # Призвище
    FamilyNameNonLatin: str | None = None
    GivenName: str | None = None  # Ім'я
    GivenNameNonLatin: str | None = None
    AdditionalName: str | None = None  # по Батькові
    AdditionalNameNonLatin: str | None = None
    BirthName: str | None = None
    BirthNameNonLatin: str | None = None
    DateOfBirth: datetime.date | None = None
    Gender: str | None = None
    Nationality: str | None = None
    CountryOfBirth: str | None = None
    TownOfBirth: str | None = None
    CountryOfResidence: str | None = None
    _ns = {"sdg": "http://data.europa.eu/p4s"}

    @staticmethod
    def _parse_name(element: etree._Element):
        if element is None:
            return None, None
        return element.text, element.get("nonLatin")

    @staticmethod
    def _get_id(element: etree._Element):
        if element is None:
            return None, None
        return element.text, element.get("schemeID")

    @staticmethod
    def _get_text(element: etree._Element):
        if element is None:
            return None
        return element.text

    @property
    def xml(self):
        root = etree.Element(self._tname("sdg", "Person"), nsmap=self._ns)

        etree.SubElement(
            root, self._tname("sdg", "LevelOfAssurance")
        ).text = self.LevelOfAssurance

        if self.identifier.value:
            etree.SubElement(
                root, self._tname("sdg", "Identifier"),
                attrib={"schemeID": self.identifier.schemeID}
            ).text = self.identifier.value

        if self.FamilyNameNonLatin:
            etree.SubElement(
                root,
                self._tname("sdg", "FamilyName"),
                attrib={"nonLatin": self.FamilyNameNonLatin},
            ).text = self.FamilyName
        else:
            etree.SubElement(
                root, self._tname("sdg", "FamilyName")
            ).text = self.FamilyName

        if self.GivenNameNonLatin:
            etree.SubElement(
                root,
                self._tname("sdg", "GivenName"),
                attrib={"nonLatin": self.GivenNameNonLatin},
            ).text = self.GivenName
        else:
            etree.SubElement(
                root, self._tname("sdg", "GivenName")
            ).text = self.GivenName

        if self.AdditionalNameNonLatin:
            etree.SubElement(
                root,
                self._tname("sdg", "AdditionalName"),
                attrib={"nonLatin": self.AdditionalNameNonLatin},
            ).text = self.AdditionalName
        else:
            etree.SubElement(
                root, self._tname("sdg", "AdditionalName")
            ).text = self.AdditionalName

        if self.BirthNameNonLatin:
            etree.SubElement(
                root,
                self._tname("sdg", "BirthName"),
                attrib={"nonLatin": self.BirthNameNonLatin},
            ).text = self.BirthName
        else:
            etree.SubElement(
                root, self._tname("sdg", "BirthName")
            ).text = self.BirthName

        if isinstance(self.DateOfBirth, datetime.date):
            etree.SubElement(
                root, self._tname("sdg", "DateOfBirth")
            ).text = self.DateOfBirth.isoformat()
        else:
            etree.SubElement(
                root, self._tname("sdg", "DateOfBirth")
            ).text = self.DateOfBirth

        etree.SubElement(root, self._tname("sdg", "Gender")).text = self.Gender
        etree.SubElement(
            root, self._tname("sdg", "Nationality")
        ).text = self.Nationality
        etree.SubElement(
            root, self._tname("sdg", "CountryOfBirth")
        ).text = self.CountryOfBirth
        etree.SubElement(
            root, self._tname("sdg", "TownOfBirth")
        ).text = self.TownOfBirth
        etree.SubElement(
            root, self._tname("sdg", "CountryOfResidence")
        ).text = self.CountryOfResidence

        self._xml = root

        return self.xml_string

    @xml.setter
    def xml(self, xml: str | bytes | etree._Element):
        if isinstance(xml, str | bytes):
            root = etree.fromstring(xml)
            _logger.debug("Xml зчитано")
        elif isinstance(xml, etree._Element):
            root = xml
            _logger.debug("Xml зчитано")
        else:
            raise TypeError("xml має бути str або bytes")

        _logger.debug("Парсинг значень")
        self.LevelOfAssurance = self._get_text(
            root.find(".//sdg:LevelOfAssurance", self._ns)  # type: ignore
        )
        self.identifier = Identifier(
            *self._get_id(
                root.find(".//sdg:Identifier", self._ns)  # type: ignore
            )
        )
        self.FamilyName, self.FamilyNameNonLatin = self._parse_name(
            root.find(".//sdg:FamilyName", self._ns)  # type: ignore
        )
        self.GivenName, self.GivenNameNonLatin = self._parse_name(
            root.find(".//sdg:GivenName", self._ns)  # type: ignore
        )
        self.BirthName, self.BirthNameNonLatin = self._parse_name(
            root.find(".//sdg:BirthName", self._ns)  # type: ignore
        )
        self.DateOfBirth = self._get_text(
            root.find(".//sdg:DateOfBirth", self._ns)  # type: ignore
        )
        self.Gender = self._get_text(
            root.find(".//sdg:Gender", self._ns)  # type: ignore
        )
        self.Nationality = self._get_text(
            root.find(".//sdg:Nationality", self._ns)  # type: ignore
        )
        self.CountryOfBirth = self._get_text(
            root.find(".//sdg:CountryOfBirth", self._ns)  # type: ignore
        )
        self.TownOfBirth = self._get_text(
            root.find(".//sdg:TownOfBirth", self._ns)  # type: ignore
        )
        self.CountryOfResidence = self._get_text(
            root.find(".//sdg:CountryOfResidence", self._ns)  # type: ignore
        )
        _logger.debug("Дані зчитані")

    @property
    def dict(self):
        r = {
            "level_of_assurance": self.LevelOfAssurance,
            "eidas_identifier": self.identifier.value,
            "family_name": self.FamilyName,
            "family_name_non_latin": self.FamilyNameNonLatin,
            "given_name": self.GivenName,
            "given_name_non_latin": self.GivenNameNonLatin,
            "date_of_birth": (
                self.DateOfBirth.isoformat()
                if isinstance(self.DateOfBirth, datetime.date)
                else self.DateOfBirth
            ),
            "gender": self.Gender}

        return r

    @dict.setter
    def dict(self, d):
        self.LevelOfAssurance = d.get("level_of_assurance")
        self.identifier = Identifier(d.get("eidas_identifier"))
        self.FamilyName = d.get("family_name")
        self.FamilyNameNonLatin = d.get("family_name_non_latin")
        self.GivenName = d.get("given_name")
        self.GivenNameNonLatin = d.get("given_name_non_latin")
        self.DateOfBirth = d.get("date_of_birth")

    async def from_redis(self, redis, key):
        data = await redis.get_from_redis(key)
        if data is not None:
            self.dict = data
