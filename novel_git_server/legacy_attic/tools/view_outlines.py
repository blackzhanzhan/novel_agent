import json
from pathlib import Path

# 读取 database.json
db_path = Path(__file__).parent / "database.json"
with open(db_path, encoding="utf-8") as f:
    data = json.load(f)

outlines = data.get("outlines", [])

print(f"\n📚 共有 {len(outlines)} 个已保存的梗概\n")
print("=" * 80)

for i, outline in enumerate(outlines, 1):
    print(f"\n梗概 #{i}")
    print(f"ID: {outline['outline_id']}")
    print(f"标题: {outline['title']}")
    print(f"创建时间: {outline['created_at']}")
    print(f"内容长度: {len(outline['content'])} 字符")
    print(f"\n内容预览（前200字）:")
    print(outline['content'][:200] + "...")
    print("-" * 80)

print(f"\n💡 提示：完整内容已保存在 {db_path}")
