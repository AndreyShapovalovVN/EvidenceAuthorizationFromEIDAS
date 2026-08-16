from oots_lib.redis_keys import Keys


class PreviewKeys(Keys):
    PROCESS_QUEUE_DISPATCHED_KEY = (
        "oots:preview:process_queue_dispatched:{conversation_id}"
    )
    EIDAS_STATE_KEY_PREFIX = "oots:preview:eidas:sp:state:{conversation_id}:"
    RETURN_URL: str = "oots:message:response:returnurl:{conversation_id}"
    REQUEST_ICEI_STATE: str = "oots:icei:state:{state}"

    def get_process_queue_dispatched_key(self, message_id: str) -> str:
        return self.PROCESS_QUEUE_DISPATCHED_KEY.format(conversation_id=message_id)

    def get_eidas_state_key(self, auth_request_id: str) -> str:
        return self.EIDAS_STATE_KEY_PREFIX.format(conversation_id=auth_request_id)

    def get_request_icei_state(self, state: str) -> str:
        return self.REQUEST_ICEI_STATE.format(state=state)

    def get_return_url(self, conversation_id: str) -> str:
        return self.RETURN_URL.format(conversation_id=conversation_id)
