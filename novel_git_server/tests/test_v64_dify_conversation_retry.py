import io
import json
import sys
import unittest
from urllib import error
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.dify_client import chat_messages, chat_messages_stream  # noqa: E402


class _JsonResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _SseResponse:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)


def _conversation_missing_error() -> error.HTTPError:
    body = {
        "code": "not_found",
        "message": "Conversation Not Exists.",
        "status": 404,
    }
    return error.HTTPError(
        url="http://localhost/v1/chat-messages",
        code=404,
        msg="not found",
        hdrs=None,
        fp=io.BytesIO(json.dumps(body).encode("utf-8")),
    )


class V64DifyConversationRetryTests(unittest.TestCase):
    def test_blocking_chat_retries_without_stale_conversation_id(self):
        with patch(
            "utils.dify_client.request.urlopen",
            side_effect=[
                _conversation_missing_error(),
                _JsonResponse({"answer": "ok", "conversation_id": "new-upstream"}),
            ],
        ) as mock_urlopen:
            response = chat_messages(
                base_url="http://localhost/v1",
                api_key="test-key",
                query="hello",
                conversation_id="old-upstream",
            )

        self.assertEqual(response["conversation_id"], "new-upstream")
        self.assertEqual(mock_urlopen.call_count, 2)
        first_payload = json.loads(mock_urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        second_payload = json.loads(mock_urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertEqual(first_payload.get("conversation_id"), "old-upstream")
        self.assertNotIn("conversation_id", second_payload)

    def test_streaming_chat_retries_without_stale_conversation_id(self):
        lines = [
            b'event: message\n',
            b'data: {"answer":"ok","conversation_id":"new-stream-upstream"}\n',
            b"\n",
        ]
        with patch(
            "utils.dify_client.request.urlopen",
            side_effect=[
                _conversation_missing_error(),
                _SseResponse(lines),
            ],
        ) as mock_urlopen:
            events = list(
                chat_messages_stream(
                    base_url="http://localhost/v1",
                    api_key="test-key",
                    query="hello",
                    conversation_id="old-stream-upstream",
                )
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["conversation_id"], "new-stream-upstream")
        self.assertEqual(mock_urlopen.call_count, 2)
        first_payload = json.loads(mock_urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        second_payload = json.loads(mock_urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertEqual(first_payload.get("conversation_id"), "old-stream-upstream")
        self.assertNotIn("conversation_id", second_payload)


if __name__ == "__main__":
    unittest.main()
