# The retrieval pipeline

How EventLoop's chatbot gets from a sentence somebody typed to an answer, mapped
onto the four stages people usually mean by a RAG pipeline: **pre-retrieval**,
**retrieval**, **fine-tuning**, **evaluation**.

Written as an audit rather than a design document, so it says what the code does
today, including where a stage is thin or deliberately absent. Where something
is missing it says so instead of describing an intention.

The short version: pre-retrieval and retrieval are the substantial parts,
fine-tuning is deliberately absent, and evaluation is the real gap — it covers
categorization well and retrieval not at all.

---

## Explain it like I'm five

Imagine a friend who knows Chicago, sitting next to a very large notebook that
lists everything happening in the city. You ask them something. Four things
have to go right.

**1. Understanding what you asked** — *pre-retrieval*

You say *"anything fun this weekend?"*. Your friend has to work out that
"this weekend" means Saturday the 10th and Sunday the 11th, that "fun" is not
a category anyone writes on a flyer, and — if you'd said "Pilsen" — that
Pilsen is a neighborhood rather than a band. They also notice when you are
not asking at all, and are just saying goodbye.

This is the part most likely to go wrong quietly. We once turned
*"What's happening this weekend?"* into a search for the literal word
*"what's"*, and 221 events came back as one.

**2. Looking it up** — *retrieval*

Your friend checks the notebook first, because it is the thing they actually
know. They flip to the right dates, then the right neighborhood, then the
right kind of event. Only if the notebook is thin do they phone around to ask
what else is on — and anything they hear that way, they tell you they haven't
checked.

The notebook lookup is ordinary database filtering, not magic: a date is a
date, and a neighborhood is a shape on a map. Only when that comes back thin
do we fall back to comparing *meanings* of words, which is the part people
usually mean by "AI search".

**3. Teaching the friend** — *fine-tuning*

We didn't. We never sent them away to learn a new language. We gave them
better notes, a clearer sense of how to talk, and a better-organised notebook.
Section 3 explains why that was the right call here, and when it would not be.

**4. Marking their homework** — *evaluation*

Every so often you check: of the things they told you, how many were right?
We do this properly for one job — sorting events into categories, scored
against 73 answers written by hand — and not yet for the main one, finding
the right events. That gap is stated plainly in section 4 rather than papered
over.

**And one distinction that matters:** working out whether you're done is not
the same as working out whether you're *happy*. "👍" and "appreciate it —
anything cheaper?" are both cheerful; one ends the conversation and one does
not. We ask what a message is *doing*, not how it feels.

---

## 1. Pre-retrieval

Everything that happens to the question before anything is searched. This is
where most of the work is, because the queries are short and ambiguous ("free
stuff near me this weekend") while the data is structured.

| Step | Where | What it does |
|---|---|---|
| Intent gate | `app/chat/intent_classifier.py` | What is this message *doing*? Explicit Chicago event requests skip the model entirely (regex fast path). Ambiguous messages go to **claude-haiku-4-5** (switched from Sonnet — ~10× cheaper, same accuracy on 4-category classification). Confidence drives three-tier routing: ≥0.85 non-event → hard redirect in Loopara's voice; 0.65–0.84 non-event → agent runs with a clarification hint injected; anything else → normal agent run. The confidence score was previously read, logged, and discarded after a binary 0.7 threshold. Off-topic and farewell never reach retrieval. |
| Keyword extraction | `_extract_keywords` | Strips filler to content words. "I'd like to go to a family friendly outdoor event" → the words that can actually match. |
| Neighborhood resolution | `_extract_neighborhoods`, `shared/database/neighborhoods.py` | Exact neighborhood names and aliases resolve against rows in the database; selected broad regions (Northwest, North, West, South Side, downtown) expand through a curated map, intersected with existing rows. |
| Category mapping | `shared/categories.py` | Maps the words a person uses to the stored vocabulary: "blues", "salsa" and "symphony" all become `Music`. See `CATEGORY_TAXONOMY` for the parent/subtag scheme. |
| Date resolution | `_extract_date_range` | "tonight", "this weekend", "in October" become a real date window, in `America/Chicago`. |
| Temporal grounding | `todays_date` system prompt | Injects today's date, the timezone and the coming weekend's two dates per run. Without it the model had no idea what day it was and said so mid-answer. |

**Intent, not sentiment.** The gate classifies dialogue acts, which is a
different question from polarity and gets a different answer. "👍" and "cool
cool cool" are positive and mean the conversation is over; "appreciate it -
anything cheaper?" is positive and means it is not; "ugh, nothing good on
then?" is negative and is still a request. A sentiment model would end
conversations on a cheerful follow-up and talk through a flat "k".

It is also not keyword matching. Farewells were a regex for exactly one round
- it caught "bye" and "thanks" and missed "I'm done" - before becoming an
intent the model judges. It now handles "aight imma head out" and "merci!"
without either being written down anywhere.

The chatbot does not make a separate query-expansion model/tool call before
search. The database search already extracts dates, neighborhoods, categories
and keywords from the original request; requiring a second analysis step added
latency without changing the SQL query.

The persona prompt also stays compact: the stable voice and safety rules are
always present, while a category fact and brief seasonal guidance are added
only when relevant. Retrieved events carry their database neighborhood, and a
transit cue is included only for a small curated set of neighborhood-to-stop
mappings; the assistant is told not to infer transit details otherwise.

**What's missing:** no query rewriting or HyDE, and no synonym expansion beyond
the category vocabulary. The regional map is intentionally curated and not an
authoritative boundary definition; several local subregions and ambiguous
phrases still fall back to a citywide search.

---

## 2. Retrieval

A cascade, cheapest and most precise first. It is **hybrid by default** rather
than vector-first, because most of what makes an event the right answer is
structured — the date, the neighborhood, the price — and embeddings are bad at
all three.

```
1. Structured SQL        date window + neighborhood + category + keywords
         ↓ (few/no hits, or weak relevance)
2. Semantic fallback     model2vec static embeddings, cosine >= 0.25
         ↓ (still below the confidence threshold)
3. External search       SerpAPI, only when the local answer is poor
```

**1. Structured filters** (`search_local_db`). Real SQL over indexed columns.
A category filter matches any of an event's parent categories, so a drag show
stored primarily as `Music` still answers a question about `LGBTQ`.

**2. Semantic fallback** (`app/chat/semantic_index.py`). `minishlab/potion-base-8M`
static embeddings — a lookup table, not a transformer, so encoding is a token
lookup with no inference server and no GPU. Used two ways: to *score* the
structured results for relevance, and to *find* candidates when the structured
query comes back thin. Candidates are still constrained by the query's filters,
so a semantic match cannot smuggle in an event from the wrong weekend.

**3. External fallback** (`search_google_events`). Gated twice — on result count
(`DB_RESULT_THRESHOLD = 5`) and on the best local relevance score — because it
is the only step that costs money per call. Results are labelled as unverified
all the way to the UI and are only persisted if they carry a verifiable source
URL and a parseable date.

**What's missing:** no reranking stage. No chunking, which is correct here —
an event is a short record, not a document.

---

## 3. Fine-tuning

**None, deliberately.** Nothing in this project is trained.

The reasons, in order of weight:

1. **No training data.** There is no corpus of question/answer pairs for
   "what's on in Chicago this weekend", and manufacturing one would mean
   inventing the ground truth we would then measure against.
2. **The embedding model is static by design.** model2vec distils a transformer
   into a fixed token-to-vector table. That is what makes it cheap enough to run
   in-process, and it is not a thing you fine-tune.
3. **The hard problems here are not model problems.** The failures found in
   practice were a venue's calendar changing shape, a category label nobody had
   mapped, a date parsed in the wrong timezone, and prices never being collected.
   A fine-tuned model fixes none of those.

Where behaviour needed changing, the levers used instead were the system prompt
(`app/chat/persona.py`), the category vocabulary and taxonomy, and the retrieval
thresholds — all of them inspectable and testable, which a fine-tune is not.

---

## 4. Evaluation

The weakest stage, and worth being blunt about.

**What is measured.** Categorization, properly:
`backend/evaluate_categorization.py` scores strategies against 73 hand-labelled
event titles in `backend/eval/category_labels.json`, reporting coverage,
precision and overall correctness, and sweeping the similarity floor.

```
strategy                coverage   precision   correct
keyword rules only          53%        94%       50%
semantic only (0.45)        39%        85%       33%
hybrid (0.45)               62%        93%       58%
```

That harness exists because the alternative was what it replaced: notice a
misfiled event, add a keyword, notice another, add another keyword — unbounded,
and never saying whether the last change helped. It also settled a real
question with numbers rather than taste: embedding similarity cannot map
*category labels* (it ranks "Arts & Theatre"/"Arts" at 0.84 above
"Theater"/"Arts & Theatre" at 0.77, so no threshold separates them), but it does
help classify *titles*, which carry more signal. Both halves are kept because an
ablation showed removing the keywords drops the hybrid from 58% to 42%.

**What is not measured:**

- **Retrieval quality.** There is no labelled set of query → expected events, so
  no precision/recall numbers for search itself. This is the biggest gap: the
  whole cascade above is tuned by inspection.
- **Answer quality.** No rubric, no judge, no regression suite over the agent's
  replies.
- **The relevance and similarity thresholds** (`DB_RESULT_THRESHOLD = 5`,
  `MIN_SIMILARITY = 0.25`) were set by hand and have never been swept, unlike the
  categorization floor.

**A retrieval harness now exists.** `backend/evaluate_retrieval.py` runs 20
hand-labelled queries through the exact search path the chat agent uses and
reports pass/fail. Baseline on first run: **18/20 (90%)**. The two failures
are documented data-side gaps — sparse `age_range` field and a date-window
edge case at Thursday run time — not scoring bugs. Run this before and after
changing `LOCAL_CONFIDENCE_FLOOR`, `MIN_SIMILARITY`, or the SQL candidate
limit. Those numbers were previously set by hand and had never been validated.

**What covers it in the meantime.** 580 collected tests, and this is the honest part:
they did not catch the bugs that mattered. The agent not knowing the date, a
basketball game filed under Music, replies lost to an SSE parsing bug, and the
chat ending after one question were all found by *using the thing*. Every one was
invisible to the suite and obvious within seconds of opening the UI. The missing
tests are end-to-end, not more unit tests.

---

## Where a request actually goes

```
POST /api/chat
  │
  ├─ intent gate (Haiku) ──── explicit Chicago event request? skip classifier (regex fast path)
  │                           confidence ≥ 0.85 + non-event  → redirect in Loopara's voice
  │                           confidence 0.65–0.84 + non-event → inject [AMBIGUOUS_INTENT] hint
  │                           anything else                   → run agent normally
  │
  ├─ load conversation history (last 6 messages of the thread)
  │     turn ≥ 8: prepend one-sentence Haiku summary so earlier context survives the window
  │
  ├─ agent run (PydanticAI, ReAct, claude-sonnet-5-5) with two tools:
  │     search_local_db       SQL (100 rows if neighborhood-constrained, 50 otherwise)
  │                           → semantic rerank → top-5 ScoredEvents
  │     search_google_events  at most once, only after sparse/low-confidence local results
  │     per-turn caps         4 model requests, 3 tool calls, 4,000 output tokens/run
  │
  ├─ stream events over SSE: thinking → tool_call → response → complete
  │
  └─ record provider-reported classifier and agent usage; decrement the 20,000-agent-token / 12-turn budget
```
