import io

import pytest

from conftest import TEST_CARDS
from data_sentinel.classifier import classify, classify_name, classify_text, extract_text, luhn_ok


@pytest.mark.parametrize("card", TEST_CARDS)
def test_luhn_accepts_test_cards(card):
    assert luhn_ok(card)


@pytest.mark.parametrize("num", ["4111111111111112", "1234567812345678", "123456789012", "41111111111111111111"])
def test_luhn_rejects_bad_or_wrong_length(num):
    assert not luhn_ok(num)


@pytest.mark.parametrize("text,level", [
    ("Join us for the annual picnic on Friday!", 0),
    ("Internal use only. Sprint planning notes.", 1),
    ("This memo is Confidential.", 2),
    ("Q3 payroll summary attached", 2),
    ("customer list for the region", 2),
    ("".join(f"user{i}@example.com\n" for i in range(10)), 2),
    ("card 4111 1111 1111 1111", 3),
    ("PAN ABCDE1234F", 3),
    ("SSN 123-45-6789", 3),
    ("-----BEGIN RSA PRIVATE KEY-----", 3),
    ("aws AKIAABCDEFGHIJKLMNOP", 3),
    ("password = hunter22", 3),
    ('{"api_key": "sk_test_abcdef"}', 3),
    ("This is TOP SECRET", 3),
    ("strictly confidential board pack", 3),
    ("Aadhaar 2345 6789 0123", 3),
])
def test_classifier_levels(text, level):
    assert classify_text(text).level == level


def test_short_secret_and_few_emails_do_not_fire():
    assert classify_text("password = abc").level == 0
    assert classify_text("".join(f"user{i}@example.com\n" for i in range(9))).level == 0


def test_card_not_also_counted_as_aadhaar():
    r = classify_text("Test User,4111 1111 1111 1111,90000")
    assert r.matches.get("credit card number") == 1
    assert "Aadhaar-style ID" not in r.matches
    # an invalid 16-digit number is neither a card nor an Aadhaar number
    r2 = classify_text("order 4111 1111 1111 1112")
    assert r2.matches == {}


def test_random_digits_without_luhn_are_ignored():
    assert classify_text("order id 1234 5678 1234 5678").level == 0


@pytest.mark.parametrize("name,level", [
    ("id_rsa", 3), ("server.pem", 3), ("cert.p12", 3), (".env", 3), ("prod.env", 3),
    ("payroll_march.xlsx", 2), ("passport_scan.jpg", 2), ("customer_data.zip", 2),
    ("restricted_plan.txt", 2), ("backup.sql", 2), ("db.dump", 2), ("holiday.jpg", 0),
])
def test_filename_rules(name, level):
    assert classify_name(name).level == level


def test_reasons_never_contain_values():
    r = classify("deploy_notes.txt", "api_key = sk_live_51HxTestKeyOnly\ncard 4111 1111 1111 1111")
    blob = " ".join(r.reasons)
    assert "sk_live" not in blob and "4111" not in blob
    assert "content: hard-coded secret x1 -> Restricted" in r.reasons


def test_unreadable_type_is_judged_by_name_only():
    text, note = extract_text("photo.jpg", b"\xff\xd8\xff")
    assert text is None and "name only" in note
    r = classify("photo.jpg", None, note)
    assert not r.inspected and r.level == 0


def test_docx_content_is_read():
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Salary review - Confidential")
    buf = io.BytesIO()
    doc.save(buf)
    text, _ = extract_text("review.docx", buf.getvalue())
    assert classify("review.docx", text).level == 2
