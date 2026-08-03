from redis_keys import Keys


class PreviewKeys(Keys):
    PROCESS_QUEUE_DISPATCHED_KEY = (
        "oots:preview:process_queue_dispatched:{conversation_id}"
    )
    EIDAS_STATE_KEY_PREFIX = "oots:preview:eidas:sp:state:{conversation_id}:"

    def get_process_queue_dispatched_key(self, message_id: str) -> str:
        return self.PROCESS_QUEUE_DISPATCHED_KEY.format(conversation_id=message_id)

    def get_eidas_state_key(self, auth_request_id: str) -> str:
        return self.EIDAS_STATE_KEY_PREFIX.format(conversation_id=auth_request_id)
