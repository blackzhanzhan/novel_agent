from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from utils.chapter_length import split_chapter_spans


RULE_FENCE_RE = re.compile(r"```([^\n\r`]*)[\r\n]+(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class TextScope:
    kind: str
    title: str
    text: str
    start_line: int
    end_line: int


def extract_domain_rules(markdown: str) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, match in enumerate(RULE_FENCE_RE.finditer(markdown), start=1):
        info = match.group(1).strip().casefold()
        if not any(token in info for token in {"domain-rule", "domain_rules", "domain-rules"}):
            continue
        raw_block = match.group(2).strip()
        if not raw_block:
            continue
        try:
            parsed = json.loads(raw_block)
        except json.JSONDecodeError as exc:
            errors.append({"block": index, "code": "INVALID_JSON", "message": str(exc)})
            continue

        candidates = parsed.get("rules") if isinstance(parsed, dict) and isinstance(parsed.get("rules"), list) else parsed
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not isinstance(candidates, list):
            errors.append({"block": index, "code": "INVALID_RULE_BLOCK", "message": "rule block must be an object or a rules array"})
            continue
        for candidate in candidates:
            if isinstance(candidate, dict):
                rules.append(candidate)
            else:
                errors.append({"block": index, "code": "INVALID_RULE", "message": "rule must be an object"})
    return {"rules": rules, "parse_errors": errors}


def validate_domain_rules(markdown: str, rules_markdown: str) -> dict[str, Any]:
    extracted = extract_domain_rules(rules_markdown)
    violations: list[dict[str, Any]] = []
    for index, rule in enumerate(extracted["rules"], start=1):
        violations.extend(_validate_rule(markdown, rule, index))
    return {
        "ok": not violations and not extracted["parse_errors"],
        "rule_count": len(extracted["rules"]),
        "violation_count": len(violations),
        "parse_errors": extracted["parse_errors"],
        "violations": violations,
    }


def _validate_rule(markdown: str, rule: dict[str, Any], index: int) -> list[dict[str, Any]]:
    rule_type = _normalize_token(rule.get("type"))
    if rule_type == "forbidden_terms":
        return _validate_forbidden_terms(markdown, rule, index)
    if rule_type == "context_forbidden_terms":
        return _validate_context_forbidden_terms(markdown, rule, index)
    if rule_type == "regex_forbidden":
        return _validate_regex_forbidden(markdown, rule, index)
    if rule_type == "ordered_patterns_forbidden":
        return _validate_ordered_patterns_forbidden(markdown, rule, index)
    return [
        _base_violation(
            rule,
            index,
            code="UNKNOWN_RULE_TYPE",
            message=f"Unsupported domain rule type: {rule.get('type')!r}",
            scope=TextScope("document", "全文", markdown, 1, max(1, markdown.count("\n") + 1)),
            evidence="",
        )
    ]


def _validate_forbidden_terms(markdown: str, rule: dict[str, Any], index: int) -> list[dict[str, Any]]:
    terms = _string_list(rule.get("terms") or rule.get("forbidden_terms"))
    if not terms:
        return [_invalid_rule(rule, index, "terms or forbidden_terms must contain at least one string")]
    literal_err = _literal_terms_error(terms)
    if literal_err:
        return [_invalid_rule(rule, index, literal_err)]
    violations: list[dict[str, Any]] = []
    for scope in _iter_scopes(markdown, _scope_kind(rule)):
        lowered = scope.text.casefold()
        for term in terms:
            pos = lowered.find(term.casefold())
            if pos >= 0:
                violations.append(
                    _base_violation(
                        rule,
                        index,
                        code="FORBIDDEN_TERM",
                        message=_rule_message(rule, f"Forbidden term found: {term}"),
                        scope=scope,
                        evidence=_evidence(scope.text, pos, len(term)),
                        terms=[term],
                    )
                )
    return violations


def _validate_context_forbidden_terms(markdown: str, rule: dict[str, Any], index: int) -> list[dict[str, Any]]:
    context_value = rule.get("context_terms")
    if context_value is None:
        context_value = rule.get("include_terms")
    if context_value is None:
        context_value = rule.get("context")
    forbidden_value = rule.get("forbidden_terms")
    if forbidden_value is None:
        forbidden_value = rule.get("terms")

    if not isinstance(context_value, list):
        return [_invalid_rule(rule, index, "context_forbidden_terms requires context_terms as a list of literal strings")]
    if not isinstance(forbidden_value, list):
        return [_invalid_rule(rule, index, "context_forbidden_terms requires forbidden_terms as a list of literal strings")]

    context_terms = _string_list(context_value)
    forbidden_terms = _string_list(forbidden_value)
    if not context_terms or not forbidden_terms:
        return [_invalid_rule(rule, index, "context_terms and forbidden_terms are required")]
    literal_err = _literal_terms_error([*context_terms, *forbidden_terms])
    if literal_err:
        return [_invalid_rule(rule, index, literal_err)]
    window_chars = _positive_int(rule.get("window_chars"))
    violations: list[dict[str, Any]] = []
    for scope in _iter_scopes(markdown, _scope_kind(rule)):
        lowered = scope.text.casefold()
        context_hits = [_find_term(lowered, term) for term in context_terms]
        if any(hit < 0 for hit in context_hits):
            continue
        for forbidden in forbidden_terms:
            forbidden_hit = _find_term(lowered, forbidden)
            if forbidden_hit < 0:
                continue
            if window_chars is not None and all(abs(forbidden_hit - hit) > window_chars for hit in context_hits):
                continue
            violations.append(
                _base_violation(
                    rule,
                    index,
                    code="CONTEXT_FORBIDDEN_TERM",
                    message=_rule_message(rule, f"Forbidden term found in context: {forbidden}"),
                    scope=scope,
                    evidence=_evidence(scope.text, forbidden_hit, len(forbidden)),
                    terms=[*context_terms, forbidden],
                )
            )
    return violations


def _validate_regex_forbidden(markdown: str, rule: dict[str, Any], index: int) -> list[dict[str, Any]]:
    patterns = _string_list(rule.get("patterns") or rule.get("pattern") or rule.get("regex"))
    if not patterns:
        return [_invalid_rule(rule, index, "pattern or patterns must contain at least one regex string")]
    violations: list[dict[str, Any]] = []
    for scope in _iter_scopes(markdown, _scope_kind(rule)):
        for pattern in patterns:
            compiled, err = _compile_pattern(pattern, rule)
            if err:
                violations.append(_invalid_rule(rule, index, err, scope=scope))
                continue
            match = compiled.search(scope.text)
            if not match:
                continue
            violations.append(
                _base_violation(
                    rule,
                    index,
                    code="REGEX_FORBIDDEN",
                    message=_rule_message(rule, f"Forbidden pattern matched: {pattern}"),
                    scope=scope,
                    evidence=_evidence(scope.text, match.start(), max(1, match.end() - match.start())),
                    patterns=[pattern],
                )
            )
    return violations


def _validate_ordered_patterns_forbidden(markdown: str, rule: dict[str, Any], index: int) -> list[dict[str, Any]]:
    patterns = _string_list(rule.get("patterns"))
    if len(patterns) < 2:
        return [_invalid_rule(rule, index, "ordered_patterns_forbidden requires at least two patterns")]
    violations: list[dict[str, Any]] = []
    for scope in _iter_scopes(markdown, _scope_kind(rule)):
        cursor = 0
        matches: list[re.Match[str]] = []
        invalid = None
        for pattern in patterns:
            compiled, err = _compile_pattern(pattern, rule)
            if err:
                invalid = err
                break
            match = compiled.search(scope.text, cursor)
            if not match:
                matches = []
                break
            matches.append(match)
            cursor = max(match.end(), match.start() + 1)
        if invalid:
            violations.append(_invalid_rule(rule, index, invalid, scope=scope))
            continue
        if not matches:
            continue
        first = matches[0].start()
        last = matches[-1].end()
        violations.append(
            _base_violation(
                rule,
                index,
                code="ORDERED_PATTERNS_FORBIDDEN",
                message=_rule_message(rule, "Forbidden ordered pattern sequence matched"),
                scope=scope,
                evidence=_evidence(scope.text, first, max(1, last - first)),
                patterns=patterns,
            )
        )
    return violations


def _iter_scopes(markdown: str, scope_kind: str) -> list[TextScope]:
    line_count = max(1, markdown.count("\n") + 1)
    if scope_kind == "document":
        return [TextScope("document", "全文", markdown, 1, line_count)]
    if scope_kind == "line":
        scopes: list[TextScope] = []
        for line_number, line in enumerate(markdown.splitlines(), start=1):
            scopes.append(TextScope("line", f"第{line_number}行", line, line_number, line_number))
        return scopes
    chapters = split_chapter_spans(markdown)
    if chapters:
        return [
            TextScope("chapter", span.title, span.content, span.content_start_line, span.end_line)
            for span in chapters
        ]
    return [TextScope("document", "全文", markdown, 1, line_count)]


def _base_violation(rule: dict[str, Any], index: int, *, code: str, message: str, scope: TextScope, evidence: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "rule_id": str(rule.get("id") or f"rule_{index}"),
        "rule_type": _normalize_token(rule.get("type")) or "unknown",
        "severity": str(rule.get("severity") or "warning"),
        "code": code,
        "message": message,
        "scope": scope.kind,
        "scope_title": scope.title,
        "start_line": scope.start_line,
        "end_line": scope.end_line,
        "evidence": evidence,
    }
    payload.update(extra)
    return payload


def _invalid_rule(rule: dict[str, Any], index: int, message: str, scope: TextScope | None = None) -> dict[str, Any]:
    fallback_scope = scope or TextScope("document", "规则文件", "", 1, 1)
    return _base_violation(rule, index, code="INVALID_RULE", message=message, scope=fallback_scope, evidence="")


def _compile_pattern(pattern: str, rule: dict[str, Any]) -> tuple[re.Pattern[str], str | None]:
    flags = re.MULTILINE
    if rule.get("ignore_case", True) is not False:
        flags |= re.IGNORECASE
    try:
        return re.compile(pattern, flags), None
    except re.error as exc:
        return re.compile(r"$^"), f"invalid regex {pattern!r}: {exc}"


def _evidence(text: str, start: int, length: int) -> str:
    if start < 0:
        return ""
    left = max(0, start - 80)
    right = min(len(text), start + max(length, 1) + 80)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return prefix + text[left:right].replace("\n", "\\n") + suffix


def _scope_kind(rule: dict[str, Any]) -> str:
    kind = _normalize_token(rule.get("scope"))
    return kind if kind in {"document", "chapter", "line"} else "chapter"


def _rule_message(rule: dict[str, Any], fallback: str) -> str:
    message = rule.get("message")
    return message.strip() if isinstance(message, str) and message.strip() else fallback


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().casefold()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        token = item if isinstance(item, str) else str(item)
        token = token.strip()
        if token:
            output.append(token)
    return output


def _literal_terms_error(terms: list[str]) -> str | None:
    regex_markers = ["*", "+", "?", "[", "]", "{", "}", "|", "\\", "^", "$"]
    for term in terms:
        if any(marker in term for marker in regex_markers):
            return f"literal term {term!r} contains regex syntax; use regex_forbidden patterns instead"
    return None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _find_term(folded_text: str, term: str) -> int:
    return folded_text.find(term.casefold())
