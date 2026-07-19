import datetime
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from lib.NS import NS
from Models.Base import Base, MainBase


_logger = logging.getLogger(__name__)

COUNTRY = os.getenv("COUNTRY", "UA")

__all__ = [
    "Identifier",
    "Person",
    "save_person_to_redis",
    "get_person_from_redis",
]

@dataclass(init=False)
class Identifier(Base, NS):
    """Ідентифікатор у форматі `country/country_nationality/identifier`."""

    country_identifier: str = COUNTRY
    country_nationality: str = COUNTRY
    identifier: str | None = None
    schemeID: str = "eidas"

    def __init__(self, value: str | None = None, schemeID: str | None = "eidas"):     # NOSONAR
        super().__init__()
        self.country_identifier = COUNTRY
        self.country_nationality = COUNTRY
        self.identifier = None
        self.schemeID = schemeID or "eidas"
        self.value = value

    def get_element(self, sdg: bool=True) -> etree._Element:
        if sdg:
            element = etree.Element(
                self._tname("sdg", "Identifier"),
                attrib={"schemeID": self.schemeID},
                nsmap={"sdg": self._ns["sdg"]})
            self._set_text(element, self.value)
        else:
            element = etree.Element("Identifier")
            self._set_text(element, self.identifier)
        return element

    @property
    def value(self) -> str | None:
        """Повертає повне значення ідентифікатора або `None`."""
        ci = self.country_identifier
        cn = self.country_nationality
        ident = self.identifier
        if ci is None or cn is None or ident is None:
            return None
        return f"{ci}/{cn}/{ident}"

    @value.setter
    def value(self, value: str | None) -> None:
        if value is None:
            self.identifier = None
            return

        parts = value.split("/")
        if len(parts) != 3:
            raise ValueError("Значення має бути у форматі 'country/country_nationality/identifier'")

        self.country_identifier, self.country_nationality, self.identifier = parts


@dataclass
class Person(MainBase, NS):
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
    _xml: etree._Element | None = field(init=False, repr=False, default=None)
    _ns = {"sdg": "http://data.europa.eu/p4s"}  # NOSONAR

    def __post_init__(self) -> None:
        self._xml = None

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
    def xml(self) -> str:
        return self.get_xml()

    @xml.setter
    def xml(self, xml: str | bytes | etree._Element) -> None:
        if isinstance(xml, str | bytes):
            root = etree.fromstring(xml)
            _logger.debug("XML зчитано")
        elif isinstance(xml, etree._Element):
            root = xml
            _logger.debug("XML зчитано")
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
        self.AdditionalName, self.AdditionalNameNonLatin = self._parse_name(
            root.find(".//sdg:AdditionalName", self._ns)  # type: ignore
        )
        self.BirthName, self.BirthNameNonLatin = self._parse_name(
            root.find(".//sdg:BirthName", self._ns)  # type: ignore
        )
        self.DateOfBirth = self._parse_date(
            self._get_text(
                root.find(".//sdg:DateOfBirth", self._ns)  # type: ignore
            )
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
        self._xml = root
        _logger.debug("Дані зчитані")

    @property
    def xml_tree(self) -> etree._Element | None:
        return self.get_element()

    def get_element(self) -> etree._Element:
        root = etree.Element(self._tname("sdg", "Person"), nsmap=self._ns)

        etree.SubElement(
            root, self._tname("sdg", "LevelOfAssurance")
        ).text = self.LevelOfAssurance

        if self.identifier is not None and self.identifier.value:
            root.append(self.identifier.get_element(sdg=True))

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
        return root

    def get_xml(self) -> str:
        return super().get_xml()

    def get_dict(self) -> dict[str, Any]:
        return {
            "LevelOfAssurance": self.LevelOfAssurance,
            "identifier": (
                {
                    "value": self.identifier.value,
                    "schemeID": self.identifier.schemeID,
                }
                if self.identifier is not None
                else None
            ),
            "FamilyName": self.FamilyName,
            "FamilyNameNonLatin": self.FamilyNameNonLatin,
            "GivenName": self.GivenName,
            "GivenNameNonLatin": self.GivenNameNonLatin,
            "AdditionalName": self.AdditionalName,
            "AdditionalNameNonLatin": self.AdditionalNameNonLatin,
            "BirthName": self.BirthName,
            "BirthNameNonLatin": self.BirthNameNonLatin,
            "DateOfBirth": (
                self.DateOfBirth.isoformat()
                if isinstance(self.DateOfBirth, datetime.date)
                else self.DateOfBirth
            ),
            "Gender": self.Gender,
            "Nationality": self.Nationality,
            "CountryOfBirth": self.CountryOfBirth,
            "TownOfBirth": self.TownOfBirth,
            "CountryOfResidence": self.CountryOfResidence,
        }

    @classmethod
    def set_from_dict(cls, data: dict[str, Any]) -> "Person":
        if not isinstance(data, dict):
            raise TypeError(f"Очікувався dict, отримано {type(data).__name__}")

        identifier_data = data.get("identifier")
        identifier: Identifier | None
        if isinstance(identifier_data, Identifier):
            identifier = identifier_data
        elif isinstance(identifier_data, dict):
            identifier = Identifier(
                identifier_data.get("value"),
                identifier_data.get("schemeID", "eidas"),
            )
        elif isinstance(identifier_data, str):
            identifier = Identifier(identifier_data)
        else:
            legacy_identifier = data.get("eidas_identifier")
            identifier = Identifier(value=legacy_identifier) if legacy_identifier is not None else None

        date_of_birth = data.get("DateOfBirth", data.get("date_of_birth"))

        return cls(
            LevelOfAssurance=str(data.get("LevelOfAssurance", data.get("level_of_assurance", "High")) or "High"),
            identifier=identifier,
            FamilyName=data.get("FamilyName", data.get("family_name")),
            FamilyNameNonLatin=data.get("FamilyNameNonLatin", data.get("family_name_non_latin")),
            GivenName=data.get("GivenName", data.get("given_name")),
            GivenNameNonLatin=data.get("GivenNameNonLatin", data.get("given_name_non_latin")),
            AdditionalName=data.get("AdditionalName", data.get("additional_name")),
            AdditionalNameNonLatin=data.get(
                "AdditionalNameNonLatin",
                data.get("additional_name_non_latin"),
            ),
            BirthName=data.get("BirthName", data.get("birth_name")),
            BirthNameNonLatin=data.get("BirthNameNonLatin", data.get("birth_name_non_latin")),
            DateOfBirth=cls._parse_date(date_of_birth),
            Gender=data.get("Gender", data.get("gender")),
            Nationality=data.get("Nationality", data.get("nationality")),
            CountryOfBirth=data.get("CountryOfBirth", data.get("country_of_birth")),
            TownOfBirth=data.get("TownOfBirth", data.get("town_of_birth")),
            CountryOfResidence=data.get(
                "CountryOfResidence",
                data.get("country_of_residence"),
            ),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Person":
        return cls.set_from_dict(data)


    @property
    def dict(self) -> dict[str, Any]:
        return {
            "level_of_assurance": self.LevelOfAssurance,
            "eidas_identifier": self.identifier.value if self.identifier else None,
            "family_name": self.FamilyName,
            "family_name_non_latin": self.FamilyNameNonLatin,
            "given_name": self.GivenName,
            "given_name_non_latin": self.GivenNameNonLatin,
            "additional_name": self.AdditionalName,
            "additional_name_non_latin": self.AdditionalNameNonLatin,
            "birth_name": self.BirthName,
            "birth_name_non_latin": self.BirthNameNonLatin,
            "date_of_birth": (
                self.DateOfBirth.isoformat()
                if isinstance(self.DateOfBirth, datetime.date)
                else self.DateOfBirth
            ),
            "gender": self.Gender,
            "nationality": self.Nationality,
            "country_of_birth": self.CountryOfBirth,
            "town_of_birth": self.TownOfBirth,
            "country_of_residence": self.CountryOfResidence,
        }

    @dict.setter
    def dict(self, d: Any) -> None:
        person = self.set_from_dict(d)
        self.LevelOfAssurance = person.LevelOfAssurance
        self.identifier = person.identifier
        self.FamilyName = person.FamilyName
        self.FamilyNameNonLatin = person.FamilyNameNonLatin
        self.GivenName = person.GivenName
        self.GivenNameNonLatin = person.GivenNameNonLatin
        self.AdditionalName = person.AdditionalName
        self.AdditionalNameNonLatin = person.AdditionalNameNonLatin
        self.BirthName = person.BirthName
        self.BirthNameNonLatin = person.BirthNameNonLatin
        self.DateOfBirth = person.DateOfBirth
        self.Gender = person.Gender
        self.Nationality = person.Nationality
        self.CountryOfBirth = person.CountryOfBirth
        self.TownOfBirth = person.TownOfBirth
        self.CountryOfResidence = person.CountryOfResidence

    async def from_redis(self, redis, key):
        person = await get_person_from_redis(redis, key)
        if person is not None:
            self.dict = person.dict


async def save_person_to_redis(redis_client, key: str, person: Person) -> None:
    """
    Зберігає Person до Redis як JSON через властивість dict.

    Args:
        redis_client: Екземпляр UseRedisAsync
        key: Ключ Redis для збереження
        person: Об'єкт Person
    """
    if not isinstance(person, Person):
        raise TypeError(f"Очікувався Person, отримано {type(person).__name__}")

    await redis_client.save_to_redis(key, person.dict)


async def get_person_from_redis(redis_client, key: str) -> Person | None:
    """
    Отримує Person з Redis і десеріалізує у модель.

    Args:
        redis_client: Екземпляр UseRedisAsync
        key: Ключ Redis для читання

    Returns:
        Person або None, якщо ключ відсутній
    """
    data = await redis_client.get_from_redis(key)
    if data is None:
        return None

    # Підтримка старого формату зі списком
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]

    if not isinstance(data, dict):
        raise ValueError(f"Некоректний формат Person у Redis: {type(data).__name__}")

    return _dict_to_person(data)


def _dict_to_person(data: dict) -> Person:
    """Конвертує словник у Person."""
    person = Person()
    person.dict = data
    return person
