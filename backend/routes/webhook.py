import os
import hmac
import hashlib
import time
import threading
import re
from collections import deque
import requests as http_requests
import mimetypes as mt
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, current_app

from models.user import save_user, get_user_mode
from models.message import save_message, update_message_status
from models.database import get_db
from bot.ai_client import ask_ai
from bot.whatsapp_handler import send_text, send_main_menu, send_service_menu
from utils.logger import get_logger

log = get_logger(__name__)

webhook_bp = Blueprint("webhook", __name__)

_executor = ThreadPoolExecutor(max_workers=10)

# ── Duplicate-webhook-delivery guard ─────────────────────────────────────
# WhatsApp retries webhook deliveries, so we track which message ids we've
# already handled. Two fixes vs. the old plain `set()`:
#   1. Bounded via a deque + set pair, evicting the OLDEST ids once we hit
#      the cap — instead of `.clear()`-ing the whole cache, which used to
#      forget everything at once and let old retried messages slip through
#      and get reprocessed (duplicate AI replies / duplicate sends).
#   2. Guarded by a lock so the check-and-reserve is atomic — two
#      near-simultaneous webhook deliveries for the same message id can no
#      longer both pass the "not seen yet" check before either records it.
_processed_ids = set()
_processed_ids_order = deque()
_processed_lock = threading.Lock()
MAX_PROCESSED_IDS = 10000

_user_service_context = {}
_contact_collection = {}   # phone -> {"step": "awaiting_name"/"awaiting_mobile"/"awaiting_time", "name": ..., "mobile": ...}
_user_context = {}         # phone -> "main" once a consultation flow completes (kept for future use)

CONTACT = "03003029093 / 03332454111"
MEDIA_FOLDER = "media_files"

# Marker phrase embedded in every choice-gated prompt below — used to
# detect "this message just asked the customer to choose between a
# callback and calling us directly" without relying on an exact-string
# match against the whole message (fragile — breaks the instant the
# wording changes even slightly). See _is_consult_choice_prompt().
_CALLBACK_CHOICE_MARKER = "call you back? Reply:"


def _consult_choice_message(intro: str) -> str:
    """Shared template for 'Talk to Expert' / 'Talk to Lawyer' style
    replies — as opposed to explicit 'Book Consultation' replies, these
    give the phone number immediately and ASK whether the customer wants
    a callback, rather than assuming it and immediately demanding their
    name/mobile/time."""
    return (
        f"{intro}\n\n"
        f"📞 Call or WhatsApp us directly: {CONTACT}\n\n"
        f"Would you like our team to call you back? Reply:\n"
        f"1️⃣ Yes, call me back\n"
        f"2️⃣ No thanks, I'll reach out myself"
    )


# ── All your existing BUTTON_RESPONSES, BIZ_SUB_MENU, etc. ───────────────
# (keeping them exactly as you have them)

BUTTON_RESPONSES = {
    "biz_business": (
        "🏢 *Business Consultancy*\n\n"
        "We offer:\n"
        "• Private Limited / SMC / LLC Registration (UK / USA)\n"
        "• Partnership / AOP Registration\n"
        "• Proprietorship Registration\n"
        "• Trademark & Copyright Registration\n"
        "• Patent, KCCI, PEC, DTS, PSEB Registration\n\n"
        f"Reply with what you need or contact us: {CONTACT}"
    ),
    "biz_ngo": (
        "💰 *NGO / Charity Registration*\n\n"
        "Required Documents:\n"
        "• CNIC of all members\n"
        "• Contact details of all members\n"
        "• NGO Name & Office Address\n"
        "• Nature of charity (Education, Health, Food, etc.)\n"
        "• Utility Bill\n"
        "• Rent Agreement / Ownership Documents\n\n"
        f"Cost & timeline may vary. Contact us: {CONTACT}"
    ),
    "biz_tax": (
        "💰 *Taxation Services*\n\n"
        "We handle:\n"
        "• NTN Registration — Individual (Rs.500 / 30 mins)\n"
        "• NTN Registration — Business (Sole Proprietor / Partnership / Company)\n"
        "• Income Tax Returns (Salaried, Freelancer, Business, Company, Overseas Pakistani)\n"
        "• Sales Tax Registration & Monthly Returns\n"
        "• Provincial Tax (SRB, PRA, BRA, KPRA)\n"
        "• ATL Status & Restoration\n"
        "• Tax Notices (FBR, Audit, Section 111/114/122)\n"
        "• Tax Refunds\n\n"
        f"Contact our tax experts: {CONTACT}"
    ),
    "biz_accounts": (
        "📊 *Accountancy Services*\n\n"
        "We offer:\n"
        "• Bookkeeping (Sales, Purchases, Bank Reconciliation, etc.)\n"
        "• Annual Accounts Management\n"
        "• Audited Accounts\n"
        "• Internal & External Audit\n"
        "• Financial Reporting (Monthly, Quarterly, Annual)\n"
        "• Accounting Software (QuickBooks, Xero, Excel, Customized Solution)\n\n"
        "Our bookkeeping specialists can help you maintain accurate and up-to-date financial records.\n\n"
        f"Contact us: {CONTACT}"
    ),
    "biz_legal": (
        "⚖️ *Corporate Legal Advisory*\n\n"
        "We handle:\n"
        "• Contract Drafting (Business, Partnership, Employment, NDA, MoU)\n"
        "• Corporate Compliance (SECP, Annual Returns, Board Resolutions)\n"
        "• Legal Notices (Recovery, Breach of Contract, Demand, Tenant)\n"
        "• Legal Opinions & Contract Reviews\n"
        "• Regulatory Compliance (SECP, FBR, IPO, Labour Laws)\n"
        "• Company Secretarial Services\n"
        "• Legal Consultation (Startup, SME, Corporate Advisory, Business Risk Assessment)\n\n"
        "Our legal advisory specialists will assess your requirements and recommend the most suitable solution.\n\n"
        f"Contact us: {CONTACT}"
    ),
    "biz_digital": (
        "📈 *Digital Marketing*\n\n"
        "We offer:\n"
        "• Social Media Marketing\n"
        "• Meta Ads (Facebook & Instagram)\n"
        "• Google Ads\n"
        "• SEO (Search Engine Optimization)\n"
        "• Website Development\n"
        "• Content Writing\n"
        "• Branding & Graphic Design\n"
        "• Marketing Consultation\n\n"
        "Our digital marketing specialists will evaluate your business objectives and recommend the most effective strategy.\n\n"
        f"Contact us: {CONTACT}"
    ),
    "biz_urgent": (
        "🚨 *Urgent Help*\n\n"
        "If you have received any of the following, contact us immediately:\n\n"
        f"• FBR Notice Received → {CONTACT}\n"
        f"• SECP Deadline → {CONTACT}\n"
        f"• Tax Return Deadline → {CONTACT}\n"
        f"• Legal Notice Received → {CONTACT}\n\n"
        "Our team is ready to assist you right away."
    ),
    "biz_consult": _consult_choice_message(
        "👨‍💼 *Talk to an Expert*\n\nOur consultants are available to help you."
    ),
    "nikah_procedure": f"📋 *Online Nikah Procedure:*\n\n• At least one party must be residing outside Pakistan.\n• The legal process is identical to a conventional Nikah.\n• One party participates remotely through a secure online platform.\n\nWould you like to book a consultation with our legal team?",
    "nikah_documents": f"📄 *Required Documents for Online Nikah:*\n\nFrom both parties:\n• Valid CNIC / NICOP or Passport\n• Recent passport-size photographs\n• 2 Witnesses (CNIC of both witnesses)\n\nWould you like to book a consultation?",
    "nikah_consult": _consult_choice_message(
        "💬 *Online Nikah — Talk to a Lawyer*"
    ),
    "court_procedure": "📋 *Court Marriage Procedure:*\n\n• Both parties must be present in person.\n• All legal requirements are the same as a conventional Nikah.\n\nWould you like to book a consultation?",
    "court_documents": "📄 *Required Documents for Court Marriage:*\n\nFrom both parties:\n• Valid CNIC / NICOP or Passport\n• Recent passport-size photographs\n• 2 Witnesses (CNIC of both witnesses)\n\nWould you like to book a consultation?",
    "court_consult": "💬 Our legal team will be in touch shortly to assist you with Court Marriage.",
    "divorce_procedure": "📋 *Divorce / Khula Procedure:*\n\nEvery case is unique. Please consult one of our legal experts for advice tailored to your specific situation.",
    "divorce_timeline": "⏳ *Divorce / Khula Timeline:*\n\nThe timeline varies depending on the nature and complexity of your case.",
    "divorce_consult": "💬 Our legal expert will contact you shortly to discuss your Divorce / Khula case. Your matter will be handled with full confidentiality.",
    "custody_procedure": "📋 *Child Custody / Guardianship:*\n\nThis matter requires a detailed legal assessment. Our legal team will be happy to assist you personally.",
    "custody_timeline": "⏳ *Timeline:*\n\nEach case is unique; the estimated timeline may vary.",
    "custody_consult": _consult_choice_message(
        "💬 *Child Custody / Guardianship — Talk to an Expert*"
    ),
    "maintenance_procedure": "📋 *Maintenance (Nafaqa) / Dowery:*\n\nThis matter cannot be accurately assessed through chat alone. Our legal team will assist you personally.",
    "maintenance_timeline": "⏳ *Timeline:*\n\nEach case is unique; the estimated timeline may vary.",
    "maintenance_consult": _consult_choice_message(
        "💬 *Maintenance / Dowery — Talk to an Expert*"
    ),
    "property_procedure": "📋 *Property Law:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "property_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "property_consult": "💬 Our property law expert will contact you shortly.",
    "inheritance_procedure": "📋 *Inheritance:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "inheritance_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "inheritance_consult": _consult_choice_message(
        "💬 *Inheritance — Talk to an Expert*"
    ),
    "corporate_procedure": "📋 *Corporate Law:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "corporate_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "corporate_consult": _consult_choice_message(
        "💬 *Corporate Law — Talk to an Expert*"
    ),
    "docs_procedure": "📋 *Legal Documentation:*\n\nThis requires a detailed legal consultation. Our legal team can assist with document drafting and verification.",
    "docs_timeline": "⏳ *Timeline:*\n\nThe duration depends on the type and complexity of documentation required.",
    "docs_consult": "💬 Our legal team will contact you shortly to assist with your documentation needs.",
    "contact_us": _consult_choice_message("📞 *Contact Us*"),
}

TEXT_SUB_MENU = {
    "online_nikah":   "You selected *Online Marriage / Online Nikah* 🕌\n\nReply with:\n1️⃣ Procedure\n2️⃣ Documents\n3️⃣ Talk to a Lawyer",
    "court_marriage": "You selected *Court Marriage* 💍\n\nReply with:\n1️⃣ Procedure\n2️⃣ Documents\n3️⃣ Book Consultation",
    "divorce_khula":  "You selected *Divorce / Khula* 📄\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Book Consultation",
    "child_custody":  "You selected *Child Custody / Guardianship* 👶\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "maintenance":    "You selected *Maintenance / Dowery* 💰\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "property_law":   "You selected *Property Law* 🏠\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Book Consultation",
    "inheritance":    "You selected *Inheritance* 📜\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "corporate_law":  "You selected *Corporate Law* 🤝\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "legal_docs":     "You selected *Legal Documentation* 📑\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Book Consultation",
}

TEXT_SUB_RESPONSES = {
    "online_nikah":   {"1": BUTTON_RESPONSES["nikah_procedure"],    "2": BUTTON_RESPONSES["nikah_documents"],       "3": BUTTON_RESPONSES["nikah_consult"]},
    "court_marriage": {"1": BUTTON_RESPONSES["court_procedure"],    "2": BUTTON_RESPONSES["court_documents"],       "3": BUTTON_RESPONSES["court_consult"]},
    "divorce_khula":  {"1": BUTTON_RESPONSES["divorce_procedure"],  "2": BUTTON_RESPONSES["divorce_timeline"],      "3": BUTTON_RESPONSES["divorce_consult"]},
    "child_custody":  {"1": BUTTON_RESPONSES["custody_procedure"],  "2": BUTTON_RESPONSES["custody_timeline"],      "3": BUTTON_RESPONSES["custody_consult"]},
    "maintenance":    {"1": BUTTON_RESPONSES["maintenance_procedure"], "2": BUTTON_RESPONSES["maintenance_timeline"],"3": BUTTON_RESPONSES["maintenance_consult"]},
    "property_law":   {"1": BUTTON_RESPONSES["property_procedure"], "2": BUTTON_RESPONSES["property_timeline"],     "3": BUTTON_RESPONSES["property_consult"]},
    "inheritance":    {"1": BUTTON_RESPONSES["inheritance_procedure"],"2": BUTTON_RESPONSES["inheritance_timeline"],"3": BUTTON_RESPONSES["inheritance_consult"]},
    "corporate_law":  {"1": BUTTON_RESPONSES["corporate_procedure"],"2": BUTTON_RESPONSES["corporate_timeline"],   "3": BUTTON_RESPONSES["corporate_consult"]},
    "legal_docs":     {"1": BUTTON_RESPONSES["docs_procedure"],     "2": BUTTON_RESPONSES["docs_timeline"],         "3": BUTTON_RESPONSES["docs_consult"]},
}

BIZ_SUB_MENU = {
    "biz_business": (
        "🏢 *Business Consultancy* — which registration do you need?\n\n"
        "1️⃣ Private Limited / SMC / LLC (UK / USA)\n"
        "2️⃣ Partnership Firm / AOP\n"
        "3️⃣ Proprietorship\n"
        "4️⃣ Trademark Registration\n"
        "5️⃣ Copyright Registration\n"
        "6️⃣ Patent Registration\n"
        "7️⃣ Other Registrations (KCCI / PEC / DTS / PSEB)\n"
        "8️⃣ Talk to an Expert"
    ),
    "biz_tax": (
        "💰 *Taxation Services* — which service do you need?\n\n"
        "1️⃣ NTN Registration — Individual\n"
        "2️⃣ NTN Registration — Business\n"
        "3️⃣ Income Tax Return\n"
        "4️⃣ Sales Tax Registration\n"
        "5️⃣ Sales Tax Monthly Return\n"
        "6️⃣ Provincial Sales Tax (SRB/PRA/BRA/KPRA)\n"
        "7️⃣ ATL (Active Taxpayer List)\n"
        "8️⃣ Tax Notices\n"
        "9️⃣ Tax Refund\n"
        "🔟 Talk to an Expert"
    ),
    "biz_accounts": (
        "📊 *Accountancy Services* — which service do you need?\n\n"
        "1️⃣ Bookkeeping\n"
        "2️⃣ Annual Accounts Management\n"
        "3️⃣ Audited Accounts\n"
        "4️⃣ Internal & External Audit\n"
        "5️⃣ Financial Reporting\n"
        "6️⃣ Accounting Consultation\n"
        "7️⃣ Talk to an Expert"
    ),
    "biz_legal": (
        "⚖️ *Corporate Legal Advisory* — which service do you need?\n\n"
        "1️⃣ Contract Drafting\n"
        "2️⃣ Corporate Compliance\n"
        "3️⃣ Legal Notices\n"
        "4️⃣ Legal Opinions\n"
        "5️⃣ Regulatory Compliance\n"
        "6️⃣ Company Secretarial Services\n"
        "7️⃣ Legal Consultation\n"
        "8️⃣ Talk to an Expert"
    ),
}

BIZ_SUB_RESPONSES = {
    "biz_business": {
        "1": (
            "🏢 *Private Limited / SMC / LLC Registration (UK / USA)*\n\n"
            "Company Types: Private Limited Company, Single Member Company (SMC), LLC Registration (UK / USA)\n\n"
            "Required Documents:\n• Director CNIC\n• Shareholder Details\n• Company Name\n• Office Address\n"
            "• Business Activity\n• Contact Number\n• Email Address\n\n"
            f"Cost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "2": (
            "🏢 *Partnership Firm / AOP Registration*\n\n"
            "Required Documents:\n• Director CNIC\n• Shareholder Details\n• Company Name\n• Office Address\n"
            f"• Business Activity\n• Contact Number\n• Email Address\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "3": (
            "🏢 *Proprietorship Registration*\n\n"
            f"Required Documents:\n• CNIC\n• Mobile Number\n• Business Address\n• Nature of Business\n• Email Address\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "4": (
            "™️ *Trademark Registration*\n\nRegister your Brand Name or Logo.\n\n"
            f"Required Documents:\n• Applicant CNIC\n• Brand Name\n• Logo (Optional)\n• Business Details\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "5": (
            "©️ *Copyright Registration*\n\nWhat can be registered: Literary Work, Software, Music\n\n"
            f"Required Documents:\n• Business Registration Documents\n• Utility Bill\n• Owner's CNIC\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "6": (
            "📜 *Patent Registration*\n\n"
            f"Required Documents:\n• Business Registration Documents\n• Utility Bill\n• Owner's CNIC\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "7": (
            "🏛️ *Other Registrations — KCCI / PEC / DTS / PSEB*\n\n"
            "*KCCI:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo, Latest Tax Return\n\n"
            "*PEC:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo, PEC Registered Engineer\n\n"
            "*DTS:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo, 800CC+ vehicle, Bank Guarantee\n\n"
            f"*PSEB:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo\n\nContact us: {CONTACT}"
        ),
        "8": BUTTON_RESPONSES["biz_consult"],
    },
    "biz_tax": {
        "1": f"💰 *NTN Registration — Individual*\n\nRequired Documents:\n• Copy of CNIC\n• Email Address\n• Contact Number\n\nCost: Rs. 500\nTimeline: 30 minutes\n\nContact us: {CONTACT}",
        "2": f"💰 *NTN Registration — Business*\n\nRequired Documents:\n• Business Registration Documents\n• Account Maintenance Certificate\n• Utility Bill\n• Owner's CNIC\n• Contact Information\n\nCost: May vary case to case\n\nContact us: {CONTACT}",
        "3": f"🧾 *Income Tax Return*\n\n• Salaried Individual: Salary Slip, Details of Assets\n• Freelancer: Bank Statement, Source of Income, Details of Assets\n• Business Owner: Bank Statement, Source of Income, Details of Assets\n• Business Tax Return: Bank Statement, Business Internal Accounts, Details of Expenses, Tax Deduction Certificates, Details of Assets\n\nContact us: {CONTACT}",
        "4": f"🧾 *Sales Tax Registration*\n\nRequired Documents:\n• Business Registration Documents\n• Account Maintenance Certificate\n• Utility Bill\n• Owner's CNIC\n• Rent Agreement/Ownership Document\n• Contact Details\n\nCost: May vary case to case\n\nContact us: {CONTACT}",
        "5": f"🧾 *Sales Tax Monthly Return*\n\nRequirement: Details of invoices generated in the last month\n\nContact us: {CONTACT}",
        "6": f"🧾 *Provincial Sales Tax (SRB, PRA, BRA, KPRA)*\n\nRequired Documents:\n• Business Registration Documents\n• Account Maintenance Certificate\n• Utility Bill\n• Owner's CNIC/Photo\n\nCost: May vary case to case\n\nContact us: {CONTACT}",
        "7": f"📋 *ATL (Active Taxpayer List)*\n\n• Check ATL Status: Consult our specialist\n• Become Active Taxpayer: Consult our specialist\n• ATL Restoration: Consult our specialist\n\nContact us: {CONTACT}",
        "8": f"📩 *Tax Notices*\n\nFBR Notice, Audit Notice, ATL Notice, Section 114, Section 122, Section 111, Reply to Notice — all require consultation with our tax experts.\n\nContact us: {CONTACT}",
        "9": f"💵 *Tax Refund*\n\nRequires consultation with our tax experts.\n\nContact us: {CONTACT}",
        "10": BUTTON_RESPONSES["biz_consult"],
    },
    "biz_accounts": {
        "1": f"📊 *Bookkeeping*\n\nServices: Sales Recording, Purchase Recording, Cash Book, Bank Reconciliation, Accounts Receivable, Accounts Payable, General Ledger, Expense Management, Inventory Recording, Financial Reports\n\nContact us: {CONTACT}",
        "2": f"📊 *Annual Accounts Management*\n\nIncludes: Profit & Loss Account, Balance Sheet, Cash Flow Statement, Trial Balance, General Ledger Review, Financial Statements\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}",
        "3": f"📊 *Audited Accounts*\n\nWho needs an audit: Private Limited Company, NGO, Trust, Large Business, Statutory Requirement, Voluntary Audit\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}",
        "4": f"📊 *Internal & External Audit*\n\nInternal Audit: Risk Assessment, Internal Controls, Compliance Review, Operational Review, Audit Report\n\nExternal Audit: Independent Audit, Financial Verification, Statutory Compliance, Audit Opinion, Final Report\n\nContact us: {CONTACT}",
        "5": f"📊 *Financial Reporting*\n\nTypes: Monthly Reports, Quarterly Reports, Annual Reports, Management Reports, Custom Reports\n\nContact us: {CONTACT}",
        "6": f"📊 *Accounting Consultation*\n\nServices: Business Accounting, Startup Accounting, Accounting System Setup, Accounting Software (QuickBooks, Xero, Excel, Customized Solution), Financial Health Check\n\nContact us: {CONTACT}",
        "7": BUTTON_RESPONSES["biz_consult"],
    },
    "biz_legal": {
        "1": f"⚖️ *Contract Drafting*\n\nTypes: Business Contracts, Partnership Contracts, Employment Contracts, Service Agreements, NDA, MoU\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}",
        "2": f"⚖️ *Corporate Compliance*\n\nServices: SECP Compliance, Company Annual Returns, Board Resolutions, Share Transfer, Director Changes, Company Record Updates, Compliance Calendar\n\nContact us: {CONTACT}",
        "3": f"⚖️ *Legal Notices*\n\nTypes: Recovery Notice, Breach of Contract Notice, Legal Demand Notice, Employee Notice, Tenant Notice, Commercial Notice\n\nContact us: {CONTACT}",
        "4": f"⚖️ *Legal Opinions*\n\nTypes: Business Legal Opinion, Contract Review, Compliance Opinion, Investment Opinion, Property Related Opinion\n\nContact us: {CONTACT}",
        "5": f"⚖️ *Regulatory Compliance*\n\nAreas: SECP, FBR, IPO Pakistan, Labour Laws, Corporate Governance, Compliance Advisory\n\nContact us: {CONTACT}",
        "6": f"⚖️ *Company Secretarial Services*\n\nServices: Statutory Registers, Board Meeting Minutes, Share Certificates, Annual Returns, Corporate Resolutions, Company Record Maintenance\n\nContact us: {CONTACT}",
        "7": f"⚖️ *Legal Consultation*\n\nTypes: Startup Legal Advice, SME Legal Advice, Corporate Advisory, Compliance Consultation, Contract Review, Business Risk Assessment\n\nContact us: {CONTACT}",
        "8": BUTTON_RESPONSES["biz_consult"],
    },
}

ALL_SUB_MENUS = {**TEXT_SUB_MENU, **BIZ_SUB_MENU}
ALL_SUB_RESPONSES = {**TEXT_SUB_RESPONSES, **BIZ_SUB_RESPONSES}
SERVICE_MENU_IDS = set(ALL_SUB_MENUS.keys())
BIZ_DIRECT_IDS = {"biz_ngo", "biz_digital", "biz_urgent", "biz_consult", "contact_us"}

# ── Messages that mean "we've asked the user to share their contact info" ──
# _send_text_reply checks against this set after every send; a match kicks
# off the Name -> Mobile -> Best Time collection flow below, regardless of
# which menu path (main menu, sub-menu number, or an interactive tap) led
# there — they all funnel through _send_text_reply eventually.
# "Book Consultation" labeled paths — the customer already explicitly
# chose to book, so go straight into the Name -> Mobile -> Best Time
# collection flow, same as before.
CONSULT_TRIGGER_TEXTS = {
    BUTTON_RESPONSES["court_consult"],
    BUTTON_RESPONSES["divorce_consult"],
    BUTTON_RESPONSES["property_consult"],
    BUTTON_RESPONSES["docs_consult"],
}

# "Talk to Expert" / "Talk to Lawyer" labeled paths — more ambiguous
# intent (could just want the phone number), so give the number
# immediately and ask whether they'd like a callback before collecting
# any contact info. Detected via _is_consult_choice_prompt()'s marker
# phrase (see _consult_choice_message above), not exact text matching.


def _is_consult_choice_prompt(text: str) -> bool:
    return _CALLBACK_CHOICE_MARKER in text


def _interpret_yes_no(text: str):
    """Tolerant yes/no interpretation for the callback-choice step —
    accepts a numbered reply (1/2, reusing the same tolerant menu-number
    matcher used elsewhere) as well as natural language. Returns 'yes',
    'no', or None if it can't tell."""
    selection = _extract_menu_selection(text)
    if selection == "1":
        return "yes"
    if selection == "2":
        return "no"

    lower = text.strip().lower()
    yes_words = {"yes", "yeah", "yup", "sure", "ok", "okay", "haan", "ji", "yh", "y"}
    no_words = {"no", "nah", "nope", "nahi", "n"}
    if lower in yes_words or "call me" in lower or "call back" in lower or "callback" in lower:
        return "yes"
    if lower in no_words or "myself" in lower or "i'll call" in lower or "i will call" in lower:
        return "no"
    return None

TEXT_MAIN_MENU_1 = """Welcome to *BizAdvise & LawAdvise Consulting* ⚖️🏢

How can we assist you? Please reply with a number:

*BizAdvise Services:*
1️⃣ Start a New Business / Business Consultancy
2️⃣ Start a Charity / NGO Registration
3️⃣ File My Taxes — Taxation Services
4️⃣ Manage My Accounts — Accountancy
5️⃣ Corporate Legal Advisory
6️⃣ Grow My Business Online — Digital Marketing
7️⃣ 🚨 Urgent Help"""

TEXT_MAIN_MENU_2 = """*LawAdvise Services:*
8️⃣ Online Marriage / Online Nikah
9️⃣ Court Marriage
🔟 Divorce / Khula
1️⃣1️⃣ Child Custody / Guardianship
1️⃣2️⃣ Maintenance (Nafaqa) / Dowery
1️⃣3️⃣ Property Law
1️⃣4️⃣ Inheritance
1️⃣5️⃣ Legal Documentation
1️⃣6️⃣ Corporate Law
1️⃣7️⃣ 👨‍💼 Talk to an Expert

_Reply with a number to get started._"""

TEXT_SERVICE_MENUS = {
    "1":  ("Start a New Business / Business Consultancy", "biz_business"),
    "2":  ("NGO / Charity Registration", "biz_ngo"),
    "3":  ("Taxation Services", "biz_tax"),
    "4":  ("Accountancy Services", "biz_accounts"),
    "5":  ("Corporate Legal Advisory", "biz_legal"),
    "6":  ("Digital Marketing", "biz_digital"),
    "7":  ("Urgent Help", "biz_urgent"),
    "8":  ("Online Marriage / Online Nikah", "online_nikah"),
    "9":  ("Court Marriage", "court_marriage"),
    "10": ("Divorce / Khula", "divorce_khula"),
    "11": ("Child Custody / Guardianship", "child_custody"),
    "12": ("Maintenance / Dowery", "maintenance"),
    "13": ("Property Law", "property_law"),
    "14": ("Inheritance", "inheritance"),
    "15": ("Legal Documentation", "legal_docs"),
    "16": ("Corporate Law", "corporate_law"),
    "17": ("Talk to an Expert", "contact_us"),
}

MENU_TRIGGERS = {"menu", "options", "start", "help", "main menu", "مینو", "آپشنز", "info", "information", "details", "services"}
GREETING_WORDS = {"hi", "hello", "hey", "helo", "hii", "salam", "assalam", "السلام", "assalamualaikum", "aoa"}


def _get_socketio():
    return current_app.extensions["socketio"]


def _check_and_mark_processed(msg_id):
    """Atomically check whether msg_id was already handled, and if not,
    reserve it immediately — before returning — so a second, near-
    simultaneous webhook delivery for the same id (WhatsApp retries do
    happen) can't slip past this check before the first one records it.

    Returns True if this message was already processed (skip it),
    False if this call just claimed it (go ahead and process it).
    """
    if not msg_id:
        return False

    with _processed_lock:
        if msg_id in _processed_ids:
            return True
        # Reserve it now, inside the lock, so any concurrent duplicate
        # request sees it in _processed_ids immediately.
        _processed_ids.add(msg_id)
        _processed_ids_order.append(msg_id)
        # Evict the OLDEST entries once we're over the cap, instead of
        # wiping the whole cache — keeps recent history intact so
        # WhatsApp's delayed retries still get caught.
        while len(_processed_ids_order) > MAX_PROCESSED_IDS:
            oldest = _processed_ids_order.popleft()
            _processed_ids.discard(oldest)

    # Not seen in-memory — could still be a duplicate from before a
    # server restart (which clears the in-memory cache), so fall back
    # to checking the DB once.
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM messages WHERE whatsapp_message_id=?", (msg_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def _verify_signature(payload: bytes, signature: str) -> bool:
    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        return True
    try:
        expected = "sha256=" + hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


def _download_whatsapp_media(media_id, media_type):
    """Download media from WhatsApp and save locally. Returns (filepath, filename) or (None, None)."""
    try:
        WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

        # Step 1: get media URL
        url_res = http_requests.get(
            f"https://graph.facebook.com/v18.0/{media_id}",
            headers=headers, timeout=10
        )
        if url_res.status_code != 200:
            log.error(f"Failed to get media URL: {url_res.text}")
            return None, None

        media_url = url_res.json().get("url")
        if not media_url:
            return None, None

        # Step 2: download the file
        dl_res = http_requests.get(media_url, headers=headers, timeout=30)
        if dl_res.status_code != 200:
            log.error(f"Failed to download media: {dl_res.status_code}")
            return None, None

        # Step 3: determine extension from content-type
        content_type = dl_res.headers.get("Content-Type", "").split(";")[0].strip()
        ext = mt.guess_extension(content_type) or ""
        # Fix common wrong guesses
        ext_fixes = {".jpe": ".jpg", ".jpeg": ".jpg", ".jfif": ".jpg"}
        ext = ext_fixes.get(ext, ext)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{media_type}_{timestamp}{ext}"
        os.makedirs(MEDIA_FOLDER, exist_ok=True)
        filepath = os.path.join(MEDIA_FOLDER, filename)

        with open(filepath, "wb") as f:
            f.write(dl_res.content)

        log.info(f"Media saved: {filepath}")
        return filepath, filename

    except Exception as e:
        log.error(f"_download_whatsapp_media error: {e}")
        return None, None


@webhook_bp.route("/webhook", methods=["GET"])
def verify():
    verify_token = os.getenv("VERIFY_TOKEN")
    incoming = request.args.get("hub.verify_token")
    log.info(f"Webhook verify: incoming='{incoming}' expected='{verify_token}'")
    if incoming and incoming == verify_token:
        return request.args.get("hub.challenge")
    return "Forbidden", 403


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, signature):
        log.warning("Invalid webhook signature — request rejected")
        return "Forbidden", 403

    data = request.get_json(silent=True)
    log.info(f"POST received, entries={len(data.get('entry', [])) if data else 0}")
    if not data:
        log.warning("Empty/invalid JSON body — nothing to process")
        return "OK", 200

    socketio = _get_socketio()

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                contacts = {}
                for contact in value.get("contacts", []):
                    phone = contact.get("wa_id", "")
                    name = contact.get("profile", {}).get("name", "")
                    if phone and name:
                        contacts[phone] = name

                for status_update in value.get("statuses", []):
                    msg_id = status_update.get("id")
                    status = status_update.get("status")
                    if msg_id and status:
                        update_message_status(msg_id, status, socketio)

                incoming_messages = value.get("messages", [])
                log.info(f"{len(incoming_messages)} message(s) in this payload")

                for msg in incoming_messages:
                    msg_id = msg.get("id")
                    log.info(f"Handling message id={msg_id} type={msg.get('type')} from={msg.get('from')}")

                    if _check_and_mark_processed(msg_id):
                        log.info(f"Duplicate skipped: {msg_id}")
                        continue

                    phone = msg["from"]
                    name = contacts.get(phone, "")
                    _handle_message(msg, socketio, name=name)
                    log.info(f"Finished handling {msg_id}")

    except Exception as e:
        log.error(f"ERROR while processing: {e}")
        import traceback
        traceback.print_exc()

    return "OK", 200


_MENU_SELECTION_RE = re.compile(
    r'^(?:option|opt|no\.?|number|#)?\s*[:\-]?\s*\(?\s*(\d{1,2})\s*\)?\s*[.\)]?$',
    re.IGNORECASE,
)


def _extract_menu_selection(text):
    """Recognizes a menu-number reply even with the punctuation/wording
    real customers actually type — '1', '1.', '(2)', '#3', 'Option 4',
    'no. 5' — while still refusing to match ordinary sentences that
    merely happen to contain a digit ('call after 5pm', 'I have 2
    kids'), since the whole (stripped) message must match end-to-end.
    Returns the number as a string (e.g. '1'), or None if this doesn't
    look like a menu selection at all.
    """
    text = (text or "").strip()
    if not text:
        return None
    match = _MENU_SELECTION_RE.match(text)
    return match.group(1) if match else None


def _handle_message(msg, socketio, name=""):
    phone = msg["from"]
    msg_type = msg.get("type", "text")
    msg_id = msg.get("id")

    is_new = save_user(phone, socketio, name=name)

    # A brand-new contact's first message might not be plain text at all
    # — a photo of their CNIC, a voice note, a shared location. Without
    # this, only the "text" branch below ever greets a new user, so
    # anyone whose first contact is a photo/document/etc. gets total
    # silence. The text branch handles its own is_new welcome (it also
    # needs to check MENU_TRIGGERS at the same time), so skip it there
    # to avoid sending the welcome menu twice.
    if is_new and msg_type != "text":
        _user_service_context.pop(phone, None)
        _contact_collection.pop(phone, None)
        _executor.submit(_send_welcome_menu, phone, socketio)

    if msg_type == "text":
        text = msg["text"]["body"].strip()
        socketio.emit("user_typing", {"phone": phone, "typing": True})
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)

        text_lower = text.lower()

        # If we're mid-way through collecting Name / Mobile / Best Time,
        # every text reply goes to that flow until it completes — this
        # MUST be checked before MENU_TRIGGERS, otherwise a user typing
        # something like "help" or "info" as their name/mobile/best-time
        # answer would silently abort the booking flow and reset to the
        # main menu instead of completing the consultation booking.
        if phone in _contact_collection:
            _handle_contact_collection(phone, text, socketio)
            return

        if is_new or text_lower in MENU_TRIGGERS:
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio)
            return

        if text_lower in GREETING_WORDS:
            mode = get_user_mode(phone)
            if mode == 0:
                _executor.submit(_process_ai_reply, phone, text, socketio)
            return

        if phone in _user_service_context:
            service = _user_service_context[phone]
            selection = _extract_menu_selection(text)
            response = ALL_SUB_RESPONSES.get(service, {}).get(selection) if selection else None
            if response:
                _executor.submit(_send_text_reply, phone, response, socketio)
                del _user_service_context[phone]
                return
            # Didn't match this submenu — the user went off-script (asked
            # something free-form) or mistyped a number. Clear the stale
            # context so a LATER message (e.g. a genuine new main-menu
            # number) isn't misinterpreted as still answering this old
            # submenu, then fall through to check the main menu / AI below.
            del _user_service_context[phone]

        selection = _extract_menu_selection(text)
        if selection and selection in TEXT_SERVICE_MENUS:
            title, service_id = TEXT_SERVICE_MENUS[selection]
            if service_id in SERVICE_MENU_IDS:
                _user_service_context[phone] = service_id
                _executor.submit(_send_service_menu_safe, phone, service_id, socketio)
            elif service_id in BIZ_DIRECT_IDS:
                response = BUTTON_RESPONSES.get(service_id, "")
                if response:
                    _executor.submit(_send_text_reply, phone, response, socketio)
            return

        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)
        else:
            log.info(f"Human mode active for {phone} — AI skipped")

    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type", "")

        if interactive_type == "list_reply":
            selected_id = interactive["list_reply"]["id"]
            selected_title = interactive["list_reply"]["title"]
            save_message(phone, selected_title, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)
            if selected_id in BIZ_DIRECT_IDS:
                response = BUTTON_RESPONSES.get(selected_id, "")
                if response:
                    _executor.submit(_send_text_reply, phone, response, socketio)
            elif selected_id in SERVICE_MENU_IDS:
                _user_service_context[phone] = selected_id
                _executor.submit(_send_service_menu_safe, phone, selected_id, socketio)

        elif interactive_type == "button_reply":
            button_id = interactive["button_reply"]["id"]
            button_title = interactive["button_reply"]["title"]
            save_message(phone, button_title, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)
            if button_id in SERVICE_MENU_IDS:
                _user_service_context[phone] = button_id
                _executor.submit(_send_service_menu_safe, phone, button_id, socketio)
                return
            response = BUTTON_RESPONSES.get(button_id)
            if response:
                _executor.submit(_send_text_reply, phone, response, socketio)
            else:
                mode = get_user_mode(phone)
                if mode == 0:
                    _executor.submit(_process_ai_reply, phone, button_title, socketio)

    elif msg_type in ("image", "audio", "document", "video"):
        media_info = msg.get(msg_type, {})
        caption = media_info.get("caption", "") or ""
        media_id = media_info.get("id")

        # Download in background so webhook returns fast
        def save_media():
            local_path, local_filename = None, None
            if media_id:
                local_path, local_filename = _download_whatsapp_media(media_id, msg_type)
            display_text = caption or f"Sent a {msg_type}"
            save_message(
                phone, display_text, "user", socketio,
                message_type=msg_type, whatsapp_message_id=msg_id,
                media_path=local_path,
                file_name=local_filename or media_info.get("filename", ""),
            )

        _executor.submit(save_media)

    elif msg_type == "button":
        text = msg["button"]["text"]
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)
        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)

    elif msg_type == "location":
        loc = msg.get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")
        label = loc.get("name") or loc.get("address") or ""
        display_text = f"📍 Shared location{f' — {label}' if label else ''}"
        if lat is not None and lng is not None:
            display_text += f" ({lat}, {lng})"
        save_message(phone, display_text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id,
                     message_type="location")

    elif msg_type == "contacts":
        contact_cards = msg.get("contacts", [])
        names = [
            c.get("name", {}).get("formatted_name", "Contact")
            for c in contact_cards
        ] or ["a contact"]
        display_text = f"👤 Shared contact: {', '.join(names)}"
        save_message(phone, display_text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id,
                     message_type="contacts")

    else:
        # Catch-all for anything not explicitly handled above (stickers,
        # reactions, polls, unsupported/future WhatsApp message types).
        # Previously these were silently dropped — not even saved — so
        # staff had no idea the customer sent anything at all. At minimum
        # always record that something arrived.
        log.warning(f"Unhandled message type '{msg_type}' from {phone} — saving a placeholder")
        save_message(phone, f"[Unsupported message type: {msg_type}]", "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id,
                     message_type=msg_type)


def _handle_contact_collection(phone, text, socketio):
    """Walks a user through an optional callback-choice step (for the
    more ambiguous 'Talk to Expert' paths), then Name -> Mobile -> Best
    Time to Call, then emits a consultation_booked event so the
    dashboard can surface it."""
    state = _contact_collection.get(phone, {})
    step = state.get("step")

    if step == "awaiting_callback_choice":
        choice = _interpret_yes_no(text)
        if choice == "yes":
            _contact_collection[phone]["step"] = "awaiting_name"
            _executor.submit(_send_text_reply, phone,
                             "Great! Let's get you booked in. Please share your *Name*:", socketio)
        elif choice == "no":
            del _contact_collection[phone]
            _executor.submit(_send_text_reply, phone,
                             f"No problem! Feel free to reach us anytime at 📞 {CONTACT}.", socketio)
        else:
            # Didn't understand the reply — re-ask rather than silently
            # dropping into the collection flow (or out of it) on a guess.
            _executor.submit(_send_text_reply, phone,
                             "Sorry, I didn't quite catch that 🙏 Please reply *1* for a callback, or *2* if you'll reach out yourself.",
                             socketio)
        return

    if step == "awaiting_name":
        _contact_collection[phone]["name"] = text
        _contact_collection[phone]["step"] = "awaiting_mobile"
        _executor.submit(_send_text_reply, phone,
                         "Thank you! Please share your *Mobile Number*:", socketio)

    elif step == "awaiting_mobile":
        _contact_collection[phone]["mobile"] = text
        _contact_collection[phone]["step"] = "awaiting_time"
        _executor.submit(_send_text_reply, phone,
                         "Great! What is the *Best Time to Call* you?\n_(e.g. Morning, Afternoon, Evening or a specific time)_", socketio)

    elif step == "awaiting_time":
        name = state.get("name", "")
        mobile = state.get("mobile", "")
        best_time = text
        del _contact_collection[phone]
        confirmation = (
            f"✅ *Thank you, {name}!*\n\n"
            f"Our team will contact you at *{mobile}* during *{best_time}*.\n\n"
            f"If urgent, you can also reach us at:\n📞 {CONTACT}"
        )
        _executor.submit(_send_text_reply, phone, confirmation, socketio)
        _user_context[phone] = "main"
        # Emit consultation booked event for dashboard notification
        socketio.emit("consultation_booked", {
            "phone": phone,
            "name": name,
            "mobile": mobile,
            "best_time": best_time,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        log.info(f"Consultation booked: {name} ({mobile}) — best time: {best_time}")


def _send_welcome_menu(phone, socketio):
    try:
        success, wa_id = send_main_menu(phone)
        if success:
            save_message(phone, TEXT_MAIN_MENU_1 + "\n" + TEXT_MAIN_MENU_2,
                         "bot", socketio, status="sent",
                         whatsapp_message_id=wa_id, source="ai")
        else:
            success1, wa_id1 = send_text(phone, TEXT_MAIN_MENU_1)
            save_message(phone, TEXT_MAIN_MENU_1, "bot", socketio,
                         status="sent" if success1 else "failed",
                         whatsapp_message_id=wa_id1, source="ai")
            time.sleep(0.5)
            success2, wa_id2 = send_text(phone, TEXT_MAIN_MENU_2)
            save_message(phone, TEXT_MAIN_MENU_2, "bot", socketio,
                         status="sent" if success2 else "failed",
                         whatsapp_message_id=wa_id2, source="ai")
    except Exception as e:
        log.error(f"Welcome menu error for {phone}: {e}")


def _send_service_menu_safe(phone, service_id, socketio):
    try:
        success, wa_id = send_service_menu(phone, service_id)
        if success:
            save_message(phone, ALL_SUB_MENUS.get(service_id, ""), "bot", socketio,
                         status="sent", whatsapp_message_id=wa_id, source="ai")
        else:
            sub_menu = ALL_SUB_MENUS.get(service_id, "")
            if sub_menu:
                _send_text_reply(phone, sub_menu, socketio)
    except Exception as e:
        log.error(f"Service menu error for {phone}: {e}")


def _send_text_reply(phone, text, socketio):
    try:
        success, wa_id = send_text(phone, text)
        save_message(phone, text, "bot", socketio,
                     status="sent" if success else "failed",
                     whatsapp_message_id=wa_id, source="ai")
        if not success:
            return
        # "Book Consultation" paths — explicit booking intent, go
        # straight into the Name -> Mobile -> Best Time collection flow.
        if text in CONSULT_TRIGGER_TEXTS:
            _contact_collection[phone] = {"step": "awaiting_name"}
        # "Talk to Expert" / "Talk to Lawyer" paths — more ambiguous
        # intent, so ask first whether they even want a callback before
        # collecting any contact info. Matched by marker phrase rather
        # than exact text, so it doesn't silently break if the wording
        # of any individual prompt changes later.
        elif _is_consult_choice_prompt(text):
            _contact_collection[phone] = {"step": "awaiting_callback_choice"}
    except Exception as e:
        log.error(f"Text reply error for {phone}: {e}")


def _process_ai_reply(phone, text, socketio):
    try:
        reply = ask_ai(text)
        success, wa_msg_id = send_text(phone, reply)
        status = "sent" if success else "failed"
        save_message(phone, reply, "bot", socketio,
                     status=status, whatsapp_message_id=wa_msg_id, source="ai")
    except Exception as e:
        log.error(f"AI reply error for {phone}: {e}")