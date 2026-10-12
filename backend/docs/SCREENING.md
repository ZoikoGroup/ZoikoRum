# Sanctions and PEP screening

Set `ZK_SCREENING_PROVIDER=complyadvantage` and `ZK_COMPLYADVANTAGE_API_KEY` to use the ComplyAdvantage search API. `ZK_COMPLYADVANTAGE_SEARCH_PROFILE` optionally selects the partner's configured screening profile. Keep the identity verification provider configured separately: screening does not replace identity or credential verification.

The adapter submits sanctions, warning and PEP searches and stores the returned reference, match count and check timestamp. Compliance reviewers see these fields in the verification queue. Account owners cannot read internal screening references. Partner errors fail closed; a failed request never clears a person.

All results require compliance review, including zero matches. The current profile name is self-reported, so a reviewer must confirm name provenance against verified identity and investigate possible matches in the partner system. A PEP match is not automatically a sanctions determination. The adapter does not claim continuous monitoring or registry verification.

Configure the partner account's geographic coverage, screening profile, access controls and monitoring obligations before production use. Run an authorised partner sandbox check before enabling production traffic.

Protocol reference: [ComplyAdvantage API documentation](https://docs.complyadvantage.com/api-docs/).
