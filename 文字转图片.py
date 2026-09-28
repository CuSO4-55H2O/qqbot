import os
from win32com import client
from pdf2image import convert_from_path


def word_to_png(input_file, output_file):
    """
    将 Word 文件转换为 PNG 图片，保持格式。

    参数:
    input_file: str, 输入的 Word 文件路径。
    output_file: str, 输出的 PNG 图片路径。
    """
    # 检查文件是否存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"输入文件不存在: {input_file}")

    # 确保文件是 Word 格式
    if not input_file.lower().endswith(('.docx', '.doc')):
        raise ValueError("输入文件必须为 Word 格式 (.docx 或 .doc)")

    # 使用 win32com 打开 Word
    word = client.Dispatch("Word.Application")
    try:
        doc = word.Documents.Open(input_file)
        temp_pdf = os.path.splitext(input_file)[0] + ".pdf"  # 临时 PDF 路径
        doc.SaveAs(temp_pdf, FileFormat=17)  # 将 Word 保存为 PDF
        doc.Close()
    finally:
        #word.Quit()
        0

    # 将 PDF 转换为 PNG
    images = convert_from_path(temp_pdf)
    images[0].save(output_file, "PNG")  # 保存第一页为 PNG

    # 删除临时 PDF 文件
    os.remove(temp_pdf)
    print(f"成功将 {input_file} 转换为图片 {output_file}")

def generate_image():
    placex = os.path.dirname(os.getcwd())
    input_word = placex+r"/文档/帮助.docx"  # 替换为实际路径
    output_png = placex+r"/图片/帮助.png"  # 替换为实际路径
    word_to_png(input_word, output_png)
    input_word = placex+r"/文档/管理员帮助.docx"  # 替换为实际路径
    output_png = placex+r"/图片/管理员帮助.png"  # 替换为实际路径
    word_to_png(input_word, output_png)

if __name__ == "__main__":
    generate_image()
