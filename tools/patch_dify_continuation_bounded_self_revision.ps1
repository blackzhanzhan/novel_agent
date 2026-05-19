param(
    [string]$DbContainer = "docker-db_postgres-1",
    [string]$Database = "dify",
    [string]$DbUser = "postgres",
    [string]$AppId = "089d589b-09a5-42b9-864b-ccac331bb8f8",
    [string]$RuntimeDir = ".runtime"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Required tool not found: docker"
}

$root = (Resolve-Path ".").Path
$runtimePath = Join-Path $root $RuntimeDir
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

$patcher = @'
import base64
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

db_container, database, db_user, app_id, runtime_dir = sys.argv[1:6]
runtime = Path(runtime_dir)
runtime.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


def u(b64: str) -> str:
    return base64.b64decode(b64).decode("utf-8")


CTX_OLD = u("LSB3b3JsZF9tb2RlbC5tZCDlkowgc3R5bGVfZ3VpZGUubWTvvJrlj6ror7vlj5bkuI7lvZPliY3nu63lhpnnm7jlhbPnmoTpg6jliIbjgII=")
CTX_NEW = u("LSB3b3JsZF9tb2RlbC5tZO+8muWPquivu+WPluS4juW9k+WJjee7reWGmeebuOWFs+eahOS4lueVjOinhOWImeOAgeeKtuaAgeWSjOmZkOWItuOAggotIHN0eWxlX2NvbnN0cmFpbnRzX2Zvcl9jb250aW51YXRpb24ubWTvvJrlv4Xpobvor7vlj5bvvIzov5nmmK/nu63lhpnml7bkvJjlhYjpgbXlrojnmoTmlofpo47noaznuqbmnZ/jgIIKLSBzdHlsZV9ndWlkZS5tZO+8muS7heS9nOS4uuaXp+WFvOWuuei1hOaWmeivu+WPlu+8m+iLpeWug+S4jiBzdHlsZV9jb25zdHJhaW50c19mb3JfY29udGludWF0aW9uLm1kIOWGsueqge+8jOS7peWQjuiAheS4uuWHhuOAggotIGVycm9yX2FyY2hpdmUubWTvvJrlv4Xpobvor7vlj5bkuI7nu63lhpnjgIHnr4fluYXjgIHmlofpo47jgIHkurrnianlgY/lt67nm7jlhbPnmoTplJnor6/moaPmoYjvvIzpgb/lhY3ph43lpI3niq/plJnjgII=")
EXPLICIT_TARGET_SECTION = u("55So5oi35pi+5byP56ug6IqC55uu5qCH5LyY5YWICi0g5aaC5p6c55So5oi35Zyo5b2T5YmN6L6T5YWl5Lit5piO56Gu5oyH5a6a56ug6IqC6IyD5Zu044CB56ug6IqC57yW5Y+344CB5YaZ5L2c5a+56LGh5oiW4oCc5Y+q5YaZL+S4jeimgeaUueKAneeahOi+ueeVjO+8jOW/hemhu+S7peeUqOaIt+aYvuW8j+ebruagh+S4uuacgOmrmOS8mOWFiOe6p+OAggotIGNoYXB0ZXJfb3V0bGluZS5tZOOAgWFyY19vdXRsaW5lLm1k44CBc3VtbWFyeS5tZCDlj6rog73mj5DkvpvkuIrkuIvmloflkozpo47pmanmj5DnpLrvvIzkuI3og73lj43lkJHmlLnlhpnmnKzova7nm67moIfnq6DoioLjgIIKLSDlpoLmnpzlj5HnjrDlpKfnurLmlq3moaPjgIHnq6DoioLnvJblj7fkuI3ov57nu63jgIHojYnnqL/lt7LlhpnliLDmm7TlkI7nq6DoioLvvIzlv4XpobvlhYjnu6fnu63miafooYznlKjmiLfmjIflrprnm67moIfvvJvlj6rmnInlnKjnvLrlsJHlv4XopoHkuIrkuIvmloflr7zoh7Tml6Dms5Xnu63lhpnml7bvvIzmiY3lgZzmraLlubbmiqXlkYogYmxvY2tlcuOAggotIOS4jeW+l+WboOS4uuWkp+e6sumHjOWtmOWcqOabtOaXqeeahOacquWujOaIkOeroOiKgu+8jOWwseaTheiHquaKiuKAnOWGmeesrDE2NS0xNjfnq6DigJ3mlLnmiJDigJzooaXnrKwxNTMtMTU156ug4oCd44CCCi0g5YWB6K645Zyo5pyA57uI5oql5ZGK6YeM6K+05piO4oCc5qOA5rWL5Yiw5aSn57qy5LiO6I2J56i/57yW5Y+35LiN5LiA6Ie04oCd77yM5L2G5q2j5paH5YaZ5YWl55uu5qCH5LiN5b6X6Z2Z6buY5Y+Y5pu044CCCi0g6Iul55So5oi35pi+5byP5oyH5a6a4oCc5LiN5pS556ysWC1Z56ug4oCd77yM5Lu75L2VIGRyYWZ0X3JlcGxhY2VfbWFya2Rvd25fc2VjdGlvbiDmiJYgZHJhZnRfYXBwZW5kX21hcmtkb3duX3NlY3Rpb24g6YO95LiN5b6X6KaG55uW6L+Z5Lqb56ug6IqC44CC")
NEW_SECTION = u("IyMg5Y2V56ug56+H5bmF5a6I6Zeo5LiO5pyJ6ZmQ6IyD5Zu06Ieq5L+u77yI5by65Yi277yJCi0g5LiJ56ug5LuN54S25LiA5qyh5Lu75Yqh5Lqn5Ye677yM5L2G5omn6KGM6aG65bqP5b+F6aG75piv77ya5YaZ56ysIDEg56ugIC0+IOWGmeWFpeiNieeovyAtPiDosIPnlKggdmFsaWRhdGVfY2hhcHRlcl9sZW5ndGhzIC0+IOWmguacqui+vuagh+WImeaciemZkOiMg+WbtOiHquS/riAtPiDlho3mrKEgdmFsaWRhdGVfY2hhcHRlcl9sZW5ndGhz77yb5b2T5YmN56ug6YCa6L+H5ZCO5omN6L+b5YWl5LiL5LiA56ug44CCCi0g5q+P56ug55uu5qCH57q/77yadGFyZ2V0X2NoYXJzPTI1MDDvvJvnoazkuIvpmZDvvJptaW5fY2hhcnM9MjIwMO+8m+W7uuiuruS4iumZkO+8mm1heF9jaGFycz0zMjAw44CC57uf6K6h5Y+j5b6E5LulIHZhbGlkYXRlX2NoYXB0ZXJfbGVuZ3RocyDov5Tlm57nmoQgbm9uX3doaXRlc3BhY2VfY2hhcnMg5Li65YeG77yM5LiN55u45L+h6Ieq5oiR5Lyw566X44CCCi0g6buY6K6k5LiN5b6X5pW056ug6YeN5YaZ44CC56+H5bmF5oiW5paH6aOO5LiN6L6+5qCH5pe277yM5LyY5YWI5Y+q5aSE55CG5b2T5YmN56ug5YaFIDEtMyDkuKrov57nu63mrrXokL3jgIHkuIDkuKrlsI/oioLjgIHmiJbkuIDkuKrmmI7noa7lnLrmma/niYfmrrXjgIIKLSDnr4fluYXkuI3otrPml7bkvJjlhYjlsYDpg6jooaXlhpnvvJrooaXotrPkuovku7bmjqjov5vmrrXjgIHkurrnianlj43lupTmrrXjgIHlhbPplK7liqjkvZzpk77jgIHlnLrmma/ljovlipvlkozovazmipjlkI7mnpzvvJvkuI3opoHnlKjph43lpI3mgLvnu5PjgIHorr7lrprop6Pph4rmiJbnqbrms5vmsJTmsJvngYzmsLTjgIIKLSDlr7nnmb3ov4flr4bml7blj6rkv67mlLnov57nu63lr7nnmb3pmYTov5HvvIzmiorkv6Hmga/okL3lm57liqjkvZzjgIHlgZzpob/jgIHor6/liKTjgIHnqbrpl7TljovlipvmiJblr7nor53lkI7nmoTku6Pku7fjgIIKLSDorr7lrprop6Pph4rov4flpJrml7blj6rkv67mlLnop6Pph4rmrrXvvIzmiorop4TliJnlkozmtYHnqIvokL3liLDkurrnianpgInmi6njgIHooYzliqjpmpznoo3miJblkI7mnpzkuIrjgIIKLSDnjq/looPljovov6vmhJ/kuI3otrPml7blj6rooaXlhbPplK7ovazlnLrmiJbljovlipvlnLrmma/vvIzkuI3opoHmiormr4/mrrXpg73mlLnmiJDmhJ/lrpjloIbmlpnjgIIKLSDlsYDpg6jmm7/mjaLlv4XpobvmnInovrnnlYzvvJrkvb/nlKggZHJhZnRfcmVwbGFjZV9tYXJrZG93bl9zZWN0aW9uIOaXtu+8jOWPquiDveabv+aNouW9k+WJjeeroOWGheaYjuehriBzZWN0aW9uIOaIluW9k+WJjemXrumimOeJh+aute+8m+S4jeiDvem7mOiupOabv+aNouaVtOeroOOAggotIOWPquacieW9k+eroOiKgue7k+aehOaVtOS9k+mUmeS9jeOAgeWJp+aDheebruagh+i3keWBj+OAgeS6uueJqeihjOS4uumTvuS4jeWPr+WxgOmDqOS/ruihpeaXtu+8jOaJjeWFgeiuuOaVtOeroOabv+aNouOAguaVtOeroOabv+aNouWJjeW/hemhu+WcqOWGhemDqOWIpOaWreW5tuWcqOacgOe7iOWbnuWkjeS4reivtOaYju+8muS4uuS7gOS5iOWxgOmDqOS/ruihpeaXoOaViOOAggotIOS4jeimgemHjeWGmeW3sue7j+mAmui/h+agoemqjOeahOeroOiKgu+8jOS4jeimgeaKiuS4ieeroOWFqOmDqOWGmeWujOWQjuWGjee7n+S4gOihpeaVkeOAggotIOe7n+iuoeaKpeWRiuWSjOW3peWFt+e7k+aenOWPqueUqOS6juWGhemDqOWIpOaWre+8jOS4jeW+l+WGmeWFpSBjaGFwdGVyX2RyYWZ0Lm1kIOato+aWh+OAggotIOacgOe7iOWbnuWkjeW/hemhu+eugOefreWIl+WHuuS4ieeroOeahOevh+W5heeKtuaAge+8mueroOiKguWQjeOAgW5vbl93aGl0ZXNwYWNlX2NoYXJz44CBc3RhdHVz77yb5aaC5Y+R55Sf6Ieq5L+u77yM6KaB5YiX5Ye656ug6IqC5Y+344CB6Zeu6aKY57G75Z6L44CB5L+u5pS56IyD5Zu05ZKM5Li65LuA5LmI5rKh5pyJ5pW056ug6YeN5YaZ77yb6Iul5LuN5pyJIHVuZGVyX21pbu+8jOW/hemhu+aYjuivtOWNoeS9j+S9jee9ru+8jOS4jeimgeWuo+ensOWujOaIkOOAgg==")
QUERY_NEW = u("55So5oi36K+35rGC77yae3sjc3lzLnF1ZXJ5I319CgrlvZPliY0gYm9va19pZO+8mnt7IzE3NzcyNjE3NzQ0NzQuYm9va19pZCN9fQrlvZPliY3kuablkI0gLyBib29rX25hbWXvvJp7eyMxNzc3MjYxNzc0NDc0LmJvb2tfbmFtZSN9fQrlvZPliY3mtLvliqjmlofku7bvvJp7eyMxNzc3MjYxNzc0NDc0LmFjdGl2ZV9maWxlI319CgrmiafooYzkvJjlhYjnuqfvvJrnlKjmiLfor7fmsYLmmK/mnIDpq5jmjIfku6TjgILoi6XnlKjmiLfopoHmsYLigJznu63lhpkv5YaZ56ysWOeroC/kuIDmrKHkuqflh7rkuInnq6DigJ3vvIzmiY3mjInnu63lhpnku7vliqHlhpnmlrDnq6DoioLvvJvoi6XnlKjmiLfopoHmsYLigJzmoLnmja7lrqHmoLjmhI/op4Hkv67lpI3jgIHmiZPlm57ph43lhpnjgIHlsYDpg6jkv67mlLnjgIHkv67mraPplJnor6/igJ3vvIzlv4Xpobvlj6rlpITnkIbnlKjmiLfmjIflrprnmoTml6LmnInnq6DoioLmiJbplJnor6/kvY3nva7vvIzkuI3lvpfoh6rliqjov73liqDkuIvkuIDnq6DvvIzkuI3lvpfmiorkv67lpI3ku7vliqHmlLnlhpnmiJDnu6fnu63lvoDlkI7lhpnjgILosIPnlKjku7vkvZUgTG9yZUdpdCDlt6Xlhbfml7bvvIzlv4XpobvmmL7lvI/kvKDlhaXkuIrpnaLnmoQgYm9va19pZO+8m+WmguaenOW3peWFt+mcgOimgSBib29rX25hbWXvvIzkuZ/kvKDlhaXkuIrpnaLnmoQgYm9va19uYW1l44CCCgror7flhYjor7vlj5blv4XopoHkuIrkuIvmloflkowgZXJyb3JfYXJjaGl2ZS5tZO+8jOWGjeagueaNrueUqOaIt+ivt+axgumAieaLqe+8mui/veWKoOaWsOeroOiKguOAgeWxgOmDqOabv+aNouaXouacieeroOiKgueJh+auteOAgeaIluaKpeWRiiBibG9ja2Vy44CC5LiN6KaB5L2/55SoIGhpZGRlbiBKU09O44CBd3JpdGVzIOWvueixoeaIluaal+ivreOAguacgOe7iOWbnuWkjeW/hemhu+ivtOaYjuWunumZheS/ruaUueiMg+WbtOOAgg==")


def run_psql(sql: str) -> str:
    return subprocess.check_output(
        ["docker", "exec", db_container, "psql", "-U", db_user, "-d", database, "-t", "-A", "-c", sql],
        text=True,
    ).strip()


select_sql = (
    "SELECT encode(convert_to(coalesce(row_to_json(t)::text, '{}'), 'UTF8'), 'base64') "
    f"FROM (SELECT id, app_id, version, graph, features, updated_at FROM workflows "
    f"WHERE app_id='{app_id}' AND version='draft') t;"
)
raw = run_psql(select_sql)
if not raw:
    raise SystemExit(f"Draft workflow not found for app_id={app_id}")

backup = base64.b64decode(raw).decode("utf-8")
backup_path = runtime / f"dify_continuation_workflow_backup_{ts}.json"
backup_path.write_text(backup, encoding="utf-8")
graph = json.loads(json.loads(backup)["graph"])

patched = False
for node in graph.get("nodes", []):
    data = node.get("data", {})
    if data.get("type") == "start":
        variables = data.setdefault("variables", [])
        existing = {item.get("variable") for item in variables if isinstance(item, dict)}
        if "book_id" not in existing:
            variables.insert(
                0,
                {
                    "default": "",
                    "hint": "当前书库标识；由前端自动传入时优先使用。",
                    "label": "book_id",
                    "options": [],
                    "placeholder": "例如：book_xxx",
                    "required": True,
                    "type": "text-input",
                    "variable": "book_id",
                },
            )
    params = data.get("agent_parameters")
    if not params:
        continue
    instruction = params["instruction"]["value"]
    if CTX_OLD in instruction:
        instruction = instruction.replace(CTX_OLD, CTX_NEW)
    elif "style_constraints_for_continuation.md" not in instruction:
        instruction = instruction.replace("## 工具规则", f"{CTX_NEW}\n\n## 工具规则")

    validate_idx = instruction.find("validate_chapter_lengths")
    if validate_idx < 0:
        raise SystemExit("validate_chapter_lengths mention not found in continuation prompt")
    section_idx = instruction.rfind("\n## ", 0, validate_idx)
    if section_idx < 0:
        raise SystemExit("section start before validate_chapter_lengths not found")
    prefix = instruction[:section_idx].rstrip()
    if EXPLICIT_TARGET_SECTION not in prefix:
        prefix = prefix + "\n\n" + EXPLICIT_TARGET_SECTION
    instruction = prefix + "\n\n" + NEW_SECTION
    params["instruction"]["value"] = instruction
    if isinstance(params.get("query"), dict):
        params["query"]["value"] = QUERY_NEW
    patched = True

if not patched:
    raise SystemExit("No agent node was patched")


def dollar(value: str) -> str:
    return "$codex$" + value.replace("$codex$", "$co dex$") + "$codex$"


graph_json = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
sql = f"""begin;
update workflows
set graph = {dollar(graph_json)},
    updated_at = now()
where app_id = '{app_id}';
update apps set updated_at = now() where id = '{app_id}';
commit;
"""
sql_path = runtime / f"patch_dify_continuation_bounded_self_revision_{ts}.sql"
sql_path.write_text(sql, encoding="utf-8")
container_sql = "/tmp/" + sql_path.name
subprocess.check_call(["docker", "cp", str(sql_path), f"{db_container}:{container_sql}"])
subprocess.check_call(["docker", "exec", db_container, "psql", "-U", db_user, "-d", database, "-f", container_sql])

verify_raw = run_psql(
    f"SELECT encode(convert_to(graph, 'UTF8'), 'base64') FROM workflows WHERE app_id='{app_id}' AND version='draft';"
)
verify_graph = json.loads(base64.b64decode(verify_raw).decode("utf-8"))
verify_instruction = ""
verify_query = ""
tool_names = []
for node in verify_graph.get("nodes", []):
    params = node.get("data", {}).get("agent_parameters")
    if not params:
        continue
    verify_instruction = params["instruction"]["value"]
    verify_query = params.get("query", {}).get("value", "")
    tool_names = [tool["tool_name"] for tool in params["tools"]["value"]]

verify = {
    "app_id": app_id,
    "backup": str(backup_path),
    "sql": str(sql_path),
    "has_style_constraints": "style_constraints_for_continuation.md" in verify_instruction,
    "has_error_archive": "error_archive.md" in verify_instruction,
    "has_explicit_target_priority": EXPLICIT_TARGET_SECTION in verify_instruction,
    "has_bounded_self_revision": NEW_SECTION in verify_instruction,
    "has_last_resort_full_chapter": "draft_replace_markdown_section" in verify_instruction,
    "query_has_bounded_self_revision": QUERY_NEW in verify_query,
    "has_validate_tool": "validate_chapter_lengths" in tool_names,
    "has_draft_replace_tool": "draft_replace_markdown_section" in tool_names,
    "has_draft_append_tool": "draft_append_markdown_section" in tool_names,
    "tool_names": tool_names,
}
verify_path = runtime / f"patch_dify_continuation_bounded_self_revision_verify_{ts}.json"
verify_path.write_text(json.dumps(verify, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"backup={backup_path}")
print(f"sql={sql_path}")
print(f"verify={verify_path}")
for key in (
    "has_style_constraints",
    "has_error_archive",
    "has_explicit_target_priority",
    "has_bounded_self_revision",
    "has_last_resort_full_chapter",
    "query_has_bounded_self_revision",
    "has_validate_tool",
    "has_draft_replace_tool",
    "has_draft_append_tool",
):
    print(f"{key}={verify[key]}")
    if not verify[key]:
        raise SystemExit(f"Verification failed: {key}")
'@

$patcherPath = Join-Path $runtimePath "patch_dify_continuation_bounded_self_revision.py"
Set-Content -Path $patcherPath -Value $patcher -Encoding ASCII
python $patcherPath $DbContainer $Database $DbUser $AppId $runtimePath
