"""
receipt_parser.py — Dedicated Thai Bank Receipt Parser for Axe Finance Bot
===========================================================================
A robust, AI-powered receipt/slip parser optimized for Thailand banking apps.

Supported banks:
  • Bangkok Bank (primary)
  • KBank (Kasikorn)
  • SCB (Siam Commercial Bank)
  • Krungthai Bank
  • PromptPay transfers

Features:
  • AI vision parsing (GPT-4.1-mini) as primary method
  • OCR fallback with Thai+English language support
  • Smart category detection with 500+ Thai-relevant keywords
  • Transfer detection (top-ups to TrueMoney, Rabbit, MRT, etc.)
  • Note/memo field extraction with priority over merchant name
  • Thai Baht amount parsing (handles commas, decimals, Thai numerals)
  • Direction detection (IN/OUT) from slip layout

Usage:
    from receipt_parser import ReceiptParser
    parser = ReceiptParser(openai_client=ai_client)
    result = parser.parse(photo_bytes, caption="Gin Tonic")
"""

import re
import io
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

try:
    from PIL import Image
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# RESULT DATA CLASS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParseResult:
    """Structured result from receipt parsing."""
    amount: Optional[float] = None
    description: Optional[str] = None
    category: str = "Other"
    category_emoji: str = "🧾"
    account: str = "Cash"
    direction: str = "OUT"  # OUT = expense, IN = income
    is_transfer: bool = False
    transfer_to: Optional[str] = None
    bank_detected: Optional[str] = None
    confidence: float = 0.0
    raw_note: Optional[str] = None
    raw_to: Optional[str] = None
    method: str = "none"  # "ai", "ocr", "caption"

    @property
    def is_valid(self) -> bool:
        return self.amount is not None and self.amount > 0

    @property
    def is_income(self) -> bool:
        return self.direction == "IN"


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY ENGINE — 600+ keywords optimized for Thailand
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORIES = {
    # ─── Food & Drinks (restaurants, food items, delivery) ────────────────────
    'food': ('Food & Drinks', '🍜'),
    'lunch': ('Food & Drinks', '🍜'),
    'dinner': ('Food & Drinks', '🍜'),
    'breakfast': ('Food & Drinks', '🍜'),
    'brunch': ('Food & Drinks', '🍜'),
    'snack': ('Food & Drinks', '🍜'),
    'snacks': ('Food & Drinks', '🍜'),
    'meal': ('Food & Drinks', '🍜'),
    'eat': ('Food & Drinks', '🍜'),
    'restaurant': ('Food & Drinks', '🍜'),
    'kfc': ('Food & Drinks', '🍜'),
    'bonchon': ('Food & Drinks', '🍜'),
    'mcdonalds': ('Food & Drinks', '🍜'),
    'mcdonald': ('Food & Drinks', '🍜'),
    'mcd': ('Food & Drinks', '🍜'),
    'burger king': ('Food & Drinks', '🍜'),
    'pizza hut': ('Food & Drinks', '🍜'),
    'pizza company': ('Food & Drinks', '🍜'),
    'the pizza company': ('Food & Drinks', '🍜'),
    'dominos': ('Food & Drinks', '🍜'),
    'subway': ('Food & Drinks', '🍜'),
    'mos burger': ('Food & Drinks', '🍜'),
    'texas chicken': ('Food & Drinks', '🍜'),
    'popeyes': ('Food & Drinks', '🍜'),
    'wendys': ('Food & Drinks', '🍜'),
    'five guys': ('Food & Drinks', '🍜'),
    'shake shack': ('Food & Drinks', '🍜'),
    # Thai chains & restaurants
    'mk': ('Food & Drinks', '🍜'),
    'mk suki': ('Food & Drinks', '🍜'),
    'mk restaurant': ('Food & Drinks', '🍜'),
    'sizzler': ('Food & Drinks', '🍜'),
    's&p': ('Food & Drinks', '🍜'),
    'bar b q plaza': ('Food & Drinks', '🍜'),
    'bar-b-q plaza': ('Food & Drinks', '🍜'),
    'bbq plaza': ('Food & Drinks', '🍜'),
    'shabushi': ('Food & Drinks', '🍜'),
    'fuji': ('Food & Drinks', '🍜'),
    'fuji restaurant': ('Food & Drinks', '🍜'),
    'yayoi': ('Food & Drinks', '🍜'),
    'oishi': ('Food & Drinks', '🍜'),
    'oishi ramen': ('Food & Drinks', '🍜'),
    'oishi grand': ('Food & Drinks', '🍜'),
    'coco ichibanya': ('Food & Drinks', '🍜'),
    'pepper lunch': ('Food & Drinks', '🍜'),
    'hachiban ramen': ('Food & Drinks', '🍜'),
    'gyukatsu': ('Food & Drinks', '🍜'),
    'sukishi': ('Food & Drinks', '🍜'),
    'after you': ('Food & Drinks', '🍜'),
    'swensens': ('Food & Drinks', '🍜'),
    'dairy queen': ('Food & Drinks', '🍜'),
    'dq': ('Food & Drinks', '🍜'),
    'baskin robbins': ('Food & Drinks', '🍜'),
    'cold stone': ('Food & Drinks', '🍜'),
    'krispy kreme': ('Food & Drinks', '🍜'),
    'mister donut': ('Food & Drinks', '🍜'),
    'dunkin donuts': ('Food & Drinks', '🍜'),
    'dunkin': ('Food & Drinks', '🍜'),
    'auntie annes': ('Food & Drinks', '🍜'),
    # Thai food items
    'sushi': ('Food & Drinks', '🍜'),
    'ramen': ('Food & Drinks', '🍜'),
    'som tam': ('Food & Drinks', '🍜'),
    'somtam': ('Food & Drinks', '🍜'),
    'pad thai': ('Food & Drinks', '🍜'),
    'noodle': ('Food & Drinks', '🍜'),
    'noodles': ('Food & Drinks', '🍜'),
    'rice': ('Food & Drinks', '🍜'),
    'chicken': ('Food & Drinks', '🍜'),
    'pork': ('Food & Drinks', '🍜'),
    'beef': ('Food & Drinks', '🍜'),
    'fish': ('Food & Drinks', '🍜'),
    'seafood': ('Food & Drinks', '🍜'),
    'pizza': ('Food & Drinks', '🍜'),
    'burger': ('Food & Drinks', '🍜'),
    'hotdog': ('Food & Drinks', '🍜'),
    'sandwich': ('Food & Drinks', '🍜'),
    'salad': ('Food & Drinks', '🍜'),
    'steak': ('Food & Drinks', '🍜'),
    'buffet': ('Food & Drinks', '🍜'),
    'hotpot': ('Food & Drinks', '🍜'),
    'shabu': ('Food & Drinks', '🍜'),
    'yakiniku': ('Food & Drinks', '🍜'),
    'grill': ('Food & Drinks', '🍜'),
    'dim sum': ('Food & Drinks', '🍜'),
    'dimsum': ('Food & Drinks', '🍜'),
    'congee': ('Food & Drinks', '🍜'),
    'jok': ('Food & Drinks', '🍜'),
    'khao man gai': ('Food & Drinks', '🍜'),
    'boat noodle': ('Food & Drinks', '🍜'),
    'thai food': ('Food & Drinks', '🍜'),
    'japanese food': ('Food & Drinks', '🍜'),
    'korean food': ('Food & Drinks', '🍜'),
    'chinese food': ('Food & Drinks', '🍜'),
    'indian food': ('Food & Drinks', '🍜'),
    'italian food': ('Food & Drinks', '🍜'),
    'western food': ('Food & Drinks', '🍜'),
    'khao pad': ('Food & Drinks', '🍜'),
    'tom yum': ('Food & Drinks', '🍜'),
    'tom kha': ('Food & Drinks', '🍜'),
    'green curry': ('Food & Drinks', '🍜'),
    'red curry': ('Food & Drinks', '🍜'),
    'massaman': ('Food & Drinks', '🍜'),
    'pad kra pao': ('Food & Drinks', '🍜'),
    'basil': ('Food & Drinks', '🍜'),
    'fried rice': ('Food & Drinks', '🍜'),
    'sticky rice': ('Food & Drinks', '🍜'),
    'mango sticky rice': ('Food & Drinks', '🍜'),
    'papaya salad': ('Food & Drinks', '🍜'),
    'larb': ('Food & Drinks', '🍜'),
    'nam tok': ('Food & Drinks', '🍜'),
    'grilled pork': ('Food & Drinks', '🍜'),
    'moo ping': ('Food & Drinks', '🍜'),
    'satay': ('Food & Drinks', '🍜'),
    'spring roll': ('Food & Drinks', '🍜'),
    'wonton': ('Food & Drinks', '🍜'),
    'gyoza': ('Food & Drinks', '🍜'),
    'tempura': ('Food & Drinks', '🍜'),
    'donburi': ('Food & Drinks', '🍜'),
    'bento': ('Food & Drinks', '🍜'),
    'onigiri': ('Food & Drinks', '🍜'),
    'takoyaki': ('Food & Drinks', '🍜'),
    'okonomiyaki': ('Food & Drinks', '🍜'),
    # Drinks (non-alcoholic)
    'pepsi': ('Food & Drinks', '🍜'),
    'coke': ('Food & Drinks', '🍜'),
    'coca cola': ('Food & Drinks', '🍜'),
    'sprite': ('Food & Drinks', '🍜'),
    'fanta': ('Food & Drinks', '🍜'),
    'est': ('Food & Drinks', '🍜'),
    'oishi tea': ('Food & Drinks', '🍜'),
    'ichitan': ('Food & Drinks', '🍜'),
    'bubble tea': ('Food & Drinks', '🍜'),
    'boba': ('Food & Drinks', '🍜'),
    'milk tea': ('Food & Drinks', '🍜'),
    'cha tra mue': ('Food & Drinks', '🍜'),
    'thai tea': ('Food & Drinks', '🍜'),
    'smoothie': ('Food & Drinks', '🍜'),
    'juice': ('Food & Drinks', '🍜'),
    'coconut water': ('Food & Drinks', '🍜'),
    'coconut': ('Food & Drinks', '🍜'),
    'water': ('Food & Drinks', '🍜'),
    'mineral water': ('Food & Drinks', '🍜'),
    'energy drink': ('Food & Drinks', '🍜'),
    'red bull': ('Food & Drinks', '🍜'),
    'carabao': ('Food & Drinks', '🍜'),
    'm150': ('Food & Drinks', '🍜'),
    # Delivery
    'grab food': ('Food & Drinks', '🍜'),
    'grabfood': ('Food & Drinks', '🍜'),
    'food panda': ('Food & Drinks', '🍜'),
    'foodpanda': ('Food & Drinks', '🍜'),
    'lineman': ('Food & Drinks', '🍜'),
    'line man': ('Food & Drinks', '🍜'),
    'robinhood': ('Food & Drinks', '🍜'),
    # Company names on receipts
    'qsr of asia': ('Food & Drinks', '🍜'),
    'qsr': ('Food & Drinks', '🍜'),
    'minor food': ('Food & Drinks', '🍜'),
    'central restaurants': ('Food & Drinks', '🍜'),
    'crg': ('Food & Drinks', '🍜'),
    'yum restaurants': ('Food & Drinks', '🍜'),
    # Convenience store food
    'onigiri 7-11': ('Food & Drinks', '🍜'),
    'cp': ('Food & Drinks', '🍜'),
    'cp fresh': ('Food & Drinks', '🍜'),
    'cp all': ('Food & Drinks', '🍜'),

    # ─── Coffee & Cafe ────────────────────────────────────────────────────────
    'coffee': ('Coffee', '☕'),
    'cafe': ('Coffee', '☕'),
    'café': ('Coffee', '☕'),
    'starbucks': ('Coffee', '☕'),
    'amazon': ('Coffee', '☕'),
    'cafe amazon': ('Coffee', '☕'),
    'wawee': ('Coffee', '☕'),
    'wawee coffee': ('Coffee', '☕'),
    'blue cup': ('Coffee', '☕'),
    'all cafe': ('Coffee', '☕'),
    'inthanin': ('Coffee', '☕'),
    'inthanin coffee': ('Coffee', '☕'),
    'black canyon': ('Coffee', '☕'),
    'true coffee': ('Coffee', '☕'),
    'pacamara': ('Coffee', '☕'),
    'casa lapin': ('Coffee', '☕'),
    'roots': ('Coffee', '☕'),
    'roots coffee': ('Coffee', '☕'),
    'latte': ('Coffee', '☕'),
    'espresso': ('Coffee', '☕'),
    'cappuccino': ('Coffee', '☕'),
    'americano': ('Coffee', '☕'),
    'mocha': ('Coffee', '☕'),
    'macchiato': ('Coffee', '☕'),
    'frappe': ('Coffee', '☕'),
    'frappuccino': ('Coffee', '☕'),
    'cold brew': ('Coffee', '☕'),
    'matcha': ('Coffee', '☕'),
    'cocoa': ('Coffee', '☕'),
    'hot chocolate': ('Coffee', '☕'),
    'iced coffee': ('Coffee', '☕'),
    'drip coffee': ('Coffee', '☕'),
    'pour over': ('Coffee', '☕'),

    # ─── Transport ────────────────────────────────────────────────────────────
    'transport': ('Transport', '🚕'),
    'taxi': ('Transport', '🚕'),
    'grab': ('Transport', '🚕'),
    'bolt': ('Transport', '🚕'),
    'indriver': ('Transport', '🚕'),
    'bts': ('Transport', '🚕'),
    'mrt train': ('Transport', '🚕'),
    'airport link': ('Transport', '🚕'),
    'airport rail': ('Transport', '🚕'),
    'bus': ('Transport', '🚕'),
    'bmta': ('Transport', '🚕'),
    'songthaew': ('Transport', '🚕'),
    'tuk tuk': ('Transport', '🚕'),
    'tuktuk': ('Transport', '🚕'),
    'motorbike taxi': ('Transport', '🚕'),
    'motorcycle taxi': ('Transport', '🚕'),
    'win': ('Transport', '🚕'),
    'boat': ('Transport', '🚕'),
    'ferry': ('Transport', '🚕'),
    'chao phraya': ('Transport', '🚕'),
    'express boat': ('Transport', '🚕'),
    'parking': ('Transport', '🚕'),
    'toll': ('Transport', '🚕'),
    'expressway': ('Transport', '🚕'),
    'gas': ('Transport', '🚕'),
    'petrol': ('Transport', '🚕'),
    'gasoline': ('Transport', '🚕'),
    'diesel': ('Transport', '🚕'),
    'ptt': ('Transport', '🚕'),
    'shell': ('Transport', '🚕'),
    'esso': ('Transport', '🚕'),
    'caltex': ('Transport', '🚕'),
    'bangchak': ('Transport', '🚕'),
    'muvmi': ('Transport', '🚕'),
    'hailo': ('Transport', '🚕'),
    'train': ('Transport', '🚕'),
    'railway': ('Transport', '🚕'),

    # ─── Groceries ────────────────────────────────────────────────────────────
    'grocery': ('Groceries', '🛒'),
    'groceries': ('Groceries', '🛒'),
    'supermarket': ('Groceries', '🛒'),
    'big c': ('Groceries', '🛒'),
    'tesco': ('Groceries', '🛒'),
    'tesco lotus': ('Groceries', '🛒'),
    'lotus': ('Groceries', '🛒'),
    'tops': ('Groceries', '🛒'),
    'tops market': ('Groceries', '🛒'),
    'villa market': ('Groceries', '🛒'),
    'gourmet market': ('Groceries', '🛒'),
    'makro': ('Groceries', '🛒'),
    'maxvalu': ('Groceries', '🛒'),
    'foodland': ('Groceries', '🛒'),
    'rimping': ('Groceries', '🛒'),
    '7-eleven': ('Groceries', '🛒'),
    '7-11': ('Groceries', '🛒'),
    '7 eleven': ('Groceries', '🛒'),
    'seven eleven': ('Groceries', '🛒'),
    'family mart': ('Groceries', '🛒'),
    'familymart': ('Groceries', '🛒'),
    'lawson': ('Groceries', '🛒'),
    'mini big c': ('Groceries', '🛒'),
    'jiffy': ('Groceries', '🛒'),
    'cs 7-eleven': ('Groceries', '🛒'),
    'vending': ('Groceries', '🛒'),
    'vending machine': ('Groceries', '🛒'),
    'vending mpq': ('Groceries', '🛒'),

    # ─── Housing & Utilities ──────────────────────────────────────────────────
    'rent': ('Housing', '🏠'),
    'condo': ('Housing', '🏠'),
    'apartment': ('Housing', '🏠'),
    'electricity': ('Housing', '🏠'),
    'electric bill': ('Housing', '🏠'),
    'pea': ('Housing', '🏠'),
    'mea': ('Housing', '🏠'),
    'water bill': ('Housing', '🏠'),
    'internet': ('Housing', '🏠'),
    'wifi': ('Housing', '🏠'),
    'true internet': ('Housing', '🏠'),
    'ais fibre': ('Housing', '🏠'),
    '3bb': ('Housing', '🏠'),
    'phone bill': ('Housing', '🏠'),
    'mobile bill': ('Housing', '🏠'),
    'ais': ('Housing', '🏠'),
    'dtac': ('Housing', '🏠'),
    'true move': ('Housing', '🏠'),
    'truemove': ('Housing', '🏠'),
    'laundry': ('Housing', '🏠'),
    'cleaning': ('Housing', '🏠'),
    'maintenance': ('Housing', '🏠'),
    'common fee': ('Housing', '🏠'),
    'furniture': ('Housing', '🏠'),
    'home': ('Housing', '🏠'),

    # ─── Health & Medical ─────────────────────────────────────────────────────
    'hospital': ('Health', '💊'),
    'doctor': ('Health', '💊'),
    'clinic': ('Health', '💊'),
    'pharmacy': ('Health', '💊'),
    'medicine': ('Health', '💊'),
    'drug': ('Health', '💊'),
    'vitamin': ('Health', '💊'),
    'multivitamin': ('Health', '💊'),
    'supplement': ('Health', '💊'),
    'dental': ('Health', '💊'),
    'dentist': ('Health', '💊'),
    'eye doctor': ('Health', '💊'),
    'optician': ('Health', '💊'),
    'glasses': ('Health', '💊'),
    'contact lens': ('Health', '💊'),
    'boots': ('Health', '💊'),
    'watsons': ('Health', '💊'),
    'watson': ('Health', '💊'),
    'fascino': ('Health', '💊'),
    'swisse': ('Health', '💊'),
    'centrum': ('Health', '💊'),
    'blackmores': ('Health', '💊'),
    'covid test': ('Health', '💊'),
    'pcr': ('Health', '💊'),
    'atk': ('Health', '💊'),
    'bumrungrad': ('Health', '💊'),
    'samitivej': ('Health', '💊'),
    'bangkok hospital': ('Health', '💊'),
    'ram hospital': ('Health', '💊'),
    'phyathai': ('Health', '💊'),

    # ─── Shopping ─────────────────────────────────────────────────────────────
    'shopping': ('Shopping', '👗'),
    'clothes': ('Shopping', '👗'),
    'clothing': ('Shopping', '👗'),
    'shirt': ('Shopping', '👗'),
    'pants': ('Shopping', '👗'),
    'shoes': ('Shopping', '👗'),
    'sneakers': ('Shopping', '👗'),
    'bag': ('Shopping', '👗'),
    'backpack': ('Shopping', '👗'),
    'watch': ('Shopping', '👗'),
    'jewelry': ('Shopping', '👗'),
    'uniqlo': ('Shopping', '👗'),
    'h&m': ('Shopping', '👗'),
    'zara': ('Shopping', '👗'),
    'muji': ('Shopping', '👗'),
    'cotton on': ('Shopping', '👗'),
    'central': ('Shopping', '👗'),
    'robinson': ('Shopping', '👗'),
    'the mall': ('Shopping', '👗'),
    'siam paragon': ('Shopping', '👗'),
    'centralworld': ('Shopping', '👗'),
    'icon siam': ('Shopping', '👗'),
    'iconsiam': ('Shopping', '👗'),
    'terminal 21': ('Shopping', '👗'),
    'mbk': ('Shopping', '👗'),
    'platinum': ('Shopping', '👗'),
    'chatuchak': ('Shopping', '👗'),
    'jj market': ('Shopping', '👗'),
    'lazada': ('Shopping', '👗'),
    'shopee': ('Shopping', '👗'),
    'amazon shopping': ('Shopping', '👗'),
    'aliexpress': ('Shopping', '👗'),
    'tiktok shop': ('Shopping', '👗'),
    'electronics': ('Shopping', '👗'),
    'phone case': ('Shopping', '👗'),
    'charger': ('Shopping', '👗'),
    'cable': ('Shopping', '👗'),
    'headphones': ('Shopping', '👗'),
    'earbuds': ('Shopping', '👗'),
    'airpods': ('Shopping', '👗'),
    'power bank': ('Shopping', '👗'),
    'banana it': ('Shopping', '👗'),
    'jib': ('Shopping', '👗'),
    'it city': ('Shopping', '👗'),
    'power buy': ('Shopping', '👗'),

    # ─── Entertainment & Nightlife ────────────────────────────────────────────
    'movie': ('Entertainment', '🎉'),
    'cinema': ('Entertainment', '🎉'),
    'sf cinema': ('Entertainment', '🎉'),
    'major cineplex': ('Entertainment', '🎉'),
    'netflix': ('Entertainment', '🎉'),
    'spotify': ('Entertainment', '🎉'),
    'youtube premium': ('Entertainment', '🎉'),
    'disney plus': ('Entertainment', '🎉'),
    'concert': ('Entertainment', '🎉'),
    'night out': ('Entertainment', '🎉'),
    'bar': ('Entertainment', '🎉'),
    'pub': ('Entertainment', '🎉'),
    'club': ('Entertainment', '🎉'),
    'nightclub': ('Entertainment', '🎉'),
    'karaoke': ('Entertainment', '🎉'),
    'ktv': ('Entertainment', '🎉'),
    'bowling': ('Entertainment', '🎉'),
    'arcade': ('Entertainment', '🎉'),
    'escape room': ('Entertainment', '🎉'),
    'museum': ('Entertainment', '🎉'),
    'exhibition': ('Entertainment', '🎉'),
    'art gallery': ('Entertainment', '🎉'),
    'zoo': ('Entertainment', '🎉'),
    'safari world': ('Entertainment', '🎉'),
    'theme park': ('Entertainment', '🎉'),
    'water park': ('Entertainment', '🎉'),
    'spa': ('Entertainment', '🎉'),
    'massage': ('Entertainment', '🎉'),
    'thai massage': ('Entertainment', '🎉'),
    'onsen': ('Entertainment', '🎉'),
    'gym': ('Entertainment', '🎉'),
    'fitness': ('Entertainment', '🎉'),
    'fitness first': ('Entertainment', '🎉'),
    'virgin active': ('Entertainment', '🎉'),
    'jetts': ('Entertainment', '🎉'),
    'anytime fitness': ('Entertainment', '🎉'),
    'yoga': ('Entertainment', '🎉'),
    'swimming': ('Entertainment', '🎉'),
    'game': ('Entertainment', '🎉'),
    'games': ('Entertainment', '🎉'),
    'steam': ('Entertainment', '🎉'),
    'playstation': ('Entertainment', '🎉'),
    'nintendo': ('Entertainment', '🎉'),
    # Alcohol & Nightlife drinks
    'beer': ('Entertainment', '🎉'),
    'wine': ('Entertainment', '🎉'),
    'whiskey': ('Entertainment', '🎉'),
    'whisky': ('Entertainment', '🎉'),
    'vodka': ('Entertainment', '🎉'),
    'rum': ('Entertainment', '🎉'),
    'tequila': ('Entertainment', '🎉'),
    'cocktail': ('Entertainment', '🎉'),
    'gin': ('Entertainment', '🎉'),
    'gin tonic': ('Entertainment', '🎉'),
    'gin and tonic': ('Entertainment', '🎉'),
    'g&t': ('Entertainment', '🎉'),
    'mojito': ('Entertainment', '🎉'),
    'margarita': ('Entertainment', '🎉'),
    'long island': ('Entertainment', '🎉'),
    'negroni': ('Entertainment', '🎉'),
    'old fashioned': ('Entertainment', '🎉'),
    'manhattan': ('Entertainment', '🎉'),
    'martini': ('Entertainment', '🎉'),
    'daiquiri': ('Entertainment', '🎉'),
    'sangria': ('Entertainment', '🎉'),
    'soju': ('Entertainment', '🎉'),
    'sake': ('Entertainment', '🎉'),
    'alcohol': ('Entertainment', '🎉'),
    'singha': ('Entertainment', '🎉'),
    'chang beer': ('Entertainment', '🎉'),
    'leo beer': ('Entertainment', '🎉'),
    'heineken': ('Entertainment', '🎉'),
    'tiger beer': ('Entertainment', '🎉'),
    'asahi': ('Entertainment', '🎉'),
    'sapporo': ('Entertainment', '🎉'),
    'corona': ('Entertainment', '🎉'),
    'budweiser': ('Entertainment', '🎉'),
    'hoegaarden': ('Entertainment', '🎉'),
    'craft beer': ('Entertainment', '🎉'),
    'ipa': ('Entertainment', '🎉'),
    'lager': ('Entertainment', '🎉'),
    'stout': ('Entertainment', '🎉'),
    'shots': ('Entertainment', '🎉'),
    'jagermeister': ('Entertainment', '🎉'),
    'jack daniels': ('Entertainment', '🎉'),
    'johnnie walker': ('Entertainment', '🎉'),
    'chivas': ('Entertainment', '🎉'),
    'hennessy': ('Entertainment', '🎉'),
    'absolut': ('Entertainment', '🎉'),
    'grey goose': ('Entertainment', '🎉'),
    'patron': ('Entertainment', '🎉'),
    'bacardi': ('Entertainment', '🎉'),
    'captain morgan': ('Entertainment', '🎉'),
    'malibu': ('Entertainment', '🎉'),
    'baileys': ('Entertainment', '🎉'),
    'kahlua': ('Entertainment', '🎉'),
    'aperol': ('Entertainment', '🎉'),
    'aperol spritz': ('Entertainment', '🎉'),
    'spritz': ('Entertainment', '🎉'),
    'highball': ('Entertainment', '🎉'),
    'tonic': ('Entertainment', '🎉'),
    'tonic water': ('Entertainment', '🎉'),
    'mixer': ('Entertainment', '🎉'),
    'drunk': ('Entertainment', '🎉'),
    'drinks': ('Entertainment', '🎉'),
    'drinking': ('Entertainment', '🎉'),
    'booze': ('Entertainment', '🎉'),
    'hangover': ('Entertainment', '🎉'),

    # ─── Subscriptions ────────────────────────────────────────────────────────
    'subscription': ('Subscriptions', '📱'),
    'subscriptions': ('Subscriptions', '📱'),
    'google one': ('Subscriptions', '📱'),
    'icloud': ('Subscriptions', '📱'),
    'apple music': ('Subscriptions', '📱'),
    'youtube': ('Subscriptions', '📱'),
    'youtube premium': ('Subscriptions', '📱'),
    'openai': ('Subscriptions', '📱'),
    'chatgpt': ('Subscriptions', '📱'),
    'chatgpt plus': ('Subscriptions', '📱'),
    'notion': ('Subscriptions', '📱'),
    'canva': ('Subscriptions', '📱'),
    'adobe': ('Subscriptions', '📱'),
    'figma': ('Subscriptions', '📱'),
    'github': ('Subscriptions', '📱'),

    # ─── Travel ───────────────────────────────────────────────────────────────
    'travel': ('Travel', '✈️'),
    'flight': ('Travel', '✈️'),
    'airasia': ('Travel', '✈️'),
    'nok air': ('Travel', '✈️'),
    'thai airways': ('Travel', '✈️'),
    'vietjet': ('Travel', '✈️'),
    'lion air': ('Travel', '✈️'),
    'hotel': ('Travel', '✈️'),
    'hostel': ('Travel', '✈️'),
    'airbnb': ('Travel', '✈️'),
    'agoda': ('Travel', '✈️'),
    'booking.com': ('Travel', '✈️'),
    'trip': ('Travel', '✈️'),
    'vacation': ('Travel', '✈️'),
    'holiday': ('Travel', '✈️'),
    'luggage': ('Travel', '✈️'),
    'passport': ('Travel', '✈️'),
    'visa fee': ('Travel', '✈️'),
    'airport': ('Travel', '✈️'),
    'suvarnabhumi': ('Travel', '✈️'),
    'don mueang': ('Travel', '✈️'),

    # ─── School & Education ───────────────────────────────────────────────────
    'school': ('School', '🎓'),
    'university': ('School', '🎓'),
    'tuition': ('School', '🎓'),
    'course': ('School', '🎓'),
    'class': ('School', '🎓'),
    'book': ('School', '🎓'),
    'books': ('School', '🎓'),
    'textbook': ('School', '🎓'),
    'stationery': ('School', '🎓'),
    'notebook': ('School', '🎓'),
    'pen': ('School', '🎓'),
    'pencil': ('School', '🎓'),
    'udemy': ('School', '🎓'),
    'coursera': ('School', '🎓'),
    'skillshare': ('School', '🎓'),
    'exam': ('School', '🎓'),
    'test fee': ('School', '🎓'),
    'ielts': ('School', '🎓'),
    'toefl': ('School', '🎓'),

    # ─── Cigarettes ───────────────────────────────────────────────────────────
    'cigarette': ('Cigarettes', '🚬'),
    'cigarettes': ('Cigarettes', '🚬'),
    'cig': ('Cigarettes', '🚬'),
    'smoke': ('Cigarettes', '🚬'),
    'smoking': ('Cigarettes', '🚬'),
    'marlboro': ('Cigarettes', '🚬'),
    'dunhill': ('Cigarettes', '🚬'),
    'esse': ('Cigarettes', '🚬'),
    'krong thip': ('Cigarettes', '🚬'),
    'lm': ('Cigarettes', '🚬'),
    'winston': ('Cigarettes', '🚬'),
    'camel': ('Cigarettes', '🚬'),
    'lucky strike': ('Cigarettes', '🚬'),
    'vape': ('Cigarettes', '🚬'),
    'iqos': ('Cigarettes', '🚬'),
    'relx': ('Cigarettes', '🚬'),
    'pod': ('Cigarettes', '🚬'),
    'e-cigarette': ('Cigarettes', '🚬'),
    'nicotine': ('Cigarettes', '🚬'),
}

# Sorted by length (longest first) for accurate matching
_SORTED_KEYWORDS = sorted(CATEGORIES.keys(), key=len, reverse=True)

# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

ACCOUNT_MAP = {
    'bangkok bank': 'Bangkok Bank',
    'bbl': 'Bangkok Bank',
    'kbank': 'Bangkok Bank',  # Map to user's primary bank
    'kasikorn': 'Bangkok Bank',
    'scb': 'Bangkok Bank',
    'true money': 'True Money Wallet',
    'truemoney': 'True Money Wallet',
    'true wallet': 'True Money Wallet',
    'tmninapp': 'True Money Wallet',
    'mrt': 'MRT EMV Visa',
    'mrt emv': 'MRT EMV Visa',
    'emv visa': 'MRT EMV Visa',
    'rabbit': 'Rabbit Card',
    'rabbit card': 'Rabbit Card',
    'rabbit line pay': 'Rabbit Card',
    'bts': 'Rabbit Card',
    'mangmoom': 'MRT EMV Visa',
    'cash': 'Cash',
    'muvmi': 'Muvmi',
    'solsot': 'Solsot Member',
}

# Transfer destination detection keywords
TRANSFER_DESTINATIONS = {
    'True Money Wallet': [
        'truemoney', 'true money', 'tmninapp', 'transfer to true money',
        'true money wallet', 'truemoney wallet', 'top up true'
    ],
    'Rabbit Card': [
        'rabbit', 'rabbit card', 'rabbit line pay', 'bts top up',
        'bts topup', 'rabbit top up'
    ],
    'MRT EMV Visa': [
        'mrt', 'mrt card', 'mrt emv', 'mangmoom', 'mrt top up'
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# THAI NUMERAL CONVERSION
# ═══════════════════════════════════════════════════════════════════════════════

THAI_DIGITS = str.maketrans('๐๑๒๓๔๕๖๗๘๙', '0123456789')


def thai_to_arabic(text: str) -> str:
    """Convert Thai numerals to Arabic numerals."""
    return text.translate(THAI_DIGITS)


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_category(text: str) -> Tuple[str, str]:
    """
    Detect category from text using keyword matching.
    Returns (category_name, emoji).
    Matches longest keywords first for accuracy.
    """
    text_lower = text.lower().strip()
    for keyword in _SORTED_KEYWORDS:
        if keyword in text_lower:
            return CATEGORIES[keyword]
    return ('Other', '🧾')


def detect_account(text: str) -> str:
    """Detect account from text."""
    text_lower = text.lower()
    sorted_accounts = sorted(ACCOUNT_MAP.keys(), key=len, reverse=True)
    for keyword in sorted_accounts:
        if keyword in text_lower:
            return ACCOUNT_MAP[keyword]
    return 'Cash'


# ═══════════════════════════════════════════════════════════════════════════════
# OCR PARSER — Bangkok Bank & Thai Banks
# ═══════════════════════════════════════════════════════════════════════════════

class OCRParser:
    """Parse Thai bank transfer slips from OCR text."""

    # Words to skip when looking for note/description
    SKIP_WORDS = [
        'scan', 'verify', 'reference', 'transaction', 'bank ref',
        'service code', 'optional', 'bank reference', 'transaction reference',
        'biller', 'account no', 'e-wallet number', 'promptpay'
    ]

    def parse(self, ocr_text: str) -> ParseResult:
        """Parse OCR text from a bank slip."""
        result = ParseResult(method="ocr")
        text = thai_to_arabic(ocr_text)

        # Detect bank
        result.bank_detected = self._detect_bank(text)
        if result.bank_detected:
            result.account = result.bank_detected

        # Extract amount
        result.amount = self._extract_amount(text)

        # Extract note (user's description)
        result.raw_note = self._extract_note(text)

        # Extract "To" field (recipient)
        result.raw_to = self._extract_to(text)

        # Determine description: Note > To > generic
        if result.raw_note:
            result.description = result.raw_note
        elif result.raw_to:
            result.description = result.raw_to
        else:
            result.description = "Receipt scan"

        # Detect direction
        result.direction = self._detect_direction(text)

        # Detect if this is an internal transfer (top-up)
        combined_text = f"{result.raw_note or ''} {result.raw_to or ''} {text}".lower()
        for dest_account, keywords in TRANSFER_DESTINATIONS.items():
            if any(kw in combined_text for kw in keywords):
                if result.account == 'Bangkok Bank' and result.direction == 'OUT':
                    result.is_transfer = True
                    result.transfer_to = dest_account
                    break

        # Detect category from description
        if result.description and result.description != "Receipt scan":
            cat, emoji = detect_category(result.description)
            result.category = cat
            result.category_emoji = emoji

        # If still "Other", try from full OCR text
        if result.category == 'Other':
            cat, emoji = detect_category(text)
            if cat != 'Other':
                result.category = cat
                result.category_emoji = emoji

        if result.amount and result.amount > 0:
            result.confidence = 0.7

        return result

    def _detect_bank(self, text: str) -> Optional[str]:
        """Detect which bank the slip is from."""
        text_lower = text.lower()
        if 'bangkok bank' in text_lower or 'bbl' in text_lower:
            return 'Bangkok Bank'
        if 'kasikorn' in text_lower or 'kbank' in text_lower:
            return 'Bangkok Bank'  # Map to user's primary
        if 'scb' in text_lower or 'siam commercial' in text_lower:
            return 'Bangkok Bank'
        if 'krungthai' in text_lower or 'ktb' in text_lower:
            return 'Bangkok Bank'
        return None

    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract the transaction amount from OCR text."""
        # Method 1: Look near "Amount" label
        patterns = [
            r'(?:Amount|amount|จำนวนเงิน)\s*[:\s]*([0-9,]+\.?\d*)\s*(?:THB|Baht|บาท)?',
            r'([0-9,]+\.\d{2})\s*(?:THB|Baht|บาท)',
            r'(?:THB|Baht|บาท)\s*([0-9,]+\.\d{2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    amount = float(amount_str)
                    if amount > 0:
                        return amount
                except ValueError:
                    continue

        # Method 2: Find all decimal amounts, pick the largest non-zero non-fee one
        all_amounts = re.findall(r'([0-9]{1,3}(?:,[0-9]{3})*\.\d{2})', text)
        valid = []
        for a in all_amounts:
            val = float(a.replace(',', ''))
            if val > 0:
                valid.append(val)
        if valid:
            # The main amount is usually the largest (fee is 0.00 or small)
            return max(valid)

        return None

    def _extract_note(self, text: str) -> Optional[str]:
        """Extract the Note/Memo field from the slip."""
        # Method 1: Explicit "Note" / "Memo" / "Remark" / "หมายเหตุ" label
        note_patterns = [
            r'(?:Note|Memo|Remark|หมายเหตุ)\s*[:\s]+(.+?)(?:\n|$)',
        ]
        for pattern in note_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for note in matches:
                note = note.strip()
                if self._is_valid_note(note):
                    return note

        # Method 2: Text between "Fee 0.00 THB" and "Bank reference"
        fee_pattern = r'(?:0\.00\s*THB|Fee[^\n]*0\.00)\s*\n\s*(.+?)\s*(?:\n\s*(?:Bank reference|Transaction reference|\d{5,})|$)'
        match = re.search(fee_pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            note = match.group(1).strip()
            # Split by newline and take first meaningful line
            lines = note.split('\n')
            for line in lines:
                line = line.strip()
                if self._is_valid_note(line):
                    return line

        # Method 3: Look for "Note" on its own line followed by content
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if re.match(r'^\s*(?:Note|Memo|Remark)\s*$', line, re.IGNORECASE):
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if self._is_valid_note(next_line):
                        return next_line

        return None

    def _extract_to(self, text: str) -> Optional[str]:
        """Extract the recipient (To field) from the slip."""
        # Look for "To" followed by a name
        to_patterns = [
            r'To\s+(?:MS\.|MR\.|MRS\.)\s*([A-Z][A-Z\s@\-]+)',
            r'To\s+([A-Z][A-Z\s\(\)]+(?:CO\.,?LTD\.?|THAILAND|COMPANY)?)',
            r'To\s+(.+?)(?:\n|Service|Biller|Reference|e-wallet|Account)',
        ]
        for pattern in to_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                to_text = match.group(1).strip()
                # Clean up: remove trailing service codes, numbers, etc.
                to_text = re.sub(r'\s*(Service Code|Biller|Reference|e-wallet|Account|K Plus|PromptPay).*', '', to_text, flags=re.IGNORECASE)
                to_text = to_text.strip(' -–—')
                if to_text and len(to_text) > 1:
                    return to_text

        return None

    def _detect_direction(self, text: str) -> str:
        """Detect if money is going OUT or coming IN."""
        # If "From" contains user's info → OUT (user is sending)
        if re.search(r'From.*(?:MR\s*MIN|MIN\s*THU|171-4)', text, re.IGNORECASE):
            return 'OUT'
        # If "To" contains user's info → IN (user is receiving)
        if re.search(r'To.*(?:MR\s*MIN|MIN\s*THU|171-4)', text, re.IGNORECASE):
            return 'IN'
        # Default: assume OUT (expense)
        return 'OUT'

    def _is_valid_note(self, text: str) -> bool:
        """Check if extracted text is a valid note (not junk)."""
        if not text or len(text) < 2:
            return False
        if any(sw in text.lower() for sw in self.SKIP_WORDS):
            return False
        if re.match(r'^[0-9,\.\s]+$', text):  # Pure numbers
            return False
        if re.match(r'^[0-9]{5,}', text):  # Reference numbers
            return False
        if re.match(r'^\d{4}', text) and len(text) > 15:  # Transaction references
            return False
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# AI VISION PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class AIParser:
    """Parse receipts using GPT-4.1-mini vision."""

    SYSTEM_PROMPT = """You are a Thai bank transfer slip and receipt parser. You MUST extract information accurately from the image.

IMPORTANT RULES:
1. The "Note" or "Memo" field is the user's personal description — ALWAYS prioritize this over the recipient name
2. If there is a Note field visible, use it as the NOTE value
3. If there is no Note field, use the recipient name or merchant name
4. For the CATEGORY, consider the Note field content AND the recipient name together
5. Common Thai bank slip layout: Amount → From → To → Fee → Note → Bank reference
6. NEVER use "verify", "scan", "scan to verify", or any reference/transaction numbers as the NOTE value — these are UI labels, not the user's note
7. The Note field appears just above "Bank reference no." — look for it there specifically

Available categories for expenses:
Food & Drinks, Coffee, Transport, Groceries, Housing, Health, Shopping, Entertainment, Subscriptions, Travel, School, Cigarettes, Other

Available categories for income:
Salary, Freelance, Gallery Sales, Artwork / Commission, Bonus, Gift Money, Cashback / Refund, Investment, Business, Other Income

Respond in this EXACT format (no extra text):
AMOUNT: <number only, no commas>
NOTE: <the Note/Memo field content if visible, OR short description of what this payment is for>
TO: <recipient name or merchant name>
BANK: <source bank name: Bangkok Bank, KBank, SCB, True Money, or UNKNOWN>
DIRECTION: <OUT if user is paying/sending, IN if user is receiving>
CATEGORY: <one category from the list above>
TRANSFER_TO: <if this is a top-up to TrueMoney/Rabbit/MRT, write the destination. Otherwise write NONE>

Examples:
- If Note says "Gin Tonic" and To says "MS. SAI TAUNG" → NOTE should be "Gin Tonic", CATEGORY should be "Entertainment"
- If Note says "Coconut water" and To says "CS 7-Eleven" → NOTE should be "Coconut water", CATEGORY should be "Food & Drinks"
- If Note says "Bolt" → NOTE should be "Bolt", CATEGORY should be "Transport"
- If Note says "Grab" → NOTE should be "Grab", CATEGORY should be "Transport"
- If To says "TRUEMONEY" with no note → this is a transfer/top-up, TRANSFER_TO: True Money Wallet
- If Note says "Transfer to True Money" → TRANSFER_TO: True Money Wallet"""

    def __init__(self, client):
        self.client = client

    def parse(self, photo_bytes: bytes, caption: str = "") -> ParseResult:
        """Parse receipt image using AI vision."""
        result = ParseResult(method="ai")

        try:
            b64_image = base64.b64encode(photo_bytes).decode('utf-8')
            user_msg = "Extract amount, note, recipient, bank, direction, and category from this Thai bank transfer slip."
            if caption:
                user_msg += f"\n\nUser's caption: \"{caption}\" — use this as the description if relevant."

            response = self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_msg},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                        ]
                    }
                ],
                max_tokens=400,
                temperature=0.1  # Low temperature for accuracy
            )

            text = response.choices[0].message.content
            logger.info(f"AI receipt parse result: {text}")
            result = self._parse_response(text, caption)
            result.method = "ai"
            result.confidence = 0.9

        except Exception as e:
            logger.warning(f"AI receipt parsing failed: {e}")
            result.confidence = 0.0

        return result

    def _parse_response(self, text: str, caption: str = "") -> ParseResult:
        """Parse the AI response text into a ParseResult."""
        result = ParseResult(method="ai")

        # Extract fields
        amount_match = re.search(r'AMOUNT:\s*([\d,]+(?:\.\d{1,2})?)', text)
        note_match = re.search(r'NOTE:\s*(.+)', text)
        to_match = re.search(r'TO:\s*(.+)', text)
        bank_match = re.search(r'BANK:\s*(.+)', text)
        direction_match = re.search(r'DIRECTION:\s*(OUT|IN)', text, re.IGNORECASE)
        cat_match = re.search(r'CATEGORY:\s*(.+)', text)
        transfer_match = re.search(r'TRANSFER_TO:\s*(.+)', text)

        # Amount
        if amount_match:
            try:
                result.amount = float(amount_match.group(1).replace(',', ''))
            except ValueError:
                pass

        # Description: caption > AI note > "Receipt scan"
        if caption:
            result.description = caption
        elif note_match:
            note = note_match.group(1).strip()
            if note and note.lower() not in ['none', 'n/a', '-', 'unknown', 'verify', 'scan', 'scan to verify']:
                result.description = note
            else:
                result.description = "Receipt scan"
        else:
            result.description = "Receipt scan"

        # Raw fields for reference
        if note_match:
            result.raw_note = note_match.group(1).strip()
        if to_match:
            result.raw_to = to_match.group(1).strip()

        # Bank / Account
        if bank_match:
            bank_text = bank_match.group(1).strip().lower()
            if bank_text not in ['unknown', 'none', 'n/a']:
                if 'bangkok' in bank_text or 'bbl' in bank_text:
                    result.account = 'Bangkok Bank'
                elif 'true' in bank_text:
                    result.account = 'True Money Wallet'
                elif 'rabbit' in bank_text:
                    result.account = 'Rabbit Card'
                elif 'mrt' in bank_text or 'emv' in bank_text:
                    result.account = 'MRT EMV Visa'
                else:
                    result.account = 'Bangkok Bank'  # Default
            else:
                result.account = 'Bangkok Bank'

        # Direction
        if direction_match:
            result.direction = direction_match.group(1).upper()

        # Category: detect from caption first, then AI suggestion, then description
        if caption:
            cat, emoji = detect_category(caption)
            if cat != 'Other':
                result.category = cat
                result.category_emoji = emoji
            elif cat_match:
                ai_cat = cat_match.group(1).strip()
                result.category = ai_cat
                # Get emoji for the category
                for kw, (c, e) in CATEGORIES.items():
                    if c == ai_cat:
                        result.category_emoji = e
                        break
        elif cat_match:
            ai_cat = cat_match.group(1).strip()
            # Validate against our category list
            valid_cats = set(c for c, e in CATEGORIES.values())
            valid_cats.add('Other')
            if ai_cat in valid_cats:
                result.category = ai_cat
                for kw, (c, e) in CATEGORIES.items():
                    if c == ai_cat:
                        result.category_emoji = e
                        break
            else:
                # Try to detect from description
                if result.description:
                    cat, emoji = detect_category(result.description)
                    result.category = cat
                    result.category_emoji = emoji

        # If category is still Other, try detecting from raw_note or raw_to
        if result.category == 'Other':
            for text_to_check in [result.raw_note, result.raw_to, result.description]:
                if text_to_check:
                    cat, emoji = detect_category(text_to_check)
                    if cat != 'Other':
                        result.category = cat
                        result.category_emoji = emoji
                        break

        # Transfer detection
        if transfer_match:
            transfer_dest = transfer_match.group(1).strip()
            if transfer_dest.lower() not in ['none', 'n/a', '-']:
                result.is_transfer = True
                # Normalize the destination name
                transfer_lower = transfer_dest.lower()
                if 'true' in transfer_lower:
                    result.transfer_to = 'True Money Wallet'
                elif 'rabbit' in transfer_lower:
                    result.transfer_to = 'Rabbit Card'
                elif 'mrt' in transfer_lower:
                    result.transfer_to = 'MRT EMV Visa'
                else:
                    result.transfer_to = transfer_dest

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PARSER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class ReceiptParser:
    """
    Main receipt parser that combines AI vision and OCR fallback.
    
    Usage:
        parser = ReceiptParser(openai_client=ai_client)
        result = parser.parse(photo_bytes, caption="Gin Tonic")
        
        if result.is_valid:
            print(f"Amount: {result.amount}")
            print(f"Description: {result.description}")
            print(f"Category: {result.category}")
            print(f"Account: {result.account}")
            print(f"Is transfer: {result.is_transfer}")
    """

    def __init__(self, openai_client=None):
        self.ai_parser = AIParser(openai_client) if openai_client else None
        self.ocr_parser = OCRParser()

    def parse(self, photo_bytes: bytes, caption: str = "") -> ParseResult:
        """
        Parse a receipt/bank slip photo.
        
        Priority:
        1. AI vision (most accurate for Thai slips)
        2. OCR fallback (if AI fails or unavailable)
        3. Caption override (always applied on top)
        
        Args:
            photo_bytes: Raw image bytes
            caption: Optional user caption (e.g., "Gin Tonic")
            
        Returns:
            ParseResult with all extracted information
        """
        result = ParseResult()

        # ── Step 1: Try AI vision parsing ─────────────────────────────────────
        if self.ai_parser:
            result = self.ai_parser.parse(photo_bytes, caption)
            if result.is_valid:
                logger.info(f"AI parse success: {result.amount} | {result.description} | {result.category}")
                # Apply caption override
                result = self._apply_caption(result, caption)
                return result
            else:
                logger.info("AI parse returned no valid amount, falling back to OCR")

        # ── Step 2: OCR fallback ──────────────────────────────────────────────
        try:
            if not _OCR_AVAILABLE:
                return ocr_text
            image = Image.open(io.BytesIO(photo_bytes))
            # Try English + Thai OCR
            try:
                ocr_text = pytesseract.image_to_string(image, lang='eng+tha')
            except Exception:
                ocr_text = pytesseract.image_to_string(image, lang='eng')
            
            logger.info(f"OCR text (first 500 chars): {ocr_text[:500]}")
            result = self.ocr_parser.parse(ocr_text)
            
            if result.is_valid:
                logger.info(f"OCR parse success: {result.amount} | {result.description} | {result.category}")
        except Exception as e:
            logger.error(f"OCR processing failed: {e}")

        # ── Step 3: Apply caption override ────────────────────────────────────
        result = self._apply_caption(result, caption)

        return result

    def _apply_caption(self, result: ParseResult, caption: str) -> ParseResult:
        """
        Apply user's caption as override for description and category.
        Caption ALWAYS wins over OCR/AI extracted description.
        """
        if not caption:
            return result

        caption = caption.strip()
        if not caption:
            return result

        # Caption overrides description
        result.description = caption

        # Re-detect category from caption
        cat, emoji = detect_category(caption)
        if cat != 'Other':
            result.category = cat
            result.category_emoji = emoji
        # If caption doesn't match a category, keep the AI/OCR detected one
        # (don't downgrade to "Other" just because caption is generic)

        # Check if caption indicates direction
        caption_lower = caption.lower()
        income_words = ['received', 'got', 'earned', 'income', 'money in', 'salary', 'refund']
        expense_words = ['spent', 'paid', 'bought', 'money out', 'buy']
        
        for w in income_words:
            if w in caption_lower:
                result.direction = 'IN'
                break
        for w in expense_words:
            if w in caption_lower:
                result.direction = 'OUT'
                break

        # Check if caption indicates account
        detected_acc = detect_account(caption_lower)
        if detected_acc != 'Cash':
            result.account = detected_acc

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def create_parser(openai_client=None) -> ReceiptParser:
    """Create a ReceiptParser instance."""
    return ReceiptParser(openai_client=openai_client)


# ═══════════════════════════════════════════════════════════════════════════════
# TESTING (run this file directly to test)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Test category detection
    test_cases = [
        ("Gin Tonic", "Entertainment"),
        ("gin and tonic", "Entertainment"),
        ("Coconut water", "Food & Drinks"),
        ("KFC", "Food & Drinks"),
        ("Starbucks", "Coffee"),
        ("BTS", "Transport"),
        ("Grab", "Transport"),
        ("7-Eleven", "Groceries"),
        ("Marlboro", "Cigarettes"),
        ("Netflix", "Entertainment"),
        ("Google One", "Subscriptions"),
        ("Swisse Multivitamin", "Health"),
        ("Uniqlo", "Shopping"),
        ("AirAsia", "Travel"),
        ("Udemy", "School"),
        ("vodka", "Entertainment"),
        ("mojito", "Entertainment"),
        ("aperol spritz", "Entertainment"),
        ("soju", "Entertainment"),
    ]

    print("=" * 60)
    print("RECEIPT PARSER — Category Detection Test")
    print("=" * 60)
    
    passed = 0
    failed = 0
    for text, expected in test_cases:
        cat, emoji = detect_category(text)
        status = "✅" if cat == expected else "❌"
        if cat == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status} '{text}' → {emoji} {cat} (expected: {expected})")
    
    print(f"\n  Results: {passed}/{passed+failed} passed")
    print("=" * 60)
