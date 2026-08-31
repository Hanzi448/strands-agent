"""Sample FAQ documents for each clinic's Knowledge Base.

`project-overview.md` -> Core Features: "Answer clinic-specific FAQs via
RAG (pricing, prep instructions, policies -- content differs per
clinic)." One short plain-text document per topic per clinic, uploaded by
`run_seed.py` under that clinic's own `kb/{clinic_id}/` prefix
(`architecture.md` -> Storage Model, S3) and nothing else's -- the
Knowledge Base's isolation is structural, so a document seeded here can
only ever be retrieved by its own clinic's `query_faq` calls.

Plain text rather than Markdown or PDF: `tools.faq.query_faq` reads back
whatever passages Bedrock's ingestion extracted, spoken by a model, so
formatting a patient will never see is not worth a richer source format.

Content is invented for this demo (there is no real Bright Smile Dental
or Lumiere Aesthetics) but is written the way each clinic's own site would
write it -- specific prices and timings, not placeholder text -- so a
retrieval against it reads like an answer to a patient's actual question
rather than like a fixture.
"""

from __future__ import annotations

from typing import Final

from .clinic_data import COSMETIC_CLINIC_ID, DENTAL_CLINIC_ID

DENTAL_DOCUMENTS: Final[dict[str, str]] = {
    "pricing.txt": (
        "Bright Smile Dental -- Pricing\n\n"
        "A standard check-up is 45 pounds and includes an examination and "
        "advice on any treatment you might need. A dental cleaning "
        "(scale and polish) is 75 pounds, or 110 pounds combined with a "
        "check-up on the same visit. Prices are for private patients; we "
        "do not accept NHS registrations at this location. Payment is "
        "taken on the day by card or contactless -- we do not take cash."
    ),
    "preparation.txt": (
        "Bright Smile Dental -- Before Your Appointment\n\n"
        "For a check-up, no preparation is needed -- just brush "
        "beforehand as you normally would. For a cleaning appointment, "
        "avoid eating or drinking (other than water) for 30 minutes "
        "before you arrive, so we can get a clear look at your teeth. If "
        "you take blood-thinning medication, let us know when you book: "
        "it does not usually change the appointment, but the dentist "
        "likes to know in advance."
    ),
    "policies.txt": (
        "Bright Smile Dental -- Policies\n\n"
        "We ask for at least 24 hours' notice to cancel or move an "
        "appointment; a cancellation with less notice than that may be "
        "charged at half the appointment's price. If you arrive more "
        "than 10 minutes late we may need to shorten the appointment or "
        "reschedule it, since later patients would otherwise be delayed. "
        "Children under 16 must be accompanied by a parent or guardian "
        "for the whole visit."
    ),
}

COSMETIC_DOCUMENTS: Final[dict[str, str]] = {
    "pricing.txt": (
        "Lumiere Aesthetics -- Pricing\n\n"
        "A first consultation is 50 pounds, redeemable against any "
        "treatment booked on the day. Treatment pricing depends on the "
        "procedure and is confirmed at your consultation, since it "
        "depends on what you and the practitioner agree on; as a guide, "
        "most single-area treatments range from 150 to 450 pounds. We "
        "offer a payment plan over three months for treatments over 300 "
        "pounds, arranged at the clinic."
    ),
    "preparation.txt": (
        "Lumiere Aesthetics -- Before Your Appointment\n\n"
        "For a consultation, arrive with a clean face and no make-up "
        "over the area you want to discuss, so the practitioner can "
        "assess your skin properly. For a treatment appointment, avoid "
        "alcohol for 24 hours beforehand and avoid blood-thinning "
        "medication or supplements (such as aspirin or fish oil) for 3 "
        "days beforehand unless your doctor has told you not to stop "
        "them. Please arrive without make-up on the treatment area."
    ),
    "policies.txt": (
        "Lumiere Aesthetics -- Policies\n\n"
        "We ask for at least 48 hours' notice to cancel or move a "
        "treatment appointment; the 50-pound consultation fee is "
        "non-refundable if you cancel with less notice than that. "
        "Treatments are only carried out on clients aged 18 and over. A "
        "short patch test is required at least 48 hours before certain "
        "treatments -- we will tell you at your consultation if yours "
        "needs one."
    ),
}

# What `run_seed.py` iterates over: one clinic id paired with its own
# `{filename: text}` documents. Filenames only need to be unique within a
# clinic's own prefix -- they are never read back, only the passage text.
FAQ_DOCUMENTS_BY_CLINIC: Final[dict[str, dict[str, str]]] = {
    DENTAL_CLINIC_ID: DENTAL_DOCUMENTS,
    COSMETIC_CLINIC_ID: COSMETIC_DOCUMENTS,
}
