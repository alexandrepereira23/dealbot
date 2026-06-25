import re
import json
import asyncio
import google.generativeai as genai
from .config import Config

genai.configure(api_key=Config.GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-1.5-flash")

_PROMPT = """Você recebe o texto de uma mensagem de um canal de promoções.
Extraia os dados e responda APENAS com um JSON válido, sem markdown, no formato:
{{"titulo": "...", "preco": 0.0, "preco_original": 0.0 ou null,
  "cupom": "..." ou null, "link": "..." ou null, "categoria": "..."}}

A categoria deve ser uma destas: eletronicos, casa, moda, alimentos, beleza, games, outros.
Se não for uma promoção de produto, responda exatamente: {{"ignorar": true}}

Texto da mensagem:
\"\"\"{texto}\"\"\""""


async def extrair_produto(texto: str) -> dict | None:
    """Estrutura o texto da mensagem em um dict de produto, ou None."""
    try:
        resp = await asyncio.to_thread(
            _model.generate_content, _PROMPT.format(texto=texto)
        )
        raw = re.sub(r"^```json|```$", "", resp.text.strip()).strip()
        data = json.loads(raw)
        return None if data.get("ignorar") else data
    except Exception as e:
        print(f"[gemini] erro: {e}")
        return None
