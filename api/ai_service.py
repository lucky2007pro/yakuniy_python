"""Gemini 2.5 Flash bilan ishlash uchun yengil wrapper."""
import json
import logging
from typing import Iterable, List, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'

SYSTEM_PROMPT_DEFAULT = (
    "Siz TATU Kutubxona AI maslahatchisisiz. Vazifangiz — foydalanuvchiga "
    "kitob tanlash, o'qish bo'yicha yo'l-yo'riq va tavsiyalar berish. "
    "Asosiy qoidalar:\n"
    "1. Faqat O'ZBEK tilida javob bering.\n"
    "2. Qisqa, aniq va do'stona javob bering (3-6 jumla).\n"
    "3. Kitoblar ro'yxati berilgan bo'lsa, FAQAT shu ro'yxatdagi kitoblardan tavsiya qiling. "
    "Ro'yxatda yo'q kitobni tavsiya qilmang.\n"
    "4. Kitob tavsiya qilsangiz, sarlavhasini qalin (markdown **) qilib ko'rsating va muallifini yozing.\n"
    "5. Foydalanuvchi suhbat o'rtasida boshqa mavzuga o'tib ketsa, muloyimlik bilan kitoblar mavzusiga qaytaring.\n"
    "6. Hech qanday boshqa platformani tavsiya qilmang."
)


def _gemini_endpoint() -> str:
    model = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
    return f"{GEMINI_BASE}/{model}:generateContent"


def is_configured() -> bool:
    return bool(getattr(settings, 'GEMINI_API_KEY', ''))


def chat(
    user_message: str,
    history: Optional[Iterable[Dict[str, str]]] = None,
    book_catalog: Optional[Iterable[Dict[str, str]]] = None,
    system_prompt: str = SYSTEM_PROMPT_DEFAULT,
) -> Dict[str, str]:
    """
    Foydalanuvchining xabarini Gemini ga yuboradi.
    
    Parametrlar:
      user_message: foydalanuvchi yozgan matn
      history: [{"role": "user|model", "content": "..."}], oldingi xabarlar
      book_catalog: [{"title": "...", "author": "...", "id": 1}, ...]
      system_prompt: tizim yo'riqnomasi
    
    Qaytaradi: {"reply": "..."} yoki {"error": "..."}
    """
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        return {'error': "AI xizmati sozlanmagan. Administrator GEMINI_API_KEY ni o'rnatishi kerak."}

    if book_catalog:
        catalog_lines: List[str] = []
        for b in book_catalog:
            title = b.get('title', '')
            author = b.get('author', '') or '—'
            bid = b.get('id', '')
            catalog_lines.append(f"- [#{bid}] **{title}** — {author}")
        if catalog_lines:
            system_prompt = (
                f"{system_prompt}\n\n"
                f"MAVJUD KITOBLAR RO'YXATI ({len(catalog_lines)} ta):\n"
                + "\n".join(catalog_lines)
            )

    contents: List[Dict] = []
    if history:
        for msg in history:
            role = msg.get('role', 'user')
            text = msg.get('content', '')
            if not text:
                continue
            contents.append({
                'role': 'model' if role == 'model' else 'user',
                'parts': [{'text': text}],
            })

    contents.append({
        'role': 'user',
        'parts': [{'text': user_message}],
    })

    payload = {
        'systemInstruction': {'parts': [{'text': system_prompt}]},
        'contents': contents,
        'generationConfig': {
            'temperature': 0.7,
            'topP': 0.9,
            'maxOutputTokens': 800,
        },
    }

    try:
        url = f"{_gemini_endpoint()}?key={api_key}"
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            logger.error('Gemini xato: status=%s body=%s', r.status_code, r.text[:500])
            return {'error': f"Gemini xato: HTTP {r.status_code}"}
        data = r.json()
        candidates = data.get('candidates') or []
        if not candidates:
            block = data.get('promptFeedback', {}).get('blockReason')
            if block:
                return {'error': f"So'rov bloklandi: {block}"}
            return {'error': "Gemini bo'sh javob qaytardi."}
        parts = candidates[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts).strip()
        if not text:
            return {'error': "Gemini bo'sh matn qaytardi."}
        return {'reply': text}
    except requests.Timeout:
        return {'error': "Gemini javob bermadi (timeout)."}
    except Exception as exc:  # noqa: BLE001
        logger.exception('Gemini chaqiruv xatosi')
        return {'error': f"Gemini xatosi: {exc}"}
