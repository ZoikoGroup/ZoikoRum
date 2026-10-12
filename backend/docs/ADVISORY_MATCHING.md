# Advisory discovery assistance

`POST /v1/ai/match-intent` accepts an authenticated user's search query. The discovery page exposes it through **Suggest expertise for this search**. Suggestions do not change the search until the user chooses **Apply suggested expertise**; existing jurisdiction, tier, verification and organisation filters remain in place.

Without an approved `match-intent` prompt, the service returns deterministic keyword suggestions. To enable model output, configure the existing Anthropic integration and have an AI Safety Reviewer approve a prompt for the configured model through the prompt governance workflow. The output must be exactly a JSON object containing `specializations`, an array of at most five current taxonomy slugs. Unknown slugs, extra authority-bearing fields, malformed output and provider failures use the deterministic fallback.

Inference records retain model, prompt version, input hash, output and fallback status. Suggestions carry the advisory disclaimer and do not verify credentials, bypass policy, accept proposals or make dispute decisions. Existing proposal drafting, contract summaries and assigned-mediator evidence summaries remain independently scoped to their source records.
