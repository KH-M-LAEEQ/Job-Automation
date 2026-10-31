import io

import docx


def extract_text_from_docx(content: bytes) -> str:
    document = docx.Document(io.BytesIO(content))
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())
