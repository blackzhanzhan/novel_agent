import json
import logging
import os
import socket
import tempfile
from typing import Any, Callable, Iterator
from urllib import error, request

import requests as _requests

logger = logging.getLogger(__name__)


class DifyClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def _is_missing_conversation_error(exc: DifyClientError) -> bool:
    if exc.status_code != 404:
        return False
    raw_body = exc.response_body or ""
    message = raw_body
    try:
        parsed = json.loads(raw_body) if raw_body else {}
        if isinstance(parsed, dict):
            raw_message = parsed.get("message")
            if isinstance(raw_message, str):
                message = raw_message
    except json.JSONDecodeError:
        pass
    return "conversation not exists" in message.lower()


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip()
    if not normalized:
        raise DifyClientError("Dify base URL is required")
    return normalized.rstrip("/")


def _build_payload(
    *,
    query: str,
    inputs: dict[str, Any] | None,
    user: str,
    conversation_id: str | None,
    response_mode: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "inputs": inputs or {},
        "query": query,
        "response_mode": response_mode,
        "user": user,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return payload


def _post_json(
    *,
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    accept: str = "application/json",
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    if not api_key or not api_key.strip():
        raise DifyClientError("DIFY_API_KEY is required")

    raw_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=raw_data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": accept,
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise DifyClientError(
            f"Dify API returned HTTP {exc.code}",
            status_code=exc.code,
            response_body=body,
        ) from exc
    except error.URLError as exc:
        raise DifyClientError(f"Dify API network error: {exc.reason}") from exc
    except socket.timeout as exc:
        raise DifyClientError("Dify API request timed out") from exc

    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise DifyClientError("Dify API returned invalid JSON", response_body=body) from exc

    if not isinstance(parsed, dict):
        raise DifyClientError("Dify API returned non-object JSON", response_body=body)
    return parsed


def _parse_sse_event(lines: list[str]) -> dict[str, Any] | None:
    if not lines:
        return None

    event_name = "message"
    event_id: str | None = None
    data_parts: list[str] = []
    retry: int | None = None

    for line in lines:
        if line.startswith(":"):
            continue
        if ":" not in line:
            field = line
            value = ""
        else:
            field, value = line.split(":", 1)
            if value.startswith(" "):
                value = value[1:]

        if field == "event":
            event_name = value or "message"
        elif field == "id":
            event_id = value
        elif field == "retry":
            try:
                retry = int(value)
            except ValueError:
                retry = None
        elif field == "data":
            data_parts.append(value)

    if not data_parts and event_name == "message":
        return None

    raw_data = "\n".join(data_parts)
    parsed_data: Any
    if raw_data == "[DONE]":
        parsed_data = {"done": True}
    else:
        try:
            parsed_data = json.loads(raw_data) if raw_data else {}
        except json.JSONDecodeError:
            parsed_data = {"raw": raw_data}

    event: dict[str, Any] = {
        "event": event_name,
        "data": parsed_data,
        "raw_data": raw_data,
    }
    if event_id is not None:
        event["id"] = event_id
    if retry is not None:
        event["retry"] = retry
    return event


def chat_messages(
    *,
    base_url: str,
    api_key: str,
    query: str,
    inputs: dict[str, Any] | None = None,
    user: str = "loregit",
    conversation_id: str | None = None,
    response_mode: str = "blocking",
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    if not api_key or not api_key.strip():
        raise DifyClientError("DIFY_API_KEY is required")

    endpoint = f"{_normalize_base_url(base_url)}/chat-messages"
    payload = _build_payload(
        query=query,
        inputs=inputs,
        user=user,
        conversation_id=conversation_id,
        response_mode=response_mode,
    )

    try:
        return _post_json(
            endpoint=endpoint,
            api_key=api_key,
            payload=payload,
            accept="application/json",
            timeout_seconds=timeout_seconds,
        )
    except DifyClientError as exc:
        if conversation_id and _is_missing_conversation_error(exc):
            retry_payload = _build_payload(
                query=query,
                inputs=inputs,
                user=user,
                conversation_id=None,
                response_mode=response_mode,
            )
            return _post_json(
                endpoint=endpoint,
                api_key=api_key,
                payload=retry_payload,
                accept="application/json",
                timeout_seconds=timeout_seconds,
            )
        raise


def upload_file(
    *,
    base_url: str,
    api_key: str,
    file_path: str,
    user: str = "loregit",
    timeout_seconds: int = 60,
) -> str:
    """Upload a file to Dify and return the upload_file_id."""
    if not api_key or not api_key.strip():
        raise DifyClientError("DIFY_API_KEY is required")
    endpoint = f"{_normalize_base_url(base_url)}/files/upload"
    try:
        with open(file_path, "rb") as f:
            resp = _requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key.strip()}"},
                files={"file": (os.path.basename(file_path), f, "text/plain; charset=utf-8")},
                data={"user": user},
                timeout=timeout_seconds,
            )
        resp.raise_for_status()
        result = resp.json()
        file_id = result.get("id")
        if not file_id:
            raise DifyClientError(f"Dify upload returned no id: {resp.text[:200]}")
        logger.info("Uploaded %s to Dify: id=%s size=%d", file_path, file_id, result.get("size", 0))
        return file_id
    except _requests.RequestException as exc:
        raise DifyClientError(f"Dify file upload failed: {exc}") from exc


def chat_messages_with_file(
    *,
    base_url: str,
    api_key: str,
    query: str,
    upload_file_id: str,
    inputs: dict[str, Any] | None = None,
    user: str = "loregit",
    conversation_id: str | None = None,
    response_mode: str = "blocking",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Call chat-messages with an uploaded file reference.

    Two-step flow: upload_file() first to get upload_file_id,
    then this function to trigger the workflow with the file attached.
    """
    if not api_key or not api_key.strip():
        raise DifyClientError("DIFY_API_KEY is required")

    endpoint = f"{_normalize_base_url(base_url)}/chat-messages"
    payload = _build_payload(
        query=query,
        inputs=inputs or {},
        user=user,
        conversation_id=conversation_id,
        response_mode=response_mode,
    )
    payload["files"] = [
        {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": upload_file_id,
        }
    ]

    return _post_json(
        endpoint=endpoint,
        api_key=api_key,
        payload=payload,
        accept="application/json",
        timeout_seconds=timeout_seconds,
    )


def stop_chat_message(
    *,
    base_url: str,
    api_key: str,
    task_id: str,
    user: str,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    normalized_task_id = (task_id or "").strip()
    if not normalized_task_id:
        raise DifyClientError("task_id is required")
    normalized_user = (user or "").strip()
    if not normalized_user:
        raise DifyClientError("user is required")

    endpoint = f"{_normalize_base_url(base_url)}/chat-messages/{normalized_task_id}/stop"
    return _post_json(
        endpoint=endpoint,
        api_key=api_key,
        payload={"user": normalized_user},
        accept="application/json",
        timeout_seconds=timeout_seconds,
    )


def chat_messages_stream(
    *,
    base_url: str,
    api_key: str,
    query: str,
    inputs: dict[str, Any] | None = None,
    user: str = "loregit",
    conversation_id: str | None = None,
    response_mode: str = "streaming",
    timeout_seconds: int = 90,
    on_conversation_reset: Callable[[str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    if not api_key or not api_key.strip():
        raise DifyClientError("DIFY_API_KEY is required")

    endpoint = f"{_normalize_base_url(base_url)}/chat-messages"
    attempt_conversation_id = conversation_id
    retried_without_conversation = False

    while True:
        payload = _build_payload(
            query=query,
            inputs=inputs,
            user=user,
            conversation_id=attempt_conversation_id,
            response_mode=response_mode,
        )
        raw_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=raw_data,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "text/event-stream",
            },
        )

        try:
            with request.urlopen(req, timeout=timeout_seconds) as resp:
                buffered_lines: list[str] = []
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line == "":
                        event = _parse_sse_event(buffered_lines)
                        if event is not None:
                            yield event
                        buffered_lines = []
                        continue
                    buffered_lines.append(line)

                tail_event = _parse_sse_event(buffered_lines)
                if tail_event is not None:
                    yield tail_event
            return
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            client_error = DifyClientError(
                f"Dify API returned HTTP {exc.code}",
                status_code=exc.code,
                response_body=body,
            )
            if attempt_conversation_id and not retried_without_conversation and _is_missing_conversation_error(client_error):
                if on_conversation_reset is not None:
                    on_conversation_reset(attempt_conversation_id)
                attempt_conversation_id = None
                retried_without_conversation = True
                continue
            raise client_error from exc
        except error.URLError as exc:
            raise DifyClientError(f"Dify API network error: {exc.reason}") from exc
        except socket.timeout as exc:
            raise DifyClientError("Dify API request timed out") from exc
