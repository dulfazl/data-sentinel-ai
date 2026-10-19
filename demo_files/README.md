# Demo files (synthetic only)

Every file here is made up. The card number `4111 1111 1111 1111` is the public Visa *test* number and
`sk_live_51HxTestKeyOnly` is a fake key. No real personal data, cards or keys.

| File | Sensitivity | What to do with it | Expected result |
|---|---|---|---|
| `public_notice.txt` | Public | copy to `demo_usb/`, upload to Drive | ALLOW |
| `internal_memo.txt` | Internal | copy to `demo_usb/`, upload to Drive | WARN (amber banner) |
| `customer_payroll_confidential.csv` | Restricted (test card + RESTRICTED + salary) | copy to `demo_usb/`, upload to Drive, attach in Gmail, `try-mail --attach` | BLOCK (quarantine / red banner / SMTP 550) |
| `deploy_notes.txt` | Restricted (fake API key) | upload or paste into ChatGPT | BLOCK |
| `customer_list.csv` | Confidential (25 e-mail addresses) | upload to Drive | BLOCK |
| `paste_api_key.txt` | Restricted | copy its text and paste into ChatGPT, or `try-paste --file` | BLOCK |
| `harmless_paste.txt` | Public | copy its text and paste into ChatGPT | ALLOW (text appears) |
