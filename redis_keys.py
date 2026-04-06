from dataclasses import dataclass


@dataclass
class Keys:
    RESPONSE_EVIDENCE: str = "oots:message:response:evidence:{conversation_id}"
    RESPONSE_PERMIT: str = "oots:message:request:permit:{conversation_id}"
    RESPONSE_EDM: str = "oots:message:response:edm:{conversation_id}"
    RESPONSE_EXP: str = "oots:message:response:exp:{conversation_id}"

    REQUEST_EDM: str = "oots:message:request:edm:{conversation_id}"
    REQUEST_AS4: str = "oots:message:request:as4:{conversation_id}"
    REQUEST_PREVIEW: str = "oots:message:request:preview:{conversation_id}"
    REQUEST_PERSON: str = "oots:message:request:person:{conversation_id}"

    EVIDENCE_TYPE: str = "oots:evidencetype:{evidence_type_id}"

    def response_evidence(self, conversation_id: str) -> str:
        return self.RESPONSE_EVIDENCE.format(conversation_id=conversation_id)

    def response_permit(self, conversation_id: str) -> str:
        return self.RESPONSE_PERMIT.format(conversation_id=conversation_id)

    def response_edm(self, conversation_id: str) -> str:
        return self.RESPONSE_EDM.format(conversation_id=conversation_id)

    def response_exp(self, conversation_id: str) -> str:
        return self.RESPONSE_EXP.format(conversation_id=conversation_id)

    def request_person(self, conversation_id: str) -> str:
        return self.REQUEST_PERSON.format(conversation_id=conversation_id)

    def request_edm(self, conversation_id: str) -> str:
        return self.REQUEST_EDM.format(conversation_id=conversation_id)

    def request_as4(self, conversation_id: str) -> str:
        return self.REQUEST_AS4.format(conversation_id=conversation_id)

    def request_preview(self, conversation_id: str) -> str:
        return self.REQUEST_PREVIEW.format(conversation_id=conversation_id)

    def evidence_type(self, evidence_type_id: str) -> str:
        return self.EVIDENCE_TYPE.format(evidence_type_id=evidence_type_id)

