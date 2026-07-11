"""
core.py — Shared business logic for Axe Finance
=================================================
This module holds everything the finance app needs that used to live inside
main.py's Telegram bot: category/account keyword maps, category & account
detection, database init/access, recurring-subscription auto-processing,
and the monthly Google Drive Excel backup.

It has ZERO Telegram dependencies — Axe Finance is now a pure web app
(Flask + the dashboard + the Axe chat/receipt-scanning assistant).
"""

import os
import re
import io
import json
import sqlite3
import logging
from datetime import datetime, timedelta, date
import pytz
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
AUTHORIZED_USER_ID = int(os.environ.get('AUTHORIZED_USER_ID', '0'))
DATABASE_NAME = os.path.join('/data', 'finance.db')
BANGKOK_TZ = pytz.timezone('Asia/Bangkok')

# ─── Google Drive backup (optional) ──────────────────────────────────────────
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from google.oauth2 import service_account
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False
    logger.warning("Google API packages not installed. Drive backup disabled.")


CATEGORIES = {
    # ─── 🍜 Food & Drinks ─────────────────────────────────────────────────
    'food': ('Food & Drinks', '🍜'),
    'food & drinks': ('Food & Drinks', '🍜'),
    'restaurant': ('Food & Drinks', '🍜'),
    'street food': ('Food & Drinks', '🍜'),
    'lunch': ('Food & Drinks', '🍜'),
    'dinner': ('Food & Drinks', '🍜'),
    'breakfast': ('Food & Drinks', '🍜'),
    'brunch': ('Food & Drinks', '🍜'),
    'snack': ('Food & Drinks', '🍜'),
    'supper': ('Food & Drinks', '🍜'),
    # Fast food & chains
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
    'donut': ('Food & Drinks', '🍜'),
    'donuts': ('Food & Drinks', '🍜'),
    'golden donuts': ('Food & Drinks', '🍜'),
    'mr donut': ('Food & Drinks', '🍜'),
    'bread': ('Food & Drinks', '🍜'),
    'toast': ('Food & Drinks', '🍜'),
    'bakery': ('Food & Drinks', '🍜'),
    'cake': ('Food & Drinks', '🍜'),
    'pastry': ('Food & Drinks', '🍜'),
    'croissant': ('Food & Drinks', '🍜'),
    'waffle': ('Food & Drinks', '🍜'),
    'pancake': ('Food & Drinks', '🍜'),
    'dessert': ('Food & Drinks', '🍜'),
    'sweets': ('Food & Drinks', '🍜'),
    'candy': ('Food & Drinks', '🍜'),
    'chocolate': ('Food & Drinks', '🍜'),
    'ice cream': ('Food & Drinks', '🍜'),
    'big mac': ('Food & Drinks', '🍜'),
    'whopper': ('Food & Drinks', '🍜'),
    'fried chicken': ('Food & Drinks', '🍜'),
    'wings': ('Food & Drinks', '🍜'),
    'kebab': ('Food & Drinks', '🍜'),
    'shawarma': ('Food & Drinks', '🍜'),
    'crepe': ('Food & Drinks', '🍜'),
    'taco': ('Food & Drinks', '🍜'),
    'burrito': ('Food & Drinks', '🍜'),
    'poke': ('Food & Drinks', '🍜'),
    'acai': ('Food & Drinks', '🍜'),
    'kanom': ('Food & Drinks', '🍜'),
    'khanom': ('Food & Drinks', '🍜'),
    'cha yen': ('Food & Drinks', '🍜'),
    'mango': ('Food & Drinks', '🍜'),
    'durian': ('Food & Drinks', '🍜'),
    'fruit': ('Food & Drinks', '🍜'),
    'thirteen coins': ('Food & Drinks', '🍜'),
    'the terrace': ('Food & Drinks', '🍜'),
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
    'bbq': ('Food & Drinks', '🍜'),
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
    # Drinks
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
    # Delivery
    'grab food': ('Food & Drinks', '🍜'),
    'grabfood': ('Food & Drinks', '🍜'),
    'food panda': ('Food & Drinks', '🍜'),
    'foodpanda': ('Food & Drinks', '🍜'),
    'lineman': ('Food & Drinks', '🍜'),
    'line man': ('Food & Drinks', '🍜'),
    'robinhood': ('Food & Drinks', '🍜'),
    # QSR (Quick Service Restaurant) companies on receipts
    'qsr of asia': ('Food & Drinks', '🍜'),
    'qsr': ('Food & Drinks', '🍜'),
    'minor food': ('Food & Drinks', '🍜'),
    'the minor food': ('Food & Drinks', '🍜'),
    'central restaurants': ('Food & Drinks', '🍜'),
    'crg': ('Food & Drinks', '🍜'),
    # Thai company names that appear on bank receipts ("To" field)
    'yum restaurants': ('Food & Drinks', '🍜'),
    'yum': ('Food & Drinks', '🍜'),
    'mcdonald': ('Food & Drinks', '🍜'),
    'mcdonalds': ('Food & Drinks', '🍜'),
    'cpall': ('Food & Drinks', '🍜'),
    'cp all': ('Food & Drinks', '🍜'),
    'central food retail': ('Groceries', '🛒'),
    'central food': ('Groceries', '🛒'),
    'big c supercenter': ('Groceries', '🛒'),
    'siam makro': ('Groceries', '🛒'),
    'ek-chai distribution': ('Groceries', '🛒'),
    'cp axtra': ('Groceries', '🛒'),
    'true digital group': ('Subscriptions', '📱'),
    'true digital': ('Subscriptions', '📱'),
    'true corp': ('Subscriptions', '📱'),
    'true corporation': ('Subscriptions', '📱'),
    'dtac': ('Subscriptions', '📱'),
    'ais': ('Subscriptions', '📱'),
    'advanced info service': ('Subscriptions', '📱'),
    'shopee thailand': ('Shopping', '👗'),
    'shopee pay': ('Shopping', '👗'),
    'lazada express': ('Shopping', '👗'),
    'payment to shopee': ('Shopping', '👗'),
    'grab holdings': ('Transport', '🚕'),
    'grab taxi': ('Transport', '🚕'),
    'bolt technology': ('Transport', '🚕'),
    'ptt public': ('Transport', '🚕'),
    'ptt oil': ('Transport', '🚕'),
    'bts group': ('Transport', '🚕'),
    'bangkok expressway': ('Transport', '🚕'),
    'metropolitan electricity': ('Housing', '🏠'),
    'metropolitan waterworks': ('Housing', '🏠'),
    'provincial electricity': ('Housing', '🏠'),
    'provincial waterworks': ('Housing', '🏠'),
    'pea': ('Housing', '🏠'),
    'mea': ('Housing', '🏠'),
    'bumrungrad': ('Health', '💊'),
    'samitivej': ('Health', '💊'),
    'bangkok dusit medical': ('Health', '💊'),
    'bdms': ('Health', '💊'),
    'boots retail': ('Health', '💊'),
    'watsons thailand': ('Health', '💊'),
    'google asia': ('Subscriptions', '📱'),
    'google payment': ('Subscriptions', '📱'),
    'apple itunes': ('Subscriptions', '📱'),
    'spotify': ('Subscriptions', '📱'),
    'netflix': ('Subscriptions', '📱'),

    # ─── ☕ Coffee ─────────────────────────────────────────────────────────
    'coffee': ('Coffee', '☕'),
    'latte': ('Coffee', '☕'),
    'cappuccino': ('Coffee', '☕'),
    'espresso': ('Coffee', '☕'),
    'americano': ('Coffee', '☕'),
    'mocha': ('Coffee', '☕'),
    'macchiato': ('Coffee', '☕'),
    'frappe': ('Coffee', '☕'),
    'starbucks': ('Coffee', '☕'),
    'cafe amazon': ('Coffee', '☕'),
    'amazon': ('Coffee', '☕'),
    'inthanin': ('Coffee', '☕'),
    'inthanin coffee': ('Coffee', '☕'),
    'wawee': ('Coffee', '☕'),
    'wawee coffee': ('Coffee', '☕'),
    'bluecup': ('Coffee', '☕'),
    'blue cup': ('Coffee', '☕'),
    'all cafe': ('Coffee', '☕'),
    'dd coffee': ('Coffee', '☕'),
    'pacamara': ('Coffee', '☕'),
    'roots': ('Coffee', '☕'),
    'roots coffee': ('Coffee', '☕'),
    'brave roasters': ('Coffee', '☕'),
    'kaizen coffee': ('Coffee', '☕'),
    'nana coffee': ('Coffee', '☕'),
    'ceresia': ('Coffee', '☕'),
    'factory coffee': ('Coffee', '☕'),
    'graph coffee': ('Coffee', '☕'),
    'akha ama': ('Coffee', '☕'),
    'doi chaang': ('Coffee', '☕'),
    'true coffee': ('Coffee', '☕'),
    'black canyon': ('Coffee', '☕'),
    'flat white': ('Coffee', '☕'),
    'cortado': ('Coffee', '☕'),
    'kopi': ('Coffee', '☕'),
    '% arabica': ('Coffee', '☕'),
    'ceresia': ('Coffee', '☕'),
    'graph coffee': ('Coffee', '☕'),
    'the coffee club': ('Coffee', '☕'),
    'coffee today': ('Coffee', '☕'),
    'tom n toms': ('Coffee', '☕'),
    'hollys': ('Coffee', '☕'),
    'costa coffee': ('Coffee', '☕'),
    'dean & deluca': ('Coffee', '☕'),
    'paul': ('Coffee', '☕'),
    'cafe': ('Coffee', '☕'),

    # ─── 🚕 Transport ─────────────────────────────────────────────────────
    'transport': ('Transport', '🚕'),
    'grab': ('Transport', '🚕'),
    'bolt': ('Transport', '🚕'),
    'bolt food': ('Food & Drinks', '🍜'),
    'grabfood': ('Food & Drinks', '🍜'),
    'grab food': ('Food & Drinks', '🍜'),
    'indrive': ('Transport', '🚕'),
    'in drive': ('Transport', '🚕'),
    'hailo': ('Transport', '🚕'),
    'maxim': ('Transport', '🚕'),
    'limousine': ('Transport', '🚕'),
    'taxi': ('Transport', '🚕'),
    'grab taxi': ('Transport', '🚕'),
    'ltc': ('Transport', '🚕'),
    'taxi meter': ('Transport', '🚕'),
    'grab car': ('Transport', '🚕'),
    'grab bike': ('Transport', '🚕'),
    'grabcar': ('Transport', '🚕'),
    'grabbike': ('Transport', '🚕'),
    'bolt': ('Transport', '🚕'),
    'bts': ('Transport', '🚕'),
    'mrt': ('Transport', '🚕'),
    'taxi': ('Transport', '🚕'),
    'motorbike': ('Transport', '🚕'),
    'motorbike taxi': ('Transport', '🚕'),
    'bike': ('Transport', '🚕'),
    'bus': ('Transport', '🚕'),
    'van': ('Transport', '🚕'),
    'minivan': ('Transport', '🚕'),
    'songthaew': ('Transport', '🚕'),
    'tuk tuk': ('Transport', '🚕'),
    'tuktuk': ('Transport', '🚕'),
    'boat': ('Transport', '🚕'),
    'ferry': ('Transport', '🚕'),
    'chao phraya': ('Transport', '🚕'),
    'airport link': ('Transport', '🚕'),
    'airport rail': ('Transport', '🚕'),
    'srt': ('Transport', '🚕'),
    'train': ('Transport', '🚕'),
    'parking': ('Transport', '🚕'),
    'toll': ('Transport', '🚕'),
    'expressway': ('Transport', '🚕'),
    'gas': ('Transport', '🚕'),
    'petrol': ('Transport', '🚕'),
    'gasoline': ('Transport', '🚕'),
    'ptt': ('Transport', '🚕'),
    'shell': ('Transport', '🚕'),
    'bangchak': ('Transport', '🚕'),
    'caltex': ('Transport', '🚕'),
    'esso': ('Transport', '🚕'),
    'indriver': ('Transport', '🚕'),
    'cabb': ('Transport', '🚕'),
    'ola': ('Transport', '🚕'),
    'van tour': ('Transport', '🚕'),
    'speed boat': ('Transport', '🚕'),
    'pier': ('Transport', '🚕'),
    'line taxi': ('Transport', '🚕'),
    'robinhood ride': ('Transport', '🚕'),

    # ─── 🛒 Groceries ─────────────────────────────────────────────────────
    'groceries': ('Groceries', '🛒'),
    'grocery': ('Groceries', '🛒'),
    'supermarket': ('Groceries', '🛒'),
    'market': ('Groceries', '🛒'),
    'fresh market': ('Groceries', '🛒'),
    'wet market': ('Groceries', '🛒'),
    'big c': ('Groceries', '🛒'),
    'bigc': ('Groceries', '🛒'),
    'tops': ('Groceries', '🛒'),
    'tops market': ('Groceries', '🛒'),
    'tops daily': ('Groceries', '🛒'),
    'lotus': ('Groceries', '🛒'),
    'tesco': ('Groceries', '🛒'),
    'tesco lotus': ('Groceries', '🛒'),
    'makro': ('Groceries', '🛒'),
    'villa market': ('Groceries', '🛒'),
    'villa': ('Groceries', '🛒'),
    'gourmet market': ('Groceries', '🛒'),
    'foodland': ('Groceries', '🛒'),
    'maxvalu': ('Groceries', '🛒'),
    'max value': ('Groceries', '🛒'),
    'donki': ('Groceries', '🛒'),
    'don don donki': ('Groceries', '🛒'),
    'don quijote': ('Groceries', '🛒'),
    'lawson': ('Groceries', '🛒'),
    'family mart': ('Groceries', '🛒'),
    'familymart': ('Groceries', '🛒'),
    '7-eleven': ('Groceries', '🛒'),
    '7-11': ('Groceries', '🛒'),
    '711': ('Groceries', '🛒'),
    'seven eleven': ('Groceries', '🛒'),
    'mini big c': ('Groceries', '🛒'),
    'cp fresh mart': ('Groceries', '🛒'),
    'cp freshmart': ('Groceries', '🛒'),
    'jiffy': ('Groceries', '🛒'),
    'donki': ('Groceries', '🛒'),
    'don don donki': ('Groceries', '🛒'),
    'fresh mart': ('Groceries', '🛒'),
    'talad': ('Groceries', '🛒'),
    'ampol food': ('Groceries', '🛒'),
    'big c extra': ('Groceries', '🛒'),
    'lotus express': ('Groceries', '🛒'),
    'the mall': ('Groceries', '🛒'),
    'eathai': ('Groceries', '🛒'),
    'rimping': ('Groceries', '🛒'),

    # ─── 🏠 Housing ───────────────────────────────────────────────────────
    'housing': ('Housing', '🏠'),
    'rent': ('Housing', '🏠'),
    'condo': ('Housing', '🏠'),
    'apartment': ('Housing', '🏠'),
    'utilities': ('Housing', '🏠'),
    'electric': ('Housing', '🏠'),
    'electricity': ('Housing', '🏠'),
    'electric bill': ('Housing', '🏠'),
    'pea': ('Housing', '🏠'),
    'mea': ('Housing', '🏠'),
    'water bill': ('Housing', '🏠'),
    'mwa': ('Housing', '🏠'),
    'internet': ('Housing', '🏠'),
    'wifi': ('Housing', '🏠'),
    'true internet': ('Housing', '🏠'),
    'ais fibre': ('Housing', '🏠'),
    '3bb': ('Housing', '🏠'),
    'tot': ('Housing', '🏠'),
    'nt': ('Housing', '🏠'),
    'phone bill': ('Housing', '🏠'),
    'mobile bill': ('Housing', '🏠'),
    'ais': ('Housing', '🏠'),
    'dtac': ('Housing', '🏠'),
    'true move': ('Housing', '🏠'),
    'truemove': ('Housing', '🏠'),
    'laundry': ('Housing', '🏠'),
    'cleaning': ('Housing', '🏠'),
    'maid': ('Housing', '🏠'),
    'furniture': ('Housing', '🏠'),
    'ikea': ('Housing', '🏠'),
    'home pro': ('Housing', '🏠'),
    'homepro': ('Housing', '🏠'),
    'thai watsadu': ('Housing', '🏠'),
    'baan & beyond': ('Housing', '🏠'),
    'index living': ('Housing', '🏠'),
    'sb furniture': ('Housing', '🏠'),
    'mr diy': ('Housing', '🏠'),
    'aircon': ('Housing', '🏠'),
    'air conditioner': ('Housing', '🏠'),
    'air con': ('Housing', '🏠'),
    'true online': ('Housing', '🏠'),
    'ais broadband': ('Housing', '🏠'),
    'pest control': ('Housing', '🏠'),
    'internet bill': ('Housing', '🏠'),

    # ─── 💊 Health ────────────────────────────────────────────────────────
    'health': ('Health', '💊'),
    'pharmacy': ('Health', '💊'),
    'clinic': ('Health', '💊'),
    'hospital': ('Health', '💊'),
    'doctor': ('Health', '💊'),
    'dentist': ('Health', '💊'),
    'dental': ('Health', '💊'),
    'medicine': ('Health', '💊'),
    'drug': ('Health', '💊'),
    'drugs': ('Health', '💊'),
    'vitamin': ('Health', '💊'),
    'vitamins': ('Health', '💊'),
    'multivitamin': ('Health', '💊'),
    'supplement': ('Health', '💊'),
    'supplements': ('Health', '💊'),
    # Brands
    'swisse': ('Health', '💊'),
    'dr pong': ('Health', '💊'),
    'dr.pong': ('Health', '💊'),
    'blackmores': ('Health', '💊'),
    'centrum': ('Health', '💊'),
    'vistra': ('Health', '💊'),
    'mega we care': ('Health', '💊'),
    'mega wecare': ('Health', '💊'),
    'amsel': ('Health', '💊'),
    'bioganic': ('Health', '💊'),
    'real elixir': ('Health', '💊'),
    'dhc': ('Health', '💊'),
    'nature bounty': ('Health', '💊'),
    'gnc': ('Health', '💊'),
    'now foods': ('Health', '💊'),
    'solgar': ('Health', '💊'),
    'whey protein': ('Health', '💊'),
    'protein': ('Health', '💊'),
    'collagen': ('Health', '💊'),
    'probiotic': ('Health', '💊'),
    'fish oil': ('Health', '💊'),
    'omega': ('Health', '💊'),
    'zinc': ('Health', '💊'),
    'magnesium': ('Health', '💊'),
    # Pharmacies & hospitals
    'boots': ('Health', '💊'),
    'watsons': ('Health', '💊'),
    'fascino': ('Health', '💊'),
    'bumrungrad': ('Health', '💊'),
    'samitivej': ('Health', '💊'),
    'bangkok hospital': ('Health', '💊'),
    'medpark': ('Health', '💊'),
    'praram 9': ('Health', '💊'),
    'phyathai': ('Health', '💊'),
    'dr.pong': ('Health', '💊'),
    'mega we care': ('Health', '💊'),
    'amsel': ('Health', '💊'),
    'dhc': ('Health', '💊'),
    'gnc': ('Health', '💊'),
    'now foods': ('Health', '💊'),
    'nature bounty': ('Health', '💊'),
    'real elixir': ('Health', '💊'),
    'bioganic': ('Health', '💊'),
    'protein': ('Health', '💊'),
    'whey protein': ('Health', '💊'),
    'whey': ('Health', '💊'),
    'creatine': ('Health', '💊'),
    'bcaa': ('Health', '💊'),
    'collagen': ('Health', '💊'),
    'probiotic': ('Health', '💊'),
    'probiotics': ('Health', '💊'),
    'fish oil': ('Health', '💊'),
    'omega 3': ('Health', '💊'),
    'zinc': ('Health', '💊'),
    'magnesium': ('Health', '💊'),
    'melatonin': ('Health', '💊'),
    'sunscreen': ('Health', '💊'),
    'spf': ('Health', '💊'),
    'face wash': ('Health', '💊'),
    'shampoo': ('Health', '💊'),
    'toothpaste': ('Health', '💊'),
    'toothbrush': ('Health', '💊'),
    'electric toothbrush': ('Health', '💊'),
    'panadol': ('Health', '💊'),
    'tylenol': ('Health', '💊'),
    'ibuprofen': ('Health', '💊'),
    'antigen test': ('Health', '💊'),
    'rapid test': ('Health', '💊'),
    'paolo': ('Health', '💊'),
    'sikarin': ('Health', '💊'),
    'bnh': ('Health', '💊'),
    'eye care': ('Health', '💊'),
    'glasses': ('Health', '💊'),
    'contact lens': ('Health', '💊'),
    'sunscreen': ('Health', '💊'),
    'skincare': ('Health', '💊'),

    # ─── 👗 Shopping ──────────────────────────────────────────────────────
    'shopping': ('Shopping', '👗'),
    'clothes': ('Shopping', '👗'),
    'clothing': ('Shopping', '👗'),
    'accessories': ('Shopping', '👗'),
    'shoes': ('Shopping', '👗'),
    'sneakers': ('Shopping', '👗'),
    'bag': ('Shopping', '👗'),
    'bags': ('Shopping', '👗'),
    'watch': ('Shopping', '👗'),
    'jewelry': ('Shopping', '👗'),
    'perfume': ('Shopping', '👗'),
    'cosmetics': ('Shopping', '👗'),
    'makeup': ('Shopping', '👗'),
    # Brands & stores
    'uniqlo': ('Shopping', '👗'),
    'h&m': ('Shopping', '👗'),
    'zara': ('Shopping', '👗'),
    'muji': ('Shopping', '👗'),
    'cotton on': ('Shopping', '👗'),
    'gu': ('Shopping', '👗'),
    'nike': ('Shopping', '👗'),
    'adidas': ('Shopping', '👗'),
    'converse': ('Shopping', '👗'),
    'vans': ('Shopping', '👗'),
    'new balance': ('Shopping', '👗'),
    'charles & keith': ('Shopping', '👗'),
    'aldo': ('Shopping', '👗'),
    'sephora': ('Shopping', '👗'),
    'eveandboy': ('Shopping', '👗'),
    'eve and boy': ('Shopping', '👗'),
    'beautrium': ('Shopping', '👗'),
    'naraya': ('Shopping', '👗'),
    'jaspal': ('Shopping', '👗'),
    'cc double o': ('Shopping', '👗'),
    'gentlewoman': ('Shopping', '👗'),
    'pomelo': ('Shopping', '👗'),
    # Online shopping
    'shopee': ('Shopping', '👗'),
    'lazada': ('Shopping', '👗'),
    'shopeepay': ('Shopping', '👗'),
    'tiktok shop': ('Shopping', '👗'),
    'amazon': ('Shopping', '👗'),
    'aliexpress': ('Shopping', '👗'),
    # Tech & electronics
    'headphones': ('Shopping', '👗'),
    'earbuds': ('Shopping', '👗'),
    'airpods': ('Shopping', '👗'),
    'sennheiser': ('Shopping', '👗'),
    'sony': ('Shopping', '👗'),
    'samsung': ('Shopping', '👗'),
    'apple': ('Shopping', '👗'),
    'iphone': ('Shopping', '👗'),
    'ipad': ('Shopping', '👗'),
    'macbook': ('Shopping', '👗'),
    'laptop': ('Shopping', '👗'),
    'phone case': ('Shopping', '👗'),
    'charger': ('Shopping', '👗'),
    'power bank': ('Shopping', '👗'),
    'banana it': ('Shopping', '👗'),
    'jib': ('Shopping', '👗'),
    'power buy': ('Shopping', '👗'),
    'powerbuy': ('Shopping', '👗'),
    'daiso': ('Shopping', '👗'),
    'miniso': ('Shopping', '👗'),
    'loft': ('Shopping', '👗'),
    'sephora': ('Shopping', '👗'),
    'eveandboy': ('Shopping', '👗'),
    'eve and boy': ('Shopping', '👗'),
    'beautrium': ('Shopping', '👗'),
    'mac cosmetics': ('Shopping', '👗'),
    'innisfree': ('Shopping', '👗'),
    'the face shop': ('Shopping', '👗'),
    'etude': ('Shopping', '👗'),
    'missha': ('Shopping', '👗'),
    'it city': ('Shopping', '👗'),
    'studio 7': ('Shopping', '👗'),
    'istudio': ('Shopping', '👗'),
    # Malls
    'central': ('Shopping', '👗'),
    'centralworld': ('Shopping', '👗'),
    'siam paragon': ('Shopping', '👗'),
    'emquartier': ('Shopping', '👗'),
    'emporium': ('Shopping', '👗'),
    'iconsiam': ('Shopping', '👗'),
    'terminal 21': ('Shopping', '👗'),
    'mbk': ('Shopping', '👗'),
    'platinum': ('Shopping', '👗'),
    'pratunam': ('Shopping', '👗'),
    'chatuchak': ('Shopping', '👗'),
    'jj market': ('Shopping', '👗'),
    'robinson': ('Shopping', '👗'),
    'mega bangna': ('Shopping', '👗'),
    'fashion island': ('Shopping', '👗'),
    'future park': ('Shopping', '👗'),
    'seacon': ('Shopping', '👗'),

    # ─── 🎉 Entertainment ─────────────────────────────────────────────────
    'entertainment': ('Entertainment', '🎉'),
    'movies': ('Entertainment', '🎉'),
    'movie': ('Entertainment', '🎉'),
    'cinema': ('Entertainment', '🎉'),
    'sf cinema': ('Entertainment', '🎉'),
    'major cineplex': ('Entertainment', '🎉'),
    'major': ('Entertainment', '🎉'),
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
    'siam ocean world': ('Entertainment', '🎉'),
    'madame tussauds': ('Entertainment', '🎉'),
    'kidzania': ('Entertainment', '🎉'),
    'theme park': ('Entertainment', '🎉'),
    'water park': ('Entertainment', '🎉'),
    'spa': ('Entertainment', '🎉'),
    'massage': ('Entertainment', '🎉'),
    'thai massage': ('Entertainment', '🎉'),
    'onsen': ('Entertainment', '🎉'),
    'let relax': ('Entertainment', '🎉'),
    'health land': ('Entertainment', '🎉'),
    'gym': ('Entertainment', '🎉'),
    'fitness': ('Entertainment', '🎉'),
    'fitness first': ('Entertainment', '🎉'),
    'virgin active': ('Entertainment', '🎉'),
    'jetts': ('Entertainment', '🎉'),
    'anytime fitness': ('Entertainment', '🎉'),
    'yoga': ('Entertainment', '🎉'),
    'swimming': ('Entertainment', '🎉'),
    'pool': ('Entertainment', '🎉'),
    'game': ('Entertainment', '🎉'),
    'games': ('Entertainment', '🎉'),
    'steam': ('Entertainment', '🎉'),
    'playstation': ('Entertainment', '🎉'),
    'nintendo': ('Entertainment', '🎉'),
    'hbo': ('Entertainment', '🎉'),
    'hbo go': ('Entertainment', '🎉'),
    'wetv': ('Entertainment', '🎉'),
    'viu': ('Entertainment', '🎉'),
    'monomax': ('Entertainment', '🎉'),
    'true id': ('Entertainment', '🎉'),
    'joox': ('Entertainment', '🎉'),
    'muay thai': ('Entertainment', '🎉'),
    'boxing': ('Entertainment', '🎉'),
    'pilates': ('Entertainment', '🎉'),
    'crossfit': ('Entertainment', '🎉'),
    'badminton': ('Entertainment', '🎉'),
    'tennis': ('Entertainment', '🎉'),
    'golf': ('Entertainment', '🎉'),
    'running': ('Entertainment', '🎉'),
    'beer': ('Entertainment', '🎉'),
    'wine': ('Entertainment', '🎉'),
    'whiskey': ('Entertainment', '🎉'),
    'cocktail': ('Entertainment', '🎉'),
    'alcohol': ('Entertainment', '🎉'),
    'singha': ('Entertainment', '🎉'),
    'chang': ('Entertainment', '🎉'),
    'leo': ('Entertainment', '🎉'),
    'heineken': ('Entertainment', '🎉'),

    # ─── 📱 Subscriptions ─────────────────────────────────────────────────
    'subscription': ('Subscriptions', '📱'),
    'subscriptions': ('Subscriptions', '📱'),
    'youtube': ('Subscriptions', '📱'),
    'youtube premium': ('Subscriptions', '📱'),
    'netflix': ('Subscriptions', '📱'),
    'spotify': ('Subscriptions', '📱'),
    'apple music': ('Subscriptions', '📱'),
    'disney plus': ('Subscriptions', '📱'),
    'disney+': ('Subscriptions', '📱'),
    'hbo go': ('Subscriptions', '📱'),
    'viu': ('Subscriptions', '📱'),
    'wetv': ('Subscriptions', '📱'),
    'iqiyi': ('Subscriptions', '📱'),
    'google one': ('Subscriptions', '📱'),
    'icloud': ('Subscriptions', '📱'),
    'chatgpt': ('Subscriptions', '📱'),
    'openai': ('Subscriptions', '📱'),
    'canva': ('Subscriptions', '📱'),
    'adobe': ('Subscriptions', '📱'),
    'notion': ('Subscriptions', '📱'),
    'line': ('Subscriptions', '📱'),
    'true id': ('Subscriptions', '📱'),
    'ais play': ('Subscriptions', '📱'),
    'monomax': ('Subscriptions', '📱'),

    # ─── ✈️ Travel ─────────────────────────────────────────────────────────
    'travel': ('Travel', '✈️'),
    'hotel': ('Travel', '✈️'),
    'hostel': ('Travel', '✈️'),
    'airbnb': ('Travel', '✈️'),
    'agoda': ('Travel', '✈️'),
    'booking.com': ('Travel', '✈️'),
    'flight': ('Travel', '✈️'),
    'airline': ('Travel', '✈️'),
    'airasia': ('Travel', '✈️'),
    'nok air': ('Travel', '✈️'),
    'lion air': ('Travel', '✈️'),
    'thai airways': ('Travel', '✈️'),
    'vietjet': ('Travel', '✈️'),
    'bangkok airways': ('Travel', '✈️'),
    'trip': ('Travel', '✈️'),
    'vacation': ('Travel', '✈️'),
    'holiday': ('Travel', '✈️'),
    'passport': ('Travel', '✈️'),
    'visa fee': ('Travel', '✈️'),
    'luggage': ('Travel', '✈️'),
    'suitcase': ('Travel', '✈️'),
    'klook': ('Travel', '✈️'),
    'kkday': ('Travel', '✈️'),
    'traveloka': ('Travel', '✈️'),

    # ─── 🎓 School ────────────────────────────────────────────────────────
    'school': ('School', '🎓'),
    'tuition': ('School', '🎓'),
    'books': ('School', '🎓'),
    'book': ('School', '🎓'),
    'textbook': ('School', '🎓'),
    'stationery': ('School', '🎓'),
    'language': ('School', '🎓'),
    'italian': ('School', '🎓'),
    'class': ('School', '🎓'),
    'course': ('School', '🎓'),
    'workshop': ('School', '🎓'),
    'seminar': ('School', '🎓'),
    'training': ('School', '🎓'),
    'udemy': ('School', '🎓'),
    'skillshare': ('School', '🎓'),
    'coursera': ('School', '🎓'),
    'se-ed': ('School', '🎓'),
    'b2s': ('School', '🎓'),
    'kinokuniya': ('School', '🎓'),
    'asia books': ('School', '🎓'),

    # ─── 🚬 Cigarettes ──────────────────────────────────────────────────
    'cigarette': ('Cigarettes', '🚬'),
    'cigarettes': ('Cigarettes', '🚬'),
    'cig': ('Cigarettes', '🚬'),
    'cigs': ('Cigarettes', '🚬'),
    'smoke': ('Cigarettes', '🚬'),
    'smoking': ('Cigarettes', '🚬'),
    'tobacco': ('Cigarettes', '🚬'),
    'marlboro': ('Cigarettes', '🚬'),
    'lm': ('Cigarettes', '🚬'),
    'winston': ('Cigarettes', '🚬'),
    'camel': ('Cigarettes', '🚬'),
    'lucky strike': ('Cigarettes', '🚬'),
    'dunhill': ('Cigarettes', '🚬'),
    'esse': ('Cigarettes', '🚬'),
    'krong thip': ('Cigarettes', '🚬'),
    'krongthip': ('Cigarettes', '🚬'),
    'sai fon': ('Cigarettes', '🚬'),
    'falling rain': ('Cigarettes', '🚬'),
    'wonder': ('Cigarettes', '🚬'),
    'vape': ('Cigarettes', '🚬'),
    'pod': ('Cigarettes', '🚬'),
    'iqos': ('Cigarettes', '🚬'),
    'relx': ('Cigarettes', '🚬'),

    # ─── 💵 Income ────────────────────────────────────────────────────────
    'salary': ('Salary', '💵'),
    'freelance': ('Freelance', '💼'),
    'gallery': ('Gallery Sales', '🖼️'),
    'gallery sales': ('Gallery Sales', '🖼️'),
    'artwork': ('Artwork / Commission', '🎨'),
    'sold': ('Gallery Sales', '🖼️'),
    'commission': ('Artwork / Commission', '🎨'),
    'bonus': ('Bonus', '🏆'),
    'refund': ('Cashback / Refund', '💳'),
    'cashback': ('Cashback / Refund', '💳'),
    'dividend': ('Investment', '💹'),
    'interest': ('Investment', '💹'),
    'investment': ('Investment', '💹'),
    'gift money': ('Gift Money', '🎁'),
    'angpao': ('Gift Money', '🎁'),
    'prize': ('Bonus', '🏆'),
    'business': ('Business', '🤝'),
}

CATEGORY_LIST = [
    ('🍜', 'Food & Drinks'),
    ('☕', 'Coffee'),
    ('🚕', 'Transport'),
    ('🛒', 'Groceries'),
    ('🏠', 'Housing'),
    ('💊', 'Health'),
    ('👗', 'Shopping'),
    ('🎉', 'Entertainment'),
    ('📱', 'Subscriptions'),
    ('✈️', 'Travel'),
    ('🎓', 'School'),
    ('🚬', 'Cigarettes'),
    ('🧾', 'Other'),
]

INCOME_CATEGORY_LIST = [
    ('💵', 'Salary'),
    ('💼', 'Freelance'),
    ('🖼️', 'Gallery Sales'),
    ('🎨', 'Artwork / Commission'),
    ('🏆', 'Bonus'),
    ('🎁', 'Gift Money'),
    ('💳', 'Cashback / Refund'),
    ('💹', 'Investment'),
    ('🤝', 'Business'),
    ('🧾', 'Other Income'),
]

ACCOUNT_KEYWORDS = {
    'bank': 'Bangkok Bank',
    'bangkok bank': 'Bangkok Bank',
    'bbl': 'Bangkok Bank',
    'true money': 'True Money Wallet',
    'truemoney': 'True Money Wallet',
    'true wallet': 'True Money Wallet',
    'mrt': 'MRT EMV Visa',
    'emv': 'MRT EMV Visa',
    'visa': 'MRT EMV Visa',
    'rabbit': 'Rabbit Card',
    'rabbit card': 'Rabbit Card',
    'cash': 'Cash',
    'muvmi': 'Muvmi',
    'solsot': 'Solsot Member',
    'solsot member': 'Solsot Member',
}


# ─── Database ─────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        balance REAL NOT NULL DEFAULT 0.0,
        UNIQUE(user_id, name)
    );
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        emoji TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        type TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'Other',
        account TEXT NOT NULL DEFAULT 'Cash',
        timestamp DATETIME DEFAULT (datetime('now', '+7 hours'))
    );
    CREATE TABLE IF NOT EXISTS recurring_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL DEFAULT 'Subscriptions',
        account TEXT NOT NULL DEFAULT 'Cash',
        next_due_date DATE NOT NULL,
        frequency TEXT NOT NULL DEFAULT 'monthly'
    );
    """)
    for emoji, name in CATEGORY_LIST:
        c.execute("INSERT OR IGNORE INTO categories (name, emoji) VALUES (?, ?)", (name, emoji))
    # Create accounts if they don't exist (with 0 balance — use /updatebalance to set correct values)
    # INSERT OR IGNORE means this only runs on a fresh database, never overwrites existing balances
    uid = AUTHORIZED_USER_ID
    for user_id, name in [
        (uid, 'Bangkok Bank'),
        (uid, 'True Money Wallet'),
        (uid, 'MRT EMV Visa'),
        (uid, 'Rabbit Card'),
        (uid, 'Cash'),
        (uid, 'Muvmi'),
        (uid, 'Solsot Member'),
    ]:
        c.execute("INSERT OR IGNORE INTO accounts (user_id, name, balance) VALUES (?, ?, 0.0)", (user_id, name))
    # Note: Subscriptions are managed via /addsubscription and /deletesubscription commands.
    # No hardcoded subscription seeds — the live database on Render has the real data.
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Helpers ──────────────────────────────────────────────────────────────
def detect_category(text):
    text_lower = text.lower()
    sorted_keywords = sorted(CATEGORIES.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if keyword in text_lower:
            return CATEGORIES[keyword]
    return ('Other', '🧾')


def detect_account(text):
    text_lower = text.lower()
    sorted_keywords = sorted(ACCOUNT_KEYWORDS.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if keyword in text_lower:
            return ACCOUNT_KEYWORDS[keyword]
    return 'Cash'


# ─── Recurring subscription auto-processing ─────────────────────────────────
def process_due_subscriptions():
    """Check and process any overdue subscriptions.
    Returns list of (sub_name, amount, account, user_id) tuples that were processed.
    """
    conn = get_db()
    c = conn.cursor()
    today = datetime.now(BANGKOK_TZ).date()
    today_str = str(today)

    logger.info(f"Checking subscriptions for date: {today_str}")

    c.execute(
        "SELECT id, user_id, name, amount, category, account, next_due_date, frequency "
        "FROM recurring_subscriptions WHERE next_due_date <= ?",
        (today_str,)
    )
    due_subs = c.fetchall()
    processed = []

    logger.info(f"Found {len(due_subs)} due subscription(s)")

    for sub in due_subs:
        amount = sub['amount']
        logger.info(f"Processing subscription: {sub['name']} ฿{amount} from {sub['account']} (due: {sub['next_due_date']})")

        c.execute(
            "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, 'expense', ?, ?)",
            (sub['user_id'], -amount, f"🔄 {sub['name']} (auto)", sub['category'], sub['account'])
        )
        c.execute(
            "UPDATE accounts SET balance = balance - ? WHERE user_id = ? AND name = ?",
            (amount, sub['user_id'], sub['account'])
        )

        # Calculate next due date
        due_date = datetime.strptime(sub['next_due_date'], "%Y-%m-%d").date()
        if sub['frequency'] == 'monthly':
            if due_date.month == 12:
                next_due = due_date.replace(year=due_date.year + 1, month=1)
            else:
                try:
                    next_due = due_date.replace(month=due_date.month + 1)
                except ValueError:
                    next_due = (due_date.replace(day=1) + timedelta(days=32)).replace(day=due_date.day)
        elif sub['frequency'] == 'weekly':
            next_due = due_date + timedelta(weeks=1)
        elif sub['frequency'] == 'yearly':
            next_due = due_date.replace(year=due_date.year + 1)
        else:
            next_due = due_date + timedelta(days=30)

        c.execute("UPDATE recurring_subscriptions SET next_due_date = ? WHERE id = ?", (str(next_due), sub['id']))
        processed.append((sub['name'], amount, sub['account'], sub['user_id']))
        logger.info(f"Subscription '{sub['name']}' logged. Next due: {next_due}")

    conn.commit()
    conn.close()
    return processed


# ─── Google Drive Monthly Backup ─────────────────────────────────────────────
GDRIVE_FOLDER_ID = '1_APGayoUno9u-7-nKHZ-Fxk0ntt-WRqg'


def get_gdrive_service():
    """Build Google Drive service from service account JSON in env var."""
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    if not creds_json:
        logger.error("GOOGLE_SERVICE_ACCOUNT_JSON not set in environment.")
        return None
    try:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build Drive service: {e}")
        return None


def upload_to_gdrive(file_bytes: bytes, filename: str, error_out: list = None) -> str:
    """Upload a file to Google Drive. Returns the file URL or empty string.
    If error_out is provided (a list), the real exception text is appended
    to it on failure so callers can surface Google's actual error message."""
    if not GDRIVE_AVAILABLE:
        logger.error("Google API packages not available.")
        if error_out is not None:
            error_out.append("Google API packages not available.")
        return ''
    service = get_gdrive_service()
    if not service:
        if error_out is not None:
            error_out.append("Could not build Google Drive service — check GOOGLE_SERVICE_ACCOUNT_JSON is valid.")
        return ''
    try:
        file_metadata = {
            'name': filename,
            'parents': [GDRIVE_FOLDER_ID]
        }
        media = MediaIoBaseUpload(
            io.BytesIO(file_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            resumable=False
        )
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        link = uploaded.get('webViewLink', '')
        logger.info(f"Uploaded {filename} to Google Drive: {link}")
        return link
    except Exception as e:
        logger.error(f"Google Drive upload failed: {e}")
        if error_out is not None:
            error_out.append(str(e))
        return ''


def generate_monthly_excel(year: int, month: int) -> bytes:
    """Generate Excel export for a given month. Returns bytes."""
    import calendar as cal_mod
    month_start = f"{year}-{month:02d}-01"
    month_end   = f"{year+1}-01-01" if month == 12 else f"{year}-{month+1:02d}-01"

    conn = get_db()
    c    = conn.cursor()
    c.execute(
        "SELECT timestamp, type, amount, description, category, account "
        "FROM transactions WHERE user_id = ? AND timestamp >= ? AND timestamp < ? "
        "ORDER BY timestamp",
        (AUTHORIZED_USER_ID, month_start, month_end)
    )
    txns = c.fetchall()
    c.execute("SELECT name, balance FROM accounts WHERE user_id = ? ORDER BY id", (AUTHORIZED_USER_ID,))
    accounts = c.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = f"{cal_mod.month_name[month]} {year}"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0052FF", end_color="0052FF", fill_type="solid")
    money_fmt   = '#,##0.00'

    headers = ['Date', 'Type', 'Amount (฿)', 'Description', 'Category', 'Account']
    for ci, h in enumerate(headers, 1):
        cell            = ws.cell(1, ci, h)
        cell.font       = header_font
        cell.fill       = header_fill
        cell.alignment  = Alignment(horizontal='center')

    income_total = 0; expense_total = 0
    for ri, txn in enumerate(txns, 2):
        ts, typ, amt, desc, cat, acc = txn
        val = abs(float(amt))
        ws.cell(ri, 1, (ts or '')[:16])
        ws.cell(ri, 2, typ.title())
        amount_cell = ws.cell(ri, 3, val if typ == 'income' else -val)
        amount_cell.number_format = money_fmt
        ws.cell(ri, 4, desc or '')
        ws.cell(ri, 5, cat or '')
        ws.cell(ri, 6, acc or '')
        if typ == 'income':   income_total  += val
        elif typ == 'expense': expense_total += val

    # Summary rows
    sr = len(txns) + 3
    ws.cell(sr,   2, "Income:").font   = Font(bold=True)
    ws.cell(sr,   3, income_total).number_format  = money_fmt
    ws.cell(sr+1, 2, "Expenses:").font = Font(bold=True)
    ws.cell(sr+1, 3, expense_total).number_format = money_fmt
    ws.cell(sr+2, 2, "Net:").font      = Font(bold=True)
    ws.cell(sr+2, 3, income_total - expense_total).number_format = money_fmt

    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 10
    ws.column_dimensions['C'].width = 14
    ws.column_dimensions['D'].width = 30
    ws.column_dimensions['E'].width = 16
    ws.column_dimensions['F'].width = 20

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# ─── Report helper used by /api endpoints (kept minimal, no Telegram) ───────
def get_account_balances(user_id=None):
    """Convenience helper: list of {name, balance} dicts."""
    user_id = user_id or AUTHORIZED_USER_ID
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, balance FROM accounts WHERE user_id = ? ORDER BY id", (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
