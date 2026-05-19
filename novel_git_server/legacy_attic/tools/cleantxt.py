import re

def clean_novel_data(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. 清理干扰项：删除那种长长的横线或等号
    # 匹配一行里全是 - 或 = 的情况
    content = re.sub(r'\n[-=]{3,}\n', '\n', content)

    # 2. 关键一步：特征注入 (Feature Injection)
    # 找到所有的 "第x章"，在它前面强行插入一个唯一的分割Token
    # 这里的 "|||CHAPTER_START|||" 就是我们要给 Dify 看的信号
    # \1 代表保留原本的 "第x章" 标题
    processed_content = re.sub(r'(第\d+章.*?)', r'\n\n|||CHAPTER_START|||\1', content)

    # 3. 再次清理多余空行 (变成紧凑模式)
    processed_content = re.sub(r'\n{3,}', '\n\n', processed_content)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(processed_content)
    
    print(f"处理完成！请上传 {output_file} 到 Dify")

# 使用方法：把文件名换成你的
clean_novel_data('重生CS：我的天命是签donk.txt', '重生CS_清洗版.txt')