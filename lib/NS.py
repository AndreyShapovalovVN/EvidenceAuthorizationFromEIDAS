from lxml import etree


class NS:
    _xml: etree._Element
    _ns: dict[str, str] = {
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "rs": "urn:oasis:names:tc:ebxml-regrep:xsd:rs:4.0",
        "rim": "urn:oasis:names:tc:ebxml-regrep:xsd:rim:4.0",
        "sdg": "http://data.europa.eu/p4s",
        "query": "urn:oasis:names:tc:ebxml-regrep:xsd:query:4.0",
        "xlink": "http://www.w3.org/1999/xlink",
        "xml": "http://www.w3.org/XML/1998/namespace",
    }

    def _tname(self, ns, tag):
        if not ns:
            return tag
        return f"{{{self._ns[ns]}}}{tag}"

    @property
    def xml(self):
        return self._xml

    @property
    def xml_string(self) -> str:
        if self._xml is None:
            return ""
        return etree.tostring(self._xml, pretty_print=True).decode("utf-8")
