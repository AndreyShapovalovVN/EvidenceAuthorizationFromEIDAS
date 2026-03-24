from dataclasses import dataclass


@dataclass
class Keys:
    REQUEST_PERSON: str = "oots:message:request:person:{conversation_id}"
    RESPONSE_EVIDENCE: str = "oots:message:response:evidence:{conversation_id}"
    RESPONSE_PERMIT: str = "oots:message:request:permit:{conversation_id}"
    RESPONSE_EDM: str = "oots:message:response:edm:{conversation_id}"
    REQUEST_EDM: str = "oots:message:request:edm:{conversation_id}"
    REQUEST_AS4: str = "oots:message:request:as4:{conversation_id}"
    REQUEST_PREVIEW: str = "oots:message:request:preview:{conversation_id}"

    EVIDENCE_TYPE: str = "oots:evidencetype:{evidence_type_id}"
