# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Loads all listings from `listings.json` via `load_listings()`, filters them by `size` `max_price` (inclusive), then scores each remaining listing by how many words from `description` appear in the listing's `title`, `description`, `style_tags`, `category`, and `colors` fields. Returns only listings with a score ≥ 1, sorted highest score first.

**Input parameters:**
- `description` (str): Free-text keywords from the user's request, e.g. `"vintage graphic tee"`. Used for keyword scoring across title, description, style_tags, category, and colors.
- `size` (str | None): Size string to filter by, e.g. `"M"` or `"W30"`. Matching is case-insensitive substring — `"M"` matches both `"M"` and `"S/M"`. Pass `None` to skip size filtering.
- `max_price` (float | None): Upper price bound (inclusive), e.g. `30.0`. Pass `None` to skip price filtering.

**What it returns:**
A `list[dict]` where each dict is one full listing record with these fields:
- `id` (str): unique listing ID, e.g. `"lst_006"`
- `title` (str): listing name, e.g. `"Graphic Tee — 2003 Tour Bootleg Style"`
- `description` (str): seller's description
- `category` (str): one of `tops`, `bottoms`, `outerwear`, `shoes`, `accessories`
- `style_tags` (list[str]): e.g. `["graphic tee", "vintage", "streetwear"]`
- `size` (str): e.g. `"L"` or `"W30 L30"`
- `condition` (str): one of `excellent`, `good`, `fair`
- `price` (float): e.g. `24.0`
- `colors` (list[str]): e.g. `["black"]`
- `brand` (str | None): brand name or `null`
- `platform` (str): one of `depop`, `thredUp`, `poshmark`

Returns an empty list `[]` if nothing matches — never raises an exception.

**What happens if it fails or returns nothing:**
If the returned list is empty, the planning loop sets `session["error"] = "No listings matched your search. Try broader keywords, a different size, or raise your price limit."` and returns that message to the user immediately without calling `suggest_outfit` or `create_fit_card`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes a single listing dict (the item the user is considering buying) and a wardrobe dict, then calls the Groq LLM to suggest 1–2 complete outfit combinations. If the wardrobe is empty it asks the LLM for general styling advice instead of named pairings.

**Input parameters:**
- `new_item` (dict): A full listing dict as returned by `search_listings` — uses `title`, `style_tags`, `colors`, `category`, and `condition` to build the prompt.
- `wardrobe` (dict): A wardrobe dict with an `"items"` key containing a list of wardrobe item dicts. Each wardrobe item has at minimum `name` (str) and `category` (str). May be an empty-items dict like `{"items": []}`.

**What it returns:**
A non-empty `str` containing 1–2 outfit suggestions. Each suggestion names specific pieces and briefly explains why the combination works, e.g.:
> "Outfit 1: pair the Graphic Tee with your Vintage Levi's 501s and white low-top Chucks — the worn-in black tee grounds the denim without competing. Outfit 2: wear it tucked into the rust cords with chunky sneakers for a 90s-inspired earthier take."

If the wardrobe is empty the string gives general styling advice without naming specific wardrobe pieces.

**What happens if it fails or returns nothing:**
If the LLM call throws or returns an empty string, the planning loop catches the exception, sets `session["error"] = "Could not generate outfit suggestions. Please try again."`, and returns that message to the user. `create_fit_card` is not called.

---

### Tool 3: create_fit_card

**What it does:**
Takes the outfit suggestion string from `suggest_outfit` and the listing dict, then calls the Groq LLM (at a higher temperature, ~0.9) to produce a 2–4 sentence Instagram/TikTok-style OOTD caption that feels authentic, mentions the item name, price, and platform once each, and captures the outfit's vibe.

**Input parameters:**
- `outfit` (str): The full suggestion string returned by `suggest_outfit`. Used verbatim in the LLM prompt. Must be a non-empty, non-whitespace string.
- `new_item` (dict): The listing dict for the thrifted item — uses `title` (str), `price` (float), and `platform` (str) to inject into the caption prompt.

**What it returns:**
A `str` of 2–4 sentences suitable as a social media caption, e.g.:
> "Found this 2003 tour bootleg tee on depop for $24 and I can't stop thinking about it. Boxy fit, black, slightly faded — it basically styled itself. Tucked into rust cords with chunky sneakers and the whole thing just clicks."

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the function immediately returns the string `"Error: outfit data is missing — cannot generate a fit card."` without calling the LLM. If the LLM call throws, the planning loop catches it and returns `"Could not generate fit card. The outfit suggestion was: {outfit}"` so the user still sees the suggestion.

---

### Additional Tools (if any)

I dont think there is any
---

## Planning Loop

**How does your agent decide which tool to call next?**

The planning loop runs inside `agent.py` and processes one user message at a time. Here is the step-by-step conditional logic:

1. **Parse the user message.** Extract a `description` string (everything the user says about the item), a `size` string (look for keywords like "size M", "small", "W30"; set to `None` if absent), and a `max_price` float (look for "$X", "under X", "less than X"; set to `None` if absent). Store these in `session["last_query"]`.

2. **Call `search_listings(description, size, max_price)`.**
   - If the result is an empty list → set `session["error"] = "No listings matched..."`, return the error message to the user, and **stop here** (do not proceed to step 3).
   - If the result is non-empty → set `session["results"] = results` and `session["selected_item"] = results[0]`. Proceed to step 3.

3. **Load the wardrobe.** Read `session["wardrobe"]` if it exists; otherwise call `get_example_wardrobe()` and store it in `session["wardrobe"]`.

4. **Call `suggest_outfit(session["selected_item"], session["wardrobe"])`.**
   - If the call throws or returns `""` → set `session["error"] = "Could not generate outfit suggestions."`, return the error message, and **stop here**.
   - If successful → store the result in `session["outfit_suggestion"]`. Proceed to step 5.

5. **Call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`.**
   - If `outfit_suggestion` is empty → return the fallback error string from `create_fit_card` directly.
   - If the LLM call throws → return `"Could not generate fit card. The outfit suggestion was: {session['outfit_suggestion']}"`.
   - If successful → store result in `session["fit_card"]`. Proceed to step 6.

6. **Return final response.** Combine `session["fit_card"]` with a short listing summary (title, price, platform, condition from `session["selected_item"]`) and return the combined string to the user. The loop is done.

The loop knows it's done when it either hits an early-return error or reaches step 6.

---

## State Management

**How does information from one tool get passed to the next?**

All state is stored in a single `session` dict that is created once per conversation and passed through every turn. The keys written and read are:

| Key | Type | Written by | Read by |
|-----|------|-----------|---------|
| `session["last_query"]` | dict with `description`, `size`, `max_price` | planning loop (parse step) | — (for debugging) |
| `session["results"]` | list[dict] | planning loop after `search_listings` | — |
| `session["selected_item"]` | dict | planning loop after `search_listings` | `suggest_outfit`, `create_fit_card` |
| `session["wardrobe"]` | dict with `"items"` key | planning loop (wardrobe load step) | `suggest_outfit` |
| `session["outfit_suggestion"]` | str | planning loop after `suggest_outfit` | `create_fit_card` |
| `session["fit_card"]` | str | planning loop after `create_fit_card` | final response assembly |
| `session["error"]` | str | planning loop on any failure | return-early path |

Each tool receives only its own required inputs (not the full session dict). The planning loop is responsible for extracting the right values from `session` and passing them as explicit arguments.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | Returns an empty list (no keyword, size, or price matches) | Set `session["error"]`, return "No listings matched your search. Try broader keywords, a different size, or raise your price limit." Stop the loop — do not call subsequent tools. |
| `suggest_outfit` | Wardrobe `items` list is empty | Call the LLM with a general styling prompt (no wardrobe references). Return general advice as the outfit string — do not raise or return `""`. |
| `suggest_outfit` | LLM call raises an exception | Catch the exception, set `session["error"]`, return "Could not generate outfit suggestions. Please try again." Stop the loop. |
| `create_fit_card` | `outfit` argument is empty or whitespace-only | Return the string `"Error: outfit data is missing — cannot generate a fit card."` immediately without calling the LLM. |
| `create_fit_card` | LLM call raises an exception | Catch the exception, return `"Could not generate fit card. The outfit suggestion was: {outfit}"` so the user still sees the suggestion text. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            USER INPUT                                   │
│  "vintage graphic tee under $30, baggy jeans, chunky sneakers"          │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ raw message
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          PLANNING LOOP                                  │
│                                                                         │
│  1. Parse → description, size, max_price                                │
│     Store in session["last_query"]                                      │
└───────────┬─────────────────────────────────────────────────────────────┘
            │ description, size, max_price
            ▼
┌───────────────────────┐
│   search_listings()   │
│  (scans listings.json)│
└───────────┬───────────┘
            │
     ┌──────┴───────┐
     │              │
  empty list     list[dict]
     │              │
     ▼              ▼
 ┌───────┐   session["results"]
 │ ERROR │   session["selected_item"] = results[0]
 │ STOP  │          │
 └───────┘          │ selected_item + wardrobe
                    ▼
        ┌───────────────────────┐
        │    suggest_outfit()   │◄── session["wardrobe"]
        │  (Groq LLM call)      │    (get_example_wardrobe()
        └───────────┬───────────┘     if not set)
                    │
             ┌──────┴───────┐
             │              │
          "" / error     str (suggestions)
             │              │
             ▼              ▼
         ┌───────┐   session["outfit_suggestion"]
         │ ERROR │          │
         │ STOP  │          │ outfit_suggestion + selected_item
         └───────┘          ▼
                  ┌───────────────────────┐
                  │   create_fit_card()   │
                  │  (Groq LLM, temp 0.9) │
                  └───────────┬───────────┘
                              │
                       ┌──────┴───────┐
                       │              │
                    error          str (caption)
                       │              │
                       ▼              ▼
                   ┌───────┐   session["fit_card"]
                   │ ERROR │          │
                   │ STOP  │          ▼
                   └───────┘  ┌────────────────┐
                              │  FINAL RESPONSE │
                              │  fit_card +     │
                              │  listing summary│
                              └────────┬────────┘
                                       │
                                       ▼
                                    USER
```

**Session state** is shared across all steps — each tool reads from it and writes back to it via the planning loop. Error paths terminate early and never reach downstream tools.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

I will give Claude the Tool 1 spec (input parameters, scoring logic, return type, failure behavior) from this planning.md and ask it to implement `search_listings()` using `load_listings()` from `data_loader.py`. I will verify by calling it with three test cases: (1) `description="vintage graphic tee", max_price=30` — should return at least `lst_006`; (2) `description="jeans", size="W30"` — should return `lst_001`; (3) `description="blazer"` — should return `[]`.

For Tool 2, I will give Claude the Tool 2 spec plus the Groq client setup already in `tools.py`. I will verify with two calls: one using `get_example_wardrobe()` (should name specific wardrobe pieces) and one using `get_empty_wardrobe()` (should give general advice without hallucinating wardrobe items).

For Tool 3, I will give Claude the Tool 3 spec and ask it to use temperature 0.9. I will verify: (1) a normal call produces a 2–4 sentence caption mentioning the item name, price, and platform; (2) passing `outfit=""` returns the error string without crashing.

**Milestone 4 — Planning loop and state management:**

I will give Claude the Planning Loop section and State Management table from this file, plus the three implemented tool signatures, and ask it to implement the loop in `agent.py`. I will verify by running one full end-to-end query through the Gradio UI and checking that: `session["selected_item"]` is set after step 2, the final output contains a fit card caption, and an intentionally zero-result query (e.g. `"leather blazer size XXS under $5"`) returns the no-match error message.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Agent description:**
FitFindr is a fashion-finding agent that takes a natural language request, searches a listings dataset for matching secondhand items, then uses the user's wardrobe to suggest how those items could be styled together. `search_listings` is triggered whenever the user describes an item they want (by category, price, style, or size), `suggest_outfit` is triggered once matching listings exist and a wardrobe is available to pair against, and `create_fit_card` is triggered last to package the result into a shareable summary. If `search_listings` returns nothing, the agent tells the user no matches were found and asks them to broaden the query; if `suggest_outfit` receives an empty wardrobe it falls back to a generic style suggestion based only on the new item; if `create_fit_card` gets incomplete outfit data it surfaces whatever it has and flags the missing fields.

**Step 1:**
The planning loop parses the message: `description = "vintage graphic tee"`, `size = None` (no size mentioned), `max_price = 30.0`. It calls `search_listings("vintage graphic tee", None, 30.0)`. The tool loads all listings, drops any over $30, then scores the rest by keyword overlap. `lst_006` ("Graphic Tee — 2003 Tour Bootleg Style", $24, depop) scores highest because it matches "graphic", "tee", and "vintage" across its title, style_tags, and description. The function returns `[lst_006, lst_002, ...]`. The loop sets `session["selected_item"] = lst_006`.

**Step 2:**
The loop loads `get_example_wardrobe()` and stores it as `session["wardrobe"]`. It calls `suggest_outfit(lst_006, session["wardrobe"])`. The LLM receives the item details and the wardrobe items list, then returns: "Outfit 1: wear the Graphic Tee with the Vintage Levi's 501s and your white low-top Chucks — the faded black tee matches the worn-in wash of the denim. Outfit 2: try it with the rust cords and chunky sneakers for a 90s-grunge-meets-earth-tone look." The loop stores this in `session["outfit_suggestion"]`.

**Step 3:**
The loop calls `create_fit_card(session["outfit_suggestion"], lst_006)`. The LLM generates a caption at temperature 0.9: "Grabbed this 2003 bootleg tour tee off depop for $24 and it's already my most-worn piece. Boxy fit, faded black, goes with literally everything — currently living in it with my 501s and chunky sneakers. Sometimes thrift luck just hits."

**Final output to user:**
The user sees the fit card caption plus a short listing block: title ("Graphic Tee — 2003 Tour Bootleg Style"), price ($24), platform (depop), condition (good), and the outfit suggestion — all in one readable response.
