from __future__ import annotations
import asyncio
import hashlib
import json
import re
import time
import uuid
from sqlalchemy import select
from zoikorum.domains.ai.models import InferenceLog, PromptVersion
from zoikorum.domains.ai import providers
from zoikorum.config import get_settings
from zoikorum.shared.events import record_event
from zoikorum.shared.event_catalog import E
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
from zoikorum.shared.crypto import canonical_json

DISCLAIMER = "Advisory assistance only. Verify against the source documents. This output does not approve terms, execute a contract, release funds or decide a dispute."
PURPOSES = {"proposal-draft", "contract-summary", "dispute-summary", "match-intent", "assistant-chat"}
CHAT_FALLBACK = (
    "I can help with how Zoikorum works: finding and comparing professionals, requests and proposals, "
    "contracts and milestones, protected payments, verification, reviews, disputes and account settings. "
    "Ask about any of these, or open the Help Center for published guidance."
)
CHAT_UNHELPFUL = (
    "I could not answer that reliably. Try rephrasing the question, or open the Help Center for published guidance."
)
CHAT_INTENTS = {
    "enterprise_discovery", "professional_onboarding", "trust_verification", "contracts_milestones",
    "protected_payments", "pricing_public", "disputes_public", "support_handoff", "account_help", "general",
}
CHAT_INSTRUCTIONS = (
    "You are the Zoikorum AI Concierge for a governed professional-services marketplace. "
    "Explain how Zoikorum works: finding professionals, requests and briefs, proposals, contracts, milestones, "
    "protected payments, delivery, reviews, verification, disputes, pricing and account help. "
    "Answer safe general-knowledge questions too, briefly and accurately, even when they are not about Zoikorum. "
    "You advise only: never claim to approve, verify, sign, release funds, decide a dispute or view someone's "
    "private account, and never invent prices, policies, certifications or personal facts. "
    "Reply with one JSON object only, no code fences:\n"
    '{"intent":"one intent key","answer":"the direct answer in one or two sentences",'
    '"sections":[{"title":"short title","items":["short point","short point"]}],'
    '"suggestions":["follow-up question","follow-up question"],'
    '"limitations":"one sentence on what you cannot do"}\n'
    "intent keys: enterprise_discovery, professional_onboarding, trust_verification, contracts_milestones, "
    "protected_payments, pricing_public, disputes_public, support_handoff, account_help, general.\n"
    "Style: plain American English, practical, specific, no markdown, no marketing superlatives. Put the direct "
    "answer first. Use at most one section with two short items, or no section when one sentence is enough. Give "
    "two short follow-up questions in the user's voice in the suggestions field only; never add a questions "
    "section or repeat the suggestions in sections. Keep the whole reply under 70 words."
)
RELATED_PAGES = {
    "enterprise_discovery": [("Browse professionals", "/professionals"), ("Help Center", "/app/help")],
    "professional_onboarding": [("Trust & Safety Charter", "/legal/trust-and-safety"), ("Help Center", "/app/help")],
    "trust_verification": [("Trust & Safety Charter", "/legal/trust-and-safety"), ("Help Center", "/app/help")],
    "contracts_milestones": [("Terms of Service", "/legal/terms"), ("Help Center", "/app/help")],
    "protected_payments": [("Terms of Service", "/legal/terms"), ("Help Center", "/app/help")],
    "pricing_public": [("Help Center", "/app/help"), ("Contact options", "/app/help")],
    "disputes_public": [("Trust & Safety Charter", "/legal/trust-and-safety"), ("Help Center", "/app/help")],
    "support_handoff": [("Help Center", "/app/help"), ("Browse professionals", "/professionals")],
    "account_help": [("Help Center", "/app/help"), ("Security settings", "/app/security")],
    "general": [("Help Center", "/app/help"), ("Browse professionals", "/professionals")],
}
CHAT_SUGGESTIONS = [
    "How do I find the right professional?",
    "How are payments protected?",
    "How does verification work?",
]
GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|hiya|greetings|good (?:morning|afternoon|evening))"
    r"(?:\s+(?:there|zoikorum))?[\s!.,?]*$",
    re.IGNORECASE,
)
PLATFORM_RE = re.compile(
    r"\b(?:zoikorum|zoiko|marketplace|professional services|this (?:site|website|app|platform))\b", re.I)
GREETING_REPLY = {
    "intent": "general",
    "answer": ("Hi! I'm the Zoikorum AI Concierge. Ask me about finding professionals, proposals, contracts, "
               "protected payments, verification or disputes."),
    "sections": [{"title": "What I can help with", "items": [
        "Finding and comparing professionals", "Requests, proposals and contracts",
        "Protected payments, milestones and delivery", "Verification, reviews and disputes"]}],
    "suggestions": CHAT_SUGGESTIONS,
    "limitations": "I can explain published information only and cannot approve, verify, execute or decide anything.",
}
# Curated answers to the questions people ask most, served without the local model so they are instant.
# Wording follows the Help Center; the model still handles everything else.
FAQ_REPLIES = [
    {
        "pattern": re.compile(
            r"\b(?:can i use zoikorum|is zoikorum available|zoikorum (?:available|operate|operates)|"
            r"use zoikorum (?:in|from)|available (?:in|to) (?:my|your) country|"
            r"outside (?:the )?(?:us|uk|europe|united states)|which countries|what countries|"
            r"supported countries|country availability|europe|asia|africa|australia|"
            r"united states|usa|canada|united kingdom|india)\b", re.I),
        "intent": "enterprise_discovery",
        "answer": ("Zoikorum is an online marketplace, so you can browse from many locations. Professionals list the "
                   "countries they serve and the languages they speak; if a professional does not serve your "
                   "country, the request is flagged before agreement and cannot proceed. Cross-border work may have "
                   "local legal, tax or payment requirements, so check the professional's listing or contact support "
                   "for a country-specific question."),
        "sections": [("Working across countries", [
            "Professionals list the countries they serve and the languages they speak.",
            "Use the location and language filters when searching.",
            "A professional who does not serve your country is flagged before agreement.",
            "Cross-border work may have local legal, tax or payment requirements."])],
        "suggestions": ["How do I find the right professional?", "How are payments protected?",
                        "How do I contact support?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:what(?:'s| is) zoikorum|how does zoikorum work|about zoikorum|what does zoikorum do|"
            r"why zoikorum|how does the platform work|what is this platform|what is the platform|"
            r"what is this site|what is this app|"
            r"explore (?:zoikorum|the platform|this platform)|tour of zoikorum|platform tour|site tour|take a tour|"
            r"what can i do (?:here|on zoikorum)?|what can you do|"
            r"how do i use (?:zoikorum|this site|this platform|the app)|how do i get started|getting started|"
            r"walk me through|show me around|overview of zoikorum|what are the main features|"
            r"what can i do on zoikorum|how does it work)\b", re.I),
        "intent": "general",
        "answer": ("Zoikorum is a governed marketplace for professional services. Buyers describe the work and request "
                   "proposals, agree a contract with milestones, fund milestones into escrow, and accept the work "
                   "before the professional is paid. Verification, reviews and disputes keep a reliable record. Ask "
                   "about finding professionals, verification, requests, contracts, payments, organisations, "
                   "security, reviews, disputes or support; the Help Center has the full answers."),
        "sections": [("For buyers", [
            "Search, compare and request proposals from verified professionals.",
            "Agree a contract and fund milestones into escrow.",
            "Accept delivered work before funds are released."]),
            ("For professionals", [
                "Publish your profile, offerings and availability.",
                "Answer requests, deliver milestones and get paid on acceptance."])],
        "suggestions": ["How do I find the right professional?", "How are payments protected?",
                        "How does verification work?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:join (?:zoikorum )?as a professional|become a professional|professional onboarding|"
            r"create a professional account|publish my profile)\b", re.I),
        "intent": "professional_onboarding",
        "answer": ("Create a professional account, complete identity and credential verification, then publish your "
                   "profile and offerings. A verification provider or compliance reviewer checks the evidence; AI "
                   "never decides a verification outcome."),
        "sections": [("Joining as a professional", [
            "Sign up, then complete identity and credential checks.",
            "Publish your profile, services and availability once verified.",
            "Requests and proposals appear in your dashboard."])],
        "suggestions": ["What does a Trust Tier mean?", "How does verification work?",
                        "How do requests and proposals work?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:find work|get work|find clients|get clients|find jobs?|get jobs?|more clients|more work|"
            r"receive (?:more )?requests|open briefs?|job leads|win work|get hired|"
            r"how do i get (?:work|clients|requests)|how do i find (?:work|clients|jobs))\b", re.I),
        "intent": "professional_onboarding",
        "answer": ("Complete verification and publish a clear professional profile with your services, availability "
                   "and pricing. Buyers find you through search and send requests, and open briefs appear in your "
                   "Professional workspace; reply with a proposal. Reviews from completed work strengthen your "
                   "track record and ranking."),
        "sections": [("Finding work", [
            "Complete verification and publish your profile, services and availability.",
            "Watch requests and open briefs in the Professional workspace.",
            "Send proposals and build reviews from completed work."])],
        "suggestions": ["How do I join as a professional?", "How does search rank professionals?",
                        "How do I ask for a proposal?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:sign up|sign-up|create (?:an? )?(?:buyer |customer |free |zoikorum )?account|"
            r"register (?:an? )?account|how do i join zoikorum|join zoikorum)\b", re.I),
        "intent": "account_help",
        "answer": ("Choose Sign up, confirm your email address, then add your profile. Buyers can browse and request "
                   "proposals straight away; organisations can invite colleagues and assign roles afterwards. "
                   "Professionals complete verification before publishing."),
        "sections": [("Creating an account", [
            "Sign up and confirm your email address.",
            "Add your profile and, for a company, your organisation details.",
            "Professionals complete verification before their profile is published."])],
        "suggestions": ["How do I join as a professional?", "How do I reset my password?",
                        "How do I add a colleague?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:escrow|protected payments?|payments? (?:are )?protected|payment protection|"
            r"how (?:are|do) (?:payments?|funds?) (?:protected|released)|how do (?:payments?|payment) work|"
            r"how do i pay|pay (?:someone|the professional)|make a payment|pay for (?:the )?work|"
            r"when (?:is|does|do) .{0,30}(?:get paid|paid)|release (?:the |a )?(?:payment|funds)|"
            r"fund (?:a |the )?milestone|held in escrow)\b", re.I),
        "intent": "protected_payments",
        "answer": ("Professionals are paid only after the buyer accepts a milestone. Until then the funds stay in "
                   "escrow for that engagement and are released milestone by milestone."),
        "sections": [("How escrow works", [
            "The buyer funds a milestone before work starts.",
            "Funds stay held until the buyer accepts the delivered work.",
            "A dispute freezes the affected milestone funds until it is resolved."])],
        "suggestions": ["Does Zoikorum store my card?", "What happens if a dispute is raised?",
                        "When does work start?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:store my card|save my card|card details|store my payment|payment method|payment methods|"
            r"how can i pay|what can i pay with|credit card|debit card|is zoikorum a bank|hold a balance|"
            r"crypto|cryptocurrency|bitcoin|ethereum|usdt|paypal|venmo|zelle|cash app|apple pay|google pay|"
            r"bank transfer|wire transfer|off-platform|off platform|accepted payment methods?|"
            r"what payments do you accept|do you accept (?:payments?|cards?|paypal|bitcoin|crypto))\b", re.I),
        "intent": "protected_payments",
        "answer": ("Protected payments use the payment partner's hosted card checkout. Zoikorum stores only a token, "
                   "never your full card details, and it is not a bank and holds no balance for you. Off-platform "
                   "methods such as PayPal, crypto, wire or cash are not used for protected payments; only methods "
                   "shown at checkout are supported."),
        "sections": [("Card and payment details", [
            "Card data is handled by the payment partner and tokenised.",
            "Zoikorum keeps the token, not the card number.",
            "Escrow funds belong to the engagement, not a Zoikorum balance.",
            "Only methods shown at checkout are supported; do not pay off-platform."])],
        "suggestions": ["How are payments protected?", "How does milestone funding work?",
                        "Terms of Service"],
    },
    {
        "pattern": re.compile(
            r"\b(?:how do i get paid|receive (?:my )?payment|payouts?|payout account|withdraw (?:my )?"
            r"(?:money|funds|earnings)|paid out|payout time|how long.*pay(?:out|ment)|"
            r"when will i (?:get paid|be paid)|when.*payout)\b", re.I),
        "intent": "protected_payments",
        "answer": ("Add a payout account in Payments, then funds are released to it after the buyer accepts each "
                   "milestone. The expected bank arrival date is shown with each payout; Zoikorum does not publish a "
                   "fixed payout time."),
        "sections": [("Getting paid", [
            "Add and verify a payout account in Payments.",
            "Escrow releases after the buyer accepts a milestone.",
            "The expected bank arrival date is shown with each payout."])],
        "suggestions": ["How are payments protected?", "When does work start?",
                        "What happens in a dispute?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:delete (?:my )?account|close (?:my )?account|erase (?:my )?account)\b", re.I),
        "intent": "account_help",
        "answer": ("Open Settings -> Privacy & data and choose Delete my account. The request is scheduled after a "
                   "14-day cooling-off period and can be cancelled. It is blocked while engagements, disputes or "
                   "payouts are open, or while you are the only admin of a team; legally required records are kept "
                   "and anonymised where possible."),
        "sections": [("Deleting your account", [
            "Start the request in Settings -> Privacy & data.",
            "There is a 14-day cooling-off period you can cancel.",
            "Open work, disputes, payouts or sole-admin status block deletion.",
            "Contracts, payments, invoices, disputes and audit records are kept by law."])],
        "suggestions": ["How do I get or delete my data?", "How do I contact support?",
                        "How do I turn on two-step verification?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:reset (?:my )?password|forgot (?:my )?password|password reset|lost password|"
            r"change (?:my )?password)\b", re.I),
        "intent": "account_help",
        "answer": ("Use the Forgot your password? link on the sign-in page to get a reset email. If it does not "
                   "arrive, check your spam folder and then contact support from the Help Center."),
        "sections": [("Resetting your password", [
            "Choose Forgot your password? on the sign-in page.",
            "Open the reset link sent to your email address.",
            "Contact support if the email does not arrive."])],
        "suggestions": ["How do I turn on two-step verification?", "How do I contact support?",
                        "How do I get or delete my data?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:(?:can't|cant|cannot|can not|unable to) (?:sign in|log in)|login|log in|"
            r"sign-in (?:problem|issue|help)|email verification|verify (?:my )?email|confirm (?:my )?email|"
            r"locked out|account locked)\b", re.I),
        "intent": "account_help",
        "answer": ("If you cannot sign in, check the email and password, then use Forgot your password? for a reset "
                   "link. For a new account, confirm the verification email first. If it still fails, contact support "
                   "with the error reference; you can review signed-in devices in Settings -> Security."),
        "sections": [("Sign-in help", [
            "Use Forgot your password? to get a reset link.",
            "Confirm your email address after signing up.",
            "Review signed-in devices in Settings -> Security."])],
        "suggestions": ["How do I reset my password?", "How do I turn on two-step verification?",
                        "How do I contact support?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:download my data|export my data|get my data|data request|delete my data|"
            r"privacy request|personal data|data retention|how long do you keep my data)\b", re.I),
        "intent": "account_help",
        "answer": ("Use Settings -> Privacy & data to export or delete your personal data. Legally required records "
                   "(contracts, payments, invoices, disputes and audit) are kept and anonymised where possible; "
                   "account deletion has a 14-day cooling-off period."),
        "sections": [("Your data", [
            "Export or delete personal data in Settings -> Privacy & data.",
            "Contracts, payments, invoices, disputes and audit records are kept by law.",
            "Account deletion has a 14-day cooling-off period you can cancel."])],
        "suggestions": ["How do I delete my account?", "How do I contact support?",
                        "Privacy Notice"],
    },
    {
        "pattern": re.compile(
            r"\b(?:terms of service|terms of use|terms and conditions|privacy policy|privacy notice|"
            r"cookie policy|cookies|trust & safety charter|trust and safety charter|legal documents)\b", re.I),
        "intent": "support_handoff",
        "answer": ("The Terms of Service, Privacy Notice and Trust & Safety Charter are linked from the footer and "
                   "the Help Center. They explain the rules for using Zoikorum, how data is handled and the trust "
                   "and safety standards."),
        "sections": [("Where to find them", [
            "Terms of Service and Privacy Notice are in the footer.",
            "The Trust & Safety Charter is linked from the Help Center.",
            "Each page shows the current version and its effective date."])],
        "suggestions": ["How do I get or delete my data?", "How does verification work?",
                        "How do I contact support?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:two-step|two step|2fa|authenticator|recovery codes?|passkeys?|"
            r"lost (?:my )?(?:phone|authenticator)|security settings|signed-in devices|"
            r"sign out (?:a |this )?device|continue with google|continue with microsoft|"
            r"sign in (?:with )?(?:my )?google|sign in (?:with )?(?:my )?microsoft|"
            r"google sign-in|microsoft sign-in|social sign-in)\b", re.I),
        "intent": "account_help",
        "answer": ("Turn on two-step verification in Settings -> Security; admin roles must use it. On the Security "
                   "page you can also add a passkey, create recovery codes, and review or sign out signed-in devices. "
                   "If you lose your authenticator, use a recovery code at sign-in; if you have none, contact support. "
                   "Google or Microsoft sign-in appears when your organisation offers it."),
        "sections": [("Account and security", [
            "Two-step verification, passkeys and recovery codes live on the Security page.",
            "Admin roles must keep two-step verification on.",
            "Sign out signed-in devices from the same page."]),
            ("Sign-in options", [
                "Use a passkey instead of a password and code on supported devices.",
                "Google or Microsoft sign-in appears when your organisation enables it.",
                "Organisations can also use single sign-on with their identity provider."])],
        "suggestions": ["How do I reset my password?", "How do I contact support?",
                        "How do I set up single sign-on?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:edit (?:my )?profile|update (?:my )?profile|change my (?:name|email|phone)|"
            r"update my (?:name|email|phone)|change (?:the )?email|profile details)\b", re.I),
        "intent": "account_help",
        "answer": ("Update your name and phone in Settings -> Account. The email you sign in with can only be "
                   "changed by contacting support. Professionals manage their public profile and offerings in the "
                   "Professional workspace."),
        "sections": [("Profile and account details", [
            "Name and phone: Settings -> Account.",
            "Sign-in email: contact support to change it.",
            "Professionals edit their public profile in the Professional workspace."])],
        "suggestions": ["How do I contact support?", "How does verification work?",
                        "How do I join as a professional?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:notification|notifications|email alerts|browser push|push notification|digest|"
            r"email digest|bell menu|calendar feed)\b", re.I),
        "intent": "account_help",
        "answer": ("Manage email, in-app, SMS and product-news notifications in Settings -> Notifications. Choose "
                   "each update as it happens, a daily or weekly email summary, or browser push on supported "
                   "devices; urgent payment and security messages always arrive straight away."),
        "sections": [("Notification settings", [
            "Settings -> Notifications controls email, in-app, SMS and product news.",
            "Email delivery can be instant, a daily digest or a weekly digest.",
            "Browser push and the calendar feed are on the same page."])],
        "suggestions": ["How do I contact support?", "How do I turn on two-step verification?",
                        "How do I change my email address?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:mobile app|app store|google play|apple app store|download (?:the )?app|ios app|android app|"
            r"phone app|tablet app|is there an app|do you have an app)\b", re.I),
        "intent": "account_help",
        "answer": ("Zoikorum runs in your web browser on desktop and mobile, so you do not need to install a "
                   "separate app. Sign in at app.zoikorum.com; browser notifications can be enabled in "
                   "Settings -> Notifications."),
        "sections": [("Using Zoikorum on a phone", [
            "Open app.zoikorum.com in your browser.",
            "No separate app install is required.",
            "Browser push notifications are in Settings -> Notifications."])],
        "suggestions": ["How do I contact support?", "How do I turn on two-step verification?",
                        "How do I get or delete my data?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:verification|verified professional|trust tier|trust score|trust light|trust lights|"
            r"who verifies|how does verification work|get verified|become verified|verify my profile|"
            r"tier (?:a|b|c)|green light|amber light|red light|"
            r"what (?:does|do) (?:the )?(?:green|amber|red) (?:mean|light))\b", re.I),
        "intent": "trust_verification",
        "answer": ("A verification provider or a compliance reviewer checks identity, credentials and eligibility; "
                   "AI never decides a verification outcome. On profiles, a green light means fully verified, amber "
                   "means identity verified with restrictions clear, and red means verification is not complete. "
                   "The raw trust score is internal; you see the light and each verified dimension."),
        "sections": [("Trust Tiers", [
            "Tier A: identity, credentials and eligibility verified.",
            "Tier B: identity verified and restrictions clear.",
            "Tier C: verification not complete."]),
            ("Trust lights", [
                "Green: fully verified.",
                "Amber: identity verified and restrictions clear.",
                "Red: verification not complete."])],
        "suggestions": ["Why can't I see a trust score?", "How do I join as a professional?",
                        "How does search rank professionals?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:professionals? (?:tab|section|page)|professional (?:dashboard|workspace|area)|"
            r"provider (?:dashboard|workspace|area)|what(?:'s| is) (?:in )?the professionals? (?:tab|section|page)|"
            r"explain (?:me )?(?:about )?(?:the )?professionals? (?:tab|section|page))\b", re.I),
        "intent": "enterprise_discovery",
        "answer": ("The Professionals area has two sides. Buyers use it to find, filter, save and compare verified "
                   "professionals and request proposals. Professional accounts use the Professional workspace to "
                   "manage their profile, offerings, verification, requests, briefs, engagements and earnings."),
        "sections": [("For buyers", [
            "Search, filter and sort verified professionals.",
            "Save and compare up to three, then request a proposal.",
            "Each result shows its trust light and why it matched."]),
            ("For professionals", [
                "Manage your profile, service offerings and verification.",
                "Handle requests, open briefs, engagements and earnings."])],
        "suggestions": ["How do I find the right professional?", "How does verification work?",
                        "How do I ask for a proposal?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:find (?:a |the )?(?:right )?professionals?|choose (?:a |the )?professional|"
            r"compare (?:professionals?|them|up to|two|three)|how do i compare|how can i compare|"
            r"how many .{0,20}compare|"
            r"search (?:for )?(?:professionals?|work|help)|how do i (?:find|search)|how can my company find|"
            r"save (?:a |the )?professional|saved professionals|favourite|favorite|"
            r"ranking|ranked|rank higher|pay for ranking|paid ranking|"
            r"how are results (?:sorted|ranked)|search rank)\b", re.I),
        "intent": "enterprise_discovery",
        "answer": ("Search results are ranked by relevance to your words, then verification, availability and fit. "
                   "Nobody can pay to rank higher, and each result shows why it matched."),
        "sections": [("Finding and comparing", [
            "Use filters for service, location, availability and Trust Tier.",
            "Compare up to three professionals side by side.",
            "Open a profile or result to request a proposal."])],
        "suggestions": ["What does a Trust Tier mean?", "How do I ask for a proposal?",
                        "How do requests and proposals work?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:filter|filters|search by language|language filter|speaks|languages|what languages|"
            r"location|remote|on-site|onsite|hybrid|availability|timezone|countries|country)\b", re.I),
        "intent": "enterprise_discovery",
        "answer": ("Use Find filters for service, location, delivery (remote, on-site or hybrid), availability, "
                   "language, Trust Tier, budget and pricing model. Professionals list the countries they serve and "
                   "the languages they speak, and each result shows why it matched."),
        "sections": [("Finding and comparing", [
            "Filter by service, location, delivery mode and availability.",
            "Filter by language, Trust Tier, budget and pricing model.",
            "Each result shows its trust light and why it matched."])],
        "suggestions": ["How do I find the right professional?", "What does a Trust Tier mean?",
                        "How do I ask for a proposal?"],
    },
    {
        "pattern": re.compile(r"\bnda\b", re.I),
        "intent": "contracts_milestones",
        "answer": "Yes. A request can require an NDA before the professional sees its details.",
        "sections": [("NDAs", [
            "The requirement is set on the request.",
            "The professional accepts before seeing the brief.",
            "The acceptance is recorded with the engagement."])],
        "suggestions": ["How do I ask for a proposal?", "Can the terms change after signing?",
                        "When does work start?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:proposal|ask for a proposal|request proposal|send a request|"
            r"create (?:a )?(?:request|brief)|post (?:a )?(?:request|brief|job)|start a request|"
            r"hire (?:a |the )?professional|hire someone|how do i hire|start a project|post a project|"
            r"need (?:a |the )?professional|looking for (?:a |the )?professional|"
            r"brief|how many professionals|how many can i (?:request|send)|"
            r"how do (?:requests|proposals) work)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("Open a verified professional's profile or a search result and choose Request proposal. Describe "
                   "the work, deliverables and budget; the professional answers with a proposal you can compare, "
                   "revise or accept."),
        "sections": [("Requests and proposals", [
            "A request describes the work, deliverables and budget.",
            "A request can go to up to five professionals; each replies separately.",
            "The professional replies with a structured proposal.",
            "You can compare, revise or accept before a contract exists."])],
        "suggestions": ["Can I require an NDA?", "Can the terms change after signing?",
                        "When does work start?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:message (?:a |the )?professional|message (?:the )?buyer|message (?:someone|anyone)|"
            r"how do i message|send (?:a |the )?message|messaging|chat with (?:a |the )?professional|"
            r"contact (?:a |the )?(?:professional|buyer)|communicate with|direct message)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("Open the engagement's Messages tab to talk with the other side. Messages are tied to the engagement "
                   "and stay on record. If a dispute is open, direct messages move to the dispute thread."),
        "sections": [("Messaging", [
            "Messages live in the engagement workspace.",
            "The conversation stays with the engagement record.",
            "An open dispute moves discussion to the dispute thread."])],
        "suggestions": ["How do I contact support?", "What happens in a dispute?",
                        "How do I ask for a proposal?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:attach (?:a |the )?file|attachment|attachments|upload (?:a |the )?file|"
            r"send (?:a |the )?file|share (?:a |the )?file|stored file|file storage)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("Attach files to requests, proposals, milestones and messages. Every upload is scanned before it "
                   "can be opened, and files are kept with the engagement record."),
        "sections": [("Files and attachments", [
            "Add attachments to a request, proposal, milestone or message.",
            "Uploads are virus-scanned before they open.",
            "Files stay with the engagement record."])],
        "suggestions": ["How do I message a professional?", "How do I ask for a proposal?",
                        "How do I contact support?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:accept (?:the )?(?:work|delivery|milestone)|approve (?:the )?(?:work|delivery|milestone)|"
            r"request (?:a )?revision|revision request|request (?:a )?changes?|ask for (?:a )?changes?|"
            r"changes to the (?:work|deliverable)|revise (?:the )?work|deliverable|"
            r"late delivery|work is late)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("When a milestone is delivered, review it against the agreed acceptance criteria. Accept it to "
                   "release the milestone funds, or request a revision first. Every revision request stays on the "
                   "engagement record."),
        "sections": [("Delivering and accepting", [
            "Review the delivery against the agreed acceptance criteria.",
            "Accept to release the milestone funds to the professional.",
            "Request a revision before accepting if something is missing."])],
        "suggestions": ["When is the professional paid?", "What happens in a dispute?",
                        "How do I sign a contract?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:cancel (?:a |the |my )?(?:contract|engagement)|end (?:a |the |my )?(?:contract|engagement)|"
            r"terminate (?:a |the |my )?(?:contract|engagement)|how do i terminate|termination)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("If no money is held in escrow, the professional or the buyer's requester or approver can end the "
                   "engagement directly. If funds are held, send the other side a request to end it by agreement; "
                   "they can agree, decline, or let it lapse, and an open dispute decides how it ends."),
        "sections": [("Ending an engagement", [
            "No escrow funds: the authorised side can end it directly.",
            "Funds held: the other side must agree to the termination request.",
            "An open dispute decides how the engagement ends."])],
        "suggestions": ["What happens in a dispute?", "How are payments protected?",
                        "Can the terms change after signing?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:withdraw (?:my |the )?proposal|decline (?:a |the )?proposal|reject (?:a |the )?proposal|"
            r"cancel (?:my |a |the )?request|close (?:my |a |the )?request|stop (?:my |the )?request)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("A professional can withdraw a proposal before it is accepted. A buyer can decline a proposal, "
                   "and can cancel or close a request while it is still open; accepting one proposal closes the "
                   "others for that request."),
        "sections": [("Closing a request or proposal", [
            "Professionals can withdraw a proposal before acceptance.",
            "Buyers can decline a proposal or close an open request.",
            "Accepting one proposal closes the others for that request."])],
        "suggestions": ["How do I ask for a proposal?", "How do I sign a contract?",
                        "How do I contact support?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:contract|engagement|what is an engagement|change order|terms change|"
            r"when does work start|milestones?|engagement terms)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("Work starts after the contract is signed and the first milestone is funded. The buyer signs "
                   "first and the professional countersigns, each with a fresh two-step check. Terms change only "
                   "through a versioned change order that both parties accept."),
        "sections": [("Contracts and milestones", [
            "The buyer's requester or approver signs first; the professional countersigns.",
            "Each milestone has an amount and a due date.",
            "The buyer funds a milestone before work on it starts.",
            "Change orders keep every accepted revision on record."])],
        "suggestions": ["How are payments protected?", "When is the professional paid?",
                        "What happens in a dispute?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:refund|money back|invoice|receipt|billing document|download (?:my )?invoice)\b", re.I),
        "intent": "protected_payments",
        "answer": ("Refunds follow the agreed outcome: if work is not accepted, the professional can agree to release "
                   "the unused amount, or a mediator decides in a dispute. The payment partner returns the money to "
                   "the original payment method. Invoices and receipts are available from Payments."),
        "sections": [("Refunds and documents", [
            "Unused milestone funds can be refunded by agreement or a dispute decision.",
            "The payment partner returns funds to the original payment method.",
            "Download invoices and receipts from Payments & Protection."])],
        "suggestions": ["What happens in a dispute?", "How are payments protected?",
                        "When is the professional paid?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:dispute|disagreement|something went wrong|problem with (?:the )?(?:work|delivery))\b", re.I),
        "intent": "disputes_public",
        "answer": ("If something goes wrong on a funded milestone, raise a dispute from the engagement. The "
                   "milestone's funds are frozen while a mediator reviews the evidence, and direct messages move "
                   "to the dispute thread."),
        "sections": [("When something goes wrong", [
            "Raise the dispute from the affected engagement.",
            "The affected milestone funds are frozen.",
            "A mediator reviews the evidence and records a decision.",
            "If you disagree with the decision, file an appeal on the case."])],
        "suggestions": ["How are payments protected?", "How do I contact support?",
                        "Trust & Safety Charter"],
    },
    {
        "pattern": re.compile(
            r"\b(?:leave (?:a |the )?review|write (?:a |the )?review|how do reviews work|what are reviews|"
            r"are reviews (?:public|verified)|review (?:a |the )?professional|rate (?:a |the )?professional|"
            r"star rating|ratings? (?:count|matter|work)|reply to (?:a )?review|respond to (?:a )?review|"
            r"review reply|review score|rating score|edit (?:my )?(?:review|reply)|change (?:my )?(?:review|reply)|"
            r"delete (?:my )?review)\b", re.I),
        "intent": "trust_verification",
        "answer": ("After an engagement is completed, the buyer can leave one rating from 1 to 5 and a review. It "
                   "appears on the professional's public profile; the professional can post one public reply and "
                   "edit it, with edits recorded. Reviews feed the professional's track record and ranking. A buyer "
                   "cannot edit a review after posting; contact support if it contains a mistake."),
        "sections": [("Reviews", [
            "Reviews open after the engagement is completed.",
            "One review per engagement, rated 1 to 5.",
            "The professional can post and edit one public reply; edits are recorded.",
            "Reviews feed the professional's track record and ranking."])],
        "suggestions": ["How does search rank professionals?", "What does a Trust Tier mean?",
                        "What happens in a dispute?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:platform fee|fees?|commission|how much (?:does|do) (?:zoikorum|you) charge|"
            r"pricing|cost|free|membership|subscription|sign-up fee|joining fee|how much to join|"
            r"charge|charges|do you charge|pay to join|cost to join|set my rate|set my price|set my rates|"
            r"hourly rate|fixed price|pricing model|charge per hour|how much should i charge|rate card)\b", re.I),
        "intent": "pricing_public",
        "answer": ("The price for the work is agreed in the proposal and contract, and any platform fee is shown "
                   "there before you commit. Professionals set their own price and pricing model, such as fixed "
                   "price, hourly or retainer. Joining and browsing are free; no payment is taken until you fund a "
                   "milestone in a signed contract."),
        "sections": [("Pricing", [
            "Professionals set their own proposal price and pricing model.",
            "Any platform fee is displayed before signing.",
            "Joining and browsing are free; payment starts when you fund a milestone.",
            "Escrow funding follows the agreed milestones."])],
        "suggestions": ["How are payments protected?", "How do I ask for a proposal?",
                        "Terms of Service"],
    },
    {
        "pattern": re.compile(
            r"\b(?:suspend|suspended|ban|banned|account (?:is )?blocked|account (?:is )?suspended|"
            r"restricted|appeal|appeals)\b", re.I),
        "intent": "support_handoff",
        "answer": ("If an account or case is restricted, Trust & Safety records the reason and the evidence. You can "
                   "file an appeal on the case with your explanation and supporting evidence; the decision is "
                   "reviewed on the record."),
        "sections": [("Restrictions and appeals", [
            "Trust & Safety records the reason and evidence for a restriction.",
            "File an appeal on the case with your explanation and evidence.",
            "The decision is reviewed on the record."])],
        "suggestions": ["How do I report a scam?", "How do I contact support?",
                        "What happens in a dispute?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:report (?:a |the )?(?:user|professional|profile|fraud|scam|abuse|review|message|"
            r"account|organisation)|fake profile|scam|fraud|abuse|trust & safety)\b", re.I),
        "intent": "support_handoff",
        "answer": ("Report a profile, message or engagement to Trust & Safety from the app or Help & Support, "
                   "including the link or reference. Reports are reviewed and recorded; conduct and compliance "
                   "cases skip direct resolution."),
        "sections": [("Reporting a concern", [
            "Report the profile or engagement with its link or reference.",
            "Our team reviews the report and records the outcome.",
            "Conduct and compliance cases go straight to review."])],
        "suggestions": ["How do I contact support?", "What happens in a dispute?",
                        "How does verification work?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:contact support|get help|help & support|help and support|customer service|help center|"
            r"support hours|support (?:ticket|time|response|sla)|response time|how long.*reply|"
            r"how long (?:does|do) (?:support|it) take|how quickly.*(?:support|help|reply)|"
            r"talk to (?:a |the )?human|contact (?:a |the )?human|get in touch|reach (?:support|you|the team)|"
            r"contact us|how do i contact (?:support|you|the team|zoikorum)|"
            r"report a bug|something is broken|not working|technical problem|feature request|request a feature|"
            r"product feedback|feedback about (?:zoikorum|the platform|the app|the site)|"
            r"live chat|chat with support|support email|email support)\b", re.I),
        "intent": "support_handoff",
        "answer": ("Open Help & Support in the app to search answers or send a help request; we reply within one "
                   "business day. Choose Technical for a bug and include the page or error reference. For "
                   "disagreements about delivered work, raise a dispute from the engagement instead."),
        "sections": [("Getting help", [
            "Search the Help Center for common answers.",
            "Send a help request with the page or error reference.",
            "Use Technical for a bug or something that is not working.",
            "Raise a dispute for problems with delivered work."])],
        "suggestions": ["What happens in a dispute?", "How do I turn on two-step verification?",
                        "How do I get or delete my data?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:organisation|organization|add a colleague|invite (?:a )?(?:colleague|member)|"
            r"invite (?:someone|a user|people)|team member|set up a team|team setup|manage a team|"
            r"spending approval|spend limit|who can approve|roles? and permissions|"
            r"permissions|single sign-on|sso|create (?:an )?organisation|"
            r"okta|entra|google workspace|identity provider|scim|directory sync|oidc|openid connect)\b", re.I),
        "intent": "account_help",
        "answer": ("Org Admins invite members and assign roles from Organisation -> Members & access. Approvers can "
                   "approve spending up to their spend limit, and requesters cannot approve their own requests. "
                   "Org Admins can also connect single sign-on with OpenID Connect (Okta, Microsoft Entra ID, "
                   "Google Workspace and others) under Organisation -> Security and enable SCIM provisioning."),
        "sections": [("Organisation and access", [
            "Org Admins manage members and roles.",
            "Approvers work within their spend limit.",
            "Requesters cannot approve their own requests."]),
            ("Single sign-on", [
                "Connect an OpenID Connect identity provider under Organisation -> Security.",
                "Providers include Okta, Microsoft Entra ID and Google Workspace.",
                "SCIM provisioning can be enabled for automatic member sync."])],
        "suggestions": ["How do I turn on two-step verification?", "How do I contact support?",
                        "How do I get or delete my data?"],
    },
]
GENERAL_FAQ = next(entry for entry in FAQ_REPLIES if entry["intent"] == "general")
CHAT_CACHE: dict[str, tuple[float, dict, str]] = {}
CHAT_CACHE_TTL_SECONDS = 600
CHAT_CACHE_MAX = 200
CHAT_FALLBACK_MODELS = ["qwen2.5:0.5b"]


async def _ollama_chat_with(settings, message: str, model: str) -> str:
    """Local model through Ollama's chat API, for a specific model."""
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{settings.ollama_url.rstrip('/')}/api/chat", json={
            "model": model,
            "messages": [{"role": "system", "content": CHAT_INSTRUCTIONS},
                         {"role": "user", "content": message}],
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": 300},
        })
        response.raise_for_status()
        return ((response.json().get("message") or {}).get("content") or "").strip()


async def _ollama_chat(settings, message: str) -> str:
    """Local model through Ollama's chat API, so the assistant answers without an external API key."""
    return await _ollama_chat_with(settings, message, settings.ollama_model)


def _clean(value, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _is_greeting(message: str) -> bool:
    return bool(GREETING_RE.match(" ".join(message.split())))


def _normalize_chat(raw: str) -> dict:
    """Validate the model's JSON contract; degrade gracefully to the raw text if it is not JSON."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    data = {}
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    answer = _clean(data.get("answer") or data.get("text") or raw, 1200)
    if re.fullmatch(r"<[^>]*>", answer):
        answer = ""
    intent = data.get("intent") if data.get("intent") in CHAT_INTENTS else "general"
    sections = []
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = _clean(section.get("title"), 80)
        items = [_clean(item, 280) for item in (section.get("items") or []) if _clean(item, 280)]
        if title and items:
            sections.append({"title": title, "items": items[:4]})
        if len(sections) == 3:
            break
    suggestions = [_clean(item, 140) for item in (data.get("suggestions") or []) if _clean(item, 140)]
    suggestions = suggestions[:3] or CHAT_SUGGESTIONS[:2]
    limitations = _clean(data.get("limitations"), 260) or (
        "I can explain published information only and cannot approve, verify, execute or decide anything.")
    return {
        "intent": intent,
        "answer": answer or CHAT_UNHELPFUL,
        "sections": sections,
        "suggestions": suggestions,
        "limitations": limitations,
        "related": [{"label": label, "to": to} for label, to in RELATED_PAGES.get(intent, RELATED_PAGES["general"])],
    }


def _match_faq(message: str):
    return next((entry for entry in FAQ_REPLIES if entry["pattern"].search(message)), None)


def _curated_reply(entry: dict) -> dict:
    return {
        "intent": entry["intent"],
        "answer": entry["answer"],
        "sections": [{"title": title, "items": list(items)} for title, items in entry["sections"]],
        "suggestions": list(entry["suggestions"]),
        "limitations": "I can explain published information only and cannot approve, verify, execute or decide anything.",
        "related": [{"label": label, "to": to}
                    for label, to in RELATED_PAGES.get(entry["intent"], RELATED_PAGES["general"])],
    }


def _fallback_chat() -> dict:
    return {
        "intent": "general",
        "answer": CHAT_FALLBACK,
        "sections": [{"title": "What I can help with", "items": [
            "Finding and comparing professionals", "Requests, proposals and contracts",
            "Protected payments, milestones and delivery", "Verification, reviews and disputes"]}],
        "suggestions": CHAT_SUGGESTIONS,
        "limitations": "I can explain published information only and cannot access your account or take any action.",
        "related": [{"label": label, "to": to} for label, to in RELATED_PAGES["general"]],
    }


async def chat(session, actor_id, message: str):
    started = time.monotonic()
    settings = get_settings()
    facts = {"message": message[:4000]}
    faq = _match_faq(message)
    if _is_greeting(message):
        payload = {**GREETING_REPLY, "related": [{"label": label, "to": to}
                                                 for label, to in RELATED_PAGES["general"]]}
        model, fallback_used = "deterministic:greeting:v1", False
    elif faq:
        payload, model, fallback_used = _curated_reply(faq), "deterministic:faq:v1", False
    elif PLATFORM_RE.search(message):
        payload, model, fallback_used = _curated_reply(GENERAL_FAQ), "deterministic:overview:v1", False
    else:
        key = " ".join(message.lower().split())
        cached = CHAT_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CHAT_CACHE_TTL_SECONDS:
            payload, model, fallback_used = cached[1], cached[2], cached[3]
        else:
            fallback_used = True
            payload = _fallback_chat()
            anthropic = settings.ai_provider == "anthropic" and bool(settings.anthropic_api_key)
            models = list(dict.fromkeys([settings.ollama_model, *CHAT_FALLBACK_MODELS]))
            tries = 1 if anthropic else len(models)
            for attempt in range(tries):
                try:
                    if anthropic:
                        raw = await providers.provider().generate(CHAT_INSTRUCTIONS, message[:4000])
                        model = settings.ai_model
                    elif attempt == 0:
                        raw = await _ollama_chat(settings, message[:4000])
                        model = f"ollama:{models[0]}"
                    else:
                        raw = await _ollama_chat_with(settings, message[:4000], models[attempt])
                        model = f"ollama:{models[attempt]}"
                    if not raw.strip():
                        raise ValueError("Empty provider output")
                    payload = _normalize_chat(raw)
                    if payload["answer"] == CHAT_UNHELPFUL:
                        raise ValueError("Unusable provider output")
                    fallback_used = False
                    break
                except Exception:
                    if attempt + 1 < tries:
                        await asyncio.sleep(0.5)
            if fallback_used:
                payload, model = _fallback_chat(), "fallback:deterministic:v1"
            else:
                if len(CHAT_CACHE) >= CHAT_CACHE_MAX:
                    CHAT_CACHE.pop(next(iter(CHAT_CACHE)))
                CHAT_CACHE[key] = (time.monotonic(), payload, model, fallback_used)
    output = json.dumps({
        "intent": payload["intent"],
        "answerSha256": hashlib.sha256(payload["answer"].encode("utf-8")).hexdigest(),
        "answerLength": len(payload["answer"]),
        "sectionCount": len(payload["sections"]),
        "suggestionCount": len(payload["suggestions"]),
        "redacted": True,
    }, ensure_ascii=False)
    log = InferenceLog(prompt_id=None, prompt_version=None,
        model=model if not fallback_used else "fallback:deterministic:v1",
        input_sha256=hashlib.sha256(canonical_json(facts)).hexdigest(), output=output, purpose="assistant-chat",
        subject_id=None, requested_by=actor_id, latency_ms=round((time.monotonic() - started) * 1000),
        fallback_used=fallback_used)
    session.add(log); await session.flush()
    record_event(session, E.AI_OUTPUT_GENERATED, aggregate_type="InferenceLog", aggregate_id=log.id,
                 payload={"inferenceId": log.id, "purpose": "assistant-chat", "subjectId": None,
                          "promptVersion": None, "model": log.model, "fallbackUsed": fallback_used,
                          "inputHash": log.input_sha256})
    return {"answerId": str(log.id), **payload, "text": payload["answer"], "disclaimer": DISCLAIMER,
            "model": log.model, "fallbackUsed": fallback_used, "inferenceId": str(log.id)}


async def infer(session, actor_id, purpose, subject_id, facts, fallback):
    started = time.monotonic()
    settings = get_settings()
    model = settings.ai_model if settings.ai_provider == "anthropic" else "offline:v1"
    prompt = await session.scalar(select(PromptVersion).where(PromptVersion.prompt_key == purpose,
        PromptVersion.status == "APPROVED", PromptVersion.target_model == model).order_by(PromptVersion.version.desc()).limit(1))
    output, fallback_used = fallback, True
    if prompt and (settings.ai_provider == "offline" or (settings.ai_provider == "anthropic" and settings.anthropic_api_key)):
        try:
            output = await providers.provider().generate(prompt.instructions, canonical_json(facts).decode())
            if not output.strip():
                raise ValueError("Empty provider output")
            fallback_used = False
        except Exception:
            output = fallback
    log = InferenceLog(prompt_id=prompt.id if prompt else None, prompt_version=prompt.version if prompt else None,
        model=model if not fallback_used else "fallback:deterministic:v1", input_sha256=hashlib.sha256(canonical_json(facts)).hexdigest(),
        output=output, purpose=purpose, subject_id=subject_id, requested_by=actor_id,
        latency_ms=round((time.monotonic() - started) * 1000), fallback_used=fallback_used)
    session.add(log); await session.flush()
    record_event(session, E.AI_OUTPUT_GENERATED, aggregate_type="InferenceLog", aggregate_id=log.id,
                 payload={"inferenceId": log.id, "purpose": purpose, "subjectId": subject_id, "promptVersion": log.prompt_version,
                          "model": log.model, "fallbackUsed": fallback_used, "inputHash": log.input_sha256})
    return {"text": output, "disclaimer": DISCLAIMER, "model": log.model, "promptVersion": log.prompt_version,
            "fallbackUsed": fallback_used, "inferenceId": str(log.id)}


def prompt_out(p):
    return {"id": str(p.id), "promptKey": p.prompt_key, "version": p.version, "owner": str(p.owner), "targetModel": p.target_model,
            "instructions": p.instructions, "goldenTests": p.golden_tests, "status": p.status, "approvedBy": str(p.approved_by) if p.approved_by else None}


async def create_prompt(session, actor, body):
    from zoikorum.domains.admin import facade as admin
    from zoikorum.domains.identity import facade as identity
    from zoikorum.shared.capabilities import Cap, capabilities_for
    from zoikorum.shared.errors import Forbidden
    actor.require_capability(Cap.AI_PROMPTS_MANAGE); actor.require_step_up()
    if Cap.AI_PROMPTS_MANAGE not in capabilities_for(await identity.live_platform_roles(session, actor.identity_id)):
        raise Forbidden("Requires live AI Safety Reviewer authority")
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"prompt:{body.promptKey}"})
    latest = await session.scalar(select(PromptVersion.version).where(PromptVersion.prompt_key == body.promptKey).order_by(PromptVersion.version.desc()).limit(1)) or 0
    p = PromptVersion(prompt_key=body.promptKey, version=latest + 1, owner=actor.identity_id, target_model=body.targetModel,
                      instructions=body.instructions, golden_tests=[t.model_dump() for t in body.goldenTests])
    session.add(p); await session.flush()
    return prompt_out(p)


async def approve_prompt(session, actor, prompt_id):
    from zoikorum.domains.identity import facade as identity
    from zoikorum.shared.capabilities import Cap, capabilities_for
    from zoikorum.shared.errors import Forbidden
    actor.require_capability(Cap.AI_PROMPTS_MANAGE); actor.require_step_up()
    if Cap.AI_PROMPTS_MANAGE not in capabilities_for(await identity.live_platform_roles(session, actor.identity_id)):
        raise Forbidden("Requires live AI Safety Reviewer authority")
    p = await session.get(PromptVersion, prompt_id, with_for_update=True)
    if not p:
        raise NotFound("Prompt version not found")
    if p.status != "DRAFT":
        raise Conflict("Only a draft prompt can be approved")
    model = get_settings().ai_model if get_settings().ai_provider == "anthropic" else "offline:v1"
    if p.target_model != model:
        raise ValidationFailed("Configure the target provider/model before validating this prompt")
    if get_settings().ai_provider == "anthropic" and not get_settings().anthropic_api_key:
        raise Conflict("Configure the provider credentials before approving this prompt", code="AI_PROVIDER_UNAVAILABLE")
    for test in p.golden_tests:
        try:
            result = await providers.provider().generate(p.instructions, test["input"])
        except Exception as exc:
            raise Conflict("The provider could not validate golden tests; the prompt remains unapproved", code="AI_PROVIDER_UNAVAILABLE") from exc
        if not all(word.casefold() in result.casefold() for word in test["mustContain"]):
            raise Conflict("Golden tests failed; prompt remains unapproved", code="PROMPT_TEST_FAILED")
    p.status, p.approved_by = "APPROVED", actor.identity_id
    record_event(session, E.PROMPT_VERSION_ACTIVATED, aggregate_type="PromptVersion", aggregate_id=p.id,
        payload={"promptKey": p.prompt_key, "version": p.version, "approvedBy": actor.identity_id, "targetModel": p.target_model})
    return prompt_out(p)
