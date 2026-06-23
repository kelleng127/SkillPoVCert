"""
get_slot_data.py
----------------
Scans the Alexa skill interaction model (en-US.json) for slot definitions
that indicate personal data collection. This catches skills that collect data
via slot filling rather than explicit conversational prompts — the most common
pattern in production Alexa skills.

Findings are APPENDED to content_safety/outputs_data_collection.csv in the
same (filename, evidence, 'collect data <type>') format used by
get_content_safety.py, so the rest of the pipeline sees them identically.

Called from scan_skills.py after get_content_safety().
"""

import csv
import json
import os
from path import results_path

# Amazon built-in slot types that directly indicate PII collection.
# Only types that unambiguously map to a personal data category are included.
AMAZON_SLOT_MAPPING = {
    'AMAZON.PhoneNumber':   'phone number',
    'AMAZON.EmailAddress':  'email',
    'AMAZON.PostalAddress': 'address',
    'AMAZON.US_FIRST_NAME': 'name',
    'AMAZON.Person':        'name',
    'AMAZON.Actor':         'name',
    'AMAZON.City':          'location',
    'AMAZON.Country':       'location',
    'AMAZON.US_STATE':      'location',
    'AMAZON.US_CITY':       'location',
}

# Keywords matched as substrings of a normalized (lowercased, no separators)
# slot variable name or custom slot type name.
# Format: (data_type_label, [keyword_substrings])
SLOT_NAME_KEYWORDS = [
    ('name',         ['username', 'firstname', 'lastname', 'fullname',
                      'personname', 'customername', 'speakername']),
    ('email',        ['email']),
    ('phone number', ['phonenumber', 'telephone', 'mobilenum', 'cellphone']),
    ('address',      ['address', 'streetaddr', 'homeaddr']),
    ('location',     ['zipcode', 'postalcode', 'postal']),
    ('birthday',     ['birthday', 'birthdate', 'dateofbirth', 'dob', 'birthyear']),
    ('age',          ['userage', 'customerage', 'personage']),
    ('health',       ['health', 'medical', 'symptom', 'diagnosis',
                      'medication', 'prescription', 'bodyweight', 'bloodpressure']),
    ('financial',    ['creditcard', 'debitcard', 'bankaccount',
                      'paymentmethod', 'billinginfo', 'cardnumber']),
    ('gender',       ['gender']),
]


def _normalize(name):
    """Lowercase and strip separators for keyword matching."""
    return name.lower().replace('_', '').replace('-', '').replace(' ', '')


def _keyword_match(name, keywords):
    normalized = _normalize(name)
    return any(kw in normalized for kw in keywords)


def _load_language_model(intent_file):
    """Return the languageModel dict from en-US.json, or None on failure."""
    try:
        raw = json.loads(open(intent_file, encoding='utf-8', errors='ignore').read())
    except Exception:
        return None
    if 'interactionModel' in raw:
        return raw['interactionModel'].get('languageModel', {})
    if 'languageModel' in raw:
        return raw['languageModel']
    return None


def _scan_model(intent_file):
    """
    Extract PII-indicating findings from the interaction model.
    Returns list of (source_file, evidence_string, 'collect data <type>') tuples.
    """
    model = _load_language_model(intent_file)
    if not model:
        return []

    findings = []
    seen = set()  # one finding per data type to avoid redundant report entries

    for intent in model.get('intents', []):
        for slot in intent.get('slots', []):
            slot_name = slot.get('name', '')
            slot_type = slot.get('type', '')

            # 1 — Amazon built-in type mapping
            if slot_type in AMAZON_SLOT_MAPPING:
                data_type = AMAZON_SLOT_MAPPING[slot_type]
                key = ('builtin', data_type)
                if key not in seen:
                    seen.add(key)
                    evidence = f'Amazon slot type {slot_type} (slot variable: {slot_name})'
                    findings.append((intent_file, evidence, 'collect data ' + data_type))

            # 2 — Keyword match on the slot VARIABLE name
            for data_type, keywords in SLOT_NAME_KEYWORDS:
                if _keyword_match(slot_name, keywords):
                    key = ('slot_var', data_type)
                    if key not in seen:
                        seen.add(key)
                        evidence = f'slot variable name "{slot_name}" indicates {data_type}'
                        findings.append((intent_file, evidence, 'collect data ' + data_type))
                    break

            # 3 — Keyword match on a CUSTOM slot type name (skip AMAZON.* types)
            if slot_type and not slot_type.startswith('AMAZON.'):
                for data_type, keywords in SLOT_NAME_KEYWORDS:
                    if _keyword_match(slot_type, keywords):
                        key = ('slot_type', data_type)
                        if key not in seen:
                            seen.add(key)
                            evidence = f'custom slot type name "{slot_type}" indicates {data_type}'
                            findings.append((intent_file, evidence, 'collect data ' + data_type))
                        break

    return findings


def get_slot_data(skill_name):
    """
    Entry point called from scan_skills.py.
    Reads skill.json, scans the interaction model, and appends any slot-based
    data collection findings to content_safety/outputs_data_collection.csv.
    """
    skill_json_path = os.path.join(results_path, skill_name, 'skill.json')
    try:
        skill = json.loads(open(skill_json_path).read())
    except Exception:
        return

    intent_file = skill.get('intent_file', '')
    if not intent_file or not os.path.isfile(intent_file):
        return

    findings = _scan_model(intent_file)
    if not findings:
        return

    out_path = os.path.join(results_path, skill_name, 'content_safety', 'outputs_data_collection.csv')
    with open(out_path, 'a', newline='') as f:
        writer = csv.writer(f)
        for row in findings:
            writer.writerow(row)
