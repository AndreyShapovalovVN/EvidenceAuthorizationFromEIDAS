import datetime
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

from lxml import etree


@dataclass
class Base(ABC):
    @staticmethod
    def _set_text(element: etree._Element, value) -> None:
        if value is None:
            ...
        elif isinstance(value, bool):
            element.text = str(value).lower()
        elif isinstance(value, (datetime.date, datetime.datetime)):
            element.text = value.isoformat()
        else:
            element.text = str(value)

    @staticmethod
    def _parse_date(value) -> datetime.date | None:
        if value in (None, "", {}):
            return None
        if isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(str(value))

    @staticmethod
    def _parse_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() == "true"

    @abstractmethod
    def get_element(self) -> etree._Element:
        pass


@dataclass
class MainBase(Base):
    _name_: str | None = None

    @classmethod
    def set_from_dict(cls, data: dict):
        raise NotImplementedError(
            "Метод set_from_dict должен быть реализован в подклассе"
        )

    def get_xml(self) -> str:
        xml_bytes: bytes = etree.tostring(
            self.get_element(),
            pretty_print=True,
            encoding="utf-8",
        )
        return xml_bytes.decode("utf-8")

    def get_dict(self) -> dict:
        return_dict = asdict(self)
        return_dict.pop("_name_", None)
        if self._name_:
            return {self._name_: return_dict}
        return return_dict

    def get_json(self) -> str:
        return json.dumps(self.get_dict(), default=str, ensure_ascii=False)
