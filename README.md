# FitFindr

FitFindr is an AI agent that helps you find secondhand clothing and style it with what you already own. Describe what you're looking for in plain English — include a size or price ceiling if you want — and the agent searches a dataset of 40 mock thrift listings, generates outfit suggestions using your wardrobe, and produces a shareable fit card caption.

---

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Groq API key (free at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the Gradio UI:

```bash
python3 app.py
```

Run the CLI test (happy path + no-results path):

```bash
python3 agent.py
```

Run all tests:

```bash
pytest tests/
```

---

## Tool Inventory

### Tool 1: `search_listings`

**Purpose:** Searches the mock listings dataset for secondhand items that match the user's description, size, and price ceiling. No LLM call — pure keyword filtering and scoring.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | `str` | Free-text keywords from the user's query, e.g. `"vintage graphic tee"`. Scored against each listing's title, description, category, style_tags, and colors. |
| `size` | `str \| None` | Size to filter by, e.g. `"M"` or `"W30"`. Case-insensitive substring match — `"M"` matches `"S/M"`. Pass `None` to skip. |
| `max_price` | `float \| None` | Upper price bound (inclusive), e.g. `30.0`. Pass `None` to skip. |

**Output:** `list[dict]` — matching listing records sorted by keyword score (highest first). Each dict contains: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Returns `[]` on no match — never raises.

---

### Tool 2: `suggest_outfit`

**Purpose:** Given the item the user is considering buying and their current wardrobe, calls the Groq LLM to suggest 1–2 complete outfit combinations. Handles an empty wardrobe gracefully by falling back to general styling advice.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | `dict` | A full listing dict as returned by `search_listings`. Uses `title`, `category`, `style_tags`, `colors`, and `condition` to build the prompt. |
| `wardrobe` | `dict` | A wardrobe dict with an `"items"` key containing a list of wardrobe item dicts (each with at minimum `name` and `category`). May be empty. |

**Output:** `str` — 1–2 outfit suggestions naming specific wardrobe pieces and explaining why each combination works. If the wardrobe is empty, returns general styling advice instead. Never returns an empty string in the normal path.

**Model:** `llama-3.3-70b-versatile` via Groq, temperature 0.7.

---

### Tool 3: `create_fit_card`

**Purpose:** Takes the outfit suggestion and the listing, then calls the Groq LLM to produce a 2–4 sentence Instagram/TikTok-style OOTD caption that feels authentic and mentions the item name, price, and platform exactly once each.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | `str` | The full suggestion string from `suggest_outfit`. Must be non-empty and non-whitespace. |
| `new_item` | `dict` | The listing dict for the thrifted item. Uses `title`, `price`, and `platform` to inject into the caption prompt. |

**Output:** `str` — a 2–4 sentence caption suitable for social media. If `outfit` is empty or whitespace-only, returns `"Error: outfit data is missing — cannot generate a fit card."` immediately without calling the LLM.

**Model:** `llama-3.3-70b-versatile` via Groq, temperature 0.9 (higher than `suggest_outfit` to ensure caption variety across repeated calls on the same input).

---

## Planning Loop

The loop lives in `run_agent()` in `agent.py`. It runs seven steps in sequence and exits early if any step produces no usable output.

1. **Initialize** a fresh `session` dict to hold all state for this interaction.
2. **Parse** the user's query with regex: extract a `description` (leftover keywords after removing price/size fragments), a `size` string (e.g. `"M"`, `"W30"`), and a `max_price` float (e.g. `30.0`). Store in `session["parsed"]`.
3. **Call `search_listings`** with the parsed parameters. Store results in `session["search_results"]`. If the list is empty, set `session["error"]` and return immediately — `suggest_outfit` and `create_fit_card` are never called.
4. **Select** `session["selected_item"] = session["search_results"][0]` (highest-scoring match).
5. **Call `suggest_outfit`** with `selected_item` and `session["wardrobe"]`. Store the result in `session["outfit_suggestion"]`.
6. **Call `create_fit_card`** with `outfit_suggestion` and `selected_item`. Store the result in `session["fit_card"]`.
7. **Return** the session dict. The caller checks `session["error"]` first; if `None`, all three output fields are populated.

The loop only calls all three tools when `search_listings` returns results. A no-match query terminates at Step 3 with the error set and the LLM never contacted.

---

## State Management

All state is stored in a single `session` dict initialized by `_new_session()` and threaded through the loop by `run_agent()`. Tools receive only their required inputs as explicit arguments — they never read from or write to the session directly.

| Key | Type | Written at | Read at |
|-----|------|-----------|---------|
| `session["query"]` | `str` | initialization | — |
| `session["parsed"]` | `dict` | Step 2 (parse) | Step 3 (search) |
| `session["search_results"]` | `list[dict]` | Step 3 | Step 4 |
| `session["selected_item"]` | `dict` | Step 4 | Steps 5, 6 |
| `session["wardrobe"]` | `dict` | initialization | Step 5 |
| `session["outfit_suggestion"]` | `str` | Step 5 | Step 6 |
| `session["fit_card"]` | `str` | Step 6 | returned to UI |
| `session["error"]` | `str \| None` | Steps 3, 5 on failure | caller / UI |

`session["selected_item"]` is the same Python object as `session["search_results"][0]` — confirmed in testing with `session["search_results"][0] is session["selected_item"]` returning `True`. No values are re-fetched or re-derived between steps.

---

## Error Handling

### `search_listings` — no results

**Failure mode:** The combination of keywords, size, and price ceiling matches zero listings.

**Agent response:** Sets `session["error"]` to `"No listings matched your search. Try broader keywords, a different size, or raise your price limit."` and returns the session immediately. `suggest_outfit` and `create_fit_card` are not called.

**Concrete example from testing:**
```
Query:  "designer ballgown size XXS under $5"
Parsed: description="designer ballgown", size="xxs", max_price=5.0

search_results:    []
selected_item:     None
outfit_suggestion: None
fit_card:          None
error:             "No listings matched your search. Try broader keywords,
                    a different size, or raise your price limit."
```
The LLM was never contacted. Confirmed by `mock_client.chat.completions.create.assert_not_called()` in `test_run_agent_no_results_returns_error_without_calling_llm`.

---

### `suggest_outfit` — empty wardrobe

**Failure mode:** `wardrobe["items"]` is an empty list (new user, no wardrobe set up).

**Agent response:** `suggest_outfit` detects the empty list and switches to a general styling prompt — asking the LLM what kinds of pieces pair well with the item, what vibe it suits, and how to build an outfit around it — rather than referencing specific wardrobe pieces. The function still returns a non-empty string; the loop continues normally to `create_fit_card`.

**Concrete example from testing:**
```python
result = suggest_outfit(item, get_empty_wardrobe())
# Returns: "For a Y2K-inspired look, try pairing this baby tee with high-waisted
#           wide-leg jeans and chunky platform sneakers..."
# Does NOT return "" or raise an exception.
```
Confirmed by `test_suggest_outfit_empty_wardrobe_does_not_crash` (returns non-empty string) and `test_suggest_outfit_empty_wardrobe_uses_general_prompt` (LLM call still happens).

---

### `create_fit_card` — empty outfit string

**Failure mode:** `outfit` argument is empty or whitespace-only (e.g. if `suggest_outfit` returned `""` in a hypothetical edge case).

**Agent response:** The guard at the top of `create_fit_card` fires before the Groq client is even instantiated, returning the string `"Error: outfit data is missing — cannot generate a fit card."` — no LLM call, no exception.

**Concrete example from testing:**
```python
result = create_fit_card("", new_item)
# Returns: "Error: outfit data is missing — cannot generate a fit card."

result = create_fit_card("   ", new_item)
# Returns: "Error: outfit data is missing — cannot generate a fit card."
```
Confirmed by `test_create_fit_card_empty_outfit_returns_error_string`, `test_create_fit_card_whitespace_outfit_returns_error_string`, and `test_create_fit_card_does_not_call_llm_when_outfit_empty`.

---

## AI Usage

### Instance 1: Implementing `search_listings`

**Input given to Claude:** The full Tool 1 spec block from `planning.md` — what it does, the three input parameters with names and types, the return value description listing all 11 fields, and the failure mode (return `[]`, never raise). Also included the note to use `load_listings()` from `utils/data_loader.py` rather than re-implementing file loading.

**What it produced:** A working implementation that loaded listings, filtered by price and size, and scored by keyword overlap. The structure was correct and matched the spec.

**What I changed:** The initial output was wrong in two ways. First, it scored only against `title` and `style_tags` — it missed `description`, `category`, and `colors`, which are all listed in the spec. I pointed this back at the spec and it added the missing fields. Second, the size filter used an exact case-insensitive match (`size.lower() == listing["size"].lower()`) instead of the substring match the spec requires — `"M"` needs to match `"S/M"`. I caught this by running `search_listings("tops", size="M")` and getting zero results when several S/M listings existed. I told Claude the spec says substring match and it corrected it to `size_lower in listing["size"].lower()`. Both bugs would have been caught by the test suite, which is part of why writing tests from the spec first is the better order.

---

### Instance 2: Implementing the planning loop in `run_agent()`

**Input given to Claude:** The Planning Loop section from `planning.md` (the seven numbered steps with explicit branch conditions), the State Management table (all session keys, their types, and when each is written vs. read), and the ASCII architecture diagram from the Architecture section showing the two early-exit error branches.

**What it produced:** A loop that called all three tools unconditionally — `suggest_outfit` and `create_fit_card` were called even when `search_results` was empty, which is exactly the failure mode the spec calls out. It also did not store `selected_item` separately from `search_results`; it passed `search_results[0]` directly into `suggest_outfit` without writing it to the session first, so the state table was not being followed.

**What I changed:** I flagged both issues against the spec. For the early-exit branch I quoted Step 3 directly: "If no results: set session['error'] to a helpful message and return the session early. Do NOT proceed to suggest_outfit with empty input." For the missing session key I pointed to the state table row showing `selected_item` is written at Step 4 and read at Steps 5 and 6. After the correction I ran `test_run_agent_no_results_returns_error_without_calling_llm` to confirm the LLM was no longer being called on the empty-results path — the mock assertion `mock_client.chat.completions.create.assert_not_called()` passed.

---

## Spec Reflection

**What matched the spec:**
The planning loop matched `planning.md` closely. The conditional branch at Step 3 (early return on empty results), the session dict structure, and the tool signatures all came directly from the spec and needed no revision. The `search_listings` keyword scoring worked on the first implementation — the five fields to score against (title, description, category, style_tags, colors) were specific enough that the implementation had no ambiguity.

**What diverged:**
The query parser ended up simpler than planned. The spec described using regex or the LLM to extract parameters; I used regex only. The LLM option would have handled more conversational phrasings (e.g. "something around thirty dollars") but added latency and a point of failure before any search result was available, so regex was the better tradeoff for this dataset.

The `search_listings` scoring returned 20 results for `"vintage graphic tee under $30"` rather than a short list, because "vintage" appears in nearly every listing in the dataset. In production this would need a relevance threshold or a top-N cap, but for the mock dataset it does not cause downstream problems — `selected_item` is always `results[0]`, the highest scorer.

**What I would do differently:**
I would write the tests before implementing the tools rather than after. Having `test_run_agent_no_results_returns_error_without_calling_llm` in place from the start would have caught any accidental unconditional tool calls immediately. The spec was detailed enough to write those tests from planning.md alone — no implementation needed first.
